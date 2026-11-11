"""Derive Naturkart data-model attributes for marine NiN polygons.

Populates the subset of ``nin_flate_NK`` fields derivable from ``nin_int``
(1-12) and ``nin_kode_fkid``. Fields requiring data not available in the
niche-model notebook (probabilities, uncertainty, alger, SeaBee, depth,
kalkinnhold, rute partitioning) are intentionally omitted.
"""

from __future__ import annotations

import geopandas as gpd

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


def add_nkm_attributes(
    gdf: gpd.GeoDataFrame,
    nin_int_col: str = "nin_int",
    kode_col: str = "nin_kode_fkid",
    substrat_kilde_col: str = "_substrat_kilde",
    metode_klassifisering: str = "NKM_regelbasert_dyp",
    extra_datakilde: tuple[str, ...] = ("lys_modellert_copernicus_S3",),
    nk_fid_start: int = 1,
) -> gpd.GeoDataFrame:
    """Add derived Naturkart attributes to *gdf*.

    ``datakilde`` is pipe-joined from the per-polygon substrate source
    (``substrat_kilde_col``) and *extra_datakilde*.
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
            lambda s: "|".join([s, *extra]) if isinstance(s, str) else "|".join(extra)
        )
    else:
        out["datakilde"] = "|".join(extra)

    out["nk_fid"] = [f"NKM-{i:010d}" for i in range(nk_fid_start, nk_fid_start + len(out))]

    return out
