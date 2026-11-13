"""Derive Naturkart data-model attributes for marine NiN polygons.

Populates the subset of ``nin_flate_NK`` fields derivable from ``nin_int``
(1-12) and ``nin_kode_fkid``. Fields requiring data not available in the
niche-model notebook (probabilities, uncertainty, alger, SeaBee, depth,
kalkinnhold, rute partitioning) are intentionally omitted.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

# nin_int (1-12) axes decoded from NIN_INT_MAP in 03_nisjemodell.
_EUFOTISK = {1, 2, 3, 4, 5, 7, 9, 11}
_BRAKKVANN = {1, 3, 5, 6, 9, 10}
_FASTBUNN = {3, 4, 9, 10, 11, 12}
_TOERFALL = {1, 2, 3, 4}

# nin_kode_fkid -> prosess-kode (KODE k_nkm_prosess coupling table).
NKM_PROSESS: dict[str, str] = {
    "NA-MA01": "A", "NA-MA02": "A", "NA-MA03": "A",
    "NA-MA04": "A", "NA-MA05": "A", "NA-MA06": "A",
    "NA-MC01": "C", "NA-MC02": "C", "NA-MC04": "A",
}

OPPHAV_KODE = "NKM"

OBS_SUBSTRAT_KILDE = "substrat_kartlagt_ngu"


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


def sannsynlighet_beskrivelse(
    gdf: gpd.GeoDataFrame,
    substrat_kilde_col: str = "_substrat_kilde",
    is_dem_col: str = "_is_dem",
) -> np.ndarray:
    """``høy`` for observed substrate, ``medium`` where DEM data exists, else ``lav``.

    ``is_dem_col`` may be real booleans, numerics, or the strings ``"True"``/
    ``"False"`` that round-trip through GeoPackage. A plain ``astype(bool)`` is
    unsafe here because ``bool("False")`` is ``True``; values are therefore
    parsed truth-aware so string ``"False"`` maps to ``False``.
    """
    has_dem = _as_bool(gdf[is_dem_col]).to_numpy()
    is_obs = (gdf[substrat_kilde_col] == OBS_SUBSTRAT_KILDE).to_numpy()
    return np.where(is_obs, "høy", np.where(has_dem, "medium", "lav"))


def add_nkm_attributes(
    gdf: gpd.GeoDataFrame,
    nin_int_col: str = "nin_int",
    kode_col: str = "nin_kode_fkid",
    substrat_kilde_col: str = "_substrat_kilde",
    metode_klassifisering: str = "NKM_regelbasert_dyp",
    extra_datakilde: tuple[str, ...] = ("lys_modellert_copernicus_S3",),
    nk_fid_start: int = 1,
    is_dem_col: str = "_is_dem",
) -> gpd.GeoDataFrame:
    """Add derived Naturkart attributes to *gdf*.

    ``datakilde`` is pipe-joined from *extra_datakilde* (e.g. the light
    source) followed by the per-polygon substrate source
    (``substrat_kilde_col``), e.g.
    ``lys_modellert_copernicus_S3|substrat_kartlagt_ngu``.

    ``sannsynlighet_beskrivelse`` is added when both ``substrat_kilde_col``
    and ``is_dem_col`` exist (see :func:`sannsynlighet_beskrivelse`).
    """
    out = gdf.copy()
    ints = out[nin_int_col]

    out["opphav_kode"] = OPPHAV_KODE
    out["metode_klassifisering"] = metode_klassifisering
    out["nkm_lys"] = ints.map(lambda v: "eufotisk" if v in _EUFOTISK else "afotisk")
    out["nkm_salinitet"] = ints.map(lambda v: "brakkvann" if v in _BRAKKVANN else "saltvann")
    out["nkm_substrat"] = ints.map(lambda v: "fastbunn" if v in _FASTBUNN else "loesbunn")
    out["nkm_toerfall"] = ints.map(
        lambda v: "toerfall" if v in _TOERFALL else "permanent_vanndekket"
    )
    out["nkm_prosess"] = out[kode_col].map(NKM_PROSESS)

    extra = list(extra_datakilde)
    if substrat_kilde_col in out.columns:
        out["datakilde"] = out[substrat_kilde_col].map(
            lambda s: "|".join([*extra, s]) if isinstance(s, str) else "|".join(extra)
        )
    else:
        out["datakilde"] = "|".join(extra)

    if {substrat_kilde_col, is_dem_col} <= set(out.columns):
        out["sannsynlighet_beskrivelse"] = sannsynlighet_beskrivelse(
            out, substrat_kilde_col, is_dem_col
        )

    out["nk_fid"] = [f"NKM-{i:010d}" for i in range(nk_fid_start, nk_fid_start + len(out))]

    return out
