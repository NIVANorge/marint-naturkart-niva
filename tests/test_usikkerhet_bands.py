import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

import mnk.utils as U
from mnk.attributes import usikkerhet_from_band

LAV, MED, HOY = 1, 2, 3


# per-pixel margins and bands


@pytest.mark.parametrize(
    "sal,brakk,band",
    [
        (25.0, False, LAV),   # +7 PSU on the salt side
        (24.0, False, LAV),   # exactly the lav threshold (6)
        (21.0, False, MED),   # +3
        (20.0, False, MED),   # exactly the høy threshold (2) is still medium
        (19.0, False, HOY),   # +1
        (16.0, False, HOY),   # salt class but brackish water: wrong side
        (10.0, True, LAV),    # +8 on the brakk side
        (20.0, True, HOY),    # brakk class but salt water
        (np.nan, False, HOY), # no salinity data: the class is a guess
    ],
)
def test_salinity_band(sal, brakk, band):
    m = U.salinity_margin(np.array([sal]), np.array([brakk]))
    assert U.margin_band(m, *U.USIKKERHET_SAL).tolist() == [band]


def test_light_margin_and_band():
    kd = np.full(6, 0.1)  # z_eu = ln(100) / 0.1 ≈ 46 m
    depth = np.array([10.0, 40.0, 50.0, 100.0, 45.0, np.nan])
    euf = np.array([True, True, True, False, False, True])
    m = U.light_margin(kd, depth, euf)
    z = U.EUPHOTIC_LN / 0.1
    assert m[:4] == pytest.approx([(z - 10) / z, (z - 40) / z, (z - 50) / z, (100 - z) / z])
    assert U.margin_band(m, *U.USIKKERHET_LYS).tolist() == [LAV, MED, HOY, LAV, HOY, HOY]


@pytest.mark.parametrize("kd", [0.0, -1.0, np.nan])
def test_light_without_kd_is_hoy(kd):
    m = U.light_margin(np.array([kd]), np.array([5.0]), np.array([True]))
    assert U.margin_band(m, *U.USIKKERHET_LYS).tolist() == [HOY]


def test_substrate_margin_sign_follows_class():
    soft, hard = np.array([0.8, 0.8]), np.array([0.1, 0.1])
    assert U.substrate_margin(soft, hard, np.array([False, True])) == pytest.approx([0.7, -0.7])


def test_margin_band_dtype_and_shape():
    out = U.margin_band(np.array([[0.5, np.nan], [0.2, -1.0]]), 0.4, 0.1)
    assert out.dtype == np.uint8
    assert out.tolist() == [[LAV, HOY], [MED, HOY]]


# polygon summary


@pytest.mark.parametrize(
    "counts,band",
    [
        ([10, 0, 0], LAV),
        ([8, 0, 2], LAV),    # 20 % høy < 25 %
        ([7, 0, 3], HOY),    # 30 % høy
        ([7, 2, 1], MED),    # 30 % medium or høy, 10 % høy
        ([0, 10, 0], MED),
        ([0, 0, 0], 0),      # no pixels
    ],
)
def test_band_from_shares(counts, band):
    assert U.band_from_shares(np.array(counts).reshape(3, 1)).tolist() == [band]


def test_band_from_shares_custom_share():
    counts = np.array([[9], [0], [1]])
    assert U.band_from_shares(counts, share=0.1).tolist() == [HOY]


def test_usikkerhet_from_band_labels():
    out = usikkerhet_from_band([1, 2, 3, 0])
    assert out.tolist()[:3] == ["lav", "medium", "høy"]
    assert pd.isna(out.iloc[3])
    assert str(out.dtype) == "string"


# polygon_usikkerhet on small rasters


def _tif(path, arr, nodata, transform=None):
    arr = arr if arr.ndim == 3 else arr[None]
    with rasterio.open(
        path, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=arr.shape[0],
        dtype="float32", crs="EPSG:25833", transform=transform or from_origin(0, 100, 10, 10), nodata=nodata,
    ) as dst:
        dst.write(arr.astype("float32"))
    return str(path)


@pytest.fixture
def rasters(tmp_path):
    """20 x 10 m grid, 10 m pixels; row 9 (y 0-10) is nodata.

    Columns 0-9 are clear on both axes (soft bottom; 10 m deep, well inside the
    ~46 m euphotic depth), columns 10-19 undecided (soft ≈ hard; 45 m deep).
    Kd490 comes on a coarser, offset grid and is warped.
    """
    soft = np.full((10, 20), 0.9, dtype="float32")
    hard = np.full((10, 20), 0.05, dtype="float32")
    soft[:, 10:], hard[:, 10:] = 0.45, 0.5
    soft[9, :], hard[9, :] = -9999, -9999
    depth = np.full((10, 20), -10.0, dtype="float32")
    depth[:, 10:] = -45.0
    depth[9, :] = 99999
    return dict(
        subprob_path=_tif(tmp_path / "subprob.tif", np.stack([soft, 1 - soft - hard, hard]), -9999),
        depth_path=_tif(tmp_path / "depth.tif", depth, 99999),
        kd_path=_tif(tmp_path / "kd.tif", np.full((3, 5), 0.1), float("nan"), from_origin(-50, 150, 60, 60)),
    )


def _polys(*boxes):
    return gpd.GeoDataFrame(geometry=list(boxes), crs="EPSG:25833")


def _run(rasters, geoms, fast, euf, **kw):
    out = U.polygon_usikkerhet(_polys(*geoms), fast=fast, eufotisk=euf, progress=False, **rasters, **kw)
    return out["substrat"].tolist(), out["lys"].tolist()


@pytest.mark.parametrize(
    "geom,fast,euf,sub,lys",
    [
        (box(0, 10, 100, 100), False, True, LAV, LAV),     # clear area, classes agree
        (box(0, 10, 100, 100), True, False, HOY, HOY),     # clear area, both classes on the wrong side
        (box(100, 10, 200, 100), False, True, HOY, HOY),   # undecided area
        (box(0, 10, 130, 100), False, True, LAV, LAV),     # 3 of 13 columns undecided: 23 % høy
        (box(0, 10, 150, 100), False, True, HOY, HOY),     # 5 of 15 columns undecided: 33 % høy
        (box(31, 51, 33, 53), False, True, LAV, LAV),      # smaller than a pixel: representative point
        (box(500, 500, 510, 510), False, True, 0, 0),      # outside the grid
    ],
)
def test_polygon_usikkerhet_single_polygon(rasters, geom, fast, euf, sub, lys):
    assert _run(rasters, [geom], [fast], [euf], block=7) == ([sub], [lys])


def test_polygon_usikkerhet_partition_in_one_call(rasters):
    # Non-overlapping polygons, as after the 03b overlays.
    g = [box(0, 10, 60, 100), box(60, 10, 140, 100), box(140, 10, 200, 100)]
    assert _run(rasters, g, [False] * 3, [True] * 3, block=7) == ([LAV, HOY, HOY], [LAV, HOY, HOY])


def test_polygon_usikkerhet_nodata_counts_as_hoy(rasters):
    # Half of the pixels lie in the nodata row of both substrate and depth.
    assert _run(rasters, [box(0, 0, 100, 20)], [False], [True]) == ([HOY], [HOY])


def test_polygon_usikkerhet_observed_substrate_is_lav(rasters):
    g = [box(100, 10, 150, 100), box(150, 10, 200, 100)]
    assert _run(rasters, g, [False, False], [True, True], is_obs=[True, False]) == ([LAV, HOY], [HOY, HOY])


def test_polygon_usikkerhet_block_size_does_not_matter(rasters):
    g = [box(0, 10, 70, 100), box(70, 10, 175, 100), box(181, 51, 183, 53)]
    a = _run(rasters, g, [False, False, True], [True, True, False], block=3)
    b = _run(rasters, g, [False, False, True], [True, True, False], block=1024)
    assert a == b


def test_polygon_usikkerhet_requires_depth_on_the_probability_grid(rasters, tmp_path):
    rasters["depth_path"] = _tif(tmp_path / "depth2.tif", np.full((5, 5), -10.0), 99999, from_origin(0, 100, 20, 20))
    with pytest.raises(ValueError, match="share the grid"):
        _run(rasters, [box(0, 10, 100, 100)], [False], [True])


# decoding the 03a raster value in 03b


def test_from_raster_class_decodes_axes_and_salinity_band():
    import mnk.rules as R
    from mnk.attributes import from_raster_class

    code = R.encode_raster_class([7, 12], [3, 1])  # 7 = eufotisk salt løst, 12 = afotisk salt fast
    out = from_raster_class(pd.Series(code, index=[40, 41]))
    assert out.index.tolist() == [40, 41]
    assert out.loc[40, R.COL_LYS] == R.NKM_LYS["eufotisk"]
    assert out.loc[41, R.COL_SUBSTRAT] == R.NKM_SUBSTRAT["fast"]
    assert out["nkm_usikkerhet_salinitet"].tolist() == ["høy", "lav"]
    assert "nkm_usikkerhet_lys" not in out


def test_from_raster_class_rejects_unbanded_03a_output():
    from mnk.attributes import from_raster_class

    with pytest.raises(ValueError, match="rerun 03a"):
        from_raster_class(pd.Series([5, 12]))
