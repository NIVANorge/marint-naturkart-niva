"""Shared utilities for the mnk package."""

import os

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from rasterio.features import rasterize
from rasterio.windows import Window
from rasterio.windows import bounds as window_bounds
from rasterio.transform import rowcol
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling
from osgeo import gdal
from sqlalchemy import create_engine

# Decision-margin thresholds for the nisjemodell usikkerhet (NKM_nisjedata_kvalitet).
# A NiN class flips when a continuous driver crosses a threshold, so a small
# margin means the pixel sits near a class boundary and is uncertain.
# (lav >= first, høy < second); between the two is medium.
USIKKERHET_SUB = (0.40, 0.10)   # |P_soft - P_hard| from the calibrated substrate probs
USIKKERHET_LYS = (0.30, 0.10)   # |z_eu - depth| / z_eu (relative: Kd490 error scales with z_eu)
USIKKERHET_SAL = (6.0, 2.0)     # |salinity - 18 PSU| (wide: HI mean-surface model error)
SALINITY_BRAKKVANN = 18.0
EUPHOTIC_LN = float(np.log(100.0))  # 1 % light (euphotic) depth = ln(100) / Kd490


def grid_subdivide(
    gdf: gpd.GeoDataFrame,
    cell: float = 10_000.0,
    max_vertices: int = 256,
) -> gpd.GeoDataFrame:
    """Split only the large polygons into a grid of small pieces.

    Polygons with more than ``max_vertices`` vertices (e.g. a single dissolved
    mainland) are clipped against a fishnet of square cells, while smaller
    polygons (islands, skerries) pass through untouched. The union of the
    output equals the input, so the coastline is preserved exactly — this just
    tiles the few huge polygons so that downstream per-polygon vector
    operations such as :func:`mnk.vectorize.subtract_land` only interact with
    nearby tiles instead of one full-resolution coastline.

    Uses an STRtree plus vectorized GEOS ``intersection`` and skips the many
    small polygons, which is substantially faster than ``gpd.overlay`` or
    tiling every geometry.

    Parameters
    ----------
    gdf : GeoDataFrame to subdivide.
    cell : grid cell size in CRS units (default 10 km).
    max_vertices : polygons with at most this many vertices are left as-is.

    Returns
    -------
    GeoDataFrame of exploded polygon pieces (attributes preserved).
    """
    geoms = gdf.geometry.to_numpy()
    is_big = shapely.get_num_coordinates(geoms) > max_vertices

    parts = [gdf.loc[~is_big]]
    if is_big.any():
        big = gdf.loc[is_big]
        big_geoms = geoms[is_big]

        xmin, ymin, xmax, ymax = shapely.total_bounds(big_geoms)
        xs = np.arange(xmin, xmax + cell, cell)
        ys = np.arange(ymin, ymax + cell, cell)
        x0, y0 = (a.ravel() for a in np.meshgrid(xs, ys))
        boxes = shapely.box(x0, y0, x0 + cell, y0 + cell)

        tree = shapely.STRtree(big_geoms)
        box_idx, geom_idx = tree.query(boxes, predicate="intersects")
        clipped = shapely.intersection(big_geoms[geom_idx], boxes[box_idx])

        tiled = big.iloc[geom_idx].reset_index(drop=True)
        tiled = tiled.set_geometry(gpd.GeoSeries(clipped, crs=gdf.crs))
        parts.append(tiled)

    out = gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True), crs=gdf.crs
    )
    out = out[~out.geometry.is_empty & out.geometry.notna()]
    out = out.explode(index_parts=False).reset_index(drop=True)
    out = out[out.geom_type.isin(["Polygon", "MultiPolygon"])].reset_index(drop=True)
    return out


def to_filename(ressurstittel, romligutstrekning, ressursdato, referansesystem):
    return f"{ressurstittel}_{romligutstrekning}_{ressursdato}_{referansesystem}"


def to_tablename(fname: str) -> str:
    """Convert a filename to a table name."""
    return "_".join(fname.lower().split("_")[0:3]).replace("-", "_")[:50]


def to_postgis(gdf, fname):
    if os.environ.get("NIVAGIS_CONNECTION_STR"):
        table_name = to_tablename(fname)
        conn = create_engine(os.environ["NIVAGIS_CONNECTION_STR"])
        gdf.to_postgis(table_name, schema="naturkartmarin", con=conn, if_exists="replace")
        print(f"Table {table_name} uploaded to PostGIS.")
    else:
        print("NIVAGIS_CONNECTION_STR not set. Skipping PostGIS upload.")


def parquet_to_postgis(parquet_path: str, crs: str = "EPSG:25833"):
    """Stream a GeoParquet file from GCS to PostGIS using GDAL."""

    gdal.UseExceptions()

    if not os.environ.get("NIVAGIS_CONNECTION_STR"):
        print("NIVAGIS_CONNECTION_STR not set. Skipping PostGIS upload.")
        return

    pg_conn_str = os.environ["NIVAGIS_CONNECTION_STR"]

    print("Streaming GeoParquet from GCS to PostGIS using osgeo.gdal...")

    source = f"/vsicurl/{parquet_path}" if parquet_path.startswith("https://") else parquet_path
    table_name = "naturkartmarin." + to_tablename(os.path.basename(parquet_path).split(".")[0])
    gdal.SetConfigOption("PG_USE_COPY", "YES")

    options = gdal.VectorTranslateOptions(
        format="PostgreSQL",
        layerName=table_name,
        layerCreationOptions=[
            "GEOMETRY_NAME=geom",
            "FID=fid",
            "SPATIAL_INDEX=GIST",
        ],
        callback=gdal.TermProgress_nocb,
        SRC_SRS=crs,
        DST_SRS=crs,
    )

    gdal.VectorTranslate(
        destNameOrDestDS=f"PG:{pg_conn_str}",
        srcDS=source,
        options=options,
    )

    print("Table successfully loaded!")


def _axis_usikkerhet(margin: np.ndarray, lav: float, hoy: float) -> np.ndarray:
    """Map a per-polygon decision margin to 1=lav, 2=medium, 3=høy; 0 where NaN."""
    cls = np.where(margin >= lav, 1, np.where(margin < hoy, 3, 2))
    return np.where(np.isnan(margin), 0, cls).astype(np.int8)


def nisje_axis_margins(
    gdf: gpd.GeoDataFrame,
    *,
    kd_path: str,
    depth_path: str,
    salinity_path: str,
    subprob_path: str,
    block: int = 1024,
    progress: bool = True,
) -> np.ndarray:
    """Per-polygon decision margin for the substrate, light and salinity axes.

    A NiN class flips when a continuous driver crosses a threshold, so a polygon
    is uncertain when any axis sits near its boundary. Per-pixel margins are
    computed on the ``depth_path`` grid (``kd_path``/``salinity_path``/
    ``subprob_path`` warped onto it) and averaged per polygon via burned IDs.
    Polygons too small to cover a pixel centre fall back to the margin at their
    representative-point pixel (sampled from the same streamed data, no extra
    reads). Returns a ``(3, len(gdf))`` array (substrate, light, salinity); NaN
    only where even that pixel is nodata. :func:`usikkerhet_from_margins` turns
    it into lav/medium/høy.

    Raster data is read in ``block`` x ``block`` tiles so peak memory stays
    bounded by the tile size rather than the full raster width.
    """
    n = len(gdf)
    sums = np.zeros((3, n))
    cnts = np.zeros((3, n), dtype=np.int64)
    fb = np.full((3, n), np.nan, dtype="float32")
    with rasterio.open(depth_path) as ref:
        geoms = gdf.geometry.to_crs(ref.crs).values
        tree = shapely.STRtree(geoms)
        reps = gpd.GeoSeries(geoms, crs=ref.crs).representative_point()
        rep_r, rep_c = (np.asarray(a) for a in rowcol(ref.transform, reps.x.values, reps.y.values))
        grid = dict(crs=ref.crs, transform=ref.transform, width=ref.width, height=ref.height)
        with rasterio.open(kd_path) as kd_src, rasterio.open(salinity_path) as sal_src, \
                rasterio.open(subprob_path) as sub_src, \
                WarpedVRT(kd_src, resampling=Resampling.bilinear, **grid) as kd_v, \
                WarpedVRT(sal_src, resampling=Resampling.bilinear, **grid) as sal_v, \
                WarpedVRT(sub_src, resampling=Resampling.nearest, **grid) as sub_v:
            n_tiles = len(range(0, ref.height, block)) * len(range(0, ref.width, block))
            done = 0
            for row0 in range(0, ref.height, block):
                h = min(block, ref.height - row0)
                for col0 in range(0, ref.width, block):
                    done += 1
                    if progress:
                        covered = int((cnts[0] > 0).sum())
                        print(
                            f"\r  nisje_usikkerhet: tile {done:,}/{n_tiles:,}"
                            f" ({100 * done / n_tiles:.0f}%), {covered:,}/{n:,} polygons covered",
                            end="",
                            flush=True,
                        )
                    w = min(block, ref.width - col0)
                    win = Window(col0, row0, w, h)
                    idx = tree.query(shapely.box(*window_bounds(win, ref.transform)))
                    if not len(idx):
                        continue
                    ids = rasterize(
                        zip(geoms[idx], idx + 1),
                        out_shape=(h, w),
                        transform=ref.window_transform(win),
                        fill=0,
                        dtype="uint32",
                    )
                    hit = ids > 0
                    poly = ids[hit] - 1

                    depth_raw = ref.read(1, window=win).astype("float32")
                    depth = np.abs(np.where(depth_raw == ref.nodata, np.nan, depth_raw))
                    kd = kd_v.read(1, window=win).astype("float32")
                    kd = np.where(kd > 0, kd, np.nan)
                    sal = sal_v.read(1, window=win).astype("float32")
                    if sal_v.nodata is not None:
                        sal = np.where(sal == sal_v.nodata, np.nan, sal)
                    soft = sub_v.read(1, window=win).astype("float32")
                    hard = sub_v.read(3, window=win).astype("float32")
                    if sub_v.nodata is not None:
                        bad = soft == sub_v.nodata
                        soft = np.where(bad, np.nan, soft)
                        hard = np.where(bad, np.nan, hard)

                    z_eu = EUPHOTIC_LN / kd
                    margins = (
                        np.abs(soft - hard),
                        np.abs(z_eu - depth) / z_eu,
                        np.abs(sal - SALINITY_BRAKKVANN),
                    )
                    for a, m in enumerate(margins):
                        mv = m[hit]
                        ok = ~np.isnan(mv)
                        sums[a] += np.bincount(poly[ok], weights=mv[ok], minlength=n)
                        cnts[a] += np.bincount(poly[ok], minlength=n)

                    in_tile = np.flatnonzero(
                        (rep_r >= row0) & (rep_r < row0 + h)
                        & (rep_c >= col0) & (rep_c < col0 + w)
                    )
                    if len(in_tile):
                        lr = rep_r[in_tile] - row0
                        lc = rep_c[in_tile] - col0
                        for a, m in enumerate(margins):
                            fb[a, in_tile] = m[lr, lc]
            if progress:
                print()

    with np.errstate(invalid="ignore"):
        means = np.where(cnts > 0, sums / np.maximum(cnts, 1), np.nan)
    return np.where(cnts == 0, fb, means)


def usikkerhet_from_margins(
    means: np.ndarray,
    is_obs: np.ndarray | None = None,
    sub: tuple[float, float] = USIKKERHET_SUB,
    lys: tuple[float, float] = USIKKERHET_LYS,
    sal: tuple[float, float] = USIKKERHET_SAL,
) -> np.ndarray:
    """Classify per-axis margins into ``lav``/``medium``/``høy``.

    ``means`` is the ``(3, n)`` array from :func:`nisje_axis_margins`. The worst
    (most uncertain) axis wins; ``is_obs`` (NGU-observed substrate) forces the
    substrate axis to ``lav``; a polygon with no axis data defaults to medium.
    Thresholds default to the module ``USIKKERHET_*`` constants.
    """
    sub_c = _axis_usikkerhet(means[0], *sub)
    if is_obs is not None:
        sub_c = np.where(np.asarray(is_obs, dtype=bool), 1, sub_c).astype(np.int8)
    worst = np.maximum.reduce([
        sub_c,
        _axis_usikkerhet(means[1], *lys),
        _axis_usikkerhet(means[2], *sal),
    ])
    worst[worst == 0] = 2
    return np.array(["", "lav", "medium", "høy"], dtype=object)[worst]


def nisje_usikkerhet(
    gdf: gpd.GeoDataFrame,
    *,
    kd_path: str,
    depth_path: str,
    salinity_path: str,
    subprob_path: str,
    is_obs: np.ndarray | None = None,
    block: int = 1024,
    progress: bool = True,
) -> np.ndarray:
    """Per-polygon usikkerhet (``lav``/``medium``/``høy``) from axis decision margins.

    Thin wrapper over :func:`nisje_axis_margins` + :func:`usikkerhet_from_margins`
    using the module ``USIKKERHET_*`` thresholds.
    """
    means = nisje_axis_margins(
        gdf,
        kd_path=kd_path,
        depth_path=depth_path,
        salinity_path=salinity_path,
        subprob_path=subprob_path,
        block=block,
        progress=progress,
    )
    return usikkerhet_from_margins(means, is_obs=is_obs)
