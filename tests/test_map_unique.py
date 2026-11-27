import numpy as np
import pandas as pd

from mnk.attributes import map_unique


def _counting(fn):
    calls = []

    def wrapped(*args):
        calls.append(args)
        return fn(*args)

    return wrapped, calls


def test_calls_once_per_unique_row_and_scatters_back():
    df = pd.DataFrame({"a": ["x", "y", "x", "x", "y"], "b": [1, 1, 1, 2, 1]})
    fn, calls = _counting(lambda a, b: f"{a}{b}")
    out = map_unique(df, fn)
    assert out.tolist() == ["x1", "y1", "x1", "x2", "y1"]
    assert sorted(calls) == [("x", 1), ("x", 2), ("y", 1)]


def test_na_reaches_fn_as_none():
    df = pd.DataFrame({"a": pd.array(["x", None, None], dtype="string"), "b": [np.nan, 1.0, 1.0]})
    fn, calls = _counting(lambda a, b: (a is None, b is None))
    out = map_unique(df, fn)
    assert out.tolist() == [(False, True), (True, False), (True, False)]
    assert len(calls) == 2


def test_columns_returns_frame_on_input_index():
    df = pd.DataFrame({"a": ["x", "y", "x"]}, index=[7, 3, 9])
    out = map_unique(df, lambda a: (a.upper(), len(a)), columns=["up", "n"])
    assert out.index.tolist() == [7, 3, 9]
    assert out["up"].tolist() == ["X", "Y", "X"]
    assert out["n"].tolist() == [1, 1, 1]


def test_tuple_results_without_columns_stay_tuples():
    df = pd.DataFrame({"a": ["x", "y"]})
    out = map_unique(df, lambda a: (a, None))
    assert out.tolist() == [("x", None), ("y", None)]


def test_empty_frame():
    df = pd.DataFrame({"a": pd.Series([], dtype=object)})
    assert len(map_unique(df, lambda a: a)) == 0
    assert list(map_unique(df, lambda a: (a, a), columns=["p", "q"]).columns) == ["p", "q"]
