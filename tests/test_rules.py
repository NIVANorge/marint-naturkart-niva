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
    "lys,salinitet,substrat,toerfall",
    [
        (None, "salt", "fast", "innenfor"),
        ("eufotisk", None, "fast", "innenfor"),
        ("eufotisk", "salt", None, "innenfor"),
        ("eufotisk", "salt", "fast", None),
        (None, None, None, None),
    ],
)
def test_classify_nisje_missing_axis_returns_none(lys, salinitet, substrat, toerfall):
    assert classify_nisje(lys, salinitet, substrat, toerfall) == (None, None)


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


@pytest.mark.parametrize("seabee", ["ALGAE", "ROCK", "SEDIMENT", "ANGIO"])
def test_classify_seabee_overrides_lys(seabee):
    # Model says afotisk; SeaBee observes the bottom -> eufotisk.
    res = classify_seabee(seabee, "afotisk", "salt", "løst", "utenfor")
    assert res[0] in {"NA-MA02", "NA-MA05", "NA-MB02"}


def test_classify_seabee_deep_keeps_model_lys():
    assert classify_seabee("DEEP", "afotisk", "salt", "løst", "utenfor")[0] == "NA-MA06"


def test_classify_seabee_angio_without_salinity_is_undetermined():
    assert classify_seabee("ANGIO", "eufotisk", None, "løst", "utenfor") == (None, None)


# 03a raster coding (see the LUT comments in 03a_nisjemodell_raster.ipynb).
NIN_INT_CODES = {
    1: "NA-MC04", 2: "NA-MA04", 3: "NA-MC01", 4: "NA-MA01",
    5: "NA-MC04", 6: "NA-MC04", 7: "NA-MA05", 8: "NA-MA06",
    9: "NA-MC02", 10: "NA-MC02", 11: "NA-MA02", 12: "NA-MA03",
}


def test_nin_int_axes_are_unique_and_match_raster_codes():
    from mnk.rules import NIN_INT_AXES

    assert sorted(NIN_INT_AXES) == list(range(1, 13))
    assert len(set(NIN_INT_AXES.values())) == 12
    assert {k: classify_nisje(*v)[0] for k, v in NIN_INT_AXES.items()} == NIN_INT_CODES


def test_nin_int_lut3_matches_the_raster_03a_wrote():
    from mnk.rules import NIN_INT_LUT3

    assert NIN_INT_LUT3 == (8, 12, 6, 10, 7, 11, 5, 9)


def test_raster_class_round_trip_for_every_class_and_band():
    import itertools

    import numpy as np

    from mnk.rules import NIN_INT_AXES, decode_raster_class, encode_raster_class

    combos = np.array(list(itertools.product(NIN_INT_AXES, range(4))))
    code = encode_raster_class(combos[:, 0], combos[:, 1])
    assert code.dtype == np.uint8
    assert len(set(code.tolist())) == len(combos)
    assert code.min() >= 1 and code.max() <= 48  # 255 stays free for nodata
    nin, sal = decode_raster_class(code)
    assert np.array_equal(np.column_stack([nin, sal]), combos)


def test_unbanded_raster_classes_decode_with_band_zero():
    from mnk.rules import decode_raster_class

    nin, sal = decode_raster_class([5, 12])
    assert nin.tolist() == [5, 12] and sal.tolist() == [0, 0]
