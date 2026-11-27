import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

import mnk.attributes as A
import mnk.rules as R

CRS = "EPSG:25833"
LYS, SAL, SUB, TF = R.COL_LYS, R.COL_SALINITET, R.COL_SUBSTRAT, R.COL_TOERFALL
NIVA = A.SOURCE_SEP.join([A.SOURCE_LYS_NIVA, A.SOURCE_SALINITET_HI, A.SOURCE_SUBSTRAT_NIVA])


def _niche(*nin_ints, **cols):
    """Niche-model rows decoded from 03a raster classes, with default datakilde."""
    ints = pd.Series(nin_ints)
    g = gpd.GeoDataFrame(
        A.axes_from_nin_int(ints), geometry=[box(i, 0, i + 1, 1) for i in range(len(ints))], crs=CRS
    )
    g["datakilde"] = A.build_datakilde(A.SOURCE_SUBSTRAT_NIVA, g[TF])
    for k, v in cols.items():
        g[k] = v
    return g


# axes_from_nin_int / axis_tokens


def test_axes_from_nin_int_codes_every_class():
    ints = pd.Series(list(R.NIN_INT_AXES), index=np.arange(100, 112))
    axes = A.axes_from_nin_int(ints)
    assert list(axes.columns) == [LYS, SAL, SUB, TF]
    assert axes.index.equals(ints.index)
    for i, (lys, sal, sub, tf) in R.NIN_INT_AXES.items():
        row = axes.loc[ints[ints == i].index[0]]
        assert row.tolist() == [R.NKM_LYS[lys], R.NKM_SALINITET[sal], R.NKM_SUBSTRAT[sub], R.NKM_TOERFALL[tf]]


def test_axes_from_nin_int_rejects_unknown_class():
    with pytest.raises(ValueError, match="255"):
        A.axes_from_nin_int(pd.Series([1, 255]))


def test_axis_tokens_round_trip():
    ints = pd.Series(list(R.NIN_INT_AXES))
    tokens = A.axis_tokens(A.axes_from_nin_int(ints))
    assert list(tokens.columns) == ["lys", "salinitet", "substrat", "toerfall"]
    assert [tuple(r) for r in tokens.itertuples(index=False)] == list(R.NIN_INT_AXES.values())


def test_axis_tokens_unknown_code_is_na():
    df = pd.DataFrame({LYS: ["bogus"], SAL: ["fgh"], SUB: ["EFGY"], TF: ["LM-TV_0"]})
    assert pd.isna(A.axis_tokens(df).loc[0, "lys"])


# set_kilde


@pytest.mark.parametrize(
    "before,token,after",
    [
        (NIVA, A.SOURCE_SUBSTRAT_NGU,
         " | ".join([A.SOURCE_LYS_NIVA, A.SOURCE_SALINITET_HI, A.SOURCE_SUBSTRAT_NGU])),
        (NIVA, A.SOURCE_TOERFALL_KARTVERKET, NIVA + " | " + A.SOURCE_TOERFALL_KARTVERKET),
        (NIVA + " | " + A.SOURCE_OKSYGENMANGEL_MDIR, A.SOURCE_TOERFALL_KARTVERKET,
         NIVA + " | " + A.SOURCE_TOERFALL_KARTVERKET + " | " + A.SOURCE_OKSYGENMANGEL_MDIR),
        (NIVA + " | " + A.SOURCE_OKSYGENMANGEL_MDIR, A.SOURCE_TARETRALING_NIVA,
         NIVA + " | " + A.SOURCE_OKSYGENMANGEL_MDIR + " | " + A.SOURCE_TARETRALING_NIVA),
        (NIVA, A.SOURCE_LYS_SEABEE,
         " | ".join([A.SOURCE_LYS_SEABEE, A.SOURCE_SALINITET_HI, A.SOURCE_SUBSTRAT_NIVA])),
        (None, A.SOURCE_TARETRALING_NIVA, A.SOURCE_TARETRALING_NIVA),
        ("", A.SOURCE_TARETRALING_NIVA, A.SOURCE_TARETRALING_NIVA),
    ],
)
def test_set_kilde(before, token, after):
    assert A.set_kilde([before], token).tolist() == [after]


def test_set_kilde_is_idempotent_and_vectorised():
    dk = pd.Series([NIVA, None, NIVA], index=[5, 6, 7])
    once = A.set_kilde(dk, A.SOURCE_SUBSTRAT_NGU)
    assert len(once) == 3
    assert once[0] == once[2]
    assert A.set_kilde(once, A.SOURCE_SUBSTRAT_NGU).tolist() == once.tolist()


def test_set_kilde_matches_build_datakilde():
    toerfall = [R.NKM_TOERFALL["innenfor"]]
    built = A.build_datakilde([A.SOURCE_SUBSTRAT_NGU], toerfall)
    stepwise = A.set_kilde(A.set_kilde([NIVA], A.SOURCE_TOERFALL_KARTVERKET), A.SOURCE_SUBSTRAT_NGU)
    assert stepwise.tolist() == built.tolist()


# classify


def test_classify_niche_rows_match_classify_nisje():
    g = A.classify(_niche(*R.NIN_INT_AXES))
    expected = [R.classify_nisje(*axes) for axes in R.NIN_INT_AXES.values()]
    assert list(zip(g["nin_kode_fkid"], g["NiN_name"])) == expected


def test_classify_uses_seabee_class_and_falls_back_to_niche():
    g = _niche(8, 8, 8, 8, nkm_seabee_klasse=pd.array(["ANGIO", None, "DEEP", "TERR_VEG"], dtype="string"))
    out = A.classify(g)
    assert out["nin_kode_fkid"].tolist()[:3] == ["NA-MB02", "NA-MA06", "NA-MA06"]
    assert pd.isna(out["nin_kode_fkid"].iloc[3])


def test_classify_incomplete_axes_give_na_and_input_is_untouched():
    g = _niche(7, 7)
    g.loc[1, SAL] = None
    before = g.copy()
    out = A.classify(g)
    assert out["nin_kode_fkid"].iloc[0] == "NA-MA05"
    assert pd.isna(out["nin_kode_fkid"].iloc[1])
    assert "nin_kode_fkid" not in g
    pd.testing.assert_frame_equal(g, before)


# apply_seabee


def _seabee_pieces(klasse, usikkerhet, sal_u="høy"):
    g = _niche(*[8] * len(klasse))  # afotisk salt løst utenfor
    g["nkm_usikkerhet_substrat"] = pd.array(["medium"] * len(g), dtype="string")
    g["nkm_usikkerhet_lys"] = pd.array(["medium"] * len(g), dtype="string")
    g["nkm_usikkerhet_salinitet"] = pd.array([sal_u] * len(g), dtype="string")
    g["klasse"] = klasse
    g["_usikkerhet"] = usikkerhet
    return g


def test_apply_seabee_rock_sets_substrate_light_and_their_usikkerhet():
    out = A.apply_seabee(_seabee_pieces(["ROCK"], ["lav"])).iloc[0]
    assert out[SUB] == R.NKM_SUBSTRAT["fast"]
    assert out[LYS] == R.NKM_LYS["eufotisk"]
    assert out[SAL] == R.NKM_SALINITET["salt"]
    assert out[TF] == R.NKM_TOERFALL["utenfor"]
    assert out[R.COL_SA_FA] == R.NKM_SA_FA["stein"]
    assert out["nkm_seabee_klasse"] == "ROCK"
    assert (out["nkm_usikkerhet_substrat"], out["nkm_usikkerhet_lys"], out["nkm_usikkerhet_salinitet"]) == (
        "lav", "lav", "høy"
    )
    assert out["datakilde"] == " | ".join(
        [A.SOURCE_LYS_SEABEE, A.SOURCE_SALINITET_HI, A.SOURCE_SUBSTRAT_SEABEE]
    )
    assert out["metode_usikkerhet"] == "NKM_satelitt_habitat|NKM_nisjedata_kvalitet"


@pytest.mark.parametrize(
    "klasse,sub,sa_fa",
    [("ALGAE", "fast", "alger"), ("SEDIMENT", "løst", None), ("ANGIO", "løst", None)],
)
def test_apply_seabee_per_class(klasse, sub, sa_fa):
    out = A.apply_seabee(_seabee_pieces([klasse], ["medium"])).iloc[0]
    assert out[SUB] == R.NKM_SUBSTRAT[sub]
    assert out[LYS] == R.NKM_LYS["eufotisk"]
    assert (pd.isna(out[R.COL_SA_FA]) if sa_fa is None else out[R.COL_SA_FA] == R.NKM_SA_FA[sa_fa])


def test_apply_seabee_class_without_overrides_keeps_niche_axes():
    g = _seabee_pieces(["DEEP"], ["lav"])
    out = A.apply_seabee(g).iloc[0]
    for col in (LYS, SAL, SUB, TF, "datakilde", "nkm_usikkerhet_substrat", "nkm_usikkerhet_lys"):
        assert out[col] == g.iloc[0][col]
    assert out["metode_usikkerhet"] == "NKM_nisjedata_kvalitet"


def test_apply_seabee_without_niche_usikkerhet_is_habitat_only():
    g = _seabee_pieces(["ROCK"], ["lav"], sal_u=None)
    assert A.apply_seabee(g)["metode_usikkerhet"].iloc[0] == "NKM_satelitt_habitat"


def test_apply_seabee_missing_seabee_usikkerhet_gives_na_axes():
    out = A.apply_seabee(_seabee_pieces(["ROCK"], [None])).iloc[0]
    assert pd.isna(out["nkm_usikkerhet_substrat"]) and pd.isna(out["nkm_usikkerhet_lys"])


def test_apply_seabee_works_without_usikkerhet_columns():
    g = _niche(8, klasse=["ROCK"], _usikkerhet=["lav"])
    out = A.apply_seabee(g).iloc[0]
    assert out["nkm_usikkerhet_substrat"] == "lav"
    assert out["metode_usikkerhet"] == "NKM_satelitt_habitat"


def test_apply_seabee_then_classify():
    g = A.classify(A.apply_seabee(_seabee_pieces(["ROCK", "ANGIO", "SEDIMENT"], ["lav"] * 3)))
    assert g["nin_kode_fkid"].tolist() == ["NA-MA02", "NA-MB02", "NA-MA05"]


# finalize


def test_finalize_derives_fields_and_orders_columns():
    g = A.classify(_niche(4, 12, _junk=1, nin_int=[4, 12]))
    g["nkm_usikkerhet_substrat"] = pd.array(["lav", None], dtype="string")
    g["nkm_usikkerhet_lys"] = pd.array(["høy", None], dtype="string")
    g["nkm_usikkerhet_salinitet"] = pd.array(["lav", None], dtype="string")
    g["metode_usikkerhet"] = A.METODE_USIKKERHET_NISJEDATA
    out = A.finalize(g)
    assert list(out.columns) == [c for c in A.NIN_FLATE_COLUMNS if c in out.columns] + ["geometry"]
    assert "_junk" not in out and "nin_int" not in out
    assert out["opphav_kode"].tolist() == ["NKM", "NKM"]
    assert out["nkm_prosess"].tolist() == ["A", "A"]
    assert out["nkm_usikkerhetsklasse"].tolist() == ["høy", "medium"]
    assert out["metode_klassifisering"].iloc[0] == (
        "NKM_modell_lyssone|NKM_modell_salinitet|NKM_modell_bunntype|NKM_regelbasert_fjaeresone"
    )


def test_finalize_without_usikkerhet_leaves_combined_out():
    out = A.finalize(A.classify(_niche(7)))
    assert "nkm_usikkerhetsklasse" not in out


def test_finalize_unclassified_row_has_na_prosess():
    g = _niche(7).assign(nin_kode_fkid=[None], NiN_name=[None])
    assert pd.isna(A.finalize(g)["nkm_prosess"].iloc[0])
