"""Model evaluation utilities.

The three bottom-type classes used throughout this project are not
independent categories: class 1 ("blanding") is a genuine physical *mixture*
of class 0 ("løsbunn") and class 2 ("fastbunn") — see
``subkart.utils.remap_prediction``, which resolves "blanding" pixels back to
whichever pure class is most probable. Because of this, confusing class 1
with its neighbour (0 or 2) is a much milder mistake than flipping between the
two pure classes directly (0 <-> 2): the pixel plausibly does contain some of
the predicted material either way.

The helpers below provide metrics/plots that are aware of this ordinal
structure, on top of the standard accuracy/precision/recall figures.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, cohen_kappa_score

CLASS_NAMES = {0: "løsbunn", 1: "blanding", 2: "fastbunn"}

# Severity cost of predicting `pred` when the true label is `true` (rows=true, cols=pred).
# Diagonal = 0 (correct). Errors touching class 1 ("blanding") are cheap since 1 is a
# physical mixture of 0 and 2. The only "real" error is confusing the two pure classes.
DEFAULT_COST_MATRIX = np.array(
    [
        [0.0, 0.25, 1.0],
        [0.25, 0.0, 0.25],
        [1.0, 0.25, 0.0],
    ]
)


def adjusted_accuracy(y_true, y_pred, cost_matrix: np.ndarray = DEFAULT_COST_MATRIX) -> float:
    """1 - mean severity-weighted error cost (see ``DEFAULT_COST_MATRIX``).

    Unlike plain accuracy, a "blanding" pixel misclassified as "løsbunn" or
    "fastbunn" (or vice versa) only counts as a small (0.25) error instead of a
    full miss, reflecting that "blanding" is a mixture of the two.
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    costs = cost_matrix[y_true, y_pred]
    return float(1.0 - costs.mean())


def tolerant_accuracy(y_true, y_pred, tolerance: int = 1) -> float:
    """Fraction of predictions within `tolerance` classes of the truth."""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    return float((np.abs(y_true - y_pred) <= tolerance).mean())


def severe_error_rate(y_true, y_pred) -> float:
    """Fraction of predictions that flip between the two pure classes (løsbunn <-> fastbunn)."""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    return float((np.abs(y_true - y_pred) == 2).mean())


def summarize_metrics(y_true, y_pred, cost_matrix: np.ndarray = DEFAULT_COST_MATRIX) -> pd.Series:
    """One-row summary comparing plain vs. class-1-aware performance metrics."""
    return pd.Series(
        {
            "accuracy": accuracy_score(y_true, y_pred),
            "adjusted_accuracy": adjusted_accuracy(y_true, y_pred, cost_matrix),
            "tolerant_accuracy (±1 class)": tolerant_accuracy(y_true, y_pred),
            "severe_error_rate (løsbunn<->fastbunn)": severe_error_rate(y_true, y_pred),
            "cohen_kappa": cohen_kappa_score(y_true, y_pred),
            "cohen_kappa (linear weighted)": cohen_kappa_score(y_true, y_pred, weights="linear"),
            "cohen_kappa (quadratic weighted)": cohen_kappa_score(y_true, y_pred, weights="quadratic"),
        }
    )


def performance_by_region(
    y_true, y_pred, region_labels, cost_matrix: np.ndarray = DEFAULT_COST_MATRIX
) -> pd.DataFrame:
    """Per-region accuracy / adjusted accuracy table for spatial performance analysis."""
    df = pd.DataFrame({"y_true": np.asarray(y_true), "y_pred": np.asarray(y_pred), "region": np.asarray(region_labels)})
    rows = []
    for region, g in df.groupby("region"):
        rows.append(
            {
                "region": region,
                "n_samples": len(g),
                "accuracy": accuracy_score(g["y_true"], g["y_pred"]),
                "adjusted_accuracy": adjusted_accuracy(g["y_true"].to_numpy(), g["y_pred"].to_numpy(), cost_matrix),
                "severe_error_rate": severe_error_rate(g["y_true"].to_numpy(), g["y_pred"].to_numpy()),
            }
        )
    return pd.DataFrame(rows).sort_values("region").reset_index(drop=True)
