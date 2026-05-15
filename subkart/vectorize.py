"""Vectorize prediction raster and fill to marine vanntyper outline via GRASS GIS.

Pipeline: r.in.gdal → r.to.vect -s → v.generalize → v.out.ogr
Any gap inside the marine vanntyper outline not covered by the raster polygons is
appended as a row with ``class_int = -1`` (unclassified).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import numpy as np

import geopandas as gpd
import pandas as pd
import shapely
from osgeo import gdal, ogr, osr

# Douglas-Peucker threshold: collapses 50 m raster staircase steps.
SMOOTH_THRESHOLD: float = 25.0


def with_gdal(input_raster, output_gpkg, epsg_code, nodata=255):

    gdal.UseExceptions()
    ds = gdal.Open(input_raster)
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray()

    final_labels = np.full(arr.shape, nodata, dtype=np.uint8)
    for val in [0, 1, 2]:
        final_labels[arr == val] = val

    drv_mem = gdal.GetDriverByName("Mem")
    mem_ds = drv_mem.Create("", ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Byte)
    mem_ds.SetGeoTransform(ds.GetGeoTransform())
    mem_ds.SetProjection(ds.GetProjection())

    mem_band = mem_ds.GetRasterBand(1)
    mem_band.WriteArray(final_labels)

    mask_arr = (final_labels != nodata).astype(np.uint8)
    mask_ds = drv_mem.Create("", ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Byte)
    mask_band = mask_ds.GetRasterBand(1)
    mask_band.WriteArray(mask_arr)
    # ------------------------

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg_code)

    drv_gpkg = ogr.GetDriverByName("GPKG")
    out_ds = drv_gpkg.CreateDataSource(output_gpkg)
    out_layer = out_ds.CreateLayer("polys", srs=srs, geom_type=ogr.wkbPolygon)
    out_layer.CreateField(ogr.FieldDefn("DN", ogr.OFTInteger))

    gdal.Polygonize(mem_band, mask_band, out_layer, 0, [], callback=None)

    mem_ds = None
    mask_ds = None
    out_ds = None
    ds = None
    print(f"Polygons saved to {output_gpkg}")


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


def grass(
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

    gdal.UseExceptions()
    ds = gdal.Open(str(input_raster))
    if ds is None:
        raise FileNotFoundError(f"GDAL could not open raster: {input_raster}")
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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--inner", action="store_true")
    parser.add_argument("input_raster")
    parser.add_argument("output_gpkg")
    args = parser.parse_args()

    if args.inner:
        _vectorize_inside_grass(args.input_raster, args.output_gpkg)
