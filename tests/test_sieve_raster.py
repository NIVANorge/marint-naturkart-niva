import numpy as np
import rasterio
from rasterio.transform import from_origin

from mnk.vectorize import sieve_raster


def _write(path, arr, nodata=0):
    with rasterio.open(
        path, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1,
        dtype="uint8", crs="EPSG:25833", transform=from_origin(0, 100, 10, 10), nodata=nodata,
    ) as dst:
        dst.write(arr, 1)


def _read(path):
    with rasterio.open(path) as src:
        return src.read(1), src.profile


def test_small_regions_take_their_neighbours_value(tmp_path):
    a = np.ones((10, 10), dtype=np.uint8)
    a[2, 2] = 3                # 1-pixel patch
    a[6:8, 6:8] = 2            # 4-pixel patch
    _write(tmp_path / "in.tif", a)
    out, profile = _read(sieve_raster(tmp_path / "in.tif", tmp_path / "out.tif", size=4))
    assert out[2, 2] == 1
    assert (out[6:8, 6:8] == 2).all()
    assert profile["nodata"] == 0 and profile["crs"].to_epsg() == 25833


def test_size_threshold_is_exclusive_of_large_regions(tmp_path):
    a = np.ones((10, 10), dtype=np.uint8)
    a[6:8, 6:8] = 2
    _write(tmp_path / "in.tif", a)
    out, _ = _read(sieve_raster(tmp_path / "in.tif", tmp_path / "out.tif", size=5))
    assert (out == 1).all()


def test_nodata_is_left_alone(tmp_path):
    a = np.ones((10, 10), dtype=np.uint8)
    a[:, :3] = 0               # nodata strip
    a[5, 4] = 3                # small patch next to the nodata strip
    _write(tmp_path / "in.tif", a)
    out, _ = _read(sieve_raster(tmp_path / "in.tif", tmp_path / "out.tif", size=4))
    assert (out[:, :3] == 0).all()
    assert out[5, 4] == 1


def test_source_is_not_modified(tmp_path):
    a = np.ones((5, 5), dtype=np.uint8)
    a[2, 2] = 3
    _write(tmp_path / "in.tif", a)
    sieve_raster(tmp_path / "in.tif", tmp_path / "out.tif", size=2)
    src, _ = _read(tmp_path / "in.tif")
    assert src[2, 2] == 3
