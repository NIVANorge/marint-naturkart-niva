from logging import root
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
from sqlalchemy import union_all
import xdem
import shapely
import rasterio as rio
import rasterio.warp  # noqa: F401
from shapely import union_all

import mnk
import geoutils as gu

FYLKER = [
    "03_Oslo",
    "11_Rogaland",
    "15_More_og_Romsdal",
    "18_Nordland",
    "31_Ostfold",
    "32_Akershus",
    "33_Buskerud",
    "39_Vestfold",
    "40_Telemark",
    "42_Agder",
    "46_Vestland",
    "50_Trondelag",
    "55_Troms",
    "56_Finnmark",
]

REGIONS = {
    "vestland": ["More_og_Romsdal", "Vestland", "Rogaland"],
    "sor-ost": ["Agder", "Telemark", "Vestfold", "Ostfold", "Akershus", "Buskerud", "Oslo"],
    "midt": ["Trondelag", "Nordland"],
    "nord": ["Troms", "Finnmark"],
}


def dem_data():
    dem = xdem.DEM(
        rio.open("https://storage.googleapis.com/niva-geodata/MarintNaturKart/input/kartverket/dem50_norge.tif")
    )
    return dem


def sea_map_torrfall(fylker: list[str] = FYLKER):
    """Map basis data for the specified fylker or all

    Read output from `prepare_basis_depth_data`, if all fylker are specified `depth_training_data.geo.parquet` will be used
    it already have been preprocessed to add depth features from `features.depth_preprocess`.
    """

    county_files = []
    for f in fylker:
        code = next((c for c in FYLKER if c.endswith(f)))
        county_files.append(
            f"gs://niva-geodata/MarintNaturKart/input/kartverket/Basisdata_{code}_25833_torrfall.geo.parquet"
        )

    gdfs = [gpd.read_parquet(path) for path in county_files]

    gdf = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))
    del gdfs

    return gdf

def sea_map_basisdata(fylker: list[str] = FYLKER):
    """Map basis data for the specified fylker or all

    Read output from `prepare_basis_depth_data`, if all fylker are specified `depth_training_data.geo.parquet` will be used
    it already have been preprocessed to add depth features from `features.depth_preprocess`.
    """

    county_files = []
    for f in fylker:
        code = next((c for c in FYLKER if c.endswith(f)))
        county_files.append(
            f"gs://niva-geodata/MarintNaturKart/input/kartverket/Basisdata_{code}_25833_Dybdedata_Dybdeareal.geo.parquet"
        )

    gdfs = [gpd.read_parquet(path) for path in county_files]

    gdf_depth = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))
    del gdfs

    return gdf_depth


def hi_salinity():
    """Read HI salinity dataset

    https://kartkatalog.geonorge.no/metadata/norfjords160-saltholdighet/590a2f66-8b5d-4014-a7b6-9ffb0cf17dbd

    Direct download of the actual Float32 salinity values (WCS GetCoverage):
    https://kart.hi.no/mareano/marinegrunnkart_oseanografi/ows?service=WCS&version=2.0.1&request=GetCoverage&coverageId=marinegrunnkart_oseanografi:Norfjords_160_surf_salt_mean_UTM33&format=image/tiff
    """
    salinity_path = Path(__file__).resolve().parent.parent / Path(
        "hi/Norfjords_160_surf_salt_mean_UTM33.tif"
    )
    return gu.Raster(str(salinity_path))


SUBSTRAT_PADDED_PATH = (
    "gs://niva-geodata/MarintNaturKart/results/"
    "nisjedata-substrat-xgbclassifier_norge_latest_25833_padded.tif"
)
"""Padded substrate raster that defines the reference 50 m grid."""


def prepare_brakkvann(
    substrat_padded_path: str = SUBSTRAT_PADDED_PATH,
    fill_iterations: int = 3,
):
    """Prepare brakkvann (brackish water) raster from HI salinity data.

    Reads the HI surface salinity raster via :func:`hi_salinity` and classifies
    pixels as brakkvann where mean surface salinity is below 18. Two GeoTIFFs are
    written, both with 1 for brakkvann and 0 for not brakkvann:

    1. ``Norfjords_160_surf_salt_mean_UTM33_brakkvann.tif`` on the native HI grid.
    2. ``Norfjords_160_surf_salt_mean_UTM33_brakkvann_50m_filled.tif`` on the
       same 50 m grid as the padded substrate dataset (*substrat_padded_path*).
       The continuous salinity is bilinearly interpolated to 50 m *before* the
       ``< 18`` threshold, so the brakkvann boundary follows the interpolated
       isohaline instead of the 160 m cell edges. The result is dilated outward
       by *fill_iterations* 50 m rings so it overlaps the substrate cells.
    """
    # Read with rasterio: geoutils Raster crashes (double free) on this file.
    salinity_path = Path(__file__).resolve().parent.parent / "hi/Norfjords_160_surf_salt_mean_UTM33.tif"
    with rio.open(salinity_path) as src:
        data = src.read(1)
        salinity = SimpleNamespace(transform=src.transform, crs=src.crs, nodata=src.nodata)

    invalid = ~np.isfinite(data)
    if salinity.nodata is not None:
        invalid |= data == salinity.nodata
    brakkvann_data = (data < SALINITY_BRAKKVANN_THRESHOLD).astype(np.uint8)
    brakkvann_data[invalid] = 255

    hi_dir = Path(__file__).resolve().parent.parent / "hi"
    output_path = hi_dir / "Norfjords_160_surf_salt_mean_UTM33_brakkvann.tif"
    with rio.open(
        output_path, "w", driver="GTiff", height=brakkvann_data.shape[0],
        width=brakkvann_data.shape[1], count=1, dtype="uint8", nodata=255,
        crs=salinity.crs, transform=salinity.transform, compress="lzw",
    ) as ds:
        ds.write(brakkvann_data, 1)
    print(f"Written brakkvann GeoTIFF to {output_path}")

    filled_path = hi_dir / "Norfjords_160_surf_salt_mean_UTM33_brakkvann_50m_filled.tif"
    _write_brakkvann_filled(data, invalid, salinity, substrat_padded_path, fill_iterations, filled_path)
    print(f"Written 50 m filled brakkvann GeoTIFF to {filled_path}")


SALINITY_BRAKKVANN_THRESHOLD = 18.0
"""Mean surface salinity below this value is brakkvann."""


def _write_brakkvann_filled(
    salinity_data,
    invalid,
    salinity,
    substrat_padded_path,
    fill_iterations,
    out_path,
    coast_fill: int = 3,
):
    """Interpolate salinity to the substrate grid, threshold and fill with overlap.

    1. Fill *coast_fill* native cells into land with nearest values so the
       bilinear kernel does not mix in nodata along the coast.
    2. Reproject salinity (float) bilinearly onto the 50 m reference grid.
    3. Mask back to the original sea extent (nearest-reprojected validity).
    4. Threshold ``< SALINITY_BRAKKVANN_THRESHOLD`` -> 1/0 and pad by
       *fill_iterations* 50 m rings.
    """
    sentinel = np.float32(-9999.0)
    sal = np.where(invalid, sentinel, salinity_data).astype(np.float32)
    sal = mnk.vectorize.pad_nodata(sal, nodata=sentinel, iterations=coast_fill)
    valid_src = (~invalid).astype(np.uint8)

    with rio.open(substrat_padded_path) as ref:
        sal_dst = np.full((ref.height, ref.width), sentinel, dtype=np.float32)
        rio.warp.reproject(
            source=sal,
            destination=sal_dst,
            src_transform=salinity.transform,
            src_crs=salinity.crs,
            src_nodata=sentinel,
            dst_transform=ref.transform,
            dst_crs=ref.crs,
            dst_nodata=sentinel,
            resampling=rio.warp.Resampling.bilinear,
        )
        valid_dst = np.zeros((ref.height, ref.width), dtype=np.uint8)
        rio.warp.reproject(
            source=valid_src,
            destination=valid_dst,
            src_transform=salinity.transform,
            src_crs=salinity.crs,
            dst_transform=ref.transform,
            dst_crs=ref.crs,
            resampling=rio.warp.Resampling.nearest,
        )
        profile = ref.profile.copy()

    dst = np.full(sal_dst.shape, 255, dtype=np.uint8)
    ok = (valid_dst == 1) & (sal_dst != sentinel)
    dst[ok] = (sal_dst[ok] < SALINITY_BRAKKVANN_THRESHOLD).astype(np.uint8)
    del sal_dst, valid_dst, ok

    filled = mnk.vectorize.pad_nodata(dst, nodata=255, iterations=fill_iterations)

    profile.update(count=1, dtype="uint8", nodata=255, compress="lzw")  # deflate crashes (pip pyarrow vs conda GDAL)
    with rio.open(out_path, "w", **profile) as dst_ds:
        dst_ds.write(filled, 1)


def marine_vanntyper():
    """Read marine vanntyper

    Read marine vanntyper from gs://niva-geodata/MarintNaturKart/input/mdir/NyTypologi2022.geo.parquet
    """
    return gpd.read_parquet("gs://niva-geodata/MarintNaturKart/input/mdir/NyTypologi2022.geo.parquet")


def bolge_exposure():
    """Read bolge exposure data

    Read bolge exposure raster with additional 2 pixel filling

    Bølgeeksponeringsmodellen (Isæus 2004, Isæus og Rygg 2005) er kjørt for Norge av Norsk institutt for vannforskning (NIVA), 
    tilgjengeliggjort som en del av kartgrunnlaget beskrevet i Bekkby m.fl. (2025) 
    til grunn for kartlegging etter Miljødirektoratets instruks (Miljødirektoratet 2026)

    """
    return gu.Raster("gs://niva-geodata/MarintNaturKart/input/niva/EswmRaster_filled_cog.tif")

def prepare_grid():
    """Prepare the SSB 1 km statistical grid.

    Converts the national SSB 1 km grid (``SSB_Ruter1km`` layer) from GML to
    GeoParquet. Data downloaded from Geonorge:
    https://kartkatalog.geonorge.no/metadata/statistisk-rutenett-1000m/32ac0653-d95c-456e-8f26-54b9a7a3ca9c
    """

    layer = "SSB_Ruter1km"
    base = Path(__file__).resolve().parent.parent / "ssb"
    gml_path = base / "Basisdata_0000_Norge_25833_StatistiskRutenett1km_GML.gml"
    output_path = base / "Basisdata_0000_Norge_25833_StatistiskRutenett1km.geo.parquet"
    gdf = gpd.read_file(gml_path, layer=layer)
    gdf.to_parquet(output_path, compression="snappy")
    return output_path


def prepare_eu_grid():
    """Prepare the EU reference 1 km grid for Norway.

    Converts the EEA EU reference grid (``NO_1km`` layer, EPSG:3035) from
    GeoPackage to GeoParquet and derives the ``rute_fkid`` "Rute kode" used by
    the datamodell (``EofOrigin_km``\\_``NofOrigin_km``, e.g. ``3897_3674``).
    The original ``CellCode`` (e.g. ``1kmE3897N3674``) is retained.

    Data downloaded from the EEA reference grid:
    https://www.eea.europa.eu/en/datahub/datahubitem-view/3c362237-daa4-45e2-8c16-aaadfb1a003b
    """

    layer = "NO_1km"
    base = Path(__file__).resolve().parent.parent / "eu"
    gpkg_path = base / "NO_1km.gpkg"
    output_path = base / "NO_1km.geo.parquet"
    gdf = gpd.read_file(gpkg_path, layer=layer)
    gdf["rute_fkid"] = (
        (gdf["EofOrigin"] // 1000).astype(int).astype(str)
        + "_"
        + (gdf["NofOrigin"] // 1000).astype(int).astype(str)
    )
    gdf.to_parquet(output_path, compression="snappy")
    return output_path


def prepare_torrfall():
    """Prepare torrfall.

    Data downloaded from Geonorge, at https://kartkatalog.geonorge.no/metadata/sjoekart-dybdedata/2751aacf-5472-4850-a208-3532a51c529a?search=basisdata%20sj%C3%B8
    
    """
    
    torrfall_layer = "Tørrfall"
    for region in FYLKER:
        gml_path = Path(__file__).resolve().parent.parent / f"geonorge/Basisdata_{region}_25833_Dybdedata_GML.gml"
        output_path = Path(__file__).resolve().parent.parent / Path(
            f"geonorge/Basisdata_{region}_25833_torrfall.geo.parquet"
        )
        gdf_torrfall = gpd.read_file(gml_path, layer=torrfall_layer)
        gdf_torrfall.to_parquet(output_path, compression="snappy")


def prepare_depth_point_data():
    """Extract Dybdepunkt point layer from GML files.

    These are measured depth soundings that are more accurate than the
    min/max ranges on the Dybdeareal polygons, especially for large
    polygons with wide depth ranges.  Output is saved as geoparquet
    per region.
    """
    for region in FYLKER:
        gml_path = Path(__file__).resolve().parent.parent / f"geonorge/Basisdata_{region}_25833_Dybdedata_GML.gml"
        output_path = Path(__file__).resolve().parent.parent / Path(
            f"geonorge/Basisdata_{region}_25833_Dybdepunkt.geo.parquet"
        )

        gdf = gpd.read_file(gml_path, layer="Dybdepunkt", columns=["dybde"])
        gdf = gdf[["dybde", "geometry"]]
        gdf.to_parquet(output_path, compression="snappy")
        print(f"  {region}: {len(gdf)} depth points -> {output_path}")



def depth_point_data(fylker: list[str] = FYLKER) -> gpd.GeoDataFrame:
    """Read prepared depth point data for the given fylker.

    Returns a GeoDataFrame with columns ``dybde`` and ``geometry`` (points).
    """
    county_files = []
    for f in fylker:
        code = next((c for c in FYLKER if c.endswith(f)))
        path = f"gs://niva-geodata/MarintNaturKart/input/kartverket/Basisdata_{code}_25833_Dybdepunkt.geo.parquet"
        county_files.append(path)

    gdfs = [gpd.read_parquet(p) for p in county_files]
    return gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))


def prepare_sea_basis_depth_data():
    """Prepare basis depth data for processing.

    Data downloaded from Geonorge, at https://kartkatalog.geonorge.no/metadata/sjoekart-dybdedata/2751aacf-5472-4850-a208-3532a51c529a?search=basisdata%20sj%C3%B8
    This data is used as a basis for further analysis and modeling and output saved to geoparquet format.
    """
    layer = "Dybdeareal"
    torrfall_layer = "Tørrfall"
    for region in FYLKER:
        gml_path = Path(__file__).resolve().parent.parent / f"geonorge/Basisdata_{region}_25833_Dybdedata_GML.gml"
        output_path = Path(__file__).resolve().parent.parent / Path(
            f"geonorge/Basisdata_{region}_25833_Dybdedata_{layer}.geo.parquet"
        )
        gdf = gpd.read_file(gml_path, layer=layer)
        gdf_torrfall = gpd.read_file(gml_path, layer=torrfall_layer)
        gdf_torrfall["minimumsdybde"] = 0
        gdf_torrfall["maksimumsdybde"] = 0.5
        gdf = pd.concat([gdf, gdf_torrfall], ignore_index=True)
       
        gdf.to_parquet(output_path, compression="snappy")
        print(f"Written GeoParquet to {output_path}")


WATER_MASK_PATH = (
    "field/water-mask-norway_FKB-osm-border-dissolved-fullres_v3-grunnlinje-1-nautisk-mil_25833_20260924.gpkg"
)


# Gaps at least this large (m²) are treated as standing waterbodies (possible
# brakkvannspoll), split off to their own file instead of merged into tørrfall.
BRAKKVANNSPOLL_MIN_AREA = 5e4  # 5 ha


def prepare_torrfall_filled(
    water_path: str = WATER_MASK_PATH,
    max_area: float | None = None,
    brakkvannspoll_min_area: float = BRAKKVANNSPOLL_MIN_AREA,
    tile_size: float = 5_000.0,
    workers: int = 4,
) -> Path:
    """Merge water enclosed between tørrfall and land into tørrfall; run once.

    The water mask (fits the land line) is cut by tørrfall; standalone water
    pieces cut off from the open sea are added to tørrfall
    (:func:`mnk.vectorize.fill_torrfall_gaps`). Output has a ``_gap`` column
    (False = original tørrfall, True = added piece).

    Added pieces at least ``brakkvannspoll_min_area`` m² are unusually large
    enclosed waterbodies (possible brakkvannspoll) rather than tidal flat; they
    are excluded from the filled tørrfall and written separately to
    ``geonorge/possible_brakkvannspoll_25833.geo.parquet``.

    Filled tørrfall written to
    ``geonorge/torrfall-filled_norge_25833.geo.parquet``.
    """
    crs = "EPSG:25833"
    root = Path(__file__).resolve().parent.parent
    print("Reading tørrfall ...", flush=True)
    torrfall = sea_map_torrfall().to_crs(crs)[["geometry"]].reset_index(drop=True)
    torrfall["geometry"] = shapely.make_valid(torrfall.geometry.to_numpy())
    print("Reading water mask ...", flush=True)
    water = gpd.read_file(root / water_path, columns=[]).to_crs(crs)[["geometry"]]

    gaps = mnk.vectorize.fill_torrfall_gaps(
        torrfall, water, tile_size=tile_size, max_area=max_area, workers=workers
    )
    del water

    is_poll = shapely.area(gaps.geometry.to_numpy()) >= brakkvannspoll_min_area
    polls = gaps[is_poll].reset_index(drop=True)
    gaps = gaps[~is_poll].reset_index(drop=True)
    poll_path = root / "geonorge/possible_brakkvannspoll_25833.geo.parquet"
    polls.to_parquet(poll_path, compression="snappy")
    print(
        f"Written {len(polls):,} possible brakkvannspoll "
        f"(>= {brakkvannspoll_min_area/1e4:g} ha) to {poll_path}"
    )

    out = gpd.GeoDataFrame(
        pd.concat([torrfall.assign(_gap=False), gaps.assign(_gap=True)], ignore_index=True),
        crs=crs,
    )

    output_path = root / "geonorge/torrfall-filled_norge_25833.geo.parquet"
    print(f"Writing {output_path} ...", flush=True)
    out.to_parquet(output_path, compression="snappy")
    print(f"Written {len(out):,} polygons ({len(gaps):,} added) to {output_path}")
    return output_path


def prepare_land_data():
    """Prepare basis depth data for processing.

    Data downloaded from Geonorge, at https://kartkatalog.geonorge.no/metadata/sjoekart-dybdedata/2751aacf-5472-4850-a208-3532a51c529a?search=basisdata%20sj%C3%B8
    This data is used as a basis for further analysis and modeling and output saved to geoparquet format.
    """
    layer = "Landareal"

    crs = "EPSG:25833"
    
    gdf_list = []
    for region in FYLKER:
        gml_path = Path(__file__).resolve().parent.parent / f"geonorge/Basisdata_{region}_25833_Dybdedata_GML.gml"
        gdf = gpd.read_file(gml_path, layer=layer)
        gdf_list.append(gdf.to_crs(crs).geometry.values)
    
    geoms = np.concatenate(gdf_list)
    geoms = shapely.make_valid(geoms)
    
    output_path = Path(__file__).resolve().parent.parent / "geonorge/Basisdata_Landareal.gpkg"
    
    gdf = gpd.GeoDataFrame(geometry=geoms, crs=crs)
    gdf.to_file(output_path, layer="landareal", driver="GPKG")
    gdf.to_parquet(Path(__file__).resolve().parent.parent / "geonorge/Basisdata_Landareal.geo.parquet", compression="snappy")
    union_geom = union_all(geoms)
    del geoms
    
    gdf_union = gpd.GeoDataFrame(geometry=[union_geom], crs=crs)
    gdf_union.to_file(output_path, layer="landareal_union", driver="GPKG")
    
    print(f"Written GeoPackage to {output_path}")


def prepare_bunnsediment_kornstor_detalj():
    """Prepare bunnsediment kornstor detalj data for processing.

    Data downloaded from Geonorge, at https://kartkatalog.geonorge.no/metadata/bunnsedimenter-kornstoerrelse-detaljert/79f0f17d-9f62-456d-b1a9-2a8c754c51c4
    """
    sediments_detailed = Path(__file__).resolve().parent.parent / Path(
        "ngu_sediment/Geologi_0000_Norge_25833_BunnsedimentKornstorDetalj_GML/BunnsedimentKornstorDetalj.gml"
    )
    output_path = Path(__file__).resolve().parent.parent / Path(
        "ngu_sediment/BunnsedimentKornstorDetalj.geo.parquet"
    )
    subkart.utils.to_geoparquet(sediments_detailed, "KornstrFlate", output_path)


def prepare_marine_vanntyper():
    """Prepare marine vann typer data for processing.

    Data downloaded from MDir, at https://dataleveranser.miljodirektoratet.no/nedlasting/b0fa9d93-dd2d-48fd-a89f-8fa224555c4d/
    """
    marine_vanntyper = Path(__file__).resolve().parent.parent / Path(
        "mdir/NyTypologi2022.shp"
    )
    output_path = Path(__file__).resolve().parent.parent / Path(
        "mdir/NyTypologi2022.geo.parquet"
    )
    subkart.utils.to_geoparquet(marine_vanntyper, None, output_path)


def prepare_mv_aoi():
    """
    Prepare area of interest (AOI) data for processing.

    Combines marine vanntyper and missing area geometries into a single AOI.
    """


    crs = "EPSG:25833"

    geoms = np.concatenate([
        mnk.sources.marine_vanntyper().to_crs(crs).geometry.values,
        gpd.read_parquet("gs://niva-geodata/MarintNaturKart/aux/aoi_missing.geo.parquet").to_crs(crs).geometry.values,
    ])
    geoms = shapely.make_valid(geoms)

    gpd.GeoDataFrame(geometry=geoms, crs=crs).to_parquet("aoi_from_marine_vanntyper.geo.parquet")

    union_geom = union_all(geoms)
    del geoms

    gpd.GeoDataFrame(geometry=[union_geom], crs=crs).to_parquet("aoi_from_marine_vanntyper_union.geo.parquet")

