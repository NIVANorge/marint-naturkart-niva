"""Derive Naturkart data-model attributes for marine NiN polygons.

Populates the subset of ``nin_flate_NK`` fields derivable from ``nin_int``
(1-12) and ``nin_kode_fkid``. Fields requiring data not available in the
niche-model notebook (probabilities, uncertainty, alger, SeaBee, depth,
kalkinnhold, rute partitioning) are intentionally omitted.

Column names and codes follow ``datamodell_silver_nin_flate_NK.xlsx``;
:data:`DATAMODEL_UPDATE` maps datasets written with the previous attribute
names/values onto the current data model (see :func:`update_datamodel`).
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

import mnk.rules as R

# nin_int (1-12) axes decoded from NIN_INT_MAP in 03_nisjemodell.
_EUFOTISK = {1, 2, 3, 4, 5, 7, 9, 11}
_BRAKKVANN = {1, 3, 5, 6, 9, 10}
_FASTBUNN = {3, 4, 9, 10, 11, 12}
_TOERFALL = {1, 2, 3, 4}

# nin_kode_fkid -> prosess-kode (KODE k_nkm_prosess coupling table).
NKM_PROSESS: dict[str, str] = {
    "NA-MA01": "A", "NA-MA02": "A", "NA-MA03": "A",
    "NA-MA04": "A", "NA-MA05": "A", "NA-MA06": "A",
    "NA-MB02": "B", "NA-MF01": "F",
    "NA-MC01": "C", "NA-MC02": "C", "NA-MC04": "C",
    "NA-MC08": "C",
    "NA-MJ01": "J",
}

OPPHAV_KODE = "NKM"

OBS_SUBSTRAT_KILDE = "substrat_kartlagt_ngu"

METODE_USIKKERHET_NISJEDATA = "NKM_nisjedata_kvalitet"
METODE_USIKKERHET_HABITAT = "NKM_satelitt_habitat"

# Source provenance tokens (datamodell style ``<akse>_<metode>_<kilde>``), joined
# per polygon with SOURCE_SEP into the ``datakilde`` attribute. ``kartlagt`` =
# surveyed/observed, ``modellert`` = modeled, ``fjernmaalt`` = remote-sensed.
SOURCE_LYS_NIVA = "lys_modellert_niva"
SOURCE_LYS_SEABEE = "lys_fjernmaalt_seabee"
SOURCE_SALINITET_HI = "salinitet_modellert_hi"
SOURCE_SUBSTRAT_NIVA = "substrat_modellert_niva"
SOURCE_SUBSTRAT_NGU = OBS_SUBSTRAT_KILDE  # "substrat_kartlagt_ngu"
SOURCE_SUBSTRAT_SEABEE = "substrat_fjernmaalt_seabee"
SOURCE_TOERFALL_KARTVERKET = "toerfall_kartlagt_kartverket"
SOURCE_OKSYGENMANGEL_MDIR = "oksygenmangel_kartlagt_mdir"
SOURCE_TARETRALING_NIVA = "taretraling_kartlagt_niva"
SOURCE_SEP = " | "

# Working columns dropped once their derived attributes are set.
WORKING_COLS = ("_substrat_kilde", "_is_dem")

# Canonical nin_flate_NK attribute order (nisjemodell output, notebook 03).
# The geometry column is kept on the GeoDataFrame but is not an attribute.
NIN_FLATE_COLUMNS: list[str] = [
    "nk_fid",
    "opphav_kode",
    "nin_int",
    "nin_kode_fkid",
    "NiN_name",
    "nkm_prosess",
    R.COL_LYS,
    R.COL_SALINITET,
    R.COL_SUBSTRAT,
    R.COL_TOERFALL,
    "metode_klassifisering",
    "nkm_usikkerhet",
    "metode_usikkerhet",
    "datakilde",
]

# Previous attribute set -> current data model.
# ``columns``: old column -> new column (``None`` = dropped).
# ``values``: new column -> {old value -> new code}.
DATAMODEL_UPDATE: dict[str, dict] = {
    "columns": {
        "nkm_lys": R.COL_LYS,
        "nkm_salinitet": R.COL_SALINITET,
        "nkm_substrat": R.COL_SUBSTRAT,
        "nkm_toerfall": R.COL_TOERFALL,
        "datakilde": None,
    },
    "values": {
        R.COL_LYS: {
            "eufotisk": R.NKM_LYS["eufotisk"],
            "afotisk": R.NKM_LYS["afotisk"],
        },
        R.COL_SALINITET: {
            "saltvann": R.NKM_SALINITET["salt"],
            "brakkvann": R.NKM_SALINITET["brakk"],
        },
        R.COL_SUBSTRAT: {
            "fastbunn": R.NKM_SUBSTRAT["fast"],
            "loesbunn": R.NKM_SUBSTRAT["løst"],
        },
        R.COL_TOERFALL: {
            "toerfall": R.NKM_TOERFALL["innenfor"],
            "permanent_vanndekket": R.NKM_TOERFALL["utenfor"],
        },
    },
}


def update_datamodel(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Convert a dataset with the previous attributes to the current data model.

    Renames/drops columns and recodes values per :data:`DATAMODEL_UPDATE`.
    Values already in the new codes (or nulls) are left untouched; any other
    unknown value raises ``ValueError``.
    """
    cols = DATAMODEL_UPDATE["columns"]
    out = gdf.drop(columns=[c for c, new in cols.items() if new is None and c in gdf])
    out = out.rename(columns={c: new for c, new in cols.items() if new and c in out})
    for col, mapping in DATAMODEL_UPDATE["values"].items():
        if col not in out:
            continue
        valid = set(mapping) | set(mapping.values())
        bad = set(out[col].dropna().unique()) - valid
        if bad:
            raise ValueError(f"Unknown values in {col!r}: {sorted(bad)}")
        out[col] = out[col].map(lambda v: mapping.get(v, v))
    return out


def _as_bool(series: pd.Series) -> pd.Series:
    """Truth-aware coercion to boolean, safe for string ``"False"``/``"True"``.

    Handles real booleans, numerics, and the string representations that
    GeoPackage produces. Null/unrecognised values become ``False``.
    """
    if series.dtype == bool:
        return series
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0).astype(bool)
    normalized = series.astype("string").str.strip().str.lower()
    return normalized.isin(["true", "1"]).fillna(False)


def nkm_usikkerhet(
    gdf: gpd.GeoDataFrame,
    substrat_kilde_col: str = "_substrat_kilde",
    is_dem_col: str = "_is_dem",
) -> np.ndarray:
    """``lav`` for observed substrate, ``medium`` where DEM data exists, else ``høy``.

    Uncertainty is lowest for directly observed substrate, medium where a DEM
    informs the classification, and highest where neither applies.

    ``is_dem_col`` may be real booleans, numerics, or the strings ``"True"``/
    ``"False"`` that round-trip through GeoPackage. A plain ``astype(bool)`` is
    unsafe here because ``bool("False")`` is ``True``; values are therefore
    parsed truth-aware so string ``"False"`` maps to ``False``.
    """
    has_dem = _as_bool(gdf[is_dem_col]).to_numpy()
    is_obs = (gdf[substrat_kilde_col] == OBS_SUBSTRAT_KILDE).to_numpy()
    return np.where(is_obs, "lav", np.where(has_dem, "medium", "høy"))


def habitat_usikkerhet(prob: np.ndarray, conf: np.ndarray) -> np.ndarray:
    """SeaBee-habitat usikkerhet (``lav``/``medium``/``høy``) from the model P-values.

    ``prob`` is the per-polygon class-probability matrix (the ``p_*`` columns, %);
    ``conf`` the median own-class probability (the ``p50`` column, %). Uncertainty
    is ``lav`` only when the model is both confident and unambiguous
    (``conf >= 60`` and top1-top2 margin ``>= 30``), ``høy`` when confidence is low
    or two classes nearly tie (``conf < 40`` or margin ``< 10``), else ``medium``.
    This is the :data:`METODE_USIKKERHET_HABITAT` method.
    """
    prob = np.asarray(prob, dtype=float)
    conf = np.asarray(conf, dtype=float)
    top2 = np.sort(prob, axis=1)[:, -2:]
    margin = top2[:, 1] - top2[:, 0]
    out = np.full(len(conf), "medium", dtype=object)
    out[(conf >= 60) & (margin >= 30)] = "lav"
    out[(conf < 40) | (margin < 10)] = "høy"
    return out


def build_datakilde(
    substrat_kilde,
    toerfall,
    *,
    lys_token: str = SOURCE_LYS_NIVA,
    sal_token: str = SOURCE_SALINITET_HI,
) -> np.ndarray:
    """Join the per-axis source tokens into the ``datakilde`` string (``|``-separated).

    ``substrat_kilde`` is the per-polygon substrate source token (e.g.
    :data:`SOURCE_SUBSTRAT_NIVA` / :data:`SOURCE_SUBSTRAT_NGU` /
    :data:`SOURCE_SUBSTRAT_SEABEE`); ``toerfall`` the :data:`R.COL_TOERFALL`
    value, which adds :data:`SOURCE_TOERFALL_KARTVERKET` for intertidal polygons.
    Order is lys | salinitet | substrat | toerfall.
    """
    substrat = pd.Series(np.asarray(substrat_kilde), dtype="string").reset_index(drop=True)
    toer = pd.Series(np.asarray(toerfall)).reset_index(drop=True)
    base = lys_token + SOURCE_SEP + sal_token + SOURCE_SEP + substrat
    inner = (toer == R.NKM_TOERFALL["innenfor"]).to_numpy()
    return base.where(~inner, base + SOURCE_SEP + SOURCE_TOERFALL_KARTVERKET).to_numpy()


def add_nkm_attributes(
    gdf: gpd.GeoDataFrame,
    nin_int_col: str = "nin_int",
    kode_col: str = "nin_kode_fkid",
    substrat_kilde_col: str = "_substrat_kilde",
    metode_klassifisering: str = "NKM_regelbasert_dyp",
    is_dem_col: str = "_is_dem",
) -> gpd.GeoDataFrame:
    """Add derived Naturkart attributes to *gdf* and return the nin_flate_NK schema.

    ``nkm_usikkerhet`` (and its method ``metode_usikkerhet`` =
    :data:`METODE_USIKKERHET_NISJEDATA`) are added when both ``substrat_kilde_col``
    and ``is_dem_col`` exist (see :func:`nkm_usikkerhet`). Working
    columns (:data:`WORKING_COLS`) are dropped and the result is reduced to
    :data:`NIN_FLATE_COLUMNS` (those present, in canonical order).
    """
    out = gdf.copy()
    ints = out[nin_int_col]

    def axis(members: set[int], codes: dict[str, str], yes: str, no: str) -> pd.Series:
        return ints.map(lambda v: codes[yes] if v in members else codes[no])

    out["opphav_kode"] = OPPHAV_KODE
    out["metode_klassifisering"] = metode_klassifisering
    out[R.COL_LYS] = axis(_EUFOTISK, R.NKM_LYS, "eufotisk", "afotisk")
    out[R.COL_SALINITET] = axis(_BRAKKVANN, R.NKM_SALINITET, "brakk", "salt")
    out[R.COL_SUBSTRAT] = axis(_FASTBUNN, R.NKM_SUBSTRAT, "fast", "løst")
    out[R.COL_TOERFALL] = axis(_TOERFALL, R.NKM_TOERFALL, "innenfor", "utenfor")
    out["nkm_prosess"] = out[kode_col].map(NKM_PROSESS)

    if {substrat_kilde_col, is_dem_col} <= set(out.columns):
        out["nkm_usikkerhet"] = nkm_usikkerhet(
            out, substrat_kilde_col, is_dem_col
        )
        out["metode_usikkerhet"] = METODE_USIKKERHET_NISJEDATA

    if substrat_kilde_col in out.columns:
        out["datakilde"] = build_datakilde(out[substrat_kilde_col], out[R.COL_TOERFALL])

    out = out.drop(columns=[c for c in WORKING_COLS if c in out.columns])
    keep = [c for c in NIN_FLATE_COLUMNS if c in out.columns] + [out.geometry.name]
    return out[keep]
