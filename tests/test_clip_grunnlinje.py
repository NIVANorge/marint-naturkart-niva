import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

import mnk.attributes as A
import mnk.rules as R
from mnk.vectorize import clip_to_grunnlinje

CRS = "EPSG:25833"


def test_axis_columns_survive_the_gpkg_round_trip(tmp_path):
    clip = tmp_path / "clip.gpkg"
    gpd.GeoDataFrame(geometry=[box(0, 0, 15, 10)], crs=CRS).to_file(clip, driver="GPKG")

    gdf = gpd.GeoDataFrame(
        A.axes_from_nin_int(pd.Series([7, 1])),
        geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10)],
        crs=CRS,
    )
    gdf["datakilde"] = A.build_datakilde(A.SOURCE_SUBSTRAT_NIVA, gdf[R.COL_TOERFALL])

    out = clip_to_grunnlinje(gdf, grunnlinje_url=str(clip))
    assert set(out.columns) == set(gdf.columns)
    assert out.area.sum() == pytest.approx(150)
    right = out[out.geometry.centroid.x > 10].iloc[0]
    assert right[R.COL_TOERFALL] == R.NKM_TOERFALL["innenfor"]
    assert right["datakilde"].endswith(A.SOURCE_TOERFALL_KARTVERKET)
