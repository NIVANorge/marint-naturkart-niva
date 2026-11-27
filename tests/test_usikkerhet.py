import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from mnk.attributes import USIKKERHET_AXIS_COLS
from mnk.utils import usikkerhet_axis_classes, usikkerhet_from_margins, usikkerhet_table

# Columns: lav on every axis, høy on light only, medium substrate, no data at all.
MEANS = np.array([
    [0.9, 0.9, 0.2, np.nan],
    [0.5, 0.05, 0.5, np.nan],
    [10.0, 10.0, 10.0, np.nan],
])


def test_axis_classes_per_axis():
    axes = usikkerhet_axis_classes(MEANS)
    assert axes.tolist() == [[1, 1, 2, 0], [1, 3, 1, 0], [1, 1, 1, 0]]


def test_is_obs_forces_substrate_only():
    means = np.array([[0.0], [0.0], [0.0]])
    axes = usikkerhet_axis_classes(means, is_obs=np.array([True]))
    assert axes[:, 0].tolist() == [1, 3, 3]


def test_combined_is_worst_axis():
    assert usikkerhet_from_margins(MEANS).tolist() == ["lav", "høy", "medium", "medium"]


def test_table_columns_and_na():
    t = usikkerhet_table(MEANS)
    assert list(t.columns) == ["nkm_usikkerhetsklasse", *USIKKERHET_AXIS_COLS]
    assert t["nkm_usikkerhetsklasse"].tolist() == usikkerhet_from_margins(MEANS).tolist()
    assert t["nkm_usikkerhet_lys"].iloc[:3].tolist() == ["lav", "høy", "lav"]
    assert t.iloc[3][list(USIKKERHET_AXIS_COLS)].isna().all()
    assert t.iloc[3]["nkm_usikkerhetsklasse"] == "medium"


def test_worst_usikkerhet_ignores_na_and_defaults():
    from mnk.attributes import worst_usikkerhet

    axes = pd.DataFrame(
        {
            "a": ["lav", "lav", None, None],
            "b": ["høy", None, "medium", None],
            "c": ["lav", "lav", None, None],
        },
        index=[5, 6, 7, 8],
    ).astype("string")
    out = worst_usikkerhet(axes)
    assert out.index.tolist() == [5, 6, 7, 8]
    assert out.tolist() == ["høy", "lav", "medium", "medium"]


def test_worst_usikkerhet_matches_table():
    from mnk.attributes import worst_usikkerhet

    t = usikkerhet_table(MEANS)
    assert worst_usikkerhet(t[list(USIKKERHET_AXIS_COLS)]).tolist() == t["nkm_usikkerhetsklasse"].tolist()
