import os
from pathlib import Path

import geopandas as gpd
import geoutils as gu
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import rasterio as rio
from matplotlib.colors import BoundaryNorm
from sqlalchemy import create_engine
from shapely.errors import GEOSException
from shapely.validation import explain_validity, make_valid

import subkart


def plot_prediction_raster(raster):
    data = np.array(raster.data, dtype=float)
    data[data == raster.nodata] = np.nan
    data[~np.isin(data, [0, 1, 2])] = np.nan

    # colormap: 0=bløtbunn(y), 1=blanding(p), 2=hardbunn(b)
    cmap = mcolors.ListedColormap(["#FFB300", "#803E75", "#3270AE"])
    bounds = [-0.5, 0.5, 1.5, 2.5]
    norm = mcolors.BoundaryNorm(bounds, cmap.N)

    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(data, cmap=cmap, norm=norm, interpolation="nearest")
    ax.set_title("Predicted Bunntype")
    cbar = fig.colorbar(im, ax=ax, ticks=[0, 1, 2], shrink=0.7)
    cbar.ax.set_yticklabels(["bløtbunn", "blanding", "hardbunn"])
    plt.tight_layout()
    plt.show()


def plot_terrain_features(gdf):

    feature_cols = [
        (subkart.features.TERRAIN_NAMES[0], "viridis", "Depth (m)"),
        (subkart.features.TERRAIN_NAMES[1], "terrain", "Slope (degrees)"),
        (subkart.features.TERRAIN_NAMES[2], "plasma", "Compactness"),
        (subkart.features.TERRAIN_NAMES[3], "plasma", "Convexity"),
    ]

    n = len(feature_cols)
    fig, axes = plt.subplots(1, n, figsize=(6 * n, 8))

    for ax, (col, cmap, title) in zip(axes, feature_cols):
        gdf.plot(
            column=col,
            cmap=cmap,
            legend=True,
            linewidth=0,
            ax=ax,
        )
        ax.set_title(title)
        ax.set_axis_off()

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

def dissolve_geometries(gdf: gpd.GeoDataFrame, by_col: str):
    """Dissolve geometries to fix neighboring features that are split on same depth
    
    """
    # Dissolve by "minimumsdybde"
    try:
        gdf_dissolved = gdf.dissolve(by=by_col, as_index=False)
    except GEOSException as e:
        print(f"TopologicalError while dissolving {e}")
        invalid_mask = ~gdf.geometry.is_valid
        bad = gdf.loc[invalid_mask].copy()

        print(f"Invalid geometries: {invalid_mask.sum()} / {len(gdf)}")
        for i, geom in zip(bad.index, bad.geometry):
            print(i, explain_validity(geom)) 
        gdf["geometry"] = gdf.geometry.apply(make_valid)
        gdf_dissolved = gdf.dissolve(by=by_col, as_index=False)

    # Explode dissolved geometry
    gdf_exploded = gdf_dissolved.explode(index_parts=False).reset_index(drop=True)

    return gdf_exploded

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
