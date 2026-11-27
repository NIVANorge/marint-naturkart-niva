"""03b -> 04 -> 05 chained through the mnk functions on toy polygons."""
import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

import mnk.attributes as A
import mnk.rules as R
from mnk.vectorize import overlay_update

CRS = "EPSG:25833"
LYS, SUB, TF = R.COL_LYS, R.COL_SUBSTRAT, R.COL_TOERFALL


def _gdf(geoms, **cols):
    return gpd.GeoDataFrame(cols, geometry=geoms, crs=CRS)


def _at(gdf, x, y):
    row = gdf[gdf.contains(Point(x, y))]
    assert len(row) == 1, (x, y, len(row))
    return row.iloc[0]


def _03b():
    # Raster classes: 7 = eufotisk salt løst utenfor, 8 = afotisk salt løst utenfor.
    nin = _gdf([box(0, 0, 10, 10), box(10, 0, 20, 10)], nin_int=[7, 8])
    nin = nin.join(A.axes_from_nin_int(nin["nin_int"])).drop(columns="nin_int")
    nin["datakilde"] = A.build_datakilde(A.SOURCE_SUBSTRAT_NIVA, nin[TF])

    torrfall = _gdf([box(0, 0, 4, 10), box(18, 0, 20, 10)])
    nin = overlay_update(
        nin,
        torrfall,
        lambda p: p.assign(
            **{TF: R.NKM_TOERFALL["innenfor"]},
            datakilde=A.set_kilde(p["datakilde"], A.SOURCE_TOERFALL_KARTVERKET),
        ),
        where=(nin[LYS] == R.NKM_LYS["eufotisk"]) & (nin[TF] == R.NKM_TOERFALL["utenfor"]),
    )

    obs = _gdf([box(2, 0, 6, 10)], _obs_substrat=[R.NKM_SUBSTRAT["fast"]])
    nin = overlay_update(
        nin,
        obs,
        lambda p: p.assign(
            **{SUB: p["_obs_substrat"]}, datakilde=A.set_kilde(p["datakilde"], A.SOURCE_SUBSTRAT_NGU)
        ),
        dissolve=True,
    )

    for col in A.USIKKERHET_AXIS_COLS:
        nin[col] = pd.array(["medium"] * len(nin), dtype="string")
    nin["nkm_usikkerhet_salinitet"] = pd.array(["høy"] * len(nin), dtype="string")
    nin["metode_usikkerhet"] = A.METODE_USIKKERHET_NISJEDATA
    return A.finalize(A.classify(nin))


def _04(niche):
    def update(p):
        p = A.classify(A.apply_seabee(p))
        return p[p["nin_kode_fkid"].notna()]

    seabee = _gdf([box(8, 0, 12, 10)], klasse=["ROCK"], _usikkerhet=["lav"])
    return A.finalize(overlay_update(niche, seabee, update))


def _05(final):
    kelp = _gdf([box(15, 0, 20, 5), box(16, 0, 20, 4)])

    def update(p):
        code = "NA-MJ01"
        return p.assign(
            nin_kode_fkid=code,
            NiN_name=R.NIN_NAMES[code],
            datakilde=A.set_kilde(p["datakilde"], A.SOURCE_TARETRALING_NIVA),
        )

    return A.finalize(overlay_update(final, kelp, update, dissolve=True))


def test_03b_axes_overlays_and_classification():
    out = _03b()
    assert out.area.sum() == pytest.approx(200)
    assert "nin_int" not in out
    # tørrfall + NGU fast -> NA-MA01; NGU fast outside tørrfall -> NA-MA02
    a = _at(out, 3, 5)
    assert a["nin_kode_fkid"] == "NA-MA01"
    assert a["datakilde"] == " | ".join(
        [A.SOURCE_LYS_NIVA, A.SOURCE_SALINITET_HI, A.SOURCE_SUBSTRAT_NGU, A.SOURCE_TOERFALL_KARTVERKET]
    )
    assert a["metode_klassifisering"] == (
        "NKM_modell_lyssone|NKM_modell_salinitet|NKM_direkte_bunntype|NKM_regelbasert_fjaeresone"
    )
    assert _at(out, 1, 5)["nin_kode_fkid"] == "NA-MA04"
    assert _at(out, 5, 5)["nin_kode_fkid"] == "NA-MA02"
    assert _at(out, 8, 5)["nin_kode_fkid"] == "NA-MA05"
    # afotisk is never remapped by tørrfall
    deep = _at(out, 19, 5)
    assert deep["nin_kode_fkid"] == "NA-MA06"
    assert deep[TF] == R.NKM_TOERFALL["utenfor"]
    assert set(out["nkm_usikkerhetsklasse"]) == {"høy"}
    assert list(out.columns) == [c for c in A.NIN_FLATE_COLUMNS if c in out] + ["geometry"]


def test_04_seabee_sets_its_axes_and_keeps_niche_salinity():
    out = _04(_03b())
    assert out.area.sum() == pytest.approx(200)
    for x in (9, 11):  # over the eufotisk and the afotisk niche polygon
        r = _at(out, x, 5)
        assert r["nin_kode_fkid"] == "NA-MA02"
        assert r["nkm_seabee_klasse"] == "ROCK"
        assert r[LYS] == R.NKM_LYS["eufotisk"]
        assert (r["nkm_usikkerhet_substrat"], r["nkm_usikkerhet_lys"], r["nkm_usikkerhet_salinitet"]) == (
            "lav", "lav", "høy"
        )
        assert r["nkm_usikkerhetsklasse"] == "høy"
        assert r["metode_usikkerhet"] == "NKM_satelitt_habitat|NKM_nisjedata_kvalitet"
        assert r["metode_klassifisering"] == "NKM_modell_satellitt|NKM_modell_salinitet"
    untouched = _at(out, 14, 5)
    assert untouched["nin_kode_fkid"] == "NA-MA06"
    assert pd.isna(untouched["nkm_seabee_klasse"])
    assert "klasse" not in out and "_usikkerhet" not in out


def test_05_direct_rule_overrides_type_and_appends_source():
    out = _05(_04(_03b()))
    assert out.area.sum() == pytest.approx(200)
    kelp = out[out["nin_kode_fkid"] == "NA-MJ01"]
    assert kelp.area.sum() == pytest.approx(25)
    r = _at(out, 17, 2)
    assert r["nkm_prosess"] == "J"
    assert r["datakilde"].endswith(A.SOURCE_TARETRALING_NIVA)
    assert r["metode_klassifisering"].endswith("NKM_direkte_taretralingsbunn")
    assert r["nkm_usikkerhet_salinitet"] == "høy"
