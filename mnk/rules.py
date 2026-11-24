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

NiNType = tuple[str, str]
"""A ``(nin_kode_fkid, NiN_name)`` pair."""

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
"""NiN hovedtype catalogue (navn per kode), marine types used by NKM."""


def _t(kode: str) -> NiNType:
    return (kode, NIN_NAMES[kode])


NISJE_RULES: dict[tuple[str, str, str, str], NiNType] = {
    ("eufotisk", "salt", "fast", "innenfor"): _t("NA-MA01"),
    ("eufotisk", "salt", "fast", "utenfor"): _t("NA-MA02"),
    ("afotisk", "salt", "fast", "utenfor"): _t("NA-MA03"),
    ("eufotisk", "salt", "løst", "innenfor"): _t("NA-MA04"),
    ("eufotisk", "salt", "løst", "utenfor"): _t("NA-MA05"),
    ("afotisk", "salt", "løst", "utenfor"): _t("NA-MA06"),
    ("eufotisk", "brakk", "fast", "innenfor"): _t("NA-MC01"),
    ("eufotisk", "brakk", "fast", "utenfor"): _t("NA-MC02"),
    ("afotisk", "brakk", "fast", "utenfor"): _t("NA-MC02"),
    ("eufotisk", "brakk", "løst", "innenfor"): _t("NA-MC04"),
    ("eufotisk", "brakk", "løst", "utenfor"): _t("NA-MC04"),
    ("afotisk", "brakk", "løst", "utenfor"): _t("NA-MC04"),
}
"""``(lys, salinitet, substrat, toerfall)`` -> NiN hovedtype.

The afotisk zone is always sublittoral, so its ``toerfall`` key is ``"utenfor"``.
Brackish types (NA-MC*) do not split on euphotic depth the way saltwater does,
so several keys collapse.
"""


def classify_nisje(lys: str, salinitet: str, substrat: str, toerfall: str) -> NiNType:
    """Return ``(nin_kode_fkid, NiN_name)`` for the regel-baserte nisjemodell.

    The afotisk zone is always sublittoral, so ``toerfall`` is forced to
    ``"utenfor"`` when ``lys == "afotisk"``.

    If any axis is missing (not a string — ``None``, ``pd.NA``, ``nan``) the
    class is undetermined and ``(None, None)`` is returned. A complete but
    unknown combination (e.g. an invalid token) still raises ``ValueError``.
    """
    if not all(isinstance(v, str) for v in (lys, salinitet, substrat, toerfall)):
        return (None, None)
    if lys == "afotisk":
        toerfall = "utenfor"
    try:
        return NISJE_RULES[(lys, salinitet, substrat, toerfall)]
    except KeyError as exc:
        raise ValueError(
            f"No nisje rule for lys={lys!r}, salinitet={salinitet!r}, "
            f"substrat={substrat!r}, toerfall={toerfall!r}"
        ) from exc


SEABEE_SUBSTRAT_OVERRIDE: dict[str, str] = {
    "ALGAE": "fast",
    "ROCK": "fast",
    "SEDIMENT": "løst",
}
"""SeaBee class -> substrate axis override (``fast`` / ``løst``).

A SeaBee class resolves the substrate/vegetation axis and then the NiN type is
read from the nisjemodell. Per Tabell/k_nkm_seabee:

* ANGIO -> undervannseng (vegetation) on soft bottom; substrat=løst, overrides
  the model (fjernmåling trumfer).
* ALGAE/ROCK -> hard substrate (``fast``); SEDIMENT -> soft (``løst``);
  fjernmåling trumfer modell.
* ANGIO/ALGAE/ROCK/SEDIMENT are also authoritative for lys: the bottom is
  observed from satellite, so lys=``eufotisk``.
* DEEP -> no override; nisjemodellen trumfer. ANTHRO/TERR_VEG/BEACHCAST -> not a
  marine habitat (returns ``None``).
"""
SEABEE_LYS_OVERRIDE: dict[str, str] = {
    "ANGIO": "eufotisk",
    "ALGAE": "eufotisk",
    "ROCK": "eufotisk",
    "SEDIMENT": "eufotisk",
}
"""SeaBee classes authoritative for the lys axis (bottom is visible)."""
SEABEE_SA_FA_OVERRIDE: dict[str, str] = {
    "ALGAE": "alger",
    "ROCK": "stein",
}
"""SeaBee classes that set the fastsittende-alger axis (nkm_sa-fa); set in 04 only."""
SEABEE_KEEP_MODEL: frozenset[str] = frozenset({"DEEP"})
"""SeaBee classes that keep the model substrate (no override)."""
SEABEE_NONMARINE: frozenset[str] = frozenset({"ANTHRO", "TERR_VEG", "BEACHCAST"})
"""SeaBee classes that are not a marine habitat (classify_seabee returns ``None``)."""

SEABEE_ANGIO: dict[str, str] = {"salt": "NA-MB02", "brakk": "NA-MF01"}
"""ANGIO undervannseng by salinity (euphotic vegetation)."""

SEABEE_RULES: dict[str, str] = {
    "ANGIO": "undervannseng (NA-MB02 salt / NA-MF01 brakk), substrat=løst, lys=eufotisk, overrides modell",
    "ALGAE": "substrat=fast, lys=eufotisk, sa-fa=alger, fjernmåling trumfer modell",
    "ROCK": "substrat=fast, lys=eufotisk, sa-fa=stein, fjernmåling trumfer modell",
    "SEDIMENT": "substrat=løst, lys=eufotisk, fjernmåling trumfer modell",
    "DEEP": "ingen overstyring, nisjemodellen trumfer",
    "ANTHRO": "ikke marint habitat",
    "TERR_VEG": "ikke marint habitat",
    "BEACHCAST": "ikke marint habitat",
}
"""Exposed summary of the SeaBee rule semantics (for docs/tests)."""


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
    return classify_nisje(lys, salinitet, substrat, toerfall)


NKM: dict[str, tuple[str, dict[str, str]]] = {
    "lys":       ("nkm_lys",   {"eufotisk": "0abcde", "afotisk": "y"}),
    "salinitet": ("nkm_lm-sa", {"salt": "fgh", "brakk": "abcde"}),
    "substrat":  ("nkm_lm-dk", {"fast": "EFGY", "løst": "0ABCD"}),
    "toerfall":  ("nkm_lm-tv", {"innenfor": "LM-TV_abcdefgh", "utenfor": "LM-TV_0"}),
    "sa-fa":     ("nkm_sa-fa", {"alger": "ABC", "stein": "0B"}),
}
"""One row per axis: ``(column name in nin_flate_NK, {rule token -> NiN kode})``.

From TABELL nin_flate_NK / KODE k_nkm_<..>. Edit codes here. ``sa-fa`` is a
SeaBee-only axis (set in 04, not by classify_nisje); see SEABEE_SA_FA_OVERRIDE.
"""

COL_LYS, NKM_LYS = NKM["lys"]
COL_SALINITET, NKM_SALINITET = NKM["salinitet"]
COL_SUBSTRAT, NKM_SUBSTRAT = NKM["substrat"]
COL_TOERFALL, NKM_TOERFALL = NKM["toerfall"]
COL_SA_FA, NKM_SA_FA = NKM["sa-fa"]


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
"""NyTypologi2022 ``Type`` -> beskrivelse (MDir WMS-legende)."""
WATER_TYPES_OXYGEN_POOR: list[str] = [k for k in WATER_TYPE_NAMES if k.endswith("a")]
"""NyTypologi2022 types with oksygenfattig bunnvann (the ``a`` suffix)."""

DIRECT_RULES: list[dict] = [
    {
        "nin_kode_fkid": "NA-MC08",
        "label": "Marine vanntyper oksygenfattig",
        "url": "gs://niva-geodata/MarintNaturKart/input/mdir/NyTypologi2022.geo.parquet",
        "column": "Type",
        "values": WATER_TYPES_OXYGEN_POOR,
        "where": {
            COL_LYS: [NKM_LYS["afotisk"], NKM_LYS["eufotisk"]],
            COL_TOERFALL: [NKM_TOERFALL["utenfor"]],
        },
        "metode_klassifisering": "NKM_direkte_oksygenmangel",
        "datakilde": "oksygenmangel_kartlagt_mdir",
    },
    {
        "nin_kode_fkid": "NA-MJ01",
        "url": "gs://niva-geodata/MarintNaturKart/input/niva/taretraling_polygons_2020-2025_2026-11-15.gpkg",
        "column": None,
        "values": None,
        "where": None,
        "metode_klassifisering": "NKM_direkte_taretralingsbunn",
        "datakilde": "taretraling_kartlagt_niva",
    },
]
"""Direct datasets, applied in order; a later rule overrides an earlier one where they overlap.

``where``: restrict to polygons whose nkm_* columns have these values
(``{column: [values]}``; ``None`` = all bottom).
``label``: optional name used in the diagram (defaults to the file name).
"""
