import geopandas as gpd
import numpy as np
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


def test_non_overlapping_input_is_unchanged():
    g = _gdf([box(0, 0, 1, 1), box(1, 0, 2, 1), box(5, 5, 6, 6)], v=[1, 2, 3])
    out = remove_overlaps(g, rank=g.area)
    assert out["v"].tolist() == [1, 2, 3]
    assert out.geometry.geom_equals(g.geometry).all()
