from __future__ import annotations

from pathlib import Path

import pytest

from server.synthetic.storage import _normalize_legacy_run_payload, run_dir


def test_normalize_legacy_run_payload_backfills_missing_models() -> None:
    raw = {
        "request": {
            "generator_model_override": None,
            "judge_model_override": "openai/gpt-4o-mini",
        }
    }

    out = _normalize_legacy_run_payload(raw)
    req = out["request"]
    assert req["generator_model"] == "__legacy_missing_generator_model__"
    assert req["judge_model"] == "openai/gpt-4o-mini"


def test_normalize_legacy_run_payload_preserves_explicit_models() -> None:
    raw = {
        "request": {
            "generator_model": "openai/gpt-4o-mini",
            "judge_model": "openai/gpt-4o-mini",
            "generator_model_override": None,
            "judge_model_override": None,
        }
    }

    out = _normalize_legacy_run_payload(raw)
    req = out["request"]
    assert req["generator_model"] == "openai/gpt-4o-mini"
    assert req["judge_model"] == "openai/gpt-4o-mini"


def test_run_dir_rejects_path_traversal_segments() -> None:
    with pytest.raises(ValueError):
        run_dir("../escape")
    with pytest.raises(ValueError):
        run_dir("..")
    with pytest.raises(ValueError):
        run_dir("a/b")


def test_run_dir_stays_under_synthetic_runs_root() -> None:
    path = run_dir("epstein-files-1__20260228_000001")
    root = Path(__file__).resolve().parents[2] / "data" / "synthetic_runs"
    assert path.parent == root.resolve()
