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

# Per-axis usikkerhet (lav/medium/høy, NA = no data); nkm_usikkerhetsklasse is the
# worst of these. Order matches mnk.utils.nisje_axis_margins (substrate, light, salinity).
USIKKERHET_AXIS_COLS: tuple[str, str, str] = (
    "nkm_usikkerhet_substrat",
    "nkm_usikkerhet_lys",
    "nkm_usikkerhet_salinitet",
)

USIKKERHET_KLASSER: tuple[str, str, str] = ("lav", "medium", "høy")

# Working columns dropped once their derived attributes are set.
WORKING_COLS = ("_substrat_kilde",)

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
    "nkm_usikkerhetsklasse",
    *USIKKERHET_AXIS_COLS,
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


# Each datakilde source token -> its k_metode classification code. metode_klassifisering
# is the de-duplicated, datakilde-ordered pipe-list of these; see metode_from_datakilde.
METODE_FROM_KILDE: dict[str, str] = {
    SOURCE_LYS_NIVA: "NKM_modell_lyssone",
    SOURCE_LYS_SEABEE: "NKM_modell_satellitt",
    SOURCE_SALINITET_HI: "NKM_modell_salinitet",
    SOURCE_SUBSTRAT_NIVA: "NKM_modell_bunntype",
    SOURCE_SUBSTRAT_NGU: "NKM_direkte_bunntype",
    SOURCE_SUBSTRAT_SEABEE: "NKM_modell_satellitt",
    SOURCE_TOERFALL_KARTVERKET: "NKM_regelbasert_fjaeresone",
    SOURCE_OKSYGENMANGEL_MDIR: "NKM_direkte_oksygenmangel",
    SOURCE_TARETRALING_NIVA: "NKM_direkte_taretralingsbunn",
}

METODE_SEP = "|"


def metode_from_datakilde(datakilde) -> np.ndarray:
    """Derive the ``metode_klassifisering`` pipe-list from the ``datakilde`` attribute.

    Each :data:`SOURCE_SEP`-joined datakilde token is mapped to its k_metode code
    (:data:`METODE_FROM_KILDE`); duplicates are dropped keeping datakilde order and
    the codes are joined with :data:`METODE_SEP`. NA/empty datakilde yields NA.
    """
    def one(dk):
        if pd.isna(dk) or not dk:
            return pd.NA
        codes: list[str] = []
        for tok in dk.split(SOURCE_SEP):
            code = METODE_FROM_KILDE.get(tok)
            if code and code not in codes:
                codes.append(code)
        return METODE_SEP.join(codes) if codes else pd.NA

    return pd.Series(np.asarray(datakilde), dtype="string").map(one).to_numpy()


def worst_usikkerhet(axes: pd.DataFrame, default: str = "medium") -> pd.Series:
    """Row-wise worst (most uncertain) of ``lav``/``medium``/``høy`` label columns.

    NA labels are ignored; a row with no label at all gets ``default``, matching
    the combined class from :func:`mnk.utils.usikkerhet_from_margins`.
    """
    rank = {k: i for i, k in enumerate(USIKKERHET_KLASSER, start=1)}
    worst = axes.apply(lambda s: s.map(rank)).max(axis=1)
    label = worst.map({i: k for k, i in rank.items()}).fillna(default)
    return label.astype("string")


def add_nkm_attributes(
    gdf: gpd.GeoDataFrame,
    nin_int_col: str = "nin_int",
    kode_col: str = "nin_kode_fkid",
    substrat_kilde_col: str = "_substrat_kilde",
    metode_klassifisering: str | None = None,
    usikkerhet: np.ndarray | pd.DataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Add derived Naturkart attributes to *gdf* and return the nin_flate_NK schema.

    When ``usikkerhet`` is given (the per-axis decision-margin estimate from
    :func:`mnk.utils.nisje_usikkerhet`) it sets ``nkm_usikkerhetsklasse`` with
    ``metode_usikkerhet`` = :data:`METODE_USIKKERHET_NISJEDATA`. A DataFrame
    (row-aligned with *gdf*) also sets the :data:`USIKKERHET_AXIS_COLS` it holds;
    a plain array sets only the combined class. Working columns
    (:data:`WORKING_COLS`) are dropped and the result is reduced to
    :data:`NIN_FLATE_COLUMNS` (those present, in canonical order).
    """
    out = gdf.copy()
    ints = out[nin_int_col]

    def axis(members: set[int], codes: dict[str, str], yes: str, no: str) -> pd.Series:
        return ints.map(lambda v: codes[yes] if v in members else codes[no])

    out["opphav_kode"] = OPPHAV_KODE
    out[R.COL_LYS] = axis(_EUFOTISK, R.NKM_LYS, "eufotisk", "afotisk")
    out[R.COL_SALINITET] = axis(_BRAKKVANN, R.NKM_SALINITET, "brakk", "salt")
    out[R.COL_SUBSTRAT] = axis(_FASTBUNN, R.NKM_SUBSTRAT, "fast", "løst")
    out[R.COL_TOERFALL] = axis(_TOERFALL, R.NKM_TOERFALL, "innenfor", "utenfor")
    out["nkm_prosess"] = out[kode_col].map(NKM_PROSESS)

    if isinstance(usikkerhet, pd.DataFrame):
        for col in ("nkm_usikkerhetsklasse", *USIKKERHET_AXIS_COLS):
            if col in usikkerhet:
                out[col] = usikkerhet[col].array
        out["metode_usikkerhet"] = METODE_USIKKERHET_NISJEDATA
    elif usikkerhet is not None:
        out["nkm_usikkerhetsklasse"] = np.asarray(usikkerhet)
        out["metode_usikkerhet"] = METODE_USIKKERHET_NISJEDATA

    if substrat_kilde_col in out.columns:
        out["datakilde"] = build_datakilde(out[substrat_kilde_col], out[R.COL_TOERFALL])
        out["metode_klassifisering"] = metode_from_datakilde(out["datakilde"])
    else:
        out["metode_klassifisering"] = metode_klassifisering

    out = out.drop(columns=[c for c in WORKING_COLS if c in out.columns])
    keep = [c for c in NIN_FLATE_COLUMNS if c in out.columns] + [out.geometry.name]
    return out[keep]
