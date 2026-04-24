from logging import root
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from sqlalchemy import union_all
import xdem
import rasterio as rio
from osgeo import gdal
from osgeo_utils import gdal_calc
from scipy.ndimage import distance_transform_edt
from shapely import union_all
from tqdm import tqdm

import subkart
import geoutils as gu
import requests

FYLKER = [
    "03_Oslo",
    "11_Rogaland",
    "15_More_og_Romsdal",
    "18_Nordland",
    "31_Ostfold",
    "32_Akershus",
    "33_Buskerud",
    "39_Vestfold",
    "40_Telemark",
    "42_Agder",
    "46_Vestland",
    "50_Trondelag",
    "55_Troms",
    "56_Finnmark",
]

REGIONS = {
    "vestland": ["More_og_Romsdal", "Vestland", "Rogaland"],
    "sor-ost": ["Agder", "Telemark", "Vestfold", "Ostfold", "Akershus", "Buskerud", "Oslo"],
    "midt": ["Trondelag", "Nordland"],
    "nord": ["Troms", "Finnmark"],
}


def dem_data():
    dem = xdem.DEM(
        rio.open("https://storage.googleapis.com/niva-geodata/MarintNaturKart/input/kartverket/dem50_norge.tif")
    )
    return dem


def sea_map_basisdata(fylker: list[str] = FYLKER):
    """Map basis data for the specified fylker or all

    Read output from `prepare_basis_depth_data`, if all fylker are specified `depth_training_data.geo.parquet` will be used
    it already have been preprocessed to add depth features from `features.depth_preprocess`.
    """

    if fylker == FYLKER:
        print("Reading preprocessed depth training data for all fylker.")
        return gpd.read_parquet(
            "gs://niva-geodata/MarintNaturKart/input/kartverket/sjoekart_dybdedata_trening_norge.geo.parquet"
        )

    county_files = []
    for f in fylker:
        code = next((c for c in FYLKER if c.endswith(f)))
        county_files.append(
            f"gs://niva-geodata/MarintNaturKart/input/kartverket/Basisdata_{code}_25833_Dybdedata_Dybdeareal.geo.parquet"
        )

    gdfs = [gpd.read_parquet(path) for path in county_files]

    gdf_depth = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))
    del gdfs

    return gdf_depth


def marine_vanntyper():
    """Read marine vanntyper

    Read marine vanntyper from gs://niva-geodata/MarintNaturKart/input/mdir/NyTypologi2022.geo.parquet
    """
    return gpd.read_parquet("gs://niva-geodata/MarintNaturKart/input/mdir/NyTypologi2022.geo.parquet")


def prepare_sea_basis_depth_data():
    """Prepare basis depth data for processing.

    Data downloaded from Geonorge, at https://kartkatalog.geonorge.no/metadata/sjoekart-dybdedata/2751aacf-5472-4850-a208-3532a51c529a?search=basisdata%20sj%C3%B8
    This data is used as a basis for further analysis and modeling and output saved to geoparquet format.
    """
    layer = "Dybdeareal"

    for region in FYLKER:
        gml_path = Path(__file__).resolve().parent.parent / f"geonorge/Basisdata_{region}_25833_Dybdedata_GML.gml"
        output_path = Path(__file__).resolve().parent.parent / Path(
            f"geonorge/Basisdata_{region}_25833_Dybdedata_{layer}.geo.parquet"
        )
        gdf = gpd.read_file(gml_path, layer=layer)
        gdf = subkart.utils.dissolve_geometries(gdf, by_col="minimumsdybde")
        gdf.to_parquet(output_path, compression="snappy")
        print(f"Written GeoParquet to {output_path}")


def prepare_bunnsediment_kornstor_detalj():
    """Prepare bunnsediment kornstor detalj data for processing.

    Data downloaded from Geonorge, at https://kartkatalog.geonorge.no/metadata/bunnsedimenter-kornstoerrelse-detaljert/79f0f17d-9f62-456d-b1a9-2a8c754c51c4
    """
    sediments_detailed = Path(__file__).resolve().parent.parent / Path(
        "ngu_sediment/Geologi_0000_Norge_25833_BunnsedimentKornstorDetalj_GML/BunnsedimentKornstorDetalj.gml"
    )
    output_path = Path(__file__).resolve().parent.parent / Path(
        "ngu_sediment/BunnsedimentKornstorDetalj.geo.parquet"
    )
    subkart.utils.to_geoparquet(sediments_detailed, "KornstrFlate", output_path)


def prepare_marine_vanntyper():
    """Prepare marine vann typer data for processing.

    Data downloaded from MDir, at https://dataleveranser.miljodirektoratet.no/nedlasting/b0fa9d93-dd2d-48fd-a89f-8fa224555c4d/
    """
    marine_vanntyper = Path(__file__).resolve().parent.parent / Path(
        "mdir/NyTypologi2022.shp"
    )
    output_path = Path(__file__).resolve().parent.parent / Path(
        "mdir/NyTypologi2022.geo.parquet"
    )
    subkart.utils.to_geoparquet(marine_vanntyper, None, output_path)


def prepare_mv_aoi():
    """
    Prepare area of interest (AOI) data for processing.

    Combines marine vanntyper and missing area geometries into a single AOI.
    """
    crs = "EPSG:25833"
    mv = subkart.sources.marine_vanntyper().to_crs(crs)
    missing_area = gpd.read_parquet("gs://niva-geodata/MarintNaturKart/aux/aoi_missing.geo.parquet").to_crs(crs)

    df = pd.concat([mv.geometry, missing_area.geometry])

    gpd.GeoDataFrame(geometry=df, crs=crs).to_parquet("aoi_from_marine_vanntyper.geo.parquet")

def prepare_bolge_model_data():
    """Prepare bølgemodell (wave exposure) raster data for processing.

    Clips the wave exposure raster (EswmRaster.tif) to the marine vanntyper outline,
    fills nodata (0) values inside the outline and in bølgeeksponert areas, and saves
    the result as a Cloud Optimized GeoTIFF (COG).

    Bølgeeksponeringsmodellen er utviklet av Norsk institutt for vannforskning (NIVA), tilgjengeliggjort som en del av kartgrunnlaget beskrevet i Bekkby m.fl. (2025
    Input raster expected at:  <root_path>/niva/EswmRaster.tif
    Output written to:         <root_path>/niva/EswmRaster_clipped_cog.tif

    """

    crs = "EPSG:25833"
    gdal.UseExceptions()

    root_path = Path(__file__).resolve().parent.parent
    raster_path = root_path / "niva" / "EswmRaster.tif"
    filled_path = root_path / "niva" / "EswmRaster_to_fill.tif"
    clipped_path = root_path / "niva" / "EswmRaster_clipped.tif"
    cog_path = root_path / "niva" / "EswmRaster_clipped_cog.tif"
    outline_mask_path = root_path / "niva" / "tmp_outline_mask.tif"
    bolge_exponert_mask_path = root_path / "niva" / "tmp_bolge_exponert_mask.tif"
    tmp_gpkg = root_path / "niva" / "tmp_mv_outline.gpkg"
    tmp_bolge_gpkg = root_path / "niva" / "tmp_mv_bolge_exponert.gpkg"
    tmp_coarse_path = root_path / "niva" / "tmp_coarse.tif"
    tmp_coarse_upsampled_path = root_path / "niva" / "tmp_coarse_upsampled.tif"
    tmp_coarse_merged_path = root_path / "niva" / "tmp_coarse_merged.tif"

    # Load and preprocess marine vanntyper
    aoi = gpd.read_parquet("gs://niva-geodata/MarintNaturKart/aux/aoi_from_marine_vanntyper.geo.parquet").to_crs(crs)
    aoi[["geometry"]].to_file(tmp_gpkg, driver="GPKG", layer="aoi")

    # Read source raster metadata
    with rio.open(raster_path) as src:
        b = src.bounds
        res_x, res_y = src.res
        src_width, src_height = src.width, src.height

    rasterize_opts = dict(
        burnValues=[1],
        outputType=gdal.GDT_Byte,
        initValues=[0],
        noData=255,
        outputBounds=[b.left, b.bottom, b.right, b.top],
        xRes=res_x,
        yRes=res_y,
        allTouched=True,
        creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
        callback=gdal.TermProgress_nocb,
    )

    print("Rasterizing aoi mask...")
    ds = gdal.Rasterize(str(outline_mask_path), str(tmp_gpkg), layers=["aoi"], **rasterize_opts)
    assert ds is not None, "gdal.Rasterize failed for aoi"
    ds = None
    print("AOI mask ready:", outline_mask_path)

    # Copy raster with nodata=0 for in-place filling
    print("Copying raster for filling...")
    gdal.Translate(
        str(filled_path),
        str(raster_path),
        noData=0,
        creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
    )

    ds = gdal.Open(str(filled_path), gdal.GA_Update)
    band = ds.GetRasterBand(1)

    print("Filling nodata (0) inside outline...")
    gdal.FillNodata(band, maskBand=band.GetMaskBand(), maxSearchDist=200, smoothingIterations=0, callback=gdal.TermProgress_nocb)
    ds.FlushCache()
    ds = None

    # Coarse fill: downsample → FillNodata → upsample → merge back.
    downsample_factor = 20
    print(f"Coarse fill: downsampling {downsample_factor}× ...")
    gdal.Warp(
        str(tmp_coarse_path),
        str(filled_path),
        xRes=res_x * downsample_factor,
        yRes=res_y * downsample_factor,
        resampleAlg=gdal.GRA_Average,
        srcNodata=0,
        dstNodata=0,
        creationOptions=["COMPRESS=DEFLATE"],
    )

    ds_coarse = gdal.Open(str(tmp_coarse_path), gdal.GA_Update)
    band_coarse = ds_coarse.GetRasterBand(1)
    print("Coarse fill: FillNodata at low resolution...")
    gdal.FillNodata(band_coarse, maskBand=band_coarse.GetMaskBand(), maxSearchDist=500, smoothingIterations=0, callback=gdal.TermProgress_nocb)
    ds_coarse.FlushCache()
    ds_coarse = None

    print("Coarse fill: upsampling back to original resolution...")
    gdal.Warp(
        str(tmp_coarse_upsampled_path),
        str(tmp_coarse_path),
        width=src_width,
        height=src_height,
        outputBounds=[b.left, b.bottom, b.right, b.top],
        resampleAlg=gdal.GRA_Bilinear,
        srcNodata=0,
        dstNodata=0,
        creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
    )

    print("Coarse fill: merging into raster (remaining nodata only)...")
    gdal_calc.Calc(
        calc="numpy.where(A==0, B, A)",
        outfile=str(tmp_coarse_merged_path),
        A=str(filled_path),
        B=str(tmp_coarse_upsampled_path),
        type="Int32",
        NoDataValue=0,
        hideNoData=True,
        creation_options=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
        overwrite=True,
    )

    src_nodata = 0
    print("Clipping raster to outline...")
    gdal_calc.Calc(
        calc=f"numpy.where(A==0, {src_nodata}, B)",
        outfile=clipped_path,
        A=outline_mask_path,
        B=tmp_coarse_merged_path,
        type="Int32",
        NoDataValue=src_nodata,
        hideNoData=True,
        creation_options=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
        overwrite=True,
    )


    cog_path = root_path / "niva" / "EswmRaster_clipped_cog.tif"
    gdal.Translate(
        cog_path,
        clipped_path,
        creationOptions=[
            "COMPRESS=DEFLATE",
            "BIGTIFF=IF_SAFER"
        ],
        format="COG"
    )
    print("COG saved:", cog_path)
    outline_mask_path.unlink()
    tmp_coarse_path.unlink(missing_ok=True)
    tmp_coarse_upsampled_path.unlink(missing_ok=True)
    tmp_coarse_merged_path.unlink(missing_ok=True)