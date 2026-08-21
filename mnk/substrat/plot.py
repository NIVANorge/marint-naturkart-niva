import textwrap

import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import geoutils as gu
from sklearn.metrics import ConfusionMatrixDisplay

import mnk.substrat as subkart
from sklearn.inspection import permutation_importance


def confusion_matrix(cm: np.ndarray, classes: list):
    fig, ax = plt.subplots(figsize=(6, 6))  # larger figure

    disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=classes)
    disp.plot(
        ax=ax,
        cmap="Blues",
        colorbar=True,
        values_format=".2f",
    )

    # Improve aesthetics
    ax.set_title("Confusion matrix (validation)", fontsize=14)
    ax.set_xlabel("Predicted label", fontsize=12)
    ax.set_ylabel("True label", fontsize=12)

    # Remove gridlines
    ax.grid(False)

    # Rotate x‑tick labels if desired
    plt.setp(ax.get_xticklabels(), rotation=0)

    # Thinner ticks and no grid box around
    ax.tick_params(axis="both", which="both", length=3)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    plt.tight_layout()
    plt.show()

def feature_importance(classifier, X_val, y_val):
    """Compute permutation importance for the best model on validation data"""
    result = permutation_importance(
        classifier, X_val, y_val, n_repeats=10, random_state=42, n_jobs=2
    )

    feature_names = subkart.features.NAMES

    # Sort features by importance
    importances_mean = result.importances_mean
    importances_std = result.importances_std
    sorted_idx = np.argsort(importances_mean)[::-1]

    # Print top 20 features
    top_n = 20
    for i in sorted_idx[:top_n]:
        print(f"{feature_names[i]}: mean={importances_mean[i]:.6f}, std={importances_std[i]:.6f}")

    # Prepare data for plotting
    top_idx = sorted_idx[:top_n]
    labels = [feature_names[i] for i in top_idx]
    values = importances_mean[top_idx]
    errors = importances_std[top_idx]

    # Publication-ready plot
    plt.style.use("seaborn-v0_8-whitegrid")

    fig, ax = plt.subplots(figsize=(6, 4))

    y_pos = np.arange(len(labels))
    ax.barh(
        y_pos,
        values,
        xerr=errors,
        color="#4e79a7",
        ecolor="black",
        capsize=3,
        alpha=0.9,
    )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()  # most important on top

    ax.set_xlabel("Permutation importance (mean decrease in accuracy)")
    ax.set_title("Top feature importances (validation set)")

    # Tighter layout and cleaner spines
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    plt.tight_layout()
    plt.show()

def spatial_errors(
    coords: np.ndarray,
    y_true,
    y_pred,
    crs: str = "EPSG:25833",
    region_gdf=None,
    resolution: float | None = None,
    max_grid_dim: int = 1600,
):
    """Map validation errors as coloured grid cells on the original raster pixel grid.

    Each validation sample is a single pixel of the raster the model was trained on
    (``resolution`` metres, see ``subkart.features.RESOLUTION``). 
    
    "Mild" errors are those touching class 1 ("blanding", a mixture of the two
    pure classes), "severe" errors are a direct løsbunn <-> fastbunn flip.

    Parameters
    ----------
    max_grid_dim : int
        Upper bound on the rendered grid's largest dimension (pixels). Validation
        points can be scattered across the full extent of Norway's coastline, so
        rendering at the native resolution over that whole bounding box could require
        an unreasonably large array; if needed the grid is coarsened to an integer
        multiple of ``resolution`` (taking the most severe class present in each
        coarsened cell) to stay within this bound. Left untouched (native resolution)
        when the data's extent is small enough.
    region_gdf : GeoDataFrame, optional
        Region polygons (e.g. ``mnk.sources.marine_vanntyper()`` dissolved by
        ``"Region"``) drawn as a translucent overlay with boundaries and labels, so
        errors can be related to marine vanntyper regions. If omitted, no polygons are
        drawn.
    """
    
    resolution = subkart.features.RESOLUTION

    x = np.asarray(coords[:, 0], dtype=float)
    y = np.asarray(coords[:, 1], dtype=float)
    diff = np.abs(np.asarray(y_true) - np.asarray(y_pred))
    # 0=Correct, 1=Mild error, 2=Severe error — used both as colour index and, when
    # cells must be coarsened, as a priority so the most serious class in a cell wins.
    category = np.where(diff == 0, 0, np.where(diff == 1, 1, 2)).astype(np.int8)

    xmin, xmax = x.min(), x.max()
    ymin, ymax = y.min(), y.max()
    n_cols_native = int(round((xmax - xmin) / resolution)) + 1
    n_rows_native = int(round((ymax - ymin) / resolution)) + 1

    agg = max(1, -(-max(n_rows_native, n_cols_native) // max_grid_dim))  # ceil division
    cell_size = resolution * agg

    n_cols = int((xmax - xmin) // cell_size) + 1
    n_rows = int((ymax - ymin) // cell_size) + 1
    col_idx = np.clip(((x - xmin) // cell_size).astype(int), 0, n_cols - 1)
    row_idx = np.clip(((ymax - y) // cell_size).astype(int), 0, n_rows - 1)  # row 0 = north (top)

    grid = np.full((n_rows, n_cols), -1, dtype=np.int8)
    # Sort ascending so, when multiple points fall in the same (coarsened) cell, the
    # most severe category is written last and wins — errors stay visible rather than
    # being averaged away or hidden by co-located correct predictions.
    order = np.argsort(category, kind="stable")
    grid[row_idx[order], col_idx[order]] = category[order]

    colors = {
        0: "#4C8C5B",  # Correct - green
        1: "#F2A93B",  # Mild error - yellow/orange
        2: "#D6412D",  # Severe error - red
    }
    labels = {
        0: "Correct",
        1: "Mild error (adjacent class)",
        2: "Severe error (løsbunn ↔ fastbunn)",
    }
    rgba = np.zeros((n_rows, n_cols, 4))
    for code, hex_color in colors.items():
        rgba[grid == code] = (*mcolors.to_rgb(hex_color), 1.0)
    # Cells with no validation sample stay fully transparent.
    rgba[grid == -1, 3] = 0.0

    counts = np.bincount(category, minlength=3)

    width, height = max(xmax - xmin, 1.0), max(ymax - ymin, 1.0)
    fig_height = 10
    fig_width = max(4.0, min(14.0, fig_height * width / height))
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    ax.imshow(
        rgba,
        extent=(xmin - cell_size / 2, xmin + n_cols * cell_size - cell_size / 2,
                ymax - n_rows * cell_size + cell_size / 2, ymax + cell_size / 2),
        origin="upper",
        interpolation="nearest",
        zorder=1,
    )

    n_regions = len(region_gdf)
    cmap = plt.get_cmap("tab10" if n_regions <= 10 else "tab20")
    region_gdf.plot(
        ax=ax,
        color=[cmap(i % cmap.N) for i in range(n_regions)],
        edgecolor="#333333",
        linewidth=0.8,
        alpha=0.2,
        zorder=2,
    )
    region_col = "Region" if "Region" in region_gdf.columns else region_gdf.columns[0]
    for _, row in region_gdf.iterrows():
        label_point = row.geometry.representative_point()
        ax.annotate(
            str(row[region_col]),
            xy=(label_point.x, label_point.y),
            ha="center",
            va="center",
            fontsize=9,
            fontweight="bold",
            color="#222222",
            zorder=3,
        )

    legend_handles = [
        mpatches.Patch(color=colors[code], label=f"{labels[code]} (n={counts[code]:,})")
        for code in (0, 1, 2)
    ]
    ax.legend(handles=legend_handles, loc="lower left", fontsize=8, framealpha=0.9)

    resolution_note = f"{cell_size:.0f} m pixels" if agg == 1 else f"{cell_size:.0f} m pixels, aggregated {agg}x from {resolution:.0f} m native"
    # Narrow (tall coastline) figures can't fit a long title on one line, so shrink the
    # font and wrap the text to a width proportional to the figure so it never overflows.
    title_fontsize = 14 if fig_width >= 8 else max(9, 14 * fig_width / 8)
    max_chars = max(20, int(fig_width * 7))
    title = "\n".join(textwrap.wrap(
        f"Spatial distribution of validation errors (n={len(category):,} samples, {resolution_note})",
        width=max_chars,
    ))
    ax.set_title(title, fontsize=title_fontsize)
    ax.set_aspect("equal")
    ax.set_axis_off()
    plt.tight_layout()
    plt.show()


def region_performance(region_df):
    """Bar chart comparing accuracy vs. adjusted (class-1-aware) accuracy per region."""
    fig, ax = plt.subplots(figsize=(8, 4))
    x = np.arange(len(region_df))
    width = 0.35
    ax.bar(x - width / 2, region_df["accuracy"], width, label="Accuracy", color="#4e79a7")
    ax.bar(x + width / 2, region_df["adjusted_accuracy"], width, label="Adjusted accuracy", color="#59a14f")
    ax.set_xticks(x)
    ax.set_xticklabels(region_df["region"])
    ax.set_ylim(0, 1)
    ax.set_ylabel("Score")
    ax.set_title("Performance by marine vanntyper region")
    ax.legend()

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    plt.tight_layout()
    plt.show()


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


def inspect_arrays(arrays):
    """Plot feature arrays for inspection."""

    for i, name in enumerate(subkart.features.NAMES):
        plt.figure(figsize=(8, 6))
        plt.imshow(arrays[i], cmap="viridis")
        plt.title(f"Array {name}")
        plt.colorbar()
        plt.show()
