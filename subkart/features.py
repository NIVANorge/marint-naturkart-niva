import enum
from pyexpat import features
from attr import attributes
import rasterio as rio
import numpy as np
import xdem
import geopandas as gpd
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


def rasterize_marine_types(marine_vanntyper, dem):

    _, id_type_map, type_id_map = marine_type_map()
    # Prepare shapes as (geometry, value)
    marine_vanntyper = marine_vanntyper.copy()
    marine_vanntyper["type_key"] =  marine_vanntyper["Type"].map(lambda x: next((k for k, v in VANNTYPER_COMBINED.items() if x in v), x))
    shapes = [(geom, type_id_map[t]) for geom, t in zip(marine_vanntyper.geometry, marine_vanntyper["type_key"])]

    out_shape = dem.data.shape[-2:]
    transform = dem.transform
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

    marine_vanntyper = marine_vanntyper.to_crs(dem.crs)
    marine_type_raster = subkart.features.rasterize_marine_types(marine_vanntyper, dem)
    one_hot_types = subkart.features.one_hot_encode_marine_types(marine_type_raster)

    features = np.concatenate([np.stack([depth, slope, aspect, curvature], axis=-1), one_hot_types], axis=-1)

    valid_attrs = (~np.isnan(depth)) & (~np.isnan(slope)) & (~np.isnan(aspect)) & (~np.isnan(curvature))

    return features.astype("float32"), valid_attrs
