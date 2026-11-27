import pytest

from mnk.utils import repo_root


def test_finds_pyproject_from_subdirectory(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    sub = tmp_path / "notebooks" / "01_substrat"
    sub.mkdir(parents=True)
    assert repo_root(sub) == tmp_path.resolve()
    assert repo_root(tmp_path) == tmp_path.resolve()


def test_raises_without_pyproject(tmp_path):
    with pytest.raises(FileNotFoundError):
        repo_root(tmp_path)


def test_this_repository():
    from pathlib import Path

    here = Path(__file__).resolve().parent
    assert repo_root(here) == here.parent
