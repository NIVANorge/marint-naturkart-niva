import numpy as np
import rasterio as rio

BUNNTYPE_MAPPING = {"løsbunn": 0, "blanding/uspesifisert": 1, "fastbunn": 2}


def rasterize_bunn_type(gdf, out_shape, transform):
    shapes = [
        (geom, BUNNTYPE_MAPPING[btype])
        for geom, btype in zip(gdf.geometry, gdf["BunnType"])
        if btype in BUNNTYPE_MAPPING
    ]

    bunn_raster = rio.features.rasterize(
        shapes=shapes,
        out_shape=out_shape,
        transform=transform,
        fill=255,
        dtype=np.uint8,
        all_touched=True,
    )
    valid_bunn = np.isin(bunn_raster, tuple(BUNNTYPE_MAPPING.values()))

    return bunn_raster, valid_bunn
