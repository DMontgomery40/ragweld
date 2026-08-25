from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from server.synthetic.storage import run_dir, runs_dir

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_run_dir_rejects_path_traversal_segments() -> None:
    with pytest.raises(ValueError):
        run_dir("../escape")
    with pytest.raises(ValueError):
        run_dir("..")
    with pytest.raises(ValueError):
        run_dir("a/b")


def test_run_dir_stays_under_synthetic_runs_root() -> None:
    path = run_dir("example-corpus__20260228_000001")
    assert path.parent == runs_dir().resolve()


def _with_runs_root(value: str | None):
    """Context-free helper: set/unset RAGWELD_SYNTHETIC_RUNS_ROOT and return the previous value."""
    previous = os.environ.get("RAGWELD_SYNTHETIC_RUNS_ROOT")
    if value is None:
        os.environ.pop("RAGWELD_SYNTHETIC_RUNS_ROOT", None)
    else:
        os.environ["RAGWELD_SYNTHETIC_RUNS_ROOT"] = value
    return previous


def _restore_runs_root(previous: str | None) -> None:
    if previous is None:
        os.environ.pop("RAGWELD_SYNTHETIC_RUNS_ROOT", None)
    else:
        os.environ["RAGWELD_SYNTHETIC_RUNS_ROOT"] = previous


def test_runs_root_defaults_to_the_live_store_and_honors_the_isolation_seam() -> None:
    """`RAGWELD_SYNTHETIC_RUNS_ROOT` mirrors `RAGWELD_LINEAGE_ROOT`: unset means the live
    `data/synthetic_runs`, absolute values are used as-is, relative values resolve from the
    repo root. pytest itself runs with the seam set (conftest), so the live store is never
    written by a test."""
    previous = _with_runs_root(None)
    try:
        assert runs_dir() == _REPO_ROOT / "data" / "synthetic_runs"

        with tempfile.TemporaryDirectory(prefix="ragweld-synthetic-runs-seam-") as tmp:
            absolute = Path(tmp) / "runs"
            _with_runs_root(str(absolute))
            assert runs_dir() == absolute
            assert absolute.is_dir()
            assert run_dir("seam-corpus__20260825_000001").parent == absolute.resolve()

        _with_runs_root("output/pytest-synthetic-runs-seam")
        assert runs_dir() == _REPO_ROOT / "output" / "pytest-synthetic-runs-seam"
    finally:
        _restore_runs_root(previous)
        try:
            (_REPO_ROOT / "output" / "pytest-synthetic-runs-seam").rmdir()
        except OSError:
            pass


def test_pytest_never_points_the_run_store_at_the_live_directory() -> None:
    assert runs_dir() != _REPO_ROOT / "data" / "synthetic_runs"
