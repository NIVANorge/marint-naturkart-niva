from pathlib import Path

import subkart


def basis_depth_data():
    """Prepare basis depth data for processing.

    Data downloaded from Geonorge, at https://kartkatalog.geonorge.no/metadata/sjoekart-dybdedata/2751aacf-5472-4850-a208-3532a51c529a?search=basisdata%20sj%C3%B8
    """
    layer = "Dybdeareal"
    depth_mr = Path("../geonorge/Basisdata_15_More_og_Romsdal_25833_Dybdedata_GML.gml")
    output_path = Path(f"../geonorge/Basisdata_15_More_og_Romsdal_25833_Dybdedata_{layer}.geo.parquet")
    subkart.utils.to_geoparquet(depth_mr, layer, output_path)

    depth_vl = Path("../geonorge/Basisdata_46_Vestland_25833_Dybdedata_GML.gml")
    output_path = Path(f"../geonorge/Basisdata_46_Vestland_25833_Dybdedata_{layer}.geo.parquet")
    subkart.utils.to_geoparquet(depth_vl, layer, output_path)


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
