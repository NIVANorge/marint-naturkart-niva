import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import geoutils as gu
from sklearn.metrics import ConfusionMatrixDisplay

import subkart
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
