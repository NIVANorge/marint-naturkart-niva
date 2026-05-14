"""Vectorize prediction raster and fill to marine vanntyper outline via GRASS GIS.

Pipeline: r.in.gdal → r.to.vect -s → v.generalize → v.out.ogr
Any gap inside the marine vanntyper outline not covered by the raster polygons is
appended as a row with ``class_int = -1`` (unclassified).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
from osgeo import gdal, osr

# Douglas-Peucker threshold: collapses 50 m raster staircase steps.
SMOOTH_THRESHOLD: float = 25.0


def _vectorize_inside_grass(input_raster: str, output_gpkg: str) -> None:
    import grass.script as gs  # noqa: PLC0415

    gs.run_command("r.in.gdal", input=input_raster, output="raster", overwrite=True)
    gs.run_command("g.region", raster="raster")
    gs.run_command(
        "r.to.vect",
        flags="s",
        input="raster",
        output="vector",
        type="area",
        column="class_int",
        overwrite=True,
    )
    gs.run_command(
        "v.generalize",
        input="vector",
        output="vector_smooth",
        method="douglas",
        threshold=SMOOTH_THRESHOLD,
        type="area",
        overwrite=True,
    )
    gs.run_command(
        "v.out.ogr",
        input="vector_smooth",
        output=output_gpkg,
        output_layer="bunntyper",
        format="GPKG",
        overwrite=True,
        quiet=True,
    )


def raster(
    input_raster: Path | str,
    output_gpkg: Path | str,
    vanntyper_path: Path | str | None = None,
) -> Path:
    """Vectorize prediction *input_raster* via GRASS and fill gaps to the marine
    vanntyper outline.

    Parameters
    ----------
    input_raster:
        Merged prediction raster (e.g. ``norge_merged.tif``).
    output_gpkg:
        Destination GeoPackage path. 
    """
    input_raster = Path(input_raster).resolve()
    output_gpkg = Path(output_gpkg).resolve()

    ds = gdal.Open(str(input_raster))
    epsg = osr.SpatialReference(ds.GetProjection()).GetAuthorityCode(None)
    ds = None

    print(f"Vectorizing {input_raster.name} (EPSG:{epsg}) …")
    subprocess.run(
        [
            "grass", "--tmp-project", f"EPSG:{epsg}", "--exec",
            sys.executable, str(Path(__file__).resolve()),
            "--inner", str(input_raster), str(output_gpkg),
        ],
        check=True,
    )

    print(f"Done → {output_gpkg}")
    return output_gpkg
