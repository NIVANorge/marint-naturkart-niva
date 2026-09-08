import os
from pathlib import Path

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd
import rasterio as rio
import rasterstats
import shapely
import xdem
from osgeo import gdal
from rasterio import windows as rio_windows
from rasterio.features import rasterize
from shapely.errors import GEOSException
from shapely.geometry import box
from shapely.strtree import STRtree
from shapely.validation import explain_validity, make_valid

import mnk.substrat as subkart
from mnk.substrat.labelling import BUNNTYPE_MAPPING, LM_DK_MAP

GTIFF_OPTIONS = ["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=256", "BLOCKYSIZE=256", "BIGTIFF=IF_SAFER"]
COG_OPTIONS = ["COMPRESS=DEFLATE", "OVERVIEWS=AUTO", "BIGTIFF=IF_SAFER"]

def to_serializable(obj):
    """Convert numpy arrays and other non-serializable types to JSON-serializable formats."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: to_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [to_serializable(item) for item in obj]
    else:
        return obj


def model_dir_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "model"


def load_classifier():
    classifier_path = model_dir_path() / "classifier.joblib"
    classifier = joblib.load(classifier_path)
    return classifier


def resample_dem(dem: xdem.DEM, out_shape: tuple, transform: tuple, crs="EPSG:25833"):
    dst_array = np.empty(out_shape, dtype=dem.data.dtype)

    rio.warp.reproject(
        source=dem.data,
        destination=dst_array,
        src_transform=dem.transform,
        src_crs=dem.crs,
        dst_transform=transform,
        dst_crs=crs,
        src_nodata=dem.nodata,
        dst_nodata=dem.nodata,
        resampling=rio.warp.Resampling.bilinear,
    )

    if dem.nodata is not None:
        dst_array = np.ma.masked_equal(dst_array, dem.nodata)

    return xdem.DEM.from_array(dst_array, transform=transform, crs=crs, nodata=dem.nodata)


def to_cog(src_path: str, dst_path: str) -> None:
    """Convert a GeoTIFF to a Cloud Optimized GeoTIFF, then remove the source."""
    gdal.Translate(dst_path, src_path, format="COG", creationOptions=COG_OPTIONS)
    os.remove(src_path)


def remap_prediction(
    predict_file_unmapped: str,
    prob_file: str,
    predict_file_remapped: str,
    nodata: int = 255,
    block_size: int = 256,
) -> None:
    """Remap class 1 (blanding) to the highest-probability flanking class (0=løsbunn or 2=fastbunn).

    Reads the unmapped prediction and the 3-band probability raster block by block and writes
    a new single-band prediction raster where every blanding pixel is replaced by whichever of
    class 0 or class 2 has the higher probability.
    """
    pred_ds = gdal.Open(predict_file_unmapped)
    prob_ds = gdal.Open(prob_file)

    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(
        predict_file_remapped,
        pred_ds.RasterXSize,
        pred_ds.RasterYSize,
        1,
        gdal.GDT_Byte,
        options=GTIFF_OPTIONS,
    )
    out_ds.SetGeoTransform(pred_ds.GetGeoTransform())
    out_ds.SetProjection(pred_ds.GetProjection())

    out_band = out_ds.GetRasterBand(1)
    out_band.SetNoDataValue(nodata)
    pred_band = pred_ds.GetRasterBand(1)
    prob_band1 = prob_ds.GetRasterBand(1)
    prob_band3 = prob_ds.GetRasterBand(3)

    xsize, ysize = pred_ds.RasterXSize, pred_ds.RasterYSize
    for y in range(0, ysize, block_size):
        ny = min(block_size, ysize - y)
        for x in range(0, xsize, block_size):
            nx = min(block_size, xsize - x)
            A = pred_band.ReadAsArray(x, y, nx, ny)
            B = prob_band1.ReadAsArray(x, y, nx, ny)
            C = prob_band3.ReadAsArray(x, y, nx, ny)
            result = np.where(A == 1, np.where(B >= C, np.uint8(0), np.uint8(2)), A)
            out_band.WriteArray(result, x, y)

    out_ds.FlushCache()
    out_ds = None
    pred_ds = None
    prob_ds = None


def create_probability_raster(
    predict_file_remapped: str,
    prob_file: str,
    prob_file_processed: str,
    nodata: int = 255,
    block_size: int = 256,
) -> None:
    """Create a 1-band normalised probability raster from the 3-band source.

    For each valid pixel the stored value is the probability of the predicted class relative to
    the two non-blanding classes:
      * class 0 (løsbunn): P(class=0) / (P(class=0) + P(class=2))
      * class 2 (fastbunn): P(class=2) / (P(class=0) + P(class=2))
    """
    pred_ds = gdal.Open(predict_file_remapped)
    prob_ds = gdal.Open(prob_file)

    driver = gdal.GetDriverByName("GTiff")
    tmp_path = prob_file_processed + ".tmp.tif"
    out_ds = driver.Create(
        tmp_path,
        pred_ds.RasterXSize,
        pred_ds.RasterYSize,
        1,
        gdal.GDT_Float32,
        options=GTIFF_OPTIONS,
    )
    out_ds.SetGeoTransform(pred_ds.GetGeoTransform())
    out_ds.SetProjection(pred_ds.GetProjection())

    out_band = out_ds.GetRasterBand(1)
    out_band.SetNoDataValue(-9999)
    pred_band = pred_ds.GetRasterBand(1)
    prob_band1 = prob_ds.GetRasterBand(1)
    prob_band3 = prob_ds.GetRasterBand(3)

    xsize, ysize = pred_ds.RasterXSize, pred_ds.RasterYSize
    for y in range(0, ysize, block_size):
        ny = min(block_size, ysize - y)
        for x in range(0, xsize, block_size):
            nx = min(block_size, xsize - x)
            A = pred_band.ReadAsArray(x, y, nx, ny)
            B = prob_band1.ReadAsArray(x, y, nx, ny).astype(np.float32)
            C = prob_band3.ReadAsArray(x, y, nx, ny).astype(np.float32)
            denom = B + C
            result = np.where(A == nodata, np.float32(-9999), np.where(A == 2, C / denom, B / denom))
            out_band.WriteArray(result, x, y)

    out_ds.FlushCache()
    out_ds = None
    pred_ds = None
    prob_ds = None

    to_cog(tmp_path, prob_file_processed)


def filter_isolated_pixels(
    predict_file_remapped: str,
    prob_file_processed: str,
    predict_file: str,
    nodata: int = 255,
    prob_threshold: float = 0.60,
    block_size: int = 256,
) -> None:
    """Replace single isolated pixels whose probability is below *prob_threshold*.

    Uses ``gdal.SieveFilter`` (threshold=2, 4-connected) to identify isolated pixels, then only
    applies the replacement where the normalised probability of the current class is below
    *prob_threshold*.  The probability raster is updated in-place for changed pixels
    (new probability = 1 − old probability).
    """
    driver = gdal.GetDriverByName("GTiff")

    src_ds = gdal.Open(predict_file_remapped)
    sieved_tmp = predict_file + ".sieved.tmp.tif"
    sieved_ds = driver.CreateCopy(sieved_tmp, src_ds, options=GTIFF_OPTIONS)
    gdal.SieveFilter(src_ds.GetRasterBand(1), None, sieved_ds.GetRasterBand(1), threshold=2, connectedness=4)
    sieved_ds.FlushCache()
    sieved_ds = None
    src_ds = None

    pred_orig_ds = gdal.Open(predict_file_remapped)
    pred_sieved_ds = gdal.Open(sieved_tmp)
    prob_ds = gdal.Open(prob_file_processed)

    xsize, ysize = pred_orig_ds.RasterXSize, pred_orig_ds.RasterYSize

    pred_tmp = predict_file + ".tmp.tif"
    pred_out = driver.Create(pred_tmp, xsize, ysize, 1, gdal.GDT_Byte, options=GTIFF_OPTIONS)
    pred_out.SetGeoTransform(pred_orig_ds.GetGeoTransform())
    pred_out.SetProjection(pred_orig_ds.GetProjection())
    pred_out_band = pred_out.GetRasterBand(1)
    pred_out_band.SetNoDataValue(nodata)

    prob_tmp = prob_file_processed + ".tmp.tif"
    prob_out = driver.Create(prob_tmp, xsize, ysize, 1, gdal.GDT_Float32, options=GTIFF_OPTIONS)
    prob_out.SetGeoTransform(prob_ds.GetGeoTransform())
    prob_out.SetProjection(prob_ds.GetProjection())
    prob_out_band = prob_out.GetRasterBand(1)
    prob_out_band.SetNoDataValue(-9999)

    orig_band = pred_orig_ds.GetRasterBand(1)
    sieved_band = pred_sieved_ds.GetRasterBand(1)
    prob_band = prob_ds.GetRasterBand(1)

    for y in range(0, ysize, block_size):
        ny = min(block_size, ysize - y)
        for x in range(0, xsize, block_size):
            nx = min(block_size, xsize - x)
            orig = orig_band.ReadAsArray(x, y, nx, ny)
            sieved = sieved_band.ReadAsArray(x, y, nx, ny)
            prob = prob_band.ReadAsArray(x, y, nx, ny).astype(np.float32)
            apply_change = (orig != sieved) & (orig != nodata) & (prob < prob_threshold)
            pred_out_band.WriteArray(np.where(apply_change, sieved, orig), x, y)
            prob_out_band.WriteArray(np.where(apply_change, 1.0 - prob, prob), x, y)

    pred_out.FlushCache()
    pred_out = None
    pred_orig_ds = None
    pred_sieved_ds = None
    prob_ds = None

    prob_out.FlushCache()
    prob_out = None

    os.remove(sieved_tmp)
    to_cog(pred_tmp, predict_file)
    to_cog(prob_tmp, prob_file_processed)


def sieve_prediction_3class(
    predict_file_unmapped: str,
    prob_file: str,
    predict_file: str,
    nodata: int = 255,
    prob_threshold: float = 0.60,
    block_size: int = 256,
) -> None:
    """Sieve isolated pixels in the 3-class prediction raster in-place (no remap).

    Uses ``gdal.SieveFilter`` (threshold=2, 4-connected) to identify isolated pixels, then
    only accepts the sieved value where the probability of the *original* predicted class
    (looked up from the matching band of the 3-band probability raster) is below
    *prob_threshold*. Output raster preserves all three classes (0/1/2).

    Bands of ``prob_file``: 1 → P(class 0), 2 → P(class 1), 3 → P(class 2).
    """
    driver = gdal.GetDriverByName("GTiff")

    src_ds = gdal.Open(predict_file_unmapped)
    sieved_tmp = predict_file + ".sieved.tmp.tif"
    sieved_ds = driver.CreateCopy(sieved_tmp, src_ds, options=GTIFF_OPTIONS)
    gdal.SieveFilter(
        src_ds.GetRasterBand(1), None, sieved_ds.GetRasterBand(1), threshold=2, connectedness=4
    )
    sieved_ds.FlushCache()
    sieved_ds = None
    src_ds = None

    pred_orig_ds = gdal.Open(predict_file_unmapped)
    pred_sieved_ds = gdal.Open(sieved_tmp)
    prob_ds = gdal.Open(prob_file)

    xsize, ysize = pred_orig_ds.RasterXSize, pred_orig_ds.RasterYSize

    pred_tmp = predict_file + ".tmp.tif"
    pred_out = driver.Create(pred_tmp, xsize, ysize, 1, gdal.GDT_Byte, options=GTIFF_OPTIONS)
    pred_out.SetGeoTransform(pred_orig_ds.GetGeoTransform())
    pred_out.SetProjection(pred_orig_ds.GetProjection())
    pred_out_band = pred_out.GetRasterBand(1)
    pred_out_band.SetNoDataValue(nodata)

    orig_band = pred_orig_ds.GetRasterBand(1)
    sieved_band = pred_sieved_ds.GetRasterBand(1)
    prob_b1 = prob_ds.GetRasterBand(1)
    prob_b2 = prob_ds.GetRasterBand(2)
    prob_b3 = prob_ds.GetRasterBand(3)

    for y in range(0, ysize, block_size):
        ny = min(block_size, ysize - y)
        for x in range(0, xsize, block_size):
            nx = min(block_size, xsize - x)
            orig = orig_band.ReadAsArray(x, y, nx, ny)
            sieved = sieved_band.ReadAsArray(x, y, nx, ny)
            p0 = prob_b1.ReadAsArray(x, y, nx, ny).astype(np.float32)
            p1 = prob_b2.ReadAsArray(x, y, nx, ny).astype(np.float32)
            p2 = prob_b3.ReadAsArray(x, y, nx, ny).astype(np.float32)
            p_orig = np.where(orig == 0, p0, np.where(orig == 1, p1, p2)).astype(np.float32)
            apply_change = (orig != sieved) & (orig != nodata) & (p_orig < prob_threshold)
            pred_out_band.WriteArray(np.where(apply_change, sieved, orig), x, y)

    pred_out.FlushCache()
    pred_out = None
    pred_orig_ds = None
    pred_sieved_ds = None
    prob_ds = None

    os.remove(sieved_tmp)
    to_cog(pred_tmp, predict_file)


def _mean_by_polygon_bands(
    gdf: gpd.GeoDataFrame,
    prob_file: str,
    bands: list[int],
) -> dict[int, np.ndarray]:
    """Compute mean raster value per polygon for each requested band.

    Streams the raster tile-by-tile (native GeoTIFF block windows), rasterises only the
    polygons intersecting each tile with polygon index as the pixel value, and aggregates
    per-polygon sum/count with ``np.bincount``. One pass through the raster; C-speed
    aggregation. Bounded memory: one tile + a per-polygon float64 accumulator.

    Returns a dict mapping band → 1-D array of length ``len(gdf)`` with the mean per polygon
    (NaN where no valid pixels were found).
    """
    geoms = gdf.geometry.values
    n = len(geoms)
    if n == 0:
        return {b: np.array([], dtype="float64") for b in bands}

    tree = STRtree(geoms)
    sums = {b: np.zeros(n + 1, dtype="float64") for b in bands}
    counts = {b: np.zeros(n + 1, dtype="int64") for b in bands}

    with rio.open(prob_file) as src:
        nodata = src.nodata
        transform = src.transform
        for _, win in src.block_windows(1):
            win_bounds = rio_windows.bounds(win, transform)
            win_box = box(*win_bounds)
            hits = tree.query(win_box, predicate="intersects")
            if len(hits) == 0:
                continue
            win_transform = rio_windows.transform(win, transform)
            shapes = [(geoms[int(i)], int(i) + 1) for i in hits]
            lbl = rasterize(
                shapes,
                out_shape=(int(win.height), int(win.width)),
                transform=win_transform,
                fill=0,
                dtype="uint32",
                all_touched=False,
            )
            mask = lbl > 0
            if not mask.any():
                continue
            for b in bands:
                data = src.read(b, window=win)
                if nodata is not None:
                    m = mask & (data != nodata)
                else:
                    m = mask
                if not m.any():
                    continue
                lbl_v = lbl[m]
                vals = data[m].astype("float64", copy=False)
                sums[b] += np.bincount(lbl_v, weights=vals, minlength=n + 1)
                counts[b] += np.bincount(lbl_v, minlength=n + 1)

    result = {}
    for b in bands:
        c = counts[b][1:]
        s = sums[b][1:]
        out = np.full(n, np.nan, dtype="float64")
        valid = c > 0
        out[valid] = s[valid] / c[valid]
        result[b] = out
    return result


def assign_bunn_lmdk_from_3band(
    gdf: gpd.GeoDataFrame,
    prob_file: str,
    dn_col: str = "DN",
) -> gpd.GeoDataFrame:
    """Attach BunnType, LM_DK, Sannsynlighet_LM_DK using the 3-band probability raster.

    Input polygons must carry a ``DN`` column with raw model classes (0/1/2). For DN∈{0,2}
    the polygon keeps its class. For DN=1 (blanding) the winner between P(0) and P(2) is
    picked per polygon for ``BunnType`` and ``DN``, but ``LM_DK`` stays ``DK_0``.

    ``Sannsynlighet_LM_DK`` is the raw (unnormalised) mean probability of the assigned
    **LM_DK** class per polygon, not the BunnType class. So a DK_0 polygon reports
    ``mean P(blanding)``, a DK_AB/C/D polygon reports ``mean P(løsbunn)``, and a DK_EFGY
    polygon reports ``mean P(fastbunn)``. Aggregation uses a single tiled bincount pass
    over all three bands.

    Bands of ``prob_file``: 1 → P(class 0), 2 → P(class 1), 3 → P(class 2).
    """
    reverse = {v: k for k, v in BUNNTYPE_MAPPING.items()}
    gdf = gdf.reset_index(drop=True).copy()
    gdf["BunnType"] = gdf[dn_col].map(reverse)
    gdf["LM_DK"] = gdf["BunnType"].map(LM_DK_MAP)

    means = _mean_by_polygon_bands(gdf, prob_file, bands=[1, 2, 3])
    m0 = means[1]  # P(løsbunn)
    m1 = means[2]  # P(blanding)  → probability for LM_DK == DK_0
    m2 = means[3]  # P(fastbunn)

    dn = gdf[dn_col].to_numpy()
    bl = dn == 1
    if bl.any():
        win_los = m0[bl] >= m2[bl]
        gdf.loc[bl, "BunnType"] = np.where(win_los, "løsbunn", "fastbunn")
        gdf.loc[bl, dn_col] = np.where(win_los, 0, 2).astype(gdf[dn_col].dtype)
        # LM_DK stays "DK_0" for these rows.

    # Sannsynlighet reflects the LM_DK class probability:
    # DK_AB,C,D → m0; DK_0 → m1; DK_EFGY → m2.
    lmdk = gdf["LM_DK"].to_numpy()
    sanns = np.where(lmdk == "DK_0", m1,
             np.where(lmdk == "DK_EFGY", m2, m0))
    gdf["Sannsynlighet_LM_DK"] = sanns * 100
    return gdf


def merge_rasters(file_list: list[Path], fname: Path, nodata):
    """Merge multiple raster files into one using GDAL."""

    gdal.UseExceptions()
    nodata = float(nodata)  # GDAL requires a Python float; numpy scalars (e.g. float16) cause overview dtype mismatches
    src_ds_list = [gdal.Open(f, gdal.GA_ReadOnly) for f in file_list]

    vrt_options = gdal.BuildVRTOptions(
        srcNodata=nodata,
        VRTNodata=nodata,
    )
    vrt_ds = gdal.BuildVRT("/vsimem/merged.vrt", src_ds_list, options=vrt_options)

    translate_options = gdal.TranslateOptions(
        format="GTiff",
        creationOptions=["COMPRESS=DEFLATE", "TILED=YES"],
        noData=nodata,
    )
    gdal.Translate(fname, vrt_ds, options=translate_options)


def to_geoparquet(input_gml_path: Path, layer_name: str, output_path: Path):
    """Save GML Download from NGU as GeoParquet

    Geoparquet is a really nice format for geospatial data optimized for cloud access.

    """
    gdf = gpd.read_file(input_gml_path, layer=layer_name)
    gdf.to_parquet(output_path, compression="snappy")
    print(f"Written GeoParquet to {output_path}")


def save_feature_rasters(
    out_dir: Path,
    prefix: str,
    X: np.ndarray,
    valid_mask: np.ndarray,
    transform: tuple,
    out_shape: tuple,
    nodata: float,
    crs: str = "EPSG:25833",
):
    """
    Save each feature array as a separate GeoTIFF file.
    """
    for i, feature_name in enumerate(subkart.features.DEPTH_NAMES):
        band = np.full(out_shape, nodata, dtype=np.float32)
        band[valid_mask] = X[:, i]
        out_path = out_dir / f"{prefix}_{feature_name}.tif"
        with rio.open(
            out_path,
            "w",
            driver="GTiff",
            height=out_shape[0],
            width=out_shape[1],
            count=1,
            dtype=np.float32,
            crs=crs,
            transform=transform,
            nodata=nodata,
        ) as dst:
            dst.write(band, 1)
