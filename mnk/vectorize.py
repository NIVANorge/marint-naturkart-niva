"""Vectorize rasters: common pad/polygonize/land-subtract utilities and GRASS pipeline.

Common utilities
----------------
- :func:`pad_nodata` — 1-pixel dilation of valid data into nodata border.
- :func:`vectorize_raster_to_gdf` — GDAL Polygonize → GeoDataFrame.
- :func:`subtract_land` — bulk STRtree land subtraction.

GRASS pipeline
--------------
Pipeline: r.in.gdal → r.to.vect -s → v.generalize → v.out.ogr
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


def sieve_raster(src_path, dst_path, size: int, connectivity: int = 4) -> Path:
    """Write a copy of a single-band raster with regions smaller than *size* pixels removed.

    Each small connected region takes the value of its largest neighbour (GDAL sieve
    filter). GDAL streams the raster, so memory grows with the number of regions,
    not the raster size. Nodata pixels are left alone and never absorb a region.
    """
    gdal.UseExceptions()
    src = gdal.Open(str(src_path))
    dst = gdal.GetDriverByName("GTiff").CreateCopy(
        str(dst_path), src, options=["COMPRESS=DEFLATE", "TILED=YES"]
    )
    band = src.GetRasterBand(1)
    gdal.SieveFilter(band, band.GetMaskBand(), dst.GetRasterBand(1), size, connectivity)
    dst.FlushCache()
    src = dst = None
    return Path(dst_path)


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


def _map(fn, items, workers):
    """Apply ``fn`` to ``items``, threaded when ``workers > 1`` (GEOS frees the GIL)."""
    items = list(items)
    if workers and workers > 1 and len(items) > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as pool:
            yield from pool.map(fn, items)
    else:
        yield from map(fn, items)


def subtract_land(
    gdf: gpd.GeoDataFrame, land_gdf: gpd.GeoDataFrame, workers: int = 4
) -> gpd.GeoDataFrame:
    """Subtract land polygons from a GeoDataFrame using STRtree bulk query.

    The per-polygon union+difference runs across ``workers`` threads (GEOS
    releases the GIL).

    Parameters
    ----------
    gdf : GeoDataFrame with polygons to clip.
    land_gdf : GeoDataFrame with land polygons to subtract.
    workers : threads for the per-polygon loop (1 = serial).

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
    land_values = land_gdf.geometry.values
    work = [(g_i, geoms[g_i], land_values[l_idx]) for g_i, l_idx in gdf_to_land.items()]

    def _diff(item):
        g_i, geom, land = item
        return g_i, _to_polygons(geom.difference(shapely.union_all(land)))

    for g_i, geom in _map(_diff, work, workers):
        geoms[g_i] = geom

    result = gdf.copy()
    result["geometry"] = geoms
    result = result[~result.is_empty].reset_index(drop=True)
    return result


def subtract_layer(
    gdf: gpd.GeoDataFrame,
    clip_gdf: gpd.GeoDataFrame,
    workers: int = 4,
    progress: bool = False,
) -> gpd.GeoDataFrame:
    """Subtract ``clip_gdf`` from ``gdf`` via STRtree (fast ``overlay(how="difference")``).

    Only polygons that actually intersect ``clip_gdf`` are recomputed; all
    others pass through untouched. This is dramatically faster than
    :func:`geopandas.overlay`, which differences every feature against the full
    (often huge) union geometry.

    The per-polygon union+difference is the dominant cost at national scale, so
    it is run across ``workers`` threads (GEOS releases the GIL).

    Parameters
    ----------
    gdf : GeoDataFrame whose attributes are preserved.
    clip_gdf : GeoDataFrame whose geometries are removed from ``gdf``.
    workers : threads for the per-polygon loop (1 = serial).
    progress : print a running count of processed polygons.

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
    # Precompute (index, geometry, clip geometries) so worker threads never touch
    # the shared `geoms` array; results are written back on the main thread.
    work = [(g_i, geoms[g_i], clip_values[c_idx]) for g_i, c_idx in gdf_to_clip.items()]

    def _diff(item):
        g_i, geom, clips = item
        return g_i, _to_polygons(geom.difference(shapely.union_all(clips)))

    total = len(work)
    for done, (g_i, geom) in enumerate(_map(_diff, work, workers), start=1):
        geoms[g_i] = geom
        if progress and (done % 1000 == 0 or done == total):
            print(f"\r  subtract_layer: {done:,}/{total:,} polygons", end="", flush=True)
    if progress and total:
        print()

    result = gdf.copy()
    result["geometry"] = geoms
    result = result[~result.is_empty].reset_index(drop=True)
    return result


def intersect_layers(
    left: gpd.GeoDataFrame,
    right: gpd.GeoDataFrame,
    workers: int = 4,
    progress: bool = False,
    chunk: int = 2000,
) -> gpd.GeoDataFrame:
    """Pairwise intersection via STRtree (fast ``overlay(how="intersection")``).

    Equivalent to ``geopandas.overlay(left, right, how="intersection",
    keep_geom_type=True)`` but uses a bulk STRtree query plus vectorised
    :func:`shapely.intersection`, computing only the geometrically overlapping
    pairs. Attributes from both layers are carried onto each resulting piece
    (right-layer column names colliding with the left get a ``_2`` suffix).

    The per-pair intersection runs in ``chunk``-sized blocks across ``workers``
    threads (GEOS releases the GIL).

    Parameters
    ----------
    left, right : GeoDataFrames (must share a CRS).
    workers : threads for the per-pair intersection (1 = serial).
    progress : print a running count of processed pairs.
    chunk : pairs per thread task.

    Returns
    -------
    GeoDataFrame of intersection pieces; non-polygonal and empty parts dropped.
    """
    left_geoms = left.geometry.values
    right_geoms = right.geometry.values

    tree = STRtree(right_geoms)
    left_idxs, right_idxs = tree.query(left_geoms, predicate="intersects")

    lg = left_geoms[left_idxs]
    rg = right_geoms[right_idxs]
    total = len(left_idxs)

    def _piece(start):
        sl = slice(start, start + chunk)
        return start, [_to_polygons(g) for g in shapely.intersection(lg[sl], rg[sl])]

    pieces = np.empty(total, dtype=object)
    done = 0
    for start, block in _map(_piece, range(0, total, chunk), workers):
        pieces[start:start + len(block)] = block
        done += len(block)
        if progress and (done % (chunk * 10) < chunk or done == total):
            print(f"\r  intersect_layers: {done:,}/{total:,} pairs", end="", flush=True)
    if progress and total:
        print()

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


def remove_overlaps(
    gdf: gpd.GeoDataFrame, rank, workers: int = 4, chunk: int = 50_000
) -> gpd.GeoDataFrame:
    """Make *gdf* non-overlapping: where polygons overlap, the lower ``rank`` keeps the area.

    Each polygon loses the parts covered by polygons with a lower rank (ties go to
    the earlier row), so the union is unchanged and every point ends up in exactly
    one polygon. Polygons that only share an edge do not count as overlapping.

    Memory stays bounded: pairs are found ``chunk`` polygons at a time and only the
    polygons that really overlap get a new geometry. When nothing overlaps, *gdf*
    itself is returned. Otherwise the untouched rows come first, followed by the
    trimmed ones as single-part polygons (fully covered ones disappear), on a fresh
    RangeIndex.
    """
    rank = np.asarray(rank)
    src = gdf.geometry.values
    tree = STRtree(src)
    trimmed: dict[int, object] = {}
    for start in range(0, len(src), chunk):
        idx = np.arange(start, min(start + chunk, len(src)))
        a, b = tree.query(src[idx], predicate="intersects")
        a = idx[a]
        wins = (rank[b] < rank[a]) | ((rank[b] == rank[a]) & (b < a))
        a, b = a[wins], b[wins]
        inner = ~shapely.touches(src[a], src[b])
        a, b = a[inner], b[inner]
        if not len(a):
            continue
        order = np.argsort(a, kind="stable")
        a, b = a[order], b[order]
        losers, first = np.unique(a, return_index=True)
        winners = np.split(b, first[1:])

        def _diff(k):
            i = losers[k]
            return i, _to_polygons(src[i].difference(shapely.union_all(src[winners[k]])))

        for i, geom in _map(_diff, range(len(losers)), workers):
            trimmed[int(i)] = geom

    if not trimmed:
        return gdf
    rows = np.fromiter(trimmed, dtype=np.int64, count=len(trimmed))
    keep = np.ones(len(gdf), dtype=bool)
    keep[rows] = False
    fixed = gdf.iloc[rows].copy()
    fixed[gdf.geometry.name] = [trimmed[i] for i in rows.tolist()]
    out = pd.concat([gdf[keep], _single_polygons(fixed)], ignore_index=True)
    return gpd.GeoDataFrame(out, geometry=gdf.geometry.name, crs=gdf.crs)


def _single_polygons(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.explode(index_parts=False)
    return gdf[(gdf.geom_type == "Polygon") & ~gdf.geometry.is_empty]


def overlay_update(
    base: gpd.GeoDataFrame,
    mask: gpd.GeoDataFrame,
    update,
    where=None,
    dissolve: bool = False,
    workers: int = 4,
    progress: bool = False,
) -> gpd.GeoDataFrame:
    """Cut *base* by *mask* and apply ``update`` to the pieces inside the mask.

    Polygons of *base* that intersect *mask* (and pass the boolean ``where``) are
    split into the part inside the mask, which goes through
    ``update(pieces) -> pieces``, and the part outside, which keeps its
    attributes. All other polygons pass through without geometry work.

    Mask attributes are visible to ``update`` (a name already in *base* gets a
    ``_2`` suffix, see :func:`intersect_layers`) but are not carried into the
    result; columns ``update`` adds are kept. ``update`` may drop rows, which
    leaves that area out of the result.

    Overlapping mask polygons would give overlapping pieces, so the mask is made
    non-overlapping first with :func:`remove_overlaps`: the smaller polygon wins.

    ``dissolve`` merges the updated inside pieces that share all attributes.

    Returns *base*'s rows with the affected ones replaced by single-part pieces,
    on a fresh RangeIndex.
    """
    geom = base.geometry.name
    mask = remove_overlaps(mask, rank=mask.area, workers=workers)
    ok = np.ones(len(base), dtype=bool) if where is None else np.asarray(where, dtype=bool)
    cand = np.flatnonzero(ok)
    hit_in, _ = STRtree(mask.geometry.values).query(base.geometry.values[cand], predicate="intersects")
    hit = np.zeros(len(base), dtype=bool)
    hit[cand[np.unique(hit_in)]] = True

    affected = base[hit].reset_index(drop=True)
    inside = intersect_layers(affected, mask, workers=workers, progress=progress)
    outside = subtract_layer(affected, mask, workers=workers, progress=progress)

    seen = set(inside.columns)
    inside = update(inside)
    keep = list(base.columns) + [c for c in inside.columns if c not in seen]
    inside = inside[keep]
    if dissolve and len(inside):
        by = [c for c in keep if c != geom]
        inside = inside.dissolve(by=by, as_index=False, dropna=False) if by else inside.dissolve()
        inside = inside[keep]

    changed = _single_polygons(pd.concat([outside, inside], ignore_index=True))
    out = pd.concat([base[~hit], changed], ignore_index=True)
    return gpd.GeoDataFrame(out, geometry=geom, crs=base.crs)


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


def fill_torrfall_gaps(
    torrfall: gpd.GeoDataFrame,
    water: gpd.GeoDataFrame,
    tile_size: float = 5_000.0,
    margin: float = 1_000.0,
    max_area: float | None = None,
    workers: int = 4,
) -> gpd.GeoDataFrame:
    """Find water enclosed between tørrfall and land, using a water mask.

    The water mask is cut by the tørrfall polygons (``water − tørrfall``). The
    open sea stays one large connected piece; *standalone* pieces cut off from
    it lie between tørrfall and land (or inside tørrfall) and are returned so
    they can be merged into tørrfall. Nothing seaward is ever added, because
    the open sea is connected and therefore never standalone.

    Processed in tiles of *tile_size* with *margin* overlap: in each window a
    piece counts as standalone if it touches tørrfall and does **not** touch
    the window edge (i.e. it is closed off within the window); it is assigned
    to the tile containing its representative point, so nothing is counted
    twice. Standalone pieces wider than *margin* that cross a tile edge are
    missed; raise *margin* if needed.

    Parameters
    ----------
    torrfall : tørrfall polygons.
    water : water mask polygons (sea, fits the land line), same CRS.
    tile_size, margin : tiling (CRS units).
    max_area : optional upper area limit for a standalone piece (m²).
    workers : threads (shapely releases the GIL).

    Returns
    -------
    GeoDataFrame of standalone gap pieces (single polygons).
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    tf_geoms = torrfall.geometry.to_numpy()
    water_geoms = water.geometry.to_numpy()
    tf_tree, water_tree = STRtree(tf_geoms), STRtree(water_geoms)

    xmin, ymin, xmax, ymax = shapely.total_bounds(tf_geoms)
    xs = np.arange(xmin, xmax, tile_size)
    ys = np.arange(ymin, ymax, tile_size)
    gx, gy = np.meshgrid(xs, ys)
    tiles = shapely.box(gx, gy, gx + tile_size, gy + tile_size).ravel()
    tiles = tiles[np.unique(tf_tree.query(tiles, predicate="intersects")[0])]

    def one_tile(tile):
        window = shapely.buffer(tile, margin, join_style="mitre")
        tf_idx = tf_tree.query(window, predicate="intersects")
        w_idx = water_tree.query(window, predicate="intersects")
        if len(tf_idx) == 0 or len(w_idx) == 0:
            return []
        tf_w = shapely.union_all(shapely.intersection(tf_geoms[tf_idx], window))
        water_w = shapely.union_all(shapely.intersection(water_geoms[w_idx], window))
        parts = shapely.get_parts(_to_polygons(shapely.difference(water_w, tf_w)))
        parts = parts[~shapely.is_empty(parts)]
        if len(parts) == 0:
            return []
        edge = shapely.boundary(window)
        keep = ~shapely.intersects(parts, edge)
        keep &= shapely.dwithin(parts, tf_w, 0.01)
        keep &= shapely.contains(tile, shapely.point_on_surface(parts))
        if max_area is not None:
            keep &= shapely.area(parts) <= max_area
        return list(shapely.to_wkb(parts[keep]))

    n_workers = max(1, workers)
    print(f"Filling tørrfall gaps: {len(tf_geoms):,} tørrfall, {len(water_geoms):,} water, "
          f"{len(tiles):,} tiles of {tile_size / 1000:g} km, {n_workers} threads", flush=True)
    gaps: list[bytes] = []
    t0 = time.monotonic()
    step = max(1, len(tiles) // 100)
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        for i, res in enumerate(pool.map(one_tile, tiles), start=1):
            gaps.extend(res)
            if i % step == 0 or i == len(tiles):
                elapsed = time.monotonic() - t0
                eta = elapsed / i * (len(tiles) - i)
                print(f"  {i:,}/{len(tiles):,} tiles ({100 * i / len(tiles):.0f}%), "
                      f"{len(gaps):,} gap pieces, {elapsed / 60:.1f} min elapsed, "
                      f"~{eta / 60:.1f} min left", flush=True)

    geoms = shapely.from_wkb(gaps) if gaps else np.array([], dtype=object)
    out = gpd.GeoDataFrame(geometry=geoms, crs=torrfall.crs)
    print(f"Standalone gap pieces: {len(out):,} ({out.area.sum() / 1e6:,.2f} km²)")
    return out


def coverage_gaps(
    water: gpd.GeoDataFrame,
    coverage: gpd.GeoDataFrame,
    tile_size: float = 10_000.0,
    workers: int = 4,
) -> gpd.GeoDataFrame:
    """Return the part of *water* not covered by *coverage*, computed in tiles.

    ``water − coverage`` per tile: in each tile box the full water and coverage
    geometries intersecting it are unioned and differenced, and the result is
    clipped to the tile so neighbouring tiles abut without overlap or double
    counting. Memory-bounded (no global union/difference); threaded because
    shapely releases the GIL.

    Parameters
    ----------
    water : sea-mask polygons (the authoritative sea extent), same CRS as
        *coverage*.
    coverage : already-classified polygons stamped onto the sea.
    tile_size : tile edge in CRS units.
    workers : threads.

    Returns
    -------
    GeoDataFrame of uncovered gap polygons (single polygons), CRS of *water*.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    water_geoms = water.geometry.to_numpy()
    cov_geoms = coverage.geometry.to_numpy()
    water_tree, cov_tree = STRtree(water_geoms), STRtree(cov_geoms)

    xmin, ymin, xmax, ymax = shapely.total_bounds(water_geoms)
    xs = np.arange(xmin, xmax, tile_size)
    ys = np.arange(ymin, ymax, tile_size)
    gx, gy = np.meshgrid(xs, ys)
    tiles = shapely.box(gx, gy, gx + tile_size, gy + tile_size).ravel()
    tiles = tiles[np.unique(water_tree.query(tiles, predicate="intersects")[0])]

    def one_tile(tile):
        w_idx = water_tree.query(tile, predicate="intersects")
        if len(w_idx) == 0:
            return []
        gap = shapely.intersection(shapely.union_all(water_geoms[w_idx]), tile)
        c_idx = cov_tree.query(tile, predicate="intersects")
        if len(c_idx):
            gap = shapely.difference(gap, shapely.union_all(cov_geoms[c_idx]))
        parts = shapely.get_parts(_to_polygons(gap))
        parts = parts[~shapely.is_empty(parts)]
        return list(shapely.to_wkb(parts))

    n_workers = max(1, workers)
    print(f"Coverage gaps: {len(water_geoms):,} water, {len(cov_geoms):,} coverage, "
          f"{len(tiles):,} tiles of {tile_size / 1000:g} km, {n_workers} threads", flush=True)
    gaps: list[bytes] = []
    t0 = time.monotonic()
    step = max(1, len(tiles) // 100)
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        for i, res in enumerate(pool.map(one_tile, tiles), start=1):
            gaps.extend(res)
            if i % step == 0 or i == len(tiles):
                elapsed = time.monotonic() - t0
                eta = elapsed / i * (len(tiles) - i)
                print(f"  {i:,}/{len(tiles):,} tiles ({100 * i / len(tiles):.0f}%), "
                      f"{len(gaps):,} gap pieces, {elapsed / 60:.1f} min elapsed, "
                      f"~{eta / 60:.1f} min left", flush=True)

    geoms = shapely.from_wkb(gaps) if gaps else np.array([], dtype=object)
    out = gpd.GeoDataFrame(geometry=geoms, crs=water.crs)
    print(f"Gap pieces: {len(out):,} ({out.area.sum() / 1e6:,.2f} km²)")
    return out
