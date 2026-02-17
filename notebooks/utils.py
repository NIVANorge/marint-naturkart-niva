import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm

import matplotlib.pyplot as plt
import rasterio as rio
import geoutils as gu
import rasterio.plot
from sqlalchemy import create_engine


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

BUNNTYPE_MAPPING = {"løsbunn": 0, "blanding/uspesifisert": 1, "fastbunn": 2}


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


def plot_one_hot_vanntyper(one_hot_types, id_type_map, transform, crs, cols, rows):
    # Create a grid of subplots for each marine type

    types = sorted(id_type_map.items())  # list of (class_id, type_code)
    n = len(types)
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows))

    for i, (cid, tcode) in enumerate(types):
        ax = axes.flat[i]
        layer = one_hot_types[..., cid].astype(np.uint8)
        if np.all(layer == 0):
            ax.set_title(f"{tcode} (empty)")
            ax.axis("off")
            continue
        r = gu.Raster.from_array(layer, transform=transform, crs=crs)
        r.plot(ax=ax)
        ax.set_title(f"{tcode} (id {cid})")

    # Hide any extra axes
    for j in range(i + 1, rows * cols):
        axes.flat[j].axis("off")

    plt.tight_layout()


def plot_vanntyper(marine_type_raster, transform, id_type_map):
    masked = np.ma.masked_less(marine_type_raster, 0)

    description = (
        MARINE_VANN_TYPE_DESC
        if "01" in id_type_map
        else {k: " ".join(VANNTYPER_COMBINED[k]) for k in id_type_map.values()}
    )
    # Discrete colormap and norm
    num_classes = len(id_type_map)
    cmap = plt.cm.get_cmap("tab20", num_classes)
    cmap.set_bad(color="lightgrey", alpha=0.3)
    norm = BoundaryNorm(np.arange(-0.5, num_classes + 0.5, 1), ncolors=cmap.N)

    extent = rio.plot.plotting_extent(marine_type_raster, transform=transform)
    fig, ax = plt.subplots(figsize=(10, 10))
    im = ax.imshow(masked, cmap=cmap, norm=norm, extent=extent, origin="upper")
    ax.set_title("Marine vanntyper (Type IDs)")

    tick_locs = np.arange(num_classes)
    tick_labels = [
        f"{i}: {id_type_map[i]} – {description[id_type_map[i]]}" for i in tick_locs
    ]
    cbar = fig.colorbar(im, ax=ax, ticks=tick_locs, fraction=0.046, pad=0.04)
    cbar.ax.set_yticklabels(tick_labels)
    cbar.ax.set_ylabel("Vanntype", rotation=90)

    plt.show()


def to_filename(ressurstittel, romligutstrekning, ressursdato, referansesystem):

    return f"{ressurstittel}_{romligutstrekning}_{ressursdato}_{referansesystem}"


def to_postgis(gdf, fname):
    if os.environ.get("NIVAGIS_CONNECTION_STR"):
        table_name = "_".join(fname.split("_")[:-1])[:50]
        conn = create_engine(os.environ["NIVAGIS_CONNECTION_STR"])
        gdf.to_postgis(
            table_name, schema="naturkartmarin", con=conn, if_exists="replace"
        )
        print(f"Table {table_name} uploaded to PostGIS.")
    else:
        print("NIVAGIS_CONNECTION_STR not set. Skipping PostGIS upload.")
