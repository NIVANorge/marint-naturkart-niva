import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from mnk.vectorize import overlay_update

CRS = "EPSG:25833"


def _base():
    # A: [0,2]x[0,1] (v=1), B: [5,6]x[0,1] (v=2), far from the mask.
    return gpd.GeoDataFrame({"v": [1, 2]}, geometry=[box(0, 0, 2, 1), box(5, 0, 6, 1)], crs=CRS)


def _mask(*boxes, **cols):
    return gpd.GeoDataFrame(cols, geometry=list(boxes), crs=CRS)


def _set_v(value):
    return lambda p: p.assign(v=value)


def test_inside_is_updated_outside_keeps_attributes():
    out = overlay_update(_base(), _mask(box(1, -1, 3, 2)), _set_v(9))
    a = out[out.geometry.within(box(0, 0, 2, 1))]
    assert sorted(zip(a["v"], a.area.round(6))) == [(1, 1.0), (9, 1.0)]
    piece = out.loc[out["v"] == 9].geometry.iloc[0]
    assert piece.symmetric_difference(box(1, 0, 2, 1)).area < 1e-9
    assert out.area.sum() == pytest.approx(_base().area.sum())


def test_untouched_rows_pass_through_unchanged():
    base = _base()
    out = overlay_update(base, _mask(box(1, -1, 3, 2)), _set_v(9))
    b = out[out["v"] == 2]
    assert len(b) == 1
    assert b.geometry.iloc[0] is base.geometry.iloc[1]


def test_where_excludes_candidates():
    base = _base()
    out = overlay_update(base, _mask(box(1, -1, 3, 2)), _set_v(9), where=base["v"] == 2)
    assert sorted(out["v"]) == [1, 2]
    assert out.area.sum() == pytest.approx(base.area.sum())


def test_update_sees_only_inside_pieces_and_mask_columns():
    seen = {}

    def update(p):
        seen["n"] = len(p)
        seen["cols"] = set(p.columns)
        seen["within"] = bool(p.geometry.within(box(1, -1, 3, 2)).all())
        return p.assign(v=p["k"])

    out = overlay_update(_base(), _mask(box(1, -1, 3, 2), k=[7]), update)
    assert seen == {"n": 1, "cols": {"v", "k", "geometry"}, "within": True}
    assert "k" not in out.columns
    assert sorted(out["v"]) == [1, 2, 7]


def test_colliding_mask_column_gets_suffix():
    out = overlay_update(_base(), _mask(box(1, -1, 3, 2), v=[5]), lambda p: p.assign(v=p["v_2"]))
    assert sorted(out["v"]) == [1, 2, 5]
    assert "v_2" not in out.columns


def test_columns_added_by_update_are_kept():
    out = overlay_update(_base(), _mask(box(1, -1, 3, 2)), lambda p: p.assign(flag="in"))
    assert list(out.columns) == ["v", "geometry", "flag"]
    assert out.loc[out["flag"] == "in", "v"].tolist() == [1]
    assert out["flag"].isna().sum() == 2


def test_update_can_drop_rows():
    out = overlay_update(_base(), _mask(box(1, -1, 3, 2)), lambda p: p.iloc[0:0])
    assert out.area.sum() == pytest.approx(_base().area.sum() - 1.0)


def test_overlapping_mask_duplicates_without_dissolve_and_merges_with():
    mask = _mask(box(1, -1, 3, 2), box(1.5, -1, 3, 2))
    dup = overlay_update(_base(), mask, _set_v(9))
    assert dup.loc[dup["v"] == 9].area.sum() == pytest.approx(1.5)

    merged = overlay_update(_base(), mask, _set_v(9), dissolve=True)
    nine = merged[merged["v"] == 9]
    assert len(nine) == 1
    assert nine.area.sum() == pytest.approx(1.0)
    assert merged.area.sum() == pytest.approx(_base().area.sum())


def test_dissolve_keeps_different_attributes_apart():
    mask = _mask(box(0.5, -1, 1.2, 2), box(1.2, -1, 3, 2), k=[3, 4])
    out = overlay_update(_base(), mask, lambda p: p.assign(v=p["k"]), dissolve=True)
    assert sorted(out["v"]) == [1, 2, 3, 4]


def test_dissolve_handles_na_attributes():
    base = gpd.GeoDataFrame(
        {"v": [1], "s": pd.array([None], dtype="string")}, geometry=[box(0, 0, 2, 1)], crs=CRS
    )
    mask = _mask(box(0.5, -1, 1.0, 2), box(1.0, -1, 1.5, 2))
    out = overlay_update(base, mask, _set_v(9), dissolve=True)
    assert len(out[out["v"] == 9]) == 1
    assert out.area.sum() == pytest.approx(2.0)


def test_no_hits_returns_base_rows():
    base = _base()
    out = overlay_update(base, _mask(box(100, 100, 101, 101)), _set_v(9))
    assert out["v"].tolist() == [1, 2]
    assert out.geometry.geom_equals(base.geometry).all()


def test_result_is_single_polygons_on_range_index():
    # The mask cuts A's middle, leaving a two-part outside remainder.
    base = gpd.GeoDataFrame({"v": [1]}, geometry=[box(0, 0, 3, 1)], crs=CRS, index=[42])
    out = overlay_update(base, _mask(box(1, -1, 2, 2)), _set_v(9))
    assert (out.geom_type == "Polygon").all()
    assert out.index.equals(pd.RangeIndex(len(out)))
    assert sorted(out["v"]) == [1, 1, 9]
    assert out.crs == base.crs
