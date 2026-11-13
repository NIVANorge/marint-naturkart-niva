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
from osgeo import gdal
from sqlalchemy import create_engine


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


def dem_majority(
    gdf: gpd.GeoDataFrame, dem_path: str, block_rows: int = 1024
) -> np.ndarray:
    """True where most of a polygon's pixels in *dem_path* equal 1.

    Polygons are burned as IDs onto the DEM grid in row strips and DEM
    pixels counted per ID. Polygons covering no pixel centre fall back to
    the value at their representative point.
    """
    n = len(gdf)
    dem_px = np.zeros(n, dtype=np.int64)
    all_px = np.zeros(n, dtype=np.int64)
    with rasterio.open(dem_path) as src:
        geoms = gdf.geometry.to_crs(src.crs).values
        tree = shapely.STRtree(geoms)
        for row0 in range(0, src.height, block_rows):
            win = Window(0, row0, src.width, min(block_rows, src.height - row0))
            idx = tree.query(shapely.box(*window_bounds(win, src.transform)))
            if not len(idx):
                continue
            ids = rasterize(
                zip(geoms[idx], idx + 1),
                out_shape=(int(win.height), int(win.width)),
                transform=src.window_transform(win),
                fill=0,
                dtype="uint32",
            )
            hit = ids > 0
            poly = ids[hit] - 1
            all_px += np.bincount(poly, minlength=n)
            dem_px += np.bincount(poly, weights=src.read(1, window=win)[hit] == 1, minlength=n).astype(np.int64)

        is_dem = dem_px * 2 > all_px
        tiny = np.flatnonzero(all_px == 0)
        if len(tiny):
            pts = gpd.GeoSeries(geoms[tiny], crs=src.crs).representative_point()
            vals = np.array([v[0] for v in src.sample(zip(pts.x, pts.y))])
            is_dem[tiny] = vals == 1
    return is_dem
