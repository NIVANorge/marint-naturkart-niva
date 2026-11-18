"""Classification rules for marine NiN 3.0 niche modelling (NKM).

Two authoritative rule sets, transcribed from ``datamodell_silver_nin_flate_NK.xlsx``
(sheet ``LUT nkm_klassifiseringsregler`` and ``KODE k_nkm_<..>``) and Tabell 6
(Bryn m.fl. 2025):

* :data:`NISJE_RULES` / :func:`classify_nisje` — the regel-baserte nisjemodell,
  mapping the four model axes (lys, salinitet, substrat, tørrfall) to a NiN
  hovedtype.
* :data:`SEABEE_RULES` / :func:`classify_seabee` — how a remote-sensed SeaBee
  class interacts with the niche model (overriding the substrate/vegetation axis
  or being ignored), yielding the final NiN hovedtype.

Axis values use the exact tokens from the data model:
``lys`` ∈ {``eufotisk``, ``afotisk``}, ``salinitet`` ∈ {``salt``, ``brakk``},
``substrat`` ∈ {``fast``, ``løst``}, ``toerfall`` ∈ {``innenfor``, ``utenfor``}
(``innenfor`` = i tidevannssonen/fjære, ``utenfor`` = permanent vanndekket).
The afotisk zone is always sublittoral, i.e. ``toerfall == "utenfor"``.
"""

from __future__ import annotations

from typing import Optional

NiNType = tuple[str, str]  # (nin_kode_fkid, NiN_name)

# ---------------------------------------------------------------------------
# NiN hovedtype catalogue (navn per kode), marine types used by NKM.
# ---------------------------------------------------------------------------
NIN_NAMES: dict[str, str] = {
    "NA-MA01": "Fast saltvanns-fjærebeltebunn",
    "NA-MA02": "Eufotisk fast saltvannsbunn",
    "NA-MA03": "Afotisk fast saltvannsbunn",
    "NA-MA04": "Fjærebelte-sedimentbunn",
    "NA-MA05": "Eufotisk saltvanns-sedimentbunn",
    "NA-MA06": "Afotisk saltvanns-sedimentbunn",
    "NA-MB02": "Saltvanns-undervannseng",
    "NA-MC01": "Fast brakkvanns-fjærebeltebunn",
    "NA-MC02": "Fast brakkvannsbunn",
    "NA-MC04": "Brakkvanns-sedimentbunn",
    "NA-MF01": "Brakkvanns-undervannseng",
    "NA-MC08": "Marint bunnsystem preget av oksygenmangel",
    "NA-MJ01": "Taretrålingsbunn",
}


def _t(kode: str) -> NiNType:
    return (kode, NIN_NAMES[kode])


# ---------------------------------------------------------------------------
# 1. Nisjemodell: (lys, salinitet, substrat, toerfall) -> NiN hovedtype
# ---------------------------------------------------------------------------
# The afotisk zone is always sublittoral, so its ``toerfall`` key is ``"utenfor"``.
# Brackish types (NA-MC*) do not split on euphotic depth the way saltwater does,
# so several keys collapse.
NISJE_RULES: dict[tuple[str, str, str, str], NiNType] = {
    # Saltvann
    ("eufotisk", "salt", "fast", "innenfor"): _t("NA-MA01"),
    ("eufotisk", "salt", "fast", "utenfor"): _t("NA-MA02"),
    ("afotisk", "salt", "fast", "utenfor"): _t("NA-MA03"),
    ("eufotisk", "salt", "løst", "innenfor"): _t("NA-MA04"),
    ("eufotisk", "salt", "løst", "utenfor"): _t("NA-MA05"),
    ("afotisk", "salt", "løst", "utenfor"): _t("NA-MA06"),
    # Brakkvann
    ("eufotisk", "brakk", "fast", "innenfor"): _t("NA-MC01"),
    ("eufotisk", "brakk", "fast", "utenfor"): _t("NA-MC02"),
    ("afotisk", "brakk", "fast", "utenfor"): _t("NA-MC02"),
    ("eufotisk", "brakk", "løst", "innenfor"): _t("NA-MC04"),
    ("eufotisk", "brakk", "løst", "utenfor"): _t("NA-MC04"),
    ("afotisk", "brakk", "løst", "utenfor"): _t("NA-MC04"),
}


def classify_nisje(lys: str, salinitet: str, substrat: str, toerfall: str) -> NiNType:
    """Return ``(nin_kode_fkid, NiN_name)`` for the regel-baserte nisjemodell.

    The afotisk zone is always sublittoral, so ``toerfall`` is forced to
    ``"utenfor"`` when ``lys == "afotisk"``.
    """
    if lys == "afotisk":
        toerfall = "utenfor"
    try:
        return NISJE_RULES[(lys, salinitet, substrat, toerfall)]
    except KeyError as exc:
        raise ValueError(
            f"No nisje rule for lys={lys!r}, salinitet={salinitet!r}, "
            f"substrat={substrat!r}, toerfall={toerfall!r}"
        ) from exc


# ---------------------------------------------------------------------------
# 2. SeaBee (fjernmåling) -> NiN hovedtype
# ---------------------------------------------------------------------------
# A SeaBee class resolves the substrate/vegetation axis and then the NiN type is
# read from the nisjemodell. Per Tabell/k_nkm_seabee:
#   * ANGIO  -> undervannseng (vegetation) on soft bottom; substrat=løst,
#              overrides the model (fjernmåling trumfer).
#   * ALGAE/ROCK -> hard substrate ("fast").   (fjernmåling trumfer modell)
#   * SEDIMENT   -> soft substrate ("løst").   (fjernmåling trumfer modell)
#   * ANGIO/ALGAE/ROCK/SEDIMENT are also authoritative for lys: the bottom is
#     observed from satellite, so lys="eufotisk" (fjernmåling trumfer modell).
#   * DEEP       -> no override; nisjemodellen trumfer fjernmåling (DEEP).
#   * ANTHRO/TERR_VEG/BEACHCAST -> not a marine habitat (returns ``None``).
SEABEE_SUBSTRAT_OVERRIDE: dict[str, str] = {
    "ALGAE": "fast",
    "ROCK": "fast",
    "SEDIMENT": "løst",
}
# SeaBee classes that are authoritative for the lys axis (bottom is visible).
SEABEE_LYS_OVERRIDE: dict[str, str] = {
    "ANGIO": "eufotisk",
    "ALGAE": "eufotisk",
    "ROCK": "eufotisk",
    "SEDIMENT": "eufotisk",
}
SEABEE_KEEP_MODEL: frozenset[str] = frozenset({"DEEP"})
SEABEE_NONMARINE: frozenset[str] = frozenset({"ANTHRO", "TERR_VEG", "BEACHCAST"})

# ANGIO undervannseng by salinity (euphotic vegetation).
SEABEE_ANGIO: dict[str, str] = {"salt": "NA-MB02", "brakk": "NA-MF01"}

# Exposed summary of the SeaBee rule semantics (for docs/tests).
SEABEE_RULES: dict[str, str] = {
    "ANGIO": "undervannseng (NA-MB02 salt / NA-MF01 brakk), substrat=løst, lys=eufotisk, overrides modell",
    "ALGAE": "substrat=fast, lys=eufotisk, fjernmåling trumfer modell",
    "ROCK": "substrat=fast, lys=eufotisk, fjernmåling trumfer modell",
    "SEDIMENT": "substrat=løst, lys=eufotisk, fjernmåling trumfer modell",
    "DEEP": "ingen overstyring, nisjemodellen trumfer",
    "ANTHRO": "ikke marint habitat",
    "TERR_VEG": "ikke marint habitat",
    "BEACHCAST": "ikke marint habitat",
}


def classify_seabee(
    seabee: Optional[str],
    lys: str,
    salinitet: str,
    substrat: str,
    toerfall: str,
) -> Optional[NiNType]:
    """Combine a SeaBee class with the nisjemodell axes into a NiN hovedtype.

    ``substrat`` is the model's substrate; a SeaBee class may override it.
    Returns ``None`` for non-marine SeaBee classes. ``seabee`` of ``None``/
    unknown falls back to the pure nisjemodell.
    """
    if seabee == "ANGIO":
        return _t(SEABEE_ANGIO[salinitet])
    if seabee in SEABEE_NONMARINE:
        return None
    lys = SEABEE_LYS_OVERRIDE.get(seabee, lys)
    if seabee in SEABEE_SUBSTRAT_OVERRIDE:
        substrat = SEABEE_SUBSTRAT_OVERRIDE[seabee]
    # DEEP, None, or unknown -> keep model substrate.
    return classify_nisje(lys, salinitet, substrat, toerfall)


# ---------------------------------------------------------------------------
# 3. nkm_* column values (as written to the dataset) <-> rule tokens
# ---------------------------------------------------------------------------
NKM_LYS: dict[str, str] = {"eufotisk": "eufotisk", "afotisk": "afotisk"}
NKM_SALINITET: dict[str, str] = {"salt": "saltvann", "brakk": "brakkvann"}
NKM_SUBSTRAT: dict[str, str] = {"fast": "fastbunn", "løst": "loesbunn"}
NKM_TOERFALL: dict[str, str] = {"innenfor": "toerfall", "utenfor": "permanent_vanndekket"}


# ---------------------------------------------------------------------------
# 4. Direkte datasett (burned in after nisjemodell + SeaBee, in order)
# ---------------------------------------------------------------------------
# NyTypologi2022 `Type` -> beskrivelse (MDir WMS-legende).
WATER_TYPE_NAMES: dict[str, str] = {
    "01": "Beskyttet fjord/kyst",
    "01a": "Beskyttet fjord/kyst med oksygenfattig bunnvann",
    "02": "Beskyttet ferskvannspåvirket fjord/kyst",
    "02a": "Beskyttet ferskvannspåvirket fjord med oksygenfattig bunnvann",
    "03": "Sterkt ferskvannspåvirket fjord",
    "03a": "Sterkt ferskvannspåvirket fjord med oksygenfattig bunnvann",
    "04": "Moderat eksponert fjord/kyst",
    "05": "Moderat eksponert ferskvannspåvirket fjord/kyst",
    "06": "Bølgeeksponert kyst",
    "07": "Bølgeeksponert ferskvannspåvirket kyst",
    "08": "Strømrike sund",
    "09": "Særegen vannforekomst",
}
WATER_TYPES_OXYGEN_POOR: list[str] = [k for k in WATER_TYPE_NAMES if k.endswith("a")]

# Applied in order; a later rule overrides an earlier one where they overlap.
# ``where``: restrict to polygons whose nkm_* columns have these values
# ({column: [values]}; None = all bottom).
# ``label``: optional name used in the diagram (defaults to the file name).
DIRECT_RULES: list[dict] = [
    {
        "nin_kode_fkid": "NA-MC08",
        "label": "Marine vanntyper oksygenfattig",
        "url": "gs://niva-geodata/MarintNaturKart/input/mdir/NyTypologi2022.geo.parquet",
        "column": "Type",
        "values": WATER_TYPES_OXYGEN_POOR,
        "where": {
            "nkm_lys": ["afotisk", "eufotisk"],
            "nkm_toerfall": ["permanent_vanndekket"],
        },
        "metode_klassifisering": "NKM_direkte_oksygenmangel",
        "datakilde": "oksygen_vanntype_mdir_2022",
    },
    {
        "nin_kode_fkid": "NA-MJ01",
        "url": "gs://niva-geodata/MarintNaturKart/input/niva/taretraling_polygons_2020-2025_2026-11-15.gpkg",
        "column": None,
        "values": None,
        "where": None,
        "metode_klassifisering": "NKM_direkte_taretralingsbunn",
        "datakilde": "taretraling_niva_2020-2025",
    },
]
