import geopandas as gpd
import pytest
from shapely.geometry import box

import mnk.rules as R
from mnk.attributes import DATAMODEL_UPDATE, update_datamodel

NKM_COLS = [R.COL_LYS, R.COL_SALINITET, R.COL_SUBSTRAT, R.COL_TOERFALL]


def _old_gdf():
    return gpd.GeoDataFrame(
        {
            "nkm_lys": ["eufotisk", "afotisk"],
            "nkm_salinitet": ["brakkvann", "saltvann"],
            "nkm_substrat": ["loesbunn", "fastbunn"],
            "nkm_toerfall": ["toerfall", "permanent_vanndekket"],
            "datakilde": ["lys_x|substrat_y", "lys_x"],
            "nkm_prosess": ["C", "A"],
        },
        geometry=[box(0, 0, 1, 1), box(1, 1, 2, 2)],
        crs="EPSG:25833",
    )


def test_update_datamodel_renames_and_recodes():
    out = update_datamodel(_old_gdf())
    assert "datakilde" not in out
    assert list(out.columns) == [*NKM_COLS, "nkm_prosess", "geometry"]
    assert out.iloc[0][NKM_COLS].tolist() == ["0abcde", "abcde", "0ABCD", "LM-TV_abcdefgh"]
    assert out.iloc[1][NKM_COLS].tolist() == ["y", "fgh", "EFGY", "LM-TV_0"]


def test_update_datamodel_is_idempotent():
    once = update_datamodel(_old_gdf())
    assert update_datamodel(once).equals(once)


def test_update_datamodel_rejects_unknown_values():
    gdf = _old_gdf()
    gdf.loc[0, "nkm_salinitet"] = "fersk"
    with pytest.raises(ValueError, match="nkm_lm-sa"):
        update_datamodel(gdf)


def test_update_map_covers_all_codes():
    values = DATAMODEL_UPDATE["values"]
    assert set(values[R.COL_LYS].values()) == set(R.NKM_LYS.values())
    assert set(values[R.COL_SALINITET].values()) == set(R.NKM_SALINITET.values())
    assert set(values[R.COL_SUBSTRAT].values()) == set(R.NKM_SUBSTRAT.values())
    assert set(values[R.COL_TOERFALL].values()) == set(R.NKM_TOERFALL.values())
