import os

import geoutils as gu
import matplotlib.pyplot as plt
import numpy as np
import rasterio as rio
import rasterio.plot
import geopandas as gpd
from pathlib import Path
from matplotlib.colors import BoundaryNorm
from sqlalchemy import create_engine
import xdem

import subkart


def plot_terrain_features(gdf):

    fig, axes = plt.subplots(1, 2, figsize=(16, 8))

    gdf.plot(
        column="depth",
        cmap="viridis",
        legend=True,
        linewidth=0,
        ax=axes[0],
    )
    axes[0].set_title("Depth (m)")
    axes[0].set_axis_off()

    gdf.plot(
        column="slope",
        cmap="terrain",
        legend=True,
        linewidth=0,
        ax=axes[1],
    )
    axes[1].set_title("Slope (degrees)")
    axes[1].set_axis_off()

    plt.tight_layout()


def plot_one_hot_vanntyper(one_hot_types, transform, crs, cols, rows):

    _, id_type_map, _ = subkart.features.marine_type_map()
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

    for j in range(i + 1, rows * cols):
        axes.flat[j].axis("off")

    plt.tight_layout()


def plot_vanntyper(marine_type_raster, transform):

    masked = np.ma.masked_less(marine_type_raster, 0)
    _, id_type_map, _ = subkart.features.marine_type_map()
    description = (
        subkart.features.MARINE_VANN_TYPE_DESC
        if "01" in id_type_map
        else {k: " ".join(subkart.features.VANNTYPER_COMBINED[k]) for k in id_type_map.values()}
    )
    num_classes = len(id_type_map)
    cmap = plt.cm.get_cmap("tab20", num_classes)
    cmap.set_bad(color="lightgrey", alpha=0.3)
    norm = BoundaryNorm(np.arange(-0.5, num_classes + 0.5, 1), ncolors=cmap.N)

    extent = rio.plot.plotting_extent(marine_type_raster, transform=transform)
    fig, ax = plt.subplots(figsize=(10, 10))
    im = ax.imshow(masked, cmap=cmap, norm=norm, extent=extent, origin="upper")
    ax.set_title("Marine vanntyper (Type IDs)")

    tick_locs = np.arange(num_classes)
    tick_labels = [f"{i}: {id_type_map[i]} – {description[id_type_map[i]]}" for i in tick_locs]
    cbar = fig.colorbar(im, ax=ax, ticks=tick_locs, fraction=0.046, pad=0.04)
    cbar.ax.set_yticklabels(tick_labels)
    cbar.ax.set_ylabel("Vanntype", rotation=90)

    plt.show()


def to_geoparquet(input_gml_path: Path, layer_name: str, output_path: Path):
    """Save GML Download from NGU as GeoParquet

    Geoparquet is a really nice format for geospatial data optimized for cloud access.
    
    """
    gdf = gpd.read_file(input_gml_path, layer=layer_name)
    gdf.to_parquet(output_path, compression="snappy")
    print(f"Written GeoParquet to {output_path}")


def to_filename(ressurstittel, romligutstrekning, ressursdato, referansesystem):

    return f"{ressurstittel}_{romligutstrekning}_{ressursdato}_{referansesystem}"


def to_postgis(gdf, fname):
    if os.environ.get("NIVAGIS_CONNECTION_STR"):
        table_name = "_".join(fname.split("_")[:-1])[:50]
        conn = create_engine(os.environ["NIVAGIS_CONNECTION_STR"])
        gdf.to_postgis(table_name, schema="naturkartmarin", con=conn, if_exists="replace")
        print(f"Table {table_name} uploaded to PostGIS.")
    else:
        print("NIVAGIS_CONNECTION_STR not set. Skipping PostGIS upload.")
