from __future__ import annotations

from pathlib import Path

import pytest

from server.synthetic.storage import run_dir


def test_run_dir_rejects_path_traversal_segments() -> None:
    with pytest.raises(ValueError):
        run_dir("../escape")
    with pytest.raises(ValueError):
        run_dir("..")
    with pytest.raises(ValueError):
        run_dir("a/b")


def test_run_dir_stays_under_synthetic_runs_root() -> None:
    path = run_dir("example-corpus__20260228_000001")
    root = Path(__file__).resolve().parents[2] / "data" / "synthetic_runs"
    assert path.parent == root.resolve()
