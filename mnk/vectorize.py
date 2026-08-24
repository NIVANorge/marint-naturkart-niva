"""Vectorize rasters: common pad/polygonize/land-subtract utilities and GRASS pipeline.

Common utilities
----------------
- :func:`pad_nodata` — 1-pixel dilation of valid data into nodata border.
- :func:`vectorize_raster_to_gdf` — GDAL Polygonize → GeoDataFrame.
- :func:`subtract_land` — bulk STRtree land subtraction.

GRASS pipeline
--------------
Pipeline: r.in.gdal → r.to.vect -s → v.generalize → v.out.ogr
Any gap inside the marine vanntyper outline not covered by the raster polygons is
appended as a row with ``class_int = -1`` (unclassified).
"""

from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from osgeo import gdal, ogr, osr
from scipy.ndimage import binary_dilation
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

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


def with_grass(
    input_raster: Path | str,
    output_gpkg: Path | str,
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
            "grass",
            "--tmp-project",
            f"EPSG:{epsg}",
            "--exec",
            sys.executable,
            str(Path(__file__).resolve()),
            "--inner",
            str(input_raster),
            str(output_gpkg),
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


# ---------------------------------------------------------------------------
# Common raster-to-vector utilities
# ---------------------------------------------------------------------------


def pad_nodata(arr: np.ndarray, nodata: int | float = 255) -> np.ndarray:
    """Dilate valid pixels by 1 pixel into nodata, filling with nearest value.

    This ensures vectorized polygons extend slightly beyond the data boundary
    so that land subtraction cleanly removes coastal edges.

    Uses shifted arrays to find neighbor values without allocating full-size
    index arrays (memory-efficient for large rasters).
    """
    valid_mask = arr != nodata
    boundary = binary_dilation(valid_mask) & ~valid_mask
    padded = arr.copy()

    # Fill boundary pixels by checking shifted neighbors (8-connected)
    unfilled = boundary.copy()
    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]:
        if not unfilled.any():
            break
        # Shift valid_mask and arr to align neighbors
        src_slice_r = slice(max(0, dr), arr.shape[0] + min(0, dr))
        src_slice_c = slice(max(0, dc), arr.shape[1] + min(0, dc))
        dst_slice_r = slice(max(0, -dr), arr.shape[0] + min(0, -dr))
        dst_slice_c = slice(max(0, -dc), arr.shape[1] + min(0, -dc))

        can_fill = unfilled[dst_slice_r, dst_slice_c] & valid_mask[src_slice_r, src_slice_c]
        padded[dst_slice_r, dst_slice_c][can_fill] = arr[src_slice_r, src_slice_c][can_fill]
        unfilled[dst_slice_r, dst_slice_c][can_fill] = False

    return padded


def vectorize_raster_to_gdf(
    raster_path: str | Path,
    field_name: str = "DN",
    epsg: int = 25833,
    nodata: int = 255,
) -> gpd.GeoDataFrame:
    """Polygonize a single-band raster into a GeoDataFrame, excluding nodata.

    Parameters
    ----------
    raster_path : path to a single-band GeoTIFF.
    field_name : attribute name for the raster value.
    epsg : coordinate reference system EPSG code.
    nodata : nodata value to mask out.

    Returns
    -------
    GeoDataFrame with columns [field_name, geometry].
    """
    gdal.UseExceptions()
    ds = gdal.Open(str(raster_path))
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray()

    drv_mem = gdal.GetDriverByName("Mem")
    mask_ds = drv_mem.Create("", ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Byte)
    mask_ds.SetGeoTransform(ds.GetGeoTransform())
    mask_ds.GetRasterBand(1).WriteArray((arr != nodata).astype(np.uint8))

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)

    mem_gpkg = "/vsimem/_vectorize_tmp.gpkg"
    out_ds = ogr.GetDriverByName("GPKG").CreateDataSource(mem_gpkg)
    out_layer = out_ds.CreateLayer("polys", srs=srs, geom_type=ogr.wkbPolygon)
    out_layer.CreateField(ogr.FieldDefn(field_name, ogr.OFTInteger))

    gdal.Polygonize(band, mask_ds.GetRasterBand(1), out_layer, 0, [])
    out_ds = mask_ds = ds = None

    gdf = gpd.read_file(mem_gpkg).explode(index_parts=False).reset_index(drop=True)
    gdal.Unlink(mem_gpkg)
    gdf = gdf[gdf[field_name] != nodata].reset_index(drop=True)
    gdf = gdf.set_crs(epsg=epsg)
    return gdf


def _to_polygons(geom):
    """Extract only Polygon/MultiPolygon parts from any geometry."""
    if geom is None or geom.is_empty:
        return geom
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    polys = [
        g for g in getattr(geom, "geoms", [])
        if isinstance(g, (Polygon, MultiPolygon))
    ]
    if not polys:
        return Polygon()
    return MultiPolygon(
        [p for mp in polys for p in (mp.geoms if isinstance(mp, MultiPolygon) else [mp])]
    )


def subtract_land(gdf: gpd.GeoDataFrame, land_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Subtract land polygons from a GeoDataFrame using STRtree bulk query.

    Parameters
    ----------
    gdf : GeoDataFrame with polygons to clip.
    land_gdf : GeoDataFrame with land polygons to subtract.

    Returns
    -------
    GeoDataFrame with land removed; empty geometries dropped.
    """
    geoms = gdf.geometry.values.copy()

    tree = STRtree(land_gdf.geometry)
    gdf_idxs, land_idxs = tree.query(geoms, predicate="intersects")

    gdf_to_land: dict[int, list[int]] = defaultdict(list)
    for g_i, l_i in zip(gdf_idxs.tolist(), land_idxs.tolist()):
        gdf_to_land[g_i].append(l_i)

    print(f"Subtracting land from {len(gdf_to_land):,} of {len(geoms):,} polygons...")
    for g_i, l_indices in gdf_to_land.items():
        land_union = unary_union(land_gdf.geometry.iloc[l_indices].values)
        geoms[g_i] = _to_polygons(geoms[g_i].difference(land_union))

    result = gdf.copy()
    result["geometry"] = geoms
    result = result[~result.is_empty].reset_index(drop=True)
    return result
