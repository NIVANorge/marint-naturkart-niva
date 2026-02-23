import rasterio as rio
import numpy as np


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

def one_hot_encode_marine_types(marine_type_raster, id_type_map, combine_types=False):
    num_classes = (
        len(MARINE_VANN_TYPE_DESC) if not combine_types else len(VANNTYPER_COMBINED)
    )

    one_hot_types = np.zeros(marine_type_raster.shape + (num_classes,), dtype=np.uint8)

    valid_ids = marine_type_raster >= 0  # exclude nodata (-1)
    for class_id in range(num_classes):
        mask = valid_ids & (marine_type_raster == class_id)
        one_hot_types[..., class_id][mask] = 1

    return one_hot_types


def rasterize_marine_types(mv_proj, dem, combine_types=False):
    types = (
        MARINE_VANN_TYPE_DESC.keys() if not combine_types else VANNTYPER_COMBINED.keys()
    )
    type_id_map = {t: i for i, t in enumerate(types)}
    id_type_map = {i: t for t, i in type_id_map.items()}

    # Prepare shapes as (geometry, value)
    mv_proj = mv_proj.copy()
    mv_proj["type_key"] = (
        mv_proj["Type"]
        if not combine_types
        else mv_proj["Type"].map(
            lambda x: next((k for k, v in VANNTYPER_COMBINED.items() if x in v), x)
        )
    )
    shapes = [
        (geom, type_id_map[t]) for geom, t in zip(mv_proj.geometry, mv_proj["type_key"])
    ]

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

    return marine_type_raster, id_type_map