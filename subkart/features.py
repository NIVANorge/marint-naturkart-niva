import enum
from pyexpat import features
from unicodedata import name

import geopandas as gpd
import geoutils as gu
import numpy as np
import rasterio as rio
from shapely import bounds
import xdem

import subkart

MARINE_VANN_TYPE_DESC = {
    "01": "Beskyttet fjord/kyst",
    "01a": "Beskyttet fjord/kyst med oksygenfattig bunnvann",
    "02": "Beskyttet ferskvannspåvirket fjord/kyst",
    "02a": "Beskyttet ferskvannspåvirket fjord med oksygenfattig bunnvann",
    "03": "Sterkt ferskvannspåvirket fjord",
    "03a": "Sterkt ferskvannspåvirket fjord med oksygenfattig bunnvann",
    "04": "Moderat eksponert fjord/kyst",
    "05": "Moderat eksponert ferskvannspåvirket fjord/kyst",
    "06": "Bølgeeksponert kyst",
    "07": "Bølgeeksponert ferskvannspåvirket kyst",
    "08": "Strømrike sund",
    "09": "Særegen vannforekomst",
}


VANNTYPER_COMBINED = {
    "beskyttet": ["01", "01a", "02", "02a", "03", "03a", "09"],
    # "sterkt_ferskvannspåvirket": [, ], moved to beskyttet
    "moderat_eksponert": ["04", "05", "08"],
    "bølgeeksponert": ["06", "07"],
    # "strømrike": ["08"], moved to moderat_eksponert
    # "særegen": ["09"], moved to beskyttet
}

TERRAIN_NAMES = ["depth", "slope", "compactness", "convexity"]

def marine_type_map():
    types = VANNTYPER_COMBINED.keys()
    type_id_map = {t: i for i, t in enumerate(types)}
    id_type_map = {i: t for t, i in type_id_map.items()}
    return types, id_type_map, type_id_map


def one_hot_encode_marine_types(marine_type_raster):
    num_classes = len(VANNTYPER_COMBINED)
    # Use bool to reduce memory, convert to uint8 at the end if needed
    one_hot_types = np.zeros(marine_type_raster.shape + (num_classes,), dtype=bool)
    valid_ids = marine_type_raster >= 0  # exclude nodata (-1)
    # Use advanced indexing for efficiency
    idx = np.where(valid_ids)
    class_ids = marine_type_raster[idx]
    one_hot_types[idx + (class_ids,)] = True
    return one_hot_types.astype(np.uint8, copy=False)


def rasterize_marine_types(marine_vanntyper, out_shape, transform):
    _, id_type_map, type_id_map = marine_type_map()
    # Only keep geometries with valid type_key
    shapes = [
        (geom, type_id_map[t])
        for geom, t in zip(marine_vanntyper.geometry, marine_vanntyper["type_key"])
        if t in type_id_map
    ]
    # Use int8 to reduce memory
    marine_type_raster = rio.features.rasterize(
        shapes=shapes,
        out_shape=out_shape,
        transform=transform,
        fill=-1,
        dtype=np.int8,
        all_touched=True,
    )
    return marine_type_raster


def build(dem: xdem.DEM, marine_vanntyper: gpd.GeoDataFrame) -> np.ndarray:
    """
    Build features from a digital elevation model (DEM) and marine types.
    """

    depth = np.ma.filled(dem.data, np.nan).astype(np.float32)
    slope, aspect, curvature = xdem.terrain.get_terrain_attribute(
        dem.data,
        resolution=dem.res,
        attribute=["slope", "aspect", "curvature"],
    )
    transform, shape = dem.transform, dem.data.shape[-2:]

    marine_vanntyper = marine_vanntyper.to_crs(dem.crs)
    marine_type_raster = subkart.features.rasterize_marine_types(marine_vanntyper, dem.data.shape[-2:], dem.transform)
    one_hot_types = subkart.features.one_hot_encode_marine_types(marine_type_raster)

    features = np.concatenate([np.stack([depth, slope, aspect, curvature], axis=-1), one_hot_types], axis=-1)

    valid_attrs = (~np.isnan(depth)) & (~np.isnan(slope)) & (~np.isnan(aspect)) & (~np.isnan(curvature))

    return features.astype("float32"), valid_attrs


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


def marine_vanntyper_preprocess(marine_vanntyper: gpd.GeoDataFrame):

    marine_vanntyper["type_key"] = marine_vanntyper["Type"].map(
        lambda x: next((k for k, v in VANNTYPER_COMBINED.items() if x in v), x)
    )

    return marine_vanntyper

def depth_preprocess(gdf: gpd.GeoDataFrame):

    gdf[["minimumsdybde", "maksimumsdybde"]] = gdf[["minimumsdybde", "maksimumsdybde"]].astype(np.float32)
    gdf.dissolve(by="minimumsdybde", as_index=False)
    gdf.explode(index_parts=False).reset_index()
    gdf["depth"] = (gdf["maksimumsdybde"] + gdf["minimumsdybde"]) / 2
    # Effective Width (or hydraulic mean width)
    gdf["slope"] = np.degrees(
        np.arctan((gdf["maksimumsdybde"] - gdf["minimumsdybde"]) / (4 * gdf.geometry.area / gdf.geometry.length))
    )

    gdf["compactness"] = 4 * np.pi * gdf.area / (gdf.length ** 2)
    gdf["convexity"] = gdf.area / gdf.geometry.convex_hull.area
    
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


def build_basis_raster(gdf_basis: gpd.GeoDataFrame, marine_vanntyper: gpd.GeoDataFrame, valid_mask: np.ndarray, res: int = 50, dtype=np.float32) -> tuple:
    transform, out_shape, bounds = to_raster_shapes(gdf_basis, res)
    vec_basis = gu.Vector(gdf_basis)
    
    arrays = []
    
    for i, name in enumerate(TERRAIN_NAMES):
        print(f"Processing {name}...")
        raster = subkart.features.rasterize_area(vec_basis, gdf_basis[name], bounds, res)
        
        if i == 0:
            transform, out_shape = raster.transform, raster.data.shape[-2:]

        arrays.append(raster.data.data.astype(dtype, copy=False))
        del raster
    print(f"Processing marine types...")
    marine_vanntyper = marine_vanntyper.to_crs(gdf_basis.crs)
    marine_type_raster = subkart.features.rasterize_marine_types(marine_vanntyper, out_shape, transform)
    one_hot_types = subkart.features.one_hot_encode_marine_types(marine_type_raster)
    del marine_type_raster  # Free intermediate marine raster
    print(f"Stacking feature arrays...")
    features, valid_attrs = stack(arrays, one_hot_types)

    return features, valid_attrs, out_shape, transform


def stack(arrays: list[np.ndarray],
          one_hot_types: np.ndarray,
          valid_mask: np.ndarray=None,
          dtype=np.float32
         ) -> tuple[np.ndarray, np.ndarray]:
    """
    Stack feature arrays and one-hot types into a 2D scikit-ready dataset,
    while minimizing peak memory by avoiding 3D intermediates.
    """
    if valid_mask is None:
        valid_mask = np.ones(arrays[0].shape, dtype=bool)
    for a in arrays:
        valid_mask &= np.isfinite(a)


    valid_mask &= np.isfinite(one_hot_types).all(axis=-1)
    n_valid = int(valid_mask.sum())
    num_marine_types = one_hot_types.shape[-1]
    num_features = len(arrays) + num_marine_types
    stacked_features = np.empty((n_valid, num_features), dtype=dtype)

    col = 0
    for feature_array in arrays:
        stacked_features[:, col] = feature_array[valid_mask].astype(dtype, copy=False)
        col += 1

    one_hot_types_2d = one_hot_types.reshape(-1, num_marine_types)
    stacked_features[:, col:col+num_marine_types] = one_hot_types_2d[valid_mask.ravel(), :]

    return stacked_features, valid_mask