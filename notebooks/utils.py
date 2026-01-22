import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm

import matplotlib.pyplot as plt
import rasterio as rio
import geoutils as gu

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


def one_hot_encode_marine_types(marine_type_raster, id_type_map):
    one_hot = np.zeros(
        (len(MARINE_VANN_TYPE_DESC), *marine_type_raster.shape), dtype=np.float32
    )
    for i, t in id_type_map.items():
        one_hot[i] = marine_type_raster == t
    return one_hot


def rasterize_marine_types(mv_proj, dem):
    types = MARINE_VANN_TYPE_DESC.keys()
    type_id_map = {t: i for i, t in enumerate(types)}
    id_type_map = {i: t for t, i in type_id_map.items()}

    # Prepare shapes as (geometry, value)
    shapes = [
        (geom, type_id_map[t]) for geom, t in zip(mv_proj.geometry, mv_proj["Type"])
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


def plot_one_hot_vanntyper(one_hot_types, id_type_map, transform, crs):
    # Create a grid of subplots for each marine type

    types = sorted(id_type_map.items())  # list of (class_id, type_code)
    n = len(types)
    cols = 4
    rows = 3
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

    # Discrete colormap and norm
    num_classes = len(MARINE_VANN_TYPE_DESC)
    cmap = plt.cm.get_cmap("tab20", num_classes)
    cmap.set_bad(color="lightgrey", alpha=0.3)
    norm = BoundaryNorm(np.arange(-0.5, num_classes + 0.5, 1), ncolors=cmap.N)

    extent = rio.plot.plotting_extent(marine_type_raster, transform=transform)
    fig, ax = plt.subplots(figsize=(10, 10))
    im = ax.imshow(masked, cmap=cmap, norm=norm, extent=extent, origin="upper")
    ax.set_title("Marine vanntyper (Type IDs)")

    tick_locs = np.arange(num_classes)
    tick_labels = [
        f"{i}: {id_type_map[i]} – {MARINE_VANN_TYPE_DESC[id_type_map[i]]}"
        for i in tick_locs
    ]
    cbar = fig.colorbar(im, ax=ax, ticks=tick_locs, fraction=0.046, pad=0.04)
    cbar.ax.set_yticklabels(tick_labels)
    cbar.ax.set_ylabel("Vanntype", rotation=90)

    plt.show()


def to_filename(ressurstittel, romligutstrekning, ressursdato, referansesystem):

    return f"{ressurstittel}_{romligutstrekning}_{ressursdato}_{referansesystem}"
