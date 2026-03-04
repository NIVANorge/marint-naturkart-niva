from logging import root
from pathlib import Path
from shapely.errors import GEOSException
from shapely.validation import explain_validity, make_valid
import geopandas as gpd

import subkart


def basis_depth_data():
    """Prepare basis depth data for processing.

    Data downloaded from Geonorge, at https://kartkatalog.geonorge.no/metadata/sjoekart-dybdedata/2751aacf-5472-4850-a208-3532a51c529a?search=basisdata%20sj%C3%B8
    """
    layer = "Dybdeareal"

    regions = [
        ("Oslo", "03"),
        ("Rogaland", "11"),
        ("More_og_Romsdal", "15"),
        ("Nordland", "18"),
        ("Svalbard", "21"),
        ("Ostfold", "31"),
        ("Akershus", "32"),
        ("Buskerud", "33"),
        ("Vestfold", "39"),
        ("Telemark", "40"),
        ("Agder", "42"),
        ("Vestland", "46"),
        ("Trondelag", "50"),
        ("Troms", "55"),
        ("Finnmark", "56"),
    ]
    for region_name, region_code in regions:
        gml_path = Path(f"../geonorge/Basisdata_{region_code}_{region_name}_25833_Dybdedata_GML.gml")
        output_path = Path(f"../geonorge/Basisdata_{region_code}_{region_name}_25833_Dybdedata_{layer}.geo.parquet")
        subkart.utils.to_geoparquet(gml_path, layer, output_path)

def preprocess_basisdata(root_path: Path):
    """Preprocess basis data for analysis."""


    parquet_files = sorted(root.rglob("*_25833_Dybdedata_Dybdeareal.geo.parquet"))

    print(f"Found {len(parquet_files)} dybdedata files")
    for p in parquet_files:
        print(f"Processing: {p}")

        # Read original file
        gdf = gpd.read_parquet(p)

        # Dissolve by "minimumsdybde"
        try:
            gdf_dissolved = gdf.dissolve(by="minimumsdybde", as_index=False)
        except GEOSException as e:
            invalid_mask = ~gdf.geometry.is_valid
            bad = gdf.loc[invalid_mask].copy()

            print(f"Invalid geometries: {invalid_mask.sum()} / {len(gdf)}")
            for i, geom in zip(bad.index, bad.geometry):
                print(i, explain_validity(geom)) 
            gdf["geometry"] = gdf.geometry.apply(make_valid)
            print(f"TopologicalError while dissolving {p}: {e}")
            gdf_dissolved = gdf.dissolve(by="minimumsdybde", as_index=False)
            
        # Explode dissolved geometry
        gdf_exploded = gdf_dissolved.explode(index_parts=False).reset_index(drop=True)

        # Overwrite the original parquet with processed data
        gdf_exploded.to_parquet(p)

        print(f"Written exploded GeoDataFrame back to: {p}")

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
