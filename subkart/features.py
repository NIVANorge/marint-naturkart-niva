import geopandas as gpd
import geoutils as gu
import numpy as np
import rasterio as rio
import xdem

import subkart

DEM_FEATURE_NAMES = ["dem_depth", "dem_slope", "dem_curvature", "is_dem"]
SEA_MAP_NAMES = ["sea_avg_depth", "sea_avg_slope", "sea_compactness", "sea_convexity"]

DEPTH_NAMES = DEM_FEATURE_NAMES + SEA_MAP_NAMES
NAMES = DEPTH_NAMES + ["wave_exposure"]


def rasterize_area(vector: gu.Vector, in_values, bounds: tuple, res: int = 50):
    """
    Rasterize the depth area from a GeoDataFrame.
    """

    minx, miny, maxx, maxy = bounds
    snapped_bounds = (
        np.floor(minx / res) * res,
        np.floor(miny / res) * res,
        np.ceil(maxx / res) * res,
        np.ceil(maxy / res) * res,
    )

    return vector.rasterize(
        xres=res,
        yres=res,
        crs=vector.crs,
        bounds=snapped_bounds,
        in_value=in_values,
        out_value=np.nan,
    )


def depth_preprocess(gdf: gpd.GeoDataFrame, is_rerun: bool = False) -> gpd.GeoDataFrame:

    if all(name in gdf.columns for name in SEA_MAP_NAMES) and not is_rerun:
        print("All depth features already present, skipping preprocessing.")
        return gdf
    gdf.dissolve(by="minimumsdybde", as_index=False)
    gdf.explode(index_parts=False).reset_index()
    gdf["sea_avg_depth"] = (gdf["maksimumsdybde"] + gdf["minimumsdybde"]) / 2
    # Effective Width (or hydraulic mean width)
    gdf["sea_avg_slope"] = np.degrees(
        np.arctan((gdf["maksimumsdybde"] - gdf["minimumsdybde"]) / (4 * gdf.geometry.area / gdf.geometry.length))
    )

    gdf["sea_compactness"] = 4 * np.pi * gdf.area / (gdf.length**2)
    gdf["sea_convexity"] = gdf.area / gdf.geometry.convex_hull.area
    gdf["sea_area"] = gdf.geometry.area

    return gdf


def to_raster_shapes(gdf: gpd.GeoDataFrame, res: int = 50):
    """
    Calculate the raster transform and output shape for a given GeoDataFrame and resolution.
    """
    bounds = gdf.total_bounds
    minx, miny, maxx, maxy = bounds
    snapped_bounds = (
        np.floor(minx / res) * res,
        np.floor(miny / res) * res,
        np.ceil(maxx / res) * res,
        np.ceil(maxy / res) * res,
    )
    width = int((snapped_bounds[2] - snapped_bounds[0]) / res)
    height = int((snapped_bounds[3] - snapped_bounds[1]) / res)
    transform = rio.transform.from_origin(snapped_bounds[0], snapped_bounds[3], res, res)
    out_shape = (height, width)
    return transform, out_shape, snapped_bounds


def build(
    dem: xdem.DEM,
    gdf_sea_map: gpd.GeoDataFrame,
    bolge_raster: gu.Raster,
    valid_mask: np.ndarray,
    res: int = 50,
    dtype=np.float32,
    inspect: bool = False
) -> tuple:
    transform, out_shape, bounds = to_raster_shapes(gdf_sea_map, res)

    vec_basis = gu.Vector(gdf_sea_map)

    arrays = len(DEPTH_NAMES) * [None]
    
    for name in SEA_MAP_NAMES:
        print(f"Preparing {name}...")
        raster = subkart.features.rasterize_area(vec_basis, gdf_sea_map[name], bounds, res)
        data = raster.data.data.astype(dtype, copy=False)
        arrays[DEPTH_NAMES.index(name)] = data

        if name == "sea_avg_depth":
            depth = np.ma.filled(dem.data, np.nan).astype(dtype, copy=False)
            
            depth_filled = np.where(np.isnan(depth), -data, depth)
            arrays[DEPTH_NAMES.index("dem_depth")] = depth_filled.astype(dtype, copy=False)
            arrays[DEPTH_NAMES.index("is_dem")] = np.isfinite(depth).astype(dtype, copy=False)

        elif name == "sea_avg_slope":
            slope, curvature = xdem.terrain.get_terrain_attribute(
                dem.data,
                resolution=res,
                attribute=["slope", "curvature"],
            )
            slope_filled = np.where(np.isnan(slope), data, slope)
            arrays[DEPTH_NAMES.index("dem_slope")] = slope_filled.astype(dtype, copy=False)
            arrays[DEPTH_NAMES.index("dem_curvature")] = np.nan_to_num(curvature, nan=0.0).astype(
                dtype, copy=False
            )  # Set to flat
            del slope, curvature
        del raster, data

    print("Preparing wave exposure...")
    wave_src = bolge_raster.data
    if wave_src.ndim == 3:
        wave_src = wave_src[0]
    wave_src_filled = np.ma.filled(wave_src.astype(np.float32), np.nan)
    wave_data = np.full(out_shape, np.nan, dtype=np.float32)
    rio.warp.reproject(
        source=wave_src_filled,
        destination=wave_data,
        src_transform=bolge_raster.transform,
        src_crs=bolge_raster.crs,
        dst_transform=transform,
        dst_crs=gdf_sea_map.crs,
        src_nodata=bolge_raster.nodata,
        dst_nodata=np.nan,
        resampling=rio.warp.Resampling.bilinear,
    )
    arrays.append(wave_data.astype(dtype, copy=False))
    del wave_data

    if inspect:
        subkart.plot.inspect_arrays(arrays)

    print("Stacking feature arrays...")
    features, valid_attrs = stack(arrays, valid_mask, dtype)

    return features, valid_attrs, out_shape, transform


def stack(
    arrays: list[np.ndarray], valid_mask: np.ndarray = None, dtype=np.float32
) -> tuple[np.ndarray, np.ndarray]:
    """
    Stack feature arrays into a 2D scikit-ready dataset,
    while minimizing peak memory by avoiding 3D intermediates.
    """
    if valid_mask is None:
        valid_mask = np.ones(arrays[0].shape, dtype=bool)
    for a in arrays:
        valid_mask &= np.isfinite(a)

    n_valid = int(valid_mask.sum())
    stacked_features = np.empty((n_valid, len(arrays)), dtype=dtype)

    for col, feature_array in enumerate(arrays):
        stacked_features[:, col] = feature_array[valid_mask]

    return stacked_features, valid_mask
