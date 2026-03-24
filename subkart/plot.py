import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import geoutils as gu

import subkart


def prediction_raster(raster):
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


def terrain_features(gdf):

    feature_cols = [
        (subkart.features.SEA_MAP_NAMES[0], "viridis", "Avg Depth (m)"),
        (subkart.features.SEA_MAP_NAMES[1], "terrain", "Avg Slope (degrees)"),
        (subkart.features.SEA_MAP_NAMES[2], "plasma", "Compactness"),
        (subkart.features.SEA_MAP_NAMES[3], "plasma", "Convexity"),
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


def one_hot_vanntyper(one_hot_types, transform, crs, cols, rows):

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


def vanntyper(marine_vanntyper):

    ax = marine_vanntyper.plot(
        column="type_key",
        legend=True,
        figsize=(8, 8),
        edgecolor="black",
        linewidth=0.2,
        alpha=0.7,
    )

    ax.set_title("marine_vanntyper")

def inspect_arrays(arrays):
    """Plot feature arrays for inspection."""

    for i, name in enumerate(subkart.features.DEPTH_NAMES):
        plt.figure(figsize=(8, 6))
        plt.imshow(arrays[i], cmap="viridis")
        plt.title(f"Array {name}")
        plt.colorbar()
        plt.show()
