import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import box

from mnk.vectorize import remove_overlaps

CRS = "EPSG:25833"


def _gdf(geoms, **cols):
    return gpd.GeoDataFrame(cols, geometry=geoms, crs=CRS)


def _max_pairwise_overlap(gdf):
    g = gdf.geometry.values
    a, b = shapely.STRtree(g).query(g, predicate="intersects")
    keep = a < b
    return max([0.0] + [g[i].intersection(g[j]).area for i, j in zip(a[keep], b[keep])])


def test_smaller_polygon_inside_larger_wins():
    g = _gdf([box(0, 0, 10, 10), box(4, 4, 6, 6)], v=["big", "small"])
    out = remove_overlaps(g, rank=g.area)
    assert out.set_index("v").area.to_dict() == pytest.approx({"big": 96.0, "small": 4.0})
    assert _max_pairwise_overlap(out) == 0


def test_tie_goes_to_earlier_row():
    g = _gdf([box(0, 0, 4, 4), box(2, 0, 6, 4)], v=["first", "second"])
    out = remove_overlaps(g, rank=np.zeros(2))
    assert out.set_index("v").area.to_dict() == pytest.approx({"first": 16.0, "second": 8.0})


def test_union_is_preserved_with_three_overlapping():
    g = _gdf([box(0, 0, 10, 4), box(3, 0, 7, 8), box(5, 2, 12, 6)], v=[1, 2, 3])
    out = remove_overlaps(g, rank=g.area)
    assert out.area.sum() == pytest.approx(shapely.union_all(g.geometry.values).area)
    assert _max_pairwise_overlap(out) == pytest.approx(0)


def test_fully_covered_polygon_disappears_and_split_ones_are_exploded():
    g = _gdf([box(0, 0, 2, 2), box(0, 0, 9, 1), box(4, -1, 5, 3)], v=["covered", "strip", "bar"])
    out = remove_overlaps(g, rank=[3, 2, 1])  # bar beats strip beats the covered square
    assert "covered" in set(out["v"])  # only partly covered by strip
    strip = out[out["v"] == "strip"]
    assert len(strip) == 2  # bar cuts the strip in two
    assert (out.geom_type == "Polygon").all()

    g2 = _gdf([box(0, 0, 10, 10), box(2, 2, 3, 3)], v=["big", "inside"])
    assert set(remove_overlaps(g2, rank=[1, 2])["v"]) == {"big"}


def test_non_overlapping_input_is_returned_as_is():
    g = _gdf([box(0, 0, 1, 1), box(1, 0, 2, 1), box(5, 5, 6, 6)], v=[1, 2, 3])
    assert remove_overlaps(g, rank=g.area) is g


def test_touching_tiles_are_not_overlaps():
    # A tiled layer (like a vectorised classification) shares edges everywhere.
    tiles = [box(x, y, x + 1, y + 1) for x in range(30) for y in range(30)]
    g = _gdf(tiles, v=np.arange(len(tiles)))
    assert remove_overlaps(g, rank=g.area, chunk=97) is g


def test_chunk_size_does_not_change_the_result():
    rng = np.random.default_rng(3)
    x, y = rng.uniform(0, 50, 300), rng.uniform(0, 50, 300)
    w, h = rng.uniform(1, 6, 300), rng.uniform(1, 6, 300)
    g = _gdf([box(a, b, a + c, b + d) for a, b, c, d in zip(x, y, w, h)], v=np.arange(300))
    whole = remove_overlaps(g, rank=g.area)
    chunked = remove_overlaps(g, rank=g.area, chunk=7)
    key = lambda o: o.assign(a=o.area.round(9)).sort_values(["v", "a"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(key(whole).drop(columns="geometry"), key(chunked).drop(columns="geometry"))
    assert whole.area.sum() == pytest.approx(shapely.union_all(g.geometry.values).area)
    assert _max_pairwise_overlap(whole) == pytest.approx(0, abs=1e-9)


def test_untouched_rows_keep_their_geometry_objects():
    g = _gdf([box(0, 0, 10, 10), box(4, 4, 6, 6), box(20, 20, 21, 21)], v=["big", "small", "far"])
    out = remove_overlaps(g, rank=g.area)
    assert out["v"].tolist()[:2] == ["small", "far"]  # untouched first, trimmed after
    assert out.geometry.iloc[1] is g.geometry.iloc[2]
    assert out.index.equals(pd.RangeIndex(len(out)))
