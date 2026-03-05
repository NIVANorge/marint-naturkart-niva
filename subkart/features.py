import enum
from pyexpat import features

import geopandas as gpd
import geoutils as gu
import numpy as np
import rasterio as rio
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


def marine_type_map():
    types = VANNTYPER_COMBINED.keys()
    type_id_map = {t: i for i, t in enumerate(types)}
    id_type_map = {i: t for t, i in type_id_map.items()}
    return types, id_type_map, type_id_map


def one_hot_encode_marine_types(marine_type_raster):
    num_classes = len(VANNTYPER_COMBINED)

    one_hot_types = np.zeros(marine_type_raster.shape + (num_classes,), dtype=np.uint8)

    valid_ids = marine_type_raster >= 0  # exclude nodata (-1)
    for class_id in range(num_classes):
        mask = valid_ids & (marine_type_raster == class_id)
        one_hot_types[..., class_id][mask] = 1

    return one_hot_types


def rasterize_marine_types(marine_vanntyper, out_shape, transform):

    _, id_type_map, type_id_map = marine_type_map()
    # Prepare shapes as (geometry, value)
    marine_vanntyper = marine_vanntyper.copy()
    marine_vanntyper["type_key"] = marine_vanntyper["Type"].map(
        lambda x: next((k for k, v in VANNTYPER_COMBINED.items() if x in v), x)
    )
    shapes = [(geom, type_id_map[t]) for geom, t in zip(marine_vanntyper.geometry, marine_vanntyper["type_key"])]

    marine_type_raster = rio.features.rasterize(
        shapes=shapes,
        out_shape=out_shape,
        transform=transform,
        fill=-1,
        dtype=np.int16,
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


def build_basis_raster(gdf_basis: gpd.GeoDataFrame, marine_vanntyper: gpd.GeoDataFrame):

    bounds = gdf_basis.total_bounds
    vec_basis = gu.Vector(gdf_basis)
    feature_names = ["depth", "slope", "compactness", "convexity"]
    rasters = []
    for name in feature_names:
        rasters.append(subkart.features.rasterize_area(vec_basis, gdf_basis[name], bounds))
    
    depth = rasters[0]
    transform, out_shape = depth.transform, depth.data.shape[-2:]

    marine_vanntyper = marine_vanntyper.to_crs(gdf_basis.crs)
    marine_type_raster = subkart.features.rasterize_marine_types(marine_vanntyper, out_shape, transform)
    one_hot_types = subkart.features.one_hot_encode_marine_types(marine_type_raster)

    return rasters, one_hot_types


def stack(rasters: list[gu.Raster], one_hot_types: np.ndarray) -> tuple:
    """
    Stack any number of Raster feature arrays and one-hot types, returning features and valid mask.
    """
    arrays = [r.data.data for r in rasters]
    features = np.concatenate([np.stack(arrays, axis=-1), one_hot_types], axis=-1)
    valid_attrs = np.all([~np.isnan(arr) for arr in arrays], axis=0) & (~np.isnan(one_hot_types).any(axis=-1))
    return features.astype("float32"), valid_attrs
