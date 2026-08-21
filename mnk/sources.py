from logging import root
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from sqlalchemy import union_all
import xdem
import shapely
import rasterio as rio
from shapely import union_all

import mnk
import geoutils as gu

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


def sea_map_torrfall(fylker: list[str] = FYLKER):
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
            f"gs://niva-geodata/MarintNaturKart/input/kartverket/Basisdata_{code}_25833_torrfall.geo.parquet"
        )

    gdfs = [gpd.read_parquet(path) for path in county_files]

    gdf = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))
    del gdfs

    return gdf

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


def bolge_exposure():
    """Read bolge exposure data

    Read bolge exposure raster with additional 2 pixel filling

    Bølgeeksponeringsmodellen (Isæus 2004, Isæus og Rygg 2005) er kjørt for Norge av Norsk institutt for vannforskning (NIVA), 
    tilgjengeliggjort som en del av kartgrunnlaget beskrevet i Bekkby m.fl. (2025) 
    til grunn for kartlegging etter Miljødirektoratets instruks (Miljødirektoratet 2026)

    """
    return gu.Raster("gs://niva-geodata/MarintNaturKart/input/niva/EswmRaster_filled_cog.tif")

def prepare_torrfall():
    """Prepare torrfall.

    Data downloaded from Geonorge, at https://kartkatalog.geonorge.no/metadata/sjoekart-dybdedata/2751aacf-5472-4850-a208-3532a51c529a?search=basisdata%20sj%C3%B8
    
    """
    
    torrfall_layer = "Tørrfall"
    for region in FYLKER:
        gml_path = Path(__file__).resolve().parent.parent / f"geonorge/Basisdata_{region}_25833_Dybdedata_GML.gml"
        output_path = Path(__file__).resolve().parent.parent / Path(
            f"geonorge/Basisdata_{region}_25833_torrfall.geo.parquet"
        )
        gdf_torrfall = gpd.read_file(gml_path, layer=torrfall_layer)
        gdf_torrfall.to_parquet(output_path, compression="snappy")


def prepare_depth_point_data():
    """Extract Dybdepunkt point layer from GML files.

    These are measured depth soundings that are more accurate than the
    min/max ranges on the Dybdeareal polygons, especially for large
    polygons with wide depth ranges.  Output is saved as geoparquet
    per region.
    """
    for region in FYLKER:
        gml_path = Path(__file__).resolve().parent.parent / f"geonorge/Basisdata_{region}_25833_Dybdedata_GML.gml"
        output_path = Path(__file__).resolve().parent.parent / Path(
            f"geonorge/Basisdata_{region}_25833_Dybdepunkt.geo.parquet"
        )

        gdf = gpd.read_file(gml_path, layer="Dybdepunkt", columns=["dybde"])
        gdf = gdf[["dybde", "geometry"]]
        gdf.to_parquet(output_path, compression="snappy")
        print(f"  {region}: {len(gdf)} depth points -> {output_path}")



def depth_point_data(fylker: list[str] = FYLKER) -> gpd.GeoDataFrame:
    """Read prepared depth point data for the given fylker.

    Returns a GeoDataFrame with columns ``dybde`` and ``geometry`` (points).
    """
    county_files = []
    for f in fylker:
        code = next((c for c in FYLKER if c.endswith(f)))
        path = f"gs://niva-geodata/MarintNaturKart/input/kartverket/Basisdata_{code}_25833_Dybdepunkt.geo.parquet"
        county_files.append(path)

    gdfs = [gpd.read_parquet(p) for p in county_files]
    return gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))


def prepare_sea_basis_depth_data():
    """Prepare basis depth data for processing.

    Data downloaded from Geonorge, at https://kartkatalog.geonorge.no/metadata/sjoekart-dybdedata/2751aacf-5472-4850-a208-3532a51c529a?search=basisdata%20sj%C3%B8
    This data is used as a basis for further analysis and modeling and output saved to geoparquet format.
    """
    layer = "Dybdeareal"
    torrfall_layer = "Tørrfall"
    for region in FYLKER:
        gml_path = Path(__file__).resolve().parent.parent / f"geonorge/Basisdata_{region}_25833_Dybdedata_GML.gml"
        output_path = Path(__file__).resolve().parent.parent / Path(
            f"geonorge/Basisdata_{region}_25833_Dybdedata_{layer}.geo.parquet"
        )
        gdf = gpd.read_file(gml_path, layer=layer)
        gdf_torrfall = gpd.read_file(gml_path, layer=torrfall_layer)
        gdf_torrfall["minimumsdybde"] = 0
        gdf_torrfall["maksimumsdybde"] = 0.5
        gdf = pd.concat([gdf, gdf_torrfall], ignore_index=True)
       
        gdf.to_parquet(output_path, compression="snappy")
        print(f"Written GeoParquet to {output_path}")


def prepare_land_data():
    """Prepare basis depth data for processing.

    Data downloaded from Geonorge, at https://kartkatalog.geonorge.no/metadata/sjoekart-dybdedata/2751aacf-5472-4850-a208-3532a51c529a?search=basisdata%20sj%C3%B8
    This data is used as a basis for further analysis and modeling and output saved to geoparquet format.
    """
    layer = "Landareal"

    crs = "EPSG:25833"
    
    gdf_list = []
    for region in FYLKER:
        gml_path = Path(__file__).resolve().parent.parent / f"geonorge/Basisdata_{region}_25833_Dybdedata_GML.gml"
        gdf = gpd.read_file(gml_path, layer=layer)
        gdf_list.append(gdf.to_crs(crs).geometry.values)
    
    geoms = np.concatenate(gdf_list)
    geoms = shapely.make_valid(geoms)
    
    output_path = Path(__file__).resolve().parent.parent / "geonorge/Basisdata_Landareal.gpkg"
    
    gdf = gpd.GeoDataFrame(geometry=geoms, crs=crs)
    gdf.to_file(output_path, layer="landareal", driver="GPKG")
    gdf.to_parquet(Path(__file__).resolve().parent.parent / "geonorge/Basisdata_Landareal.geo.parquet", compression="snappy")
    union_geom = union_all(geoms)
    del geoms
    
    gdf_union = gpd.GeoDataFrame(geometry=[union_geom], crs=crs)
    gdf_union.to_file(output_path, layer="landareal_union", driver="GPKG")
    
    print(f"Written GeoPackage to {output_path}")


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

    geoms = np.concatenate([
        mnk.sources.marine_vanntyper().to_crs(crs).geometry.values,
        gpd.read_parquet("gs://niva-geodata/MarintNaturKart/aux/aoi_missing.geo.parquet").to_crs(crs).geometry.values,
    ])
    geoms = shapely.make_valid(geoms)

    gpd.GeoDataFrame(geometry=geoms, crs=crs).to_parquet("aoi_from_marine_vanntyper.geo.parquet")

    union_geom = union_all(geoms)
    del geoms

    gpd.GeoDataFrame(geometry=[union_geom], crs=crs).to_parquet("aoi_from_marine_vanntyper_union.geo.parquet")

