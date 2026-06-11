import geopandas as gpd
import geoutils as gu
import numpy as np
import rasterio as rio
import rasterio.features
import xdem
from scipy.ndimage import distance_transform_edt, binary_erosion

import subkart

RESOLUTION = 50
"""Resolution of the rasterized output."""
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


def interpolate_depth_raster(
    gdf: gpd.GeoDataFrame,
    bounds: tuple,
    res: int = 50,
    dtype=np.float32,
    depth_atol: float = 0.01,
) -> np.ndarray:
    """
    Interpolate depth between matching polygon boundaries.

    For each polygon two reference edges are identified in the raster:

    * **Shallow edge** – pixels adjacent to a neighbour whose
      ``maksimumsdybde`` equals this polygon's ``minimumsdybde``
      (the contour shared with the shallower neighbour, at depth = min).
    * **Deep edge** – pixels adjacent to a neighbour whose
      ``minimumsdybde`` equals this polygon's ``maksimumsdybde``
      (the contour shared with the deeper neighbour, at depth = max).

    Each raster cell is then assigned::

        depth = min_d + (max_d - min_d) * d_to_shallow / (d_to_shallow + d_to_deep)

    The gradient direction follows the depth ordering from land outward,
    not polygon shape.  Polygons with no matching depth-neighbour on one
    or both sides fall back to the polygon's outer boundary as the
    missing reference edge (degrading to the flat midpoint average when
    both sides are absent).

    Parameters
    ----------
    depth_atol:
        Absolute tolerance for matching neighbour depth values (default 0.01 m).
    """
    minx, miny, maxx, maxy = bounds
    width  = int(round((maxx - minx) / res))
    height = int(round((maxy - miny) / res))
    transform = rio.transform.from_origin(minx, maxy, res, res)
    out_shape = (height, width)

    gdf = gdf.reset_index(drop=True)
    min_vals = gdf["minimumsdybde"].to_numpy(dtype=np.float32)
    max_vals = gdf["maksimumsdybde"].to_numpy(dtype=np.float32)

    # --- Rasterize all polygon IDs in one pass (nodata = -1) -----------------
    pid = rasterio.features.rasterize(
        ((geom, i) for i, geom in enumerate(gdf.geometry)),
        out_shape=out_shape,
        transform=transform,
        fill=-1,
        dtype=np.int32,
    )

    valid    = pid >= 0
    pid_safe = np.where(valid, pid, 0)   # safe lookup (nodata mapped to 0, gated by valid)
    min_r    = np.where(valid, min_vals[pid_safe], np.nan).astype(np.float32)
    max_r    = np.where(valid, max_vals[pid_safe], np.nan).astype(np.float32)
    del pid_safe

    # --- Build shallow / deep boundary masks via vectorised neighbour lookup --
    # For 4-connectivity: exactly one of (di, dj) is ±1, the other is 0.
    def _shift_pid(di: int, dj: int) -> np.ndarray:
        """Return pid shifted by (di, dj), filling vacated edges with -1."""
        out = np.full_like(pid, -1)
        if di > 0:
            out[di:, :]         = pid[:height - di, :]
        elif di < 0:
            out[:height + di, :] = pid[-di:, :]
        elif dj > 0:
            out[:, dj:]          = pid[:, :width - dj]
        elif dj < 0:
            out[:, :width + dj]  = pid[:, -dj:]
        return out

    shallow_bound = np.zeros(out_shape, dtype=bool)
    deep_bound    = np.zeros(out_shape, dtype=bool)

    with np.errstate(invalid="ignore"):
        for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nbr      = _shift_pid(di, dj)
            nbr_v    = nbr >= 0
            nbr_safe = np.where(nbr_v, nbr, 0)
            diff     = valid & nbr_v & (nbr != pid)

            # Shallow edge: neighbour.max == this.min  → shared contour is at min depth
            shallow_bound |= diff & (np.abs(np.where(nbr_v, max_vals[nbr_safe], np.nan) - min_r) <= depth_atol)
            # Deep edge:    neighbour.min == this.max  → shared contour is at max depth
            deep_bound    |= diff & (np.abs(np.where(nbr_v, min_vals[nbr_safe], np.nan) - max_r) <= depth_atol)
            del nbr, nbr_v, nbr_safe, diff

    del min_r, max_r   # large arrays no longer needed

    outer_edge = valid & ~binary_erosion(valid, border_value=0)

    # --- Per-polygon interpolation on bounding-box sub-arrays ----------------
    depth_out = np.full(out_shape, np.nan, dtype=dtype)

    for i, geom in enumerate(gdf.geometry):
        min_d = float(min_vals[i])
        max_d = float(max_vals[i])

        # Derive per-polygon bounding box from geometry (O(1), no full-raster scan)
        bx0, by0, bx1, by1 = geom.bounds
        r0 = max(int(np.floor((maxy - by1) / res)) - 1, 0)
        r1 = min(int(np.ceil( (maxy - by0) / res)) + 1, height)
        c0 = max(int(np.floor((bx0 - minx) / res)) - 1, 0)
        c1 = min(int(np.ceil( (bx1 - minx) / res)) + 1, width)

        m    = pid[r0:r1, c0:c1] == i
        if not m.any():
            continue

        sb_b = shallow_bound[r0:r1, c0:c1] & m
        db_b = deep_bound   [r0:r1, c0:c1] & m

        # Fallback when one or both reference edges are missing
        if not sb_b.any() or not db_b.any():
            oe = outer_edge[r0:r1, c0:c1] & m
            if not oe.any():
                oe = m & ~binary_erosion(m, border_value=0)
            if not sb_b.any():
                sb_b = oe
            if not db_b.any():
                db_b = oe

        d_s   = distance_transform_edt(~sb_b).astype(np.float32)
        d_d   = distance_transform_edt(~db_b).astype(np.float32)
        sum_d = d_s + d_d
        with np.errstate(invalid="ignore", divide="ignore"):
            t = np.where(sum_d > 0, d_s / sum_d, np.float32(0.5))

        depth_out[r0:r1, c0:c1][m] = min_d + (max_d - min_d) * t[m]

    return depth_out


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

    print("Computing interpolated depth raster...")
    interp_depth = subkart.features.interpolate_depth_raster(gdf_sea_map, bounds, res, dtype)

    for name in SEA_MAP_NAMES:
        print(f"Preparing {name}...")

        if name == "sea_avg_depth":
            data = interp_depth
        else:
            raster = subkart.features.rasterize_area(vec_basis, gdf_sea_map[name], bounds, res)
            data = raster.data.data.astype(dtype, copy=False)
            del raster

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
            # Derive slope from the interpolated depth gradient as a per-cell fallback,
            # falling back further to the flat per-polygon estimate where depth is NaN.
            dy, dx = np.gradient(np.where(np.isnan(interp_depth), 0.0, interp_depth.astype(np.float64)), res)
            interp_slope = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2))).astype(dtype)
            interp_slope = np.where(np.isnan(interp_depth), data, interp_slope)
            slope_filled = np.where(np.isnan(slope), interp_slope, slope)
            arrays[DEPTH_NAMES.index("dem_slope")] = slope_filled.astype(dtype, copy=False)
            arrays[DEPTH_NAMES.index("dem_curvature")] = np.nan_to_num(curvature, nan=0.0).astype(
                dtype, copy=False
            )  # Set to flat
            del slope, curvature, dy, dx, interp_slope

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
