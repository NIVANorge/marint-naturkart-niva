import pytest

from mnk.rules import classify_nisje, classify_seabee


@pytest.mark.parametrize(
    "lys,salinitet,substrat,toerfall,expected",
    [
        ("eufotisk", "salt", "fast", "innenfor", "NA-MA01"),
        ("eufotisk", "salt", "fast", "utenfor", "NA-MA02"),
        ("afotisk", "salt", "fast", "utenfor", "NA-MA03"),
        ("eufotisk", "salt", "løst", "innenfor", "NA-MA04"),
        ("eufotisk", "salt", "løst", "utenfor", "NA-MA05"),
        ("afotisk", "salt", "løst", "utenfor", "NA-MA06"),
        ("eufotisk", "brakk", "fast", "innenfor", "NA-MC01"),
        ("eufotisk", "brakk", "fast", "utenfor", "NA-MC02"),
        ("afotisk", "brakk", "fast", "utenfor", "NA-MC02"),
        ("eufotisk", "brakk", "løst", "innenfor", "NA-MC04"),
        ("eufotisk", "brakk", "løst", "utenfor", "NA-MC04"),
        ("afotisk", "brakk", "løst", "utenfor", "NA-MC04"),
    ],
)
def test_classify_nisje(lys, salinitet, substrat, toerfall, expected):
    assert classify_nisje(lys, salinitet, substrat, toerfall)[0] == expected


def test_afotisk_forces_utenfor():
    assert classify_nisje("afotisk", "salt", "fast", "innenfor")[0] == "NA-MA03"


def test_classify_nisje_unknown_raises():
    with pytest.raises(ValueError):
        classify_nisje("eufotisk", "fersk", "fast", "innenfor")


@pytest.mark.parametrize(
    "seabee,salinitet,toerfall,expected",
    [
        ("ANGIO", "brakk", "innenfor", "NA-MF01"),
        ("ANGIO", "salt", "utenfor", "NA-MB02"),
        ("SEDIMENT", "brakk", "innenfor", "NA-MC04"),
        ("SEDIMENT", "salt", "innenfor", "NA-MA04"),
        ("SEDIMENT", "salt", "utenfor", "NA-MA05"),
        ("ALGAE", "brakk", "innenfor", "NA-MC01"),
        ("ROCK", "salt", "utenfor", "NA-MA02"),
    ],
)
def test_classify_seabee_override_fastbunn(seabee, salinitet, toerfall, expected):
    # Model says fastbunn; SeaBee may override the substrate axis.
    assert (
        classify_seabee(seabee, "eufotisk", salinitet, "fast", toerfall)[0] == expected
    )


def test_classify_seabee_deep_keeps_model():
    assert (
        classify_seabee("DEEP", "eufotisk", "salt", "løst", "utenfor")[0] == "NA-MA05"
    )


def test_classify_seabee_nonmarine_returns_none():
    assert classify_seabee("TERR_VEG", "eufotisk", "salt", "fast", "innenfor") is None
