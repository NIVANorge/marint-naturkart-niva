import os
from pathlib import Path

import geopandas as gpd
import joblib
import numpy as np
import rasterio as rio
import xdem
from osgeo import gdal
from shapely.errors import GEOSException
from shapely.validation import explain_validity, make_valid
from sqlalchemy import create_engine

import subkart


def to_serializable(obj):
    """Convert numpy arrays and other non-serializable types to JSON-serializable formats."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: to_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [to_serializable(item) for item in obj]
    else:
        return obj

def dissolve_geometries(gdf: gpd.GeoDataFrame, by_col: str):
    """Dissolve geometries to fix neighboring features that are split on same depth"""
    try:
        gdf_dissolved = gdf.dissolve(by=by_col, as_index=False)
    except GEOSException as e:
        print(f"TopologicalError while dissolving {e}")
        invalid_mask = ~gdf.geometry.is_valid
        bad = gdf.loc[invalid_mask].copy()

        print(f"Invalid geometries: {invalid_mask.sum()} / {len(gdf)}")
        for i, geom in zip(bad.index, bad.geometry):
            print(i, explain_validity(geom))
        gdf["geometry"] = gdf.geometry.apply(make_valid)
        gdf_dissolved = gdf.dissolve(by=by_col, as_index=False)

    gdf_exploded = gdf_dissolved.explode(index_parts=False).reset_index(drop=True)

    return gdf_exploded


def model_dir_path() -> Path:
    return Path(__file__).resolve().parent.parent / "model"


def load_classifier():
    classifier_path = model_dir_path() / "classifier.joblib"
    classifier = joblib.load(classifier_path)
    return classifier


def resample_dem(dem: xdem.DEM, out_shape: tuple, transform: tuple, crs="EPSG:25833"):
    dst_array = np.empty(out_shape, dtype=dem.data.dtype)

    rio.warp.reproject(
        source=dem.data,
        destination=dst_array,
        src_transform=transform,
        src_crs=dem.crs,
        dst_transform=transform,
        dst_crs=crs,
        src_nodata=dem.nodata,
        dst_nodata=dem.nodata,
        resampling=rio.warp.Resampling.bilinear,
    )

    # Mask nodata values to avoid warning from geoutils
    if dem.nodata is not None:
        dst_array = np.ma.masked_equal(dst_array, dem.nodata)

    return xdem.DEM.from_array(dst_array, transform=transform, crs=crs, nodata=dem.nodata)


def to_geoparquet(input_gml_path: Path, layer_name: str, output_path: Path):
    """Save GML Download from NGU as GeoParquet

    Geoparquet is a really nice format for geospatial data optimized for cloud access.

    """
    gdf = gpd.read_file(input_gml_path, layer=layer_name)
    gdf.to_parquet(output_path, compression="snappy")
    print(f"Written GeoParquet to {output_path}")


def to_filename(ressurstittel, romligutstrekning, ressursdato, referansesystem):

    return f"{ressurstittel}_{romligutstrekning}_{ressursdato}_{referansesystem}"


def to_postgis(gdf, fname):

    if os.environ.get("NIVAGIS_CONNECTION_STR"):
        table_name = to_tablename(fname)
        conn = create_engine(os.environ["NIVAGIS_CONNECTION_STR"])
        gdf.to_postgis(table_name, schema="naturkartmarin", con=conn, if_exists="replace")
        print(f"Table {table_name} uploaded to PostGIS.")
    else:
        print("NIVAGIS_CONNECTION_STR not set. Skipping PostGIS upload.")


def to_tablename(fname: str) -> str:
    """Convert a filename to a table name."""
    return "_".join(fname.lower().split("_")[0:3]).replace("-", "_")[:50]


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
