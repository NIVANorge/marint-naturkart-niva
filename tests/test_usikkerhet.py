import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from mnk.attributes import NIN_FLATE_COLUMNS, USIKKERHET_AXIS_COLS, add_nkm_attributes
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


def test_add_nkm_attributes_writes_axis_columns():
    gdf = gpd.GeoDataFrame(
        {"nin_int": [2] * 4, "nin_kode_fkid": ["NA-MA04"] * 4},
        geometry=[box(i, 0, i + 1, 1) for i in range(4)],
        crs="EPSG:25833",
        index=[10, 11, 12, 13],
    )
    out = add_nkm_attributes(gdf, usikkerhet=usikkerhet_table(MEANS))
    cols = ["nkm_usikkerhetsklasse", *USIKKERHET_AXIS_COLS]
    assert [c for c in out.columns if c in cols] == cols
    assert [c for c in out.columns if c != "geometry"] == [c for c in NIN_FLATE_COLUMNS if c in out]
    assert out["nkm_usikkerhet_lys"].tolist()[:3] == ["lav", "høy", "lav"]
    assert pd.isna(out["nkm_usikkerhet_substrat"].iloc[3])


def test_add_nkm_attributes_accepts_plain_array():
    gdf = gpd.GeoDataFrame(
        {"nin_int": [2], "nin_kode_fkid": ["NA-MA04"]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:25833"
    )
    out = add_nkm_attributes(gdf, usikkerhet=np.array(["høy"], dtype=object))
    assert out["nkm_usikkerhetsklasse"].tolist() == ["høy"]
    assert not set(USIKKERHET_AXIS_COLS) & set(out.columns)


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
