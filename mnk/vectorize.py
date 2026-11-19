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

import os
import subprocess
import sys
import tempfile
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

# Norwegian baseline + 1 nautical mile boundary used to clip marine products.
GRUNNLINJE_URL: str = (
    "/vsicurl/https://storage.googleapis.com/niva-geodata/"
    "MarintNaturKart/aux/grunnlinje_1nautisk.gpkg"
)


def clip_to_grunnlinje(
    gdf: gpd.GeoDataFrame,
    grunnlinje_url: str = GRUNNLINJE_URL,
    drop_artifact_nulls: bool = True,
) -> gpd.GeoDataFrame:
    """Clip polygons to the baseline + 1 nautical mile boundary.

    Removes geometry outside the Norwegian *grunnlinje* + 1 nautical mile line
    using ``gdal.VectorTranslate(clipSrc=...)``, explodes multiparts and drops
    empty geometries.

    Parameters
    ----------
    gdf :
        Polygons to clip. Must have a valid CRS matching the clip source.
    grunnlinje_url :
        GDAL-readable path/URL to the clip boundary (defaults to the shared
        remote GeoPackage).
    drop_artifact_nulls :
        If True, drop sliver polygons where every non-geometry attribute is
        null. ``clipSrc`` can emit such rows when the clip line dissects a
        polygon awkwardly.

    Returns
    -------
    GeoDataFrame clipped to the boundary.
    """
    attr_cols = [c for c in gdf.columns if c != gdf.geometry.name]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_in = os.path.join(tmpdir, "clip_in.gpkg")
        tmp_out = os.path.join(tmpdir, "clip_out.gpkg")
        gdf.to_file(tmp_in, driver="GPKG", layer="data")
        gdal.VectorTranslate(
            tmp_out,
            tmp_in,
            options=gdal.VectorTranslateOptions(clipSrc=grunnlinje_url),
        )
        clipped = gpd.read_file(tmp_out).explode(index_parts=False).reset_index(drop=True)

    clipped = clipped[~clipped.is_empty].reset_index(drop=True)

    if drop_artifact_nulls:
        keep_cols = [c for c in attr_cols if c in clipped.columns]
        if keep_cols:
            null_mask = clipped[keep_cols].isna().all(axis=1)
            clipped = clipped[~null_mask].reset_index(drop=True)

    return clipped


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
    output_gpkg.parent.mkdir(parents=True, exist_ok=True)

    gdal.UseExceptions()
    ds = gdal.Open(str(input_raster))
    if ds is None:
        raise FileNotFoundError(f"GDAL could not open raster: {input_raster}")
    epsg = osr.SpatialReference(ds.GetProjection()).GetAuthorityCode(None)
    ds = None

    if epsg is None:
        raise ValueError(
            f"Could not determine EPSG code from raster projection: {input_raster}"
        )

    print(f"Vectorizing {input_raster.name} (EPSG:{epsg}) …")
    proc = subprocess.run(
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
    )
    # Output is not captured so GRASS progress reaches the terminal.
    if proc.returncode != 0:
        raise RuntimeError(
            f"GRASS vectorization failed (exit {proc.returncode}) for {input_raster}; "
            "see GRASS output above."
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


def pad_nodata(arr: np.ndarray, nodata: int | float = 255, iterations: int = 1) -> np.ndarray:
    """Dilate valid pixels outward into nodata, filling with nearest value.

    This ensures vectorized polygons extend slightly beyond the data boundary
    so that land subtraction cleanly removes coastal edges.

    Uses shifted arrays to find neighbor values without allocating full-size
    index arrays (memory-efficient for large rasters).

    Parameters
    ----------
    iterations :
        Number of 1-pixel rings to grow. One ring equals 50 m at the reference
        resolution, so to preserve a constant physical padding at another
        resolution use ``round(50 / res)`` (e.g. 5 at 10 m).
    """
    padded = arr.copy()

    for _ in range(max(1, iterations)):
        valid_mask = padded != nodata
        boundary = binary_dilation(valid_mask) & ~valid_mask
        if not boundary.any():
            break

        # Fill boundary pixels by checking shifted neighbors (8-connected)
        unfilled = boundary.copy()
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]:
            if not unfilled.any():
                break
            # Shift valid_mask and arr to align neighbors
            src_slice_r = slice(max(0, dr), padded.shape[0] + min(0, dr))
            src_slice_c = slice(max(0, dc), padded.shape[1] + min(0, dc))
            dst_slice_r = slice(max(0, -dr), padded.shape[0] + min(0, -dr))
            dst_slice_c = slice(max(0, -dc), padded.shape[1] + min(0, -dc))

            can_fill = unfilled[dst_slice_r, dst_slice_c] & valid_mask[src_slice_r, src_slice_c]
            padded[dst_slice_r, dst_slice_c][can_fill] = padded[src_slice_r, src_slice_c][can_fill]
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


def subtract_layer(
    gdf: gpd.GeoDataFrame, clip_gdf: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Subtract ``clip_gdf`` from ``gdf`` via STRtree (fast ``overlay(how="difference")``).

    Only polygons that actually intersect ``clip_gdf`` are recomputed; all
    others pass through untouched. This is dramatically faster than
    :func:`geopandas.overlay`, which differences every feature against the full
    (often huge) union geometry.

    Parameters
    ----------
    gdf : GeoDataFrame whose attributes are preserved.
    clip_gdf : GeoDataFrame whose geometries are removed from ``gdf``.

    Returns
    -------
    GeoDataFrame with the same columns as ``gdf``; empty geometries dropped.
    """
    geoms = gdf.geometry.values.copy()

    tree = STRtree(clip_gdf.geometry.values)
    gdf_idxs, clip_idxs = tree.query(geoms, predicate="intersects")

    gdf_to_clip: dict[int, list[int]] = defaultdict(list)
    for g_i, c_i in zip(gdf_idxs.tolist(), clip_idxs.tolist()):
        gdf_to_clip[g_i].append(c_i)

    clip_values = clip_gdf.geometry.values
    for g_i, c_indices in gdf_to_clip.items():
        clip_union = unary_union(clip_values[c_indices])
        geoms[g_i] = _to_polygons(geoms[g_i].difference(clip_union))

    result = gdf.copy()
    result["geometry"] = geoms
    result = result[~result.is_empty].reset_index(drop=True)
    return result


def intersect_layers(
    left: gpd.GeoDataFrame, right: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Pairwise intersection via STRtree (fast ``overlay(how="intersection")``).

    Equivalent to ``geopandas.overlay(left, right, how="intersection",
    keep_geom_type=True)`` but uses a bulk STRtree query plus vectorised
    :func:`shapely.intersection`, computing only the geometrically overlapping
    pairs. Attributes from both layers are carried onto each resulting piece
    (right-layer column names colliding with the left get a ``_2`` suffix).

    Parameters
    ----------
    left, right : GeoDataFrames (must share a CRS).

    Returns
    -------
    GeoDataFrame of intersection pieces; non-polygonal and empty parts dropped.
    """
    left_geoms = left.geometry.values
    right_geoms = right.geometry.values

    tree = STRtree(right_geoms)
    left_idxs, right_idxs = tree.query(left_geoms, predicate="intersects")

    pieces = shapely.intersection(left_geoms[left_idxs], right_geoms[right_idxs])
    pieces = np.array([_to_polygons(g) for g in pieces], dtype=object)

    left_cols = [c for c in left.columns if c != left.geometry.name]
    right_cols = [c for c in right.columns if c != right.geometry.name]

    data: dict[str, object] = {}
    for c in left_cols:
        data[c] = left[c].values[left_idxs]
    for c in right_cols:
        name = f"{c}_2" if c in left_cols else c
        data[name] = right[c].values[right_idxs]

    result = gpd.GeoDataFrame(data, geometry=pieces, crs=left.crs)
    result = result[~result.geometry.is_empty & result.geometry.notna()]
    return result.reset_index(drop=True)


def merge_slivers(
    gdf: gpd.GeoDataFrame,
    min_area: float,
    max_thinness: float = 0.1,
    class_col: str = "nin_int",
) -> gpd.GeoDataFrame:
    """Merge thin generalization slivers into their largest same-class neighbour.

    A polygon is treated as a sliver only if it is *both* small (``area <
    min_area``) *and* shape-degenerate (Polsby-Popper compactness
    ``4*pi*area/perimeter**2 < max_thinness``). Compact small polygons (narrow
    coastal fragments, skerries) are therefore kept. Each sliver is dissolved
    into the largest adjacent polygon sharing the same ``class_col`` value;
    slivers with no same-class neighbour are left untouched (never dropped).

    Only the sliver subset is processed via a bulk STRtree query, so this is
    fast even on national datasets.

    Parameters
    ----------
    gdf : GeoDataFrame of single-part polygons.
    min_area : area threshold in CRS units² below which a polygon may be a sliver.
    max_thinness : compactness threshold (0..1); lower = thinner.
    class_col : attribute that must match for a merge to happen.

    Returns
    -------
    GeoDataFrame with slivers merged; index reset.
    """
    area = gdf.geometry.area.values
    perim = gdf.geometry.length.values
    with np.errstate(divide="ignore", invalid="ignore"):
        thinness = np.where(perim > 0, 4.0 * np.pi * area / perim**2, 0.0)

    is_sliver = (area < min_area) & (thinness < max_thinness)
    if not is_sliver.any():
        return gdf.reset_index(drop=True)

    sliver_idx = np.flatnonzero(is_sliver)
    base_idx = np.flatnonzero(~is_sliver)
    base_geoms = gdf.geometry.values[base_idx]
    base_classes = gdf[class_col].values[base_idx]

    geoms = gdf.geometry.values.copy()
    absorbed: list[int] = []
    additions: dict[int, list[object]] = defaultdict(list)

    tree = STRtree(base_geoms)
    sliver_geoms = gdf.geometry.values[sliver_idx]
    s_local, b_local = tree.query(sliver_geoms, predicate="intersects")

    all_classes = gdf[class_col].values
    base_areas = area[base_idx]

    neighbours: dict[int, list[int]] = defaultdict(list)
    for s_i, b_i in zip(s_local.tolist(), b_local.tolist()):
        neighbours[s_i].append(b_i)

    for s_i, b_locals in neighbours.items():
        g_sliver = int(sliver_idx[s_i])
        s_class = all_classes[g_sliver]
        same = [b for b in b_locals if base_classes[b] == s_class]
        if not same:
            continue
        best = max(same, key=lambda b: base_areas[b])
        additions[int(base_idx[best])].append(geoms[g_sliver])
        absorbed.append(g_sliver)

    for g_i, parts in additions.items():
        geoms[g_i] = _to_polygons(unary_union([geoms[g_i], *parts]))

    result = gdf.copy()
    result["geometry"] = geoms
    result = result.drop(index=gdf.index[absorbed])
    return result[~result.is_empty].reset_index(drop=True)
