"""Light attenuation (KD490) preprocessing.

Reprojects KD490_2024.tif to EPSG:25833, fills missing values inside the
marine vanntyper AOI clipped to Møre og Romsdal latitude bounds, and saves
the result as KD490_2024_filled_25833.tif.
"""

import math
from pathlib import Path

import geopandas as gpd
import numpy as np
from osgeo import gdal
from osgeo_utils import gdal_calc
from shapely.geometry import box

CRS = "EPSG:25833"
RESOLUTION = 1000  # metres

# Møre og Romsdal northing bounds in EPSG:25833 (lat 61.9°N – 63.5°N)
NORTHING_MIN = 6_873_000
NORTHING_MAX = 7_052_000

AOI_FILL_URL = "gs://niva-geodata/MarintNaturKart/aux/aoi_from_marine_vanntyper.geo.parquet"


def fill_kd490(
    src_path: Path | str,
    out_path: Path | str,
    aoi_url: str = AOI_FILL_URL,
    resolution: int = RESOLUTION,
    northing_min: int = NORTHING_MIN,
    northing_max: int = NORTHING_MAX,
    fine_search_dist: int = 200,
    coarse_search_dist: int = 500,
    downsample_factor: int = 20,
) -> Path:
    """Reproject, fill and mask KD490 raster.

    Parameters
    ----------
    src_path:
        Input KD490 raster (any CRS).
    out_path:
        Output path for the filled EPSG:25833 raster.
    aoi_url:
        URL/path to marine vanntyper AOI parquet (fill boundary).
    resolution:
        Output pixel size in metres.
    northing_min / northing_max:
        EPSG:25833 northing bounds to restrict the fill area.
    fine_search_dist:
        FillNodata max search distance (pixels) for fine pass.
    coarse_search_dist:
        FillNodata max search distance (pixels) for coarse pass.
    downsample_factor:
        Factor by which to downsample for the coarse fill pass.

    Returns
    -------
    Path to the output raster.
    """
    gdal.UseExceptions()
    src_path = Path(src_path)
    out_path = Path(out_path)
    tmp_dir = out_path.parent

    tmp_projected   = tmp_dir / "tmp_kd490_25833.tif"
    tmp_fill_gpkg   = tmp_dir / "tmp_kd490_fill_aoi.gpkg"
    tmp_fill_mask   = tmp_dir / "tmp_kd490_fill_mask.tif"
    tmp_filled      = tmp_dir / "tmp_kd490_to_fill.tif"
    tmp_coarse      = tmp_dir / "tmp_kd490_coarse.tif"
    tmp_coarse_up   = tmp_dir / "tmp_kd490_coarse_up.tif"

    try:
        # --- AOI -------------------------------------------------------
        print("Loading fill AOI...")
        aoi_all = gpd.read_parquet(aoi_url).to_crs(CRS)
        mr_bbox = gpd.GeoDataFrame(
            geometry=[box(aoi_all.total_bounds[0], northing_min,
                          aoi_all.total_bounds[2], northing_max)],
            crs=CRS,
        )
        aoi = gpd.overlay(aoi_all, mr_bbox, how="intersection")
        print(f"  {len(aoi)} features, bounds: {aoi.total_bounds}")

        b = aoi.total_bounds
        snap = resolution
        minx = math.floor(b[0] / snap) * snap
        miny = math.floor(b[1] / snap) * snap
        maxx = math.ceil(b[2]  / snap) * snap
        maxy = math.ceil(b[3]  / snap) * snap
        # Expand by one pixel on each side so pixels that touch (but whose
        # centre lies outside) the AOI outline are included in the output.
        bounds = [minx - resolution, miny - resolution, maxx + resolution, maxy + resolution]

        # --- Step 1: reproject -----------------------------------------
        print(f"Reprojecting to {CRS} at {resolution} m...")
        gdal.Warp(
            str(tmp_projected), str(src_path),
            dstSRS=CRS, xRes=resolution, yRes=resolution,
            outputBounds=bounds,
            resampleAlg=gdal.GRA_Bilinear,
            srcNodata=float("nan"), dstNodata=float("nan"),
            creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512"],
        )
        with gdal.Open(str(tmp_projected)) as ds:
            src_width  = ds.RasterXSize
            src_height = ds.RasterYSize
            data = ds.GetRasterBand(1).ReadAsArray()
        print(f"  Shape: {src_width}x{src_height}, NaN: {np.sum(np.isnan(data))}/{data.size}")

        # --- Step 2: rasterize fill mask --------------------------------
        print("Rasterizing fill AOI mask...")
        aoi[["geometry"]].dissolve().to_file(tmp_fill_gpkg, driver="GPKG", layer="aoi")
        ds = gdal.Rasterize(
            str(tmp_fill_mask), str(tmp_fill_gpkg), layers=["aoi"],
            burnValues=[1], outputType=gdal.GDT_Byte, initValues=[0], noData=255,
            outputBounds=bounds, outputSRS=CRS, xRes=resolution, yRes=resolution,
            allTouched=True,
            creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512"],
        )
        assert ds is not None, "gdal.Rasterize failed"
        ds = None

        # --- Step 3: mask + fine fill -----------------------------------
        print(f"Fine fill (maxSearchDist={fine_search_dist})...")
        _mask_and_write(tmp_projected, tmp_fill_mask, tmp_filled)

        ds = gdal.Open(str(tmp_filled), gdal.GA_Update)
        gdal.FillNodata(
            ds.GetRasterBand(1),
            maskBand=ds.GetRasterBand(1).GetMaskBand(),
            maxSearchDist=fine_search_dist, smoothingIterations=0,
            callback=gdal.TermProgress_nocb,
        )
        ds.FlushCache(); ds = None

        # Re-apply mask to prevent leakage outside AOI
        _mask_and_write(tmp_filled, tmp_fill_mask, tmp_filled)

        # --- Step 4: coarse fill ----------------------------------------
        print(f"Coarse fill (downsample {downsample_factor}x, maxSearchDist={coarse_search_dist})...")
        gdal.Warp(
            str(tmp_coarse), str(tmp_filled),
            xRes=resolution * downsample_factor, yRes=resolution * downsample_factor,
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
        ds_c.FlushCache(); ds_c = None

        gdal.Warp(
            str(tmp_coarse_up), str(tmp_coarse),
            width=src_width, height=src_height, outputBounds=bounds,
            resampleAlg=gdal.GRA_Bilinear,
            srcNodata=float("nan"), dstNodata=float("nan"),
            creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512"],
        )

        # --- Step 5: merge + final mask ---------------------------------
        print("Merging and applying final AOI mask...")
        gdal_calc.Calc(
            calc="numpy.where(C == 1, numpy.where(numpy.isnan(A), B, A), numpy.nan)",
            outfile=str(out_path),
            A=str(tmp_filled), B=str(tmp_coarse_up), C=str(tmp_fill_mask),
            type="Float32", NoDataValue=float("nan"), hideNoData=True,
            creation_options=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512"],
            overwrite=True,
        )
        print(f"Saved: {out_path}")

    finally:
        for p in [tmp_projected, tmp_fill_gpkg, tmp_fill_mask, tmp_filled, tmp_coarse, tmp_coarse_up]:
            Path(p).unlink(missing_ok=True)

    return out_path


def _mask_and_write(src: Path, mask: Path, dst: Path) -> None:
    """Write src masked to AOI (mask==1) into dst, NaN outside."""
    gdal_calc.Calc(
        calc="numpy.where(B == 1, A, numpy.nan)",
        outfile=str(dst),
        A=str(src), B=str(mask),
        type="Float32", NoDataValue=float("nan"), hideNoData=True,
        creation_options=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512"],
        overwrite=True,
    )
