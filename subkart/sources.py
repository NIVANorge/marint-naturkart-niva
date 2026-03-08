from logging import root
from pathlib import Path

import geopandas as gpd
import pandas as pd

import subkart

FYLKER = [
    "03_Oslo",
    "11_Rogaland",
    "15_More_og_Romsdal",
    "18_Nordland",
    "21_Svalbard",
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


def prepare_sea_basis_depth_data():
    """Prepare basis depth data for processing.

    Data downloaded from Geonorge, at https://kartkatalog.geonorge.no/metadata/sjoekart-dybdedata/2751aacf-5472-4850-a208-3532a51c529a?search=basisdata%20sj%C3%B8
    This data is used as a basis for further analysis and modeling and output saved to geoparquet format.
    """
    layer = "Dybdeareal"


    for region in FYLKER:
        gml_path = Path(f"../geonorge/Basisdata_{region}_25833_Dybdedata_GML.gml")
        output_path = Path(f"../geonorge/Basisdata_{region}_25833_Dybdedata_{layer}.geo.parquet")
        gdf = gpd.read_file(gml_path, layer=layer)
        gdf = subkart.utils.dissolve_geometries(gdf, by_col="minimumsdybde")
        gdf.to_parquet(output_path, compression="snappy")
        print(f"Written GeoParquet to {output_path}")


def sea_map_basisdata(fylker: list[str] = FYLKER):
    """Map basis data for the specified fylker or all

    Read output from `prepare_basis_depth_data`, if all fylker are specified `depth_training_data.geo.parquet` will be used
    it already have been preprocessed to add depth features from `features.depth_preprocess`.
    """

    if fylker == FYLKER:
        print("Reading preprocessed depth training data for all fylker.")
        return gpd.read_parquet("gs://niva-geodata/MarintNaturKart/depth_training_data.geo.parquet")

    county_files = []
    for code in fylker:
        county_files.append(
            f"gs://niva-geodata/MarintNaturKart/Basisdata_{code}_25833_Dybdedata_Dybdeareal.geo.parquet"
        )

    gdfs = [gpd.read_parquet(path) for path in county_files]

    gdf_depth = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))
    del gdfs

    return gdf_depth


def bunnsediment_kornstor_detalj():
    """Prepare bunnsediment kornstor detalj data for processing.

    Data downloaded from Geonorge, at https://kartkatalog.geonorge.no/metadata/bunnsedimenter-kornstoerrelse-detaljert/79f0f17d-9f62-456d-b1a9-2a8c754c51c4
    """
    sediments_detailed = Path(
        "../ngu_sediment/Geologi_0000_Norge_25833_BunnsedimentKornstorDetalj_GML/BunnsedimentKornstorDetalj.gml"
    )
    output_path = Path("ngu_sediment/BunnsedimentKornstorDetalj.geo.parquet")
    subkart.utils.to_geoparquet(sediments_detailed, "KornstrFlate", output_path)


def marine_vanntyper():
    """Prepare marine vann typer data for processing.

    Data downloaded from MDir, at https://dataleveranser.miljodirektoratet.no/nedlasting/b0fa9d93-dd2d-48fd-a89f-8fa224555c4d/
    """
    marine_vanntyper = Path("../mdir/NyTypologi2022.shp")
    output_path = Path("../mdir/NyTypologi2022.geo.parquet")
    subkart.utils.to_geoparquet(marine_vanntyper, None, output_path)
