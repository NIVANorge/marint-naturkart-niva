"""Light attenuation (KD490) preprocessing.

Downloads KD490 from CMEMS, mosaics Atlantic and Arctic products,
reprojects to EPSG:25833, fills gaps, and computes the photic zone
classification at DEM resolution.
"""

from pathlib import Path

import numpy as np
import xarray as xr
from osgeo import gdal, osr
from osgeo_utils import gdal_calc

gdal.UseExceptions()

GTIFF_CO = [
    "COMPRESS=DEFLATE", "TILED=YES",
    "BLOCKXSIZE=256", "BLOCKYSIZE=256", "BIGTIFF=IF_SAFER",
]


def merge_kd490_datasets(
    ds_atl: xr.Dataset,
    ds_arc: xr.Dataset,
    lon_range: tuple[float, float],
    lat_range: tuple[float, float],
    res_deg: float = 0.01,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute temporal means of KD490 and mosaic onto a common grid.

    Prefers Atlantic (higher resolution) where available, fills gaps
    with Arctic data.

    Returns
    -------
    kd_merged : 2-D float32 array (lat descending, lon ascending)
    lons : 1-D longitude coordinates
    lats : 1-D latitude coordinates (descending)
    """
    lon_min, lon_max = lon_range
    lat_min, lat_max = lat_range

    kd_atl_mean = ds_atl["KD490"].mean(dim="time", skipna=True).compute()
    kd_arc_mean = ds_arc["KD490"].mean(dim="time", skipna=True).compute()

    lons = np.arange(lon_min, lon_max, res_deg)
    lats = np.arange(lat_max, lat_min, -res_deg)

    kd_atl_interp = kd_atl_mean.interp(
        latitude=xr.DataArray(lats, dims="y"),
        longitude=xr.DataArray(lons, dims="x"),
        method="nearest",
    ).values.astype(np.float32)

    kd_arc_interp = kd_arc_mean.interp(
        latitude=xr.DataArray(lats, dims="y"),
        longitude=xr.DataArray(lons, dims="x"),
        method="nearest",
    ).values.astype(np.float32)

    kd_merged = np.where(np.isfinite(kd_atl_interp), kd_atl_interp, kd_arc_interp)

    print(f"Atlantic valid: {np.sum(np.isfinite(kd_atl_interp)):,}")
    print(f"Arctic valid:   {np.sum(np.isfinite(kd_arc_interp)):,}")
    print(f"Merged valid:   {np.sum(np.isfinite(kd_merged)):,}")

    return kd_merged, lons, lats


def save_wgs84_geotiff(
    data: np.ndarray,
    lons: np.ndarray,
    lats: np.ndarray,
    out_path: str | Path,
    res_deg: float = 0.01,
) -> Path:
    """Save a 2-D array as a WGS84 GeoTIFF."""
    out_path = Path(out_path)
    ny, nx = data.shape
    drv = gdal.GetDriverByName("GTiff")
    ds_out = drv.Create(str(out_path), nx, ny, 1, gdal.GDT_Float32, options=GTIFF_CO)
    ds_out.SetGeoTransform([
        float(lons[0]) - res_deg / 2, res_deg, 0,
        float(lats[0]) + res_deg / 2, 0, -res_deg,
    ])
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds_out.SetProjection(srs.ExportToWkt())
    band = ds_out.GetRasterBand(1)
    band.SetNoDataValue(float("nan"))
    band.WriteArray(data)
    ds_out.FlushCache()
    ds_out = None
    print(f"Saved WGS84 mosaic: {out_path}")
    return out_path


def reproject_to_25833(
    src_path: str | Path,
    out_path: str | Path,
    output_bounds: list[float],
    resolution: int = 1000,
) -> Path:
    """Reproject a raster to EPSG:25833 at the given resolution."""
    out_path = Path(out_path)
    gdal.Warp(
        str(out_path), str(src_path),
        dstSRS="EPSG:25833",
        xRes=resolution, yRes=resolution,
        outputBounds=output_bounds,
        resampleAlg=gdal.GRA_Bilinear,
        srcNodata=float("nan"), dstNodata=float("nan"),
        creationOptions=GTIFF_CO,
    )
    ds = gdal.Open(str(out_path))
    data = ds.GetRasterBand(1).ReadAsArray()
    print(f"KD490 25833 — shape: {data.shape}, valid: {np.sum(np.isfinite(data)):,}/{data.size:,}")
    ds = None
    print(f"Saved (unfilled): {out_path}")
    return out_path


def fill_kd490(
    src_path: str | Path,
    out_path: str | Path,
    output_bounds: list[float],
    fine_search_dist: int = 200,
    coarse_search_dist: int = 500,
    downsample_factor: int = 20,
) -> Path:
    """Fill gaps in a KD490 raster using fine + coarse FillNodata.

    Parameters
    ----------
    src_path : unfilled KD490 raster (EPSG:25833, 1 km).
    out_path : output path for filled raster.
    output_bounds : [xmin, ymin, xmax, ymax] for the output grid.
    fine_search_dist : max pixel search distance for the fine pass.
    coarse_search_dist : max pixel search distance for the coarse pass.
    downsample_factor : downsampling factor for the coarse pass.
    """
    src_path, out_path = Path(src_path), Path(out_path)
    tmp_dir = out_path.parent
    tmp_coarse = tmp_dir / "tmp_kd490_coarse.tif"
    tmp_coarse_up = tmp_dir / "tmp_kd490_coarse_up.tif"

    # Copy source to output for in-place fill
    gdal.GetDriverByName("GTiff").CopyFiles(str(out_path), str(src_path))

    # Fine fill
    print(f"Fine fill (maxSearchDist={fine_search_dist})...")
    ds = gdal.Open(str(out_path), gdal.GA_Update)
    band = ds.GetRasterBand(1)
    gdal.FillNodata(
        band,
        maskBand=band.GetMaskBand(),
        maxSearchDist=fine_search_dist, smoothingIterations=0,
        callback=gdal.TermProgress_nocb,
    )
    ds.FlushCache()
    ds = None

    # Coarse fill: downsample → fill → upsample → merge
    ds_ref = gdal.Open(str(out_path))
    ref_width, ref_height = ds_ref.RasterXSize, ds_ref.RasterYSize
    gt = ds_ref.GetGeoTransform()
    coarse_res = abs(gt[1]) * downsample_factor
    ds_ref = None

    print(f"Coarse fill ({downsample_factor}x downsample, maxSearchDist={coarse_search_dist})...")
    gdal.Warp(
        str(tmp_coarse), str(out_path),
        xRes=coarse_res, yRes=coarse_res,
        resampleAlg=gdal.GRA_Average,
        srcNodata=float("nan"), dstNodata=float("nan"),
        creationOptions=["COMPRESS=DEFLATE"],
    )

    ds_c = gdal.Open(str(tmp_coarse), gdal.GA_Update)
    gdal.FillNodata(
        ds_c.GetRasterBand(1),
        maskBand=ds_c.GetRasterBand(1).GetMaskBand(),
        maxSearchDist=coarse_search_dist, smoothingIterations=0,
        callback=gdal.TermProgress_nocb,
    )
    ds_c.FlushCache()
    ds_c = None

    gdal.Warp(
        str(tmp_coarse_up), str(tmp_coarse),
        width=ref_width, height=ref_height,
        outputBounds=output_bounds,
        resampleAlg=gdal.GRA_Bilinear,
        srcNodata=float("nan"), dstNodata=float("nan"),
        creationOptions=GTIFF_CO,
    )

    # Merge: fine-filled where valid, coarse elsewhere
    gdal_calc.Calc(
        calc="numpy.where(numpy.isnan(A), B, A)",
        outfile=str(out_path),
        A=str(out_path), B=str(tmp_coarse_up),
        type="Float32", NoDataValue=float("nan"), hideNoData=True,
        creation_options=GTIFF_CO,
        overwrite=True,
    )

    for p in [tmp_coarse, tmp_coarse_up]:
        p.unlink(missing_ok=True)

    ds = gdal.Open(str(out_path))
    data = ds.GetRasterBand(1).ReadAsArray()
    print(f"Filled — valid: {np.sum(np.isfinite(data)):,}/{data.size:,}")
    ds = None
    print(f"Saved: {out_path}")
    return out_path


def compute_photic_zone(
    dem_path: str,
    kd_path: str | Path,
    out_path: str | Path,
    output_bounds: list[float],
    dem_xsize: int,
    dem_ysize: int,
) -> Path:
    """Classify pixels as photic (1), aphotic (0), or nodata (-1).

    The photic depth is ln(100)/Kd490 — pixels shallower than this
    threshold are classified as photic.

    Parameters
    ----------
    dem_path : path/URL to the depth DEM (negative values = depth).
    kd_path : filled KD490 raster (will be resampled to DEM grid).
    out_path : output Int16 GeoTIFF path.
    output_bounds : [xmin, ymin, xmax, ymax] matching the DEM extent.
    dem_xsize, dem_ysize : DEM raster dimensions.
    """
    out_path = Path(out_path)
    tmp_kd_resampled = out_path.parent / "tmp_kd490_dem_res.tif"

    # Resample KD490 to DEM grid
    gdal.Warp(
        str(tmp_kd_resampled), str(kd_path),
        dstSRS="EPSG:25833",
        width=dem_xsize, height=dem_ysize,
        outputBounds=output_bounds,
        resampleAlg=gdal.GRA_Bilinear,
        srcNodata=float("nan"), dstNodata=float("nan"),
        creationOptions=GTIFF_CO,
    )
    print(f"KD490 resampled to DEM grid: {dem_xsize} x {dem_ysize}")

    ds_dem = gdal.Open(dem_path)
    ds_kd = gdal.Open(str(tmp_kd_resampled))
    dem_nodata = ds_dem.GetRasterBand(1).GetNoDataValue()

    drv = gdal.GetDriverByName("GTiff")
    ds_out = drv.Create(str(out_path), dem_xsize, dem_ysize, 1, gdal.GDT_Int16, options=GTIFF_CO)
    ds_out.SetGeoTransform(ds_dem.GetGeoTransform())
    ds_out.SetProjection(ds_dem.GetProjection())
    band_out = ds_out.GetRasterBand(1)
    band_out.SetNoDataValue(-1)

    band_dem = ds_dem.GetRasterBand(1)
    band_kd = ds_kd.GetRasterBand(1)
    block_size = 256
    n_photic = 0
    n_aphotic = 0

    for y_off in range(0, dem_ysize, block_size):
        rows = min(block_size, dem_ysize - y_off)
        for x_off in range(0, dem_xsize, block_size):
            cols = min(block_size, dem_xsize - x_off)

            depth = band_dem.ReadAsArray(x_off, y_off, cols, rows).astype(np.float32)
            kd = band_kd.ReadAsArray(x_off, y_off, cols, rows).astype(np.float32)

            depth_abs = np.abs(depth)
            valid = (
                np.isfinite(depth) & np.isfinite(kd)
                & (kd > 0) & (depth_abs > 0)
            )
            if dem_nodata is not None:
                valid &= depth != dem_nodata

            block = np.full((rows, cols), -1, dtype=np.int16)
            if valid.any():
                photic_depth = np.log(100) / kd[valid]
                is_photic = depth_abs[valid] < photic_depth
                block[valid] = np.where(is_photic, 1, 0).astype(np.int16)
                n_photic += int(is_photic.sum())
                n_aphotic += int((~is_photic).sum())

            band_out.WriteArray(block, x_off, y_off)

    band_out.FlushCache()
    ds_out.FlushCache()
    ds_out = None
    ds_dem = None
    ds_kd = None
    tmp_kd_resampled.unlink(missing_ok=True)

    print(f"Photic  pixels: {n_photic:,}")
    print(f"Aphotic pixels: {n_aphotic:,}")
    print(f"Saved: {out_path}")
    return out_path
