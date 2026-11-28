"""Derive Naturkart data-model attributes for marine NiN polygons.

Through 03b-05 each polygon carries its state as the four axis columns
(:data:`AXES`, data-model codes), ``datakilde`` (one source token per axis, see
:func:`set_kilde`) and the per-axis usikkerhet. Steps only change the axes they
are responsible for; :func:`classify` derives the NiN type from the axes (plus a
SeaBee class) and :func:`finalize` derives the remaining ``nin_flate_NK`` fields
and the canonical column order.

Column names and codes follow ``datamodell_silver_nin_flate_NK.xlsx``;
:data:`DATAMODEL_UPDATE` maps datasets written with the previous attribute
names/values onto the current data model (see :func:`update_datamodel`).
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

import mnk.rules as R

# Rule axis -> (column, {rule token -> data-model code}), in classify_nisje order.
AXES: dict[str, tuple[str, dict[str, str]]] = {
    axis: R.NKM[axis] for axis in ("lys", "salinitet", "substrat", "toerfall")
}

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

# SeaBee class -> rule token per axis it overrides. ANGIO (undervannseng) is soft
# bottom; classify_seabee handles it separately, so it is added here for the column.
SEABEE_AXIS_OVERRIDE: dict[str, dict[str, str]] = {
    "substrat": {**R.SEABEE_SUBSTRAT_OVERRIDE, "ANGIO": "løst"},
    "lys": dict(R.SEABEE_LYS_OVERRIDE),
}
SEABEE_KILDE: dict[str, str] = {"substrat": SOURCE_SUBSTRAT_SEABEE, "lys": SOURCE_LYS_SEABEE}
SEABEE_USIKKERHET_COL: dict[str, str] = {
    "substrat": "nkm_usikkerhet_substrat",
    "lys": "nkm_usikkerhet_lys",
}

# Canonical nin_flate_NK attribute order; finalize() keeps those present.
# The geometry column is kept on the GeoDataFrame but is not an attribute.
NIN_FLATE_COLUMNS: list[str] = [
    "nk_fid",
    "opphav_kode",
    "nin_kode_fkid",
    "NiN_name",
    "nkm_prosess",
    R.COL_LYS,
    R.COL_SALINITET,
    R.COL_SUBSTRAT,
    R.COL_TOERFALL,
    R.COL_SA_FA,
    "metode_klassifisering",
    "nkm_usikkerhetsklasse",
    *USIKKERHET_AXIS_COLS,
    "metode_usikkerhet",
    "datakilde",
    "nkm_seabee_klasse",
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

    ``substrat_kilde`` is the substrate source token, per polygon or one for all (e.g.
    :data:`SOURCE_SUBSTRAT_NIVA` / :data:`SOURCE_SUBSTRAT_NGU` /
    :data:`SOURCE_SUBSTRAT_SEABEE`); ``toerfall`` the :data:`R.COL_TOERFALL`
    value, which adds :data:`SOURCE_TOERFALL_KARTVERKET` for intertidal polygons.
    Order is lys | salinitet | substrat | toerfall.
    """
    toer = pd.Series(np.asarray(toerfall)).reset_index(drop=True)
    substrat = pd.Series(np.broadcast_to(np.asarray(substrat_kilde, dtype=object), len(toer)), dtype="string")
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


def map_unique(df: pd.DataFrame, fn, columns: list[str] | None = None):
    """Apply ``fn(*row)`` once per unique row of *df* and scatter the results back.

    Rule lookups have few distinct inputs but run over millions of polygons, so
    this calls ``fn`` once per combination. NA values reach ``fn`` as ``None``.
    Without ``columns`` an object array aligned with *df* is returned; with
    ``columns`` each ``fn`` result is a tuple and a DataFrame on *df*'s index is.
    """
    codes = df.groupby(list(df.columns), dropna=False, sort=False).ngroup().to_numpy()
    first = np.unique(codes, return_index=True)[1]
    uniq = df.iloc[first].astype(object)
    uniq = uniq.where(uniq.notna(), None)
    res = [fn(*row) for row in uniq.itertuples(index=False, name=None)]
    if columns is not None:
        table = pd.DataFrame(res, columns=columns) if res else pd.DataFrame(columns=columns)
        return table.iloc[codes].set_axis(df.index)
    out = np.empty(len(res), dtype=object)
    for i, r in enumerate(res):
        out[i] = r
    return out[codes]


def usikkerhet_from_band(band) -> pd.Series:
    """Band (1 = lav, 2 = medium, 3 = høy, 0 = none) -> usikkerhet label (NA for 0)."""
    labels = {i: k for i, k in enumerate(USIKKERHET_KLASSER, start=1)}
    return pd.Series(np.asarray(band)).map(labels).astype("string")


def worst_usikkerhet(axes: pd.DataFrame, default: str = "medium") -> pd.Series:
    """Row-wise worst (most uncertain) of ``lav``/``medium``/``høy`` label columns.

    NA labels are ignored; a row with no label at all gets ``default``, matching
    the combined class from :func:`mnk.utils.usikkerhet_from_margins`.
    """
    rank = {k: i for i, k in enumerate(USIKKERHET_KLASSER, start=1)}
    worst = axes.apply(lambda s: s.map(rank)).max(axis=1)
    label = worst.map({i: k for k, i in rank.items()}).fillna(default)
    return label.astype("string")


# datakilde token prefix -> position; other prefixes follow in insertion order.
KILDE_ORDER: dict[str, int] = {axis: i for i, axis in enumerate(AXES)}


def axes_from_nin_int(nin_int: pd.Series) -> pd.DataFrame:
    """Decode the 03a raster class (1-12) into the four axis columns (codes).

    Returns a DataFrame on ``nin_int``'s index with the :data:`AXES` columns.
    Raises ``ValueError`` for a class not in :data:`mnk.rules.NIN_INT_AXES`.
    """
    unknown = set(pd.unique(nin_int)) - set(R.NIN_INT_AXES)
    if unknown:
        raise ValueError(f"Unknown nin_int values: {sorted(unknown)}")
    out = {}
    for i, (col, codes) in enumerate(AXES.values()):
        lut = {k: codes[axes[i]] for k, axes in R.NIN_INT_AXES.items()}
        out[col] = nin_int.map(lut)
    return pd.DataFrame(out, index=nin_int.index)


def from_raster_class(raster_class: pd.Series) -> pd.DataFrame:
    """Decode the 03a raster value into the axis columns and the salinity usikkerhet.

    The value packs the :data:`mnk.rules.NIN_INT_AXES` class and the salinity band
    (:func:`mnk.rules.encode_raster_class`). Raises ``ValueError`` for values without
    the band, i.e. a 03a output written before the band existed.
    """
    nin, sal = R.decode_raster_class(raster_class.to_numpy())
    if (sal == 0).any():
        raise ValueError("03a output without the salinity usikkerhet band; rerun 03a")
    out = axes_from_nin_int(pd.Series(nin, index=raster_class.index))
    out["nkm_usikkerhet_salinitet"] = usikkerhet_from_band(sal).array
    return out


def axis_tokens(gdf: pd.DataFrame) -> pd.DataFrame:
    """The four axis columns translated back to rule tokens (``eufotisk``, ...)."""
    return pd.DataFrame(
        {axis: gdf[col].map({v: k for k, v in codes.items()}) for axis, (col, codes) in AXES.items()},
        index=gdf.index,
    )


def _set_kilde_one(datakilde, token: str) -> str:
    prefix = token.split("_", 1)[0]
    tokens = [] if pd.isna(datakilde) or not datakilde else datakilde.split(SOURCE_SEP)
    tokens = [t for t in tokens if t.split("_", 1)[0] != prefix] + [token]
    pos = {t: (KILDE_ORDER.get(t.split("_", 1)[0], len(KILDE_ORDER)), i) for i, t in enumerate(tokens)}
    return SOURCE_SEP.join(sorted(tokens, key=pos.get))


def set_kilde(datakilde, token: str) -> np.ndarray:
    """Set the source of one axis in ``datakilde`` strings.

    A token's axis is its prefix (``substrat`` in ``substrat_kartlagt_ngu``); an
    existing token for that axis is replaced, otherwise the token is added. The
    four :data:`AXES` keep their order (lys | salinitet | substrat | toerfall); other
    tokens (direct datasets) follow in the order they were added.
    """
    s = pd.Series(np.asarray(datakilde, dtype=object))
    lut = {v: _set_kilde_one(v, token) for v in s.dropna().unique()}
    return s.map(lut).fillna(token).to_numpy(dtype=object)


def classify(gdf: gpd.GeoDataFrame, seabee_col: str = "nkm_seabee_klasse") -> gpd.GeoDataFrame:
    """Set ``nin_kode_fkid`` / ``NiN_name`` from the axes and the SeaBee class.

    Uses :func:`mnk.rules.classify_seabee`, which falls back to
    :func:`mnk.rules.classify_nisje` where ``seabee_col`` is missing or NA. Rows
    with an incomplete axis or a non-marine SeaBee class get NA.
    """
    keys = axis_tokens(gdf)
    keys.insert(0, "seabee", gdf[seabee_col] if seabee_col in gdf else None)
    nin = map_unique(
        keys,
        lambda sb, *axes: R.classify_seabee(sb, *axes) or (None, None),
        columns=["nin_kode_fkid", "NiN_name"],
    )
    return gdf.assign(
        nin_kode_fkid=nin["nin_kode_fkid"].to_numpy(),
        NiN_name=nin["NiN_name"].to_numpy(),
    )


def apply_seabee(
    gdf: gpd.GeoDataFrame, klasse_col: str = "klasse", usikkerhet_col: str = "_usikkerhet"
) -> gpd.GeoDataFrame:
    """Let the SeaBee class in ``klasse_col`` set the axes it overrides.

    Per :data:`SEABEE_AXIS_OVERRIDE` axis the class sets the axis code, its
    ``datakilde`` token (:data:`SEABEE_KILDE`) and its usikkerhet (the SeaBee
    ``usikkerhet_col``); other axes keep their values. Also sets
    ``nkm_seabee_klasse``, ``nkm_sa-fa`` and ``metode_usikkerhet``: the SeaBee
    method where it set an axis, plus the niche method where a remaining axis
    has a usikkerhet. Call :func:`classify` afterwards for the NiN type.
    """
    out = gdf.copy()
    klasse = out[klasse_col]
    seabee_axis = np.zeros(len(out), dtype=bool)
    niche_axis = np.zeros(len(out), dtype=bool)
    for axis, override in SEABEE_AXIS_OVERRIDE.items():
        col, codes = AXES[axis]
        hit = klasse.isin(override).to_numpy()
        out[col] = klasse.map({k: codes[v] for k, v in override.items()}).where(hit, out[col])
        out["datakilde"] = np.where(hit, set_kilde(out["datakilde"], SEABEE_KILDE[axis]), out["datakilde"])
        u = SEABEE_USIKKERHET_COL[axis]
        out[u] = out[usikkerhet_col].astype("string").where(hit, _string_col(out, u))
        seabee_axis |= hit
        niche_axis |= ~hit & out[u].notna().to_numpy()
    niche_axis |= _string_col(out, "nkm_usikkerhet_salinitet").notna().to_numpy()

    out["nkm_seabee_klasse"] = klasse.astype("string")
    sa_fa = {k: R.NKM_SA_FA[v] for k, v in R.SEABEE_SA_FA_OVERRIDE.items()}
    out[R.COL_SA_FA] = klasse.map(sa_fa).astype("string")
    both = METODE_SEP.join([METODE_USIKKERHET_HABITAT, METODE_USIKKERHET_NISJEDATA])
    metode = np.select(
        [seabee_axis & niche_axis, seabee_axis, niche_axis],
        [both, METODE_USIKKERHET_HABITAT, METODE_USIKKERHET_NISJEDATA],
        default="",
    )
    out["metode_usikkerhet"] = pd.Series(metode, index=out.index).replace("", pd.NA).astype("string")
    return out


def _string_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df:
        return df[col].astype("string")
    return pd.Series(pd.NA, index=df.index, dtype="string")


def finalize(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Derive the remaining nin_flate_NK fields and reduce to the canonical schema.

    Sets ``opphav_kode``, ``nkm_prosess`` (from ``nin_kode_fkid``),
    ``metode_klassifisering`` (from ``datakilde``) and, when the per-axis
    usikkerhet columns are present, ``nkm_usikkerhetsklasse`` as their worst.
    Columns not in :data:`NIN_FLATE_COLUMNS` (working columns, the SeaBee
    ``klasse``, ...) are dropped.
    """
    out = gdf.copy()
    out["opphav_kode"] = OPPHAV_KODE
    out["nkm_prosess"] = out["nin_kode_fkid"].map(NKM_PROSESS)
    out["metode_klassifisering"] = metode_from_datakilde(out["datakilde"])
    if all(c in out for c in USIKKERHET_AXIS_COLS):
        out["nkm_usikkerhetsklasse"] = worst_usikkerhet(out[list(USIKKERHET_AXIS_COLS)])
    keep = [c for c in NIN_FLATE_COLUMNS if c in out.columns] + [out.geometry.name]
    return out[keep]
