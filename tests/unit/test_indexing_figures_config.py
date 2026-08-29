"""indexing.figures is a typed, per-corpus tunable with the spec's defaults and constraints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.models.tribrid_config_model import IndexingFiguresConfig, TriBridConfig

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_defaults_match_the_spec() -> None:
    f = TriBridConfig().indexing.figures
    assert f.enabled is False
    assert f.describe is True and f.classify is True
    assert f.vision_model == "z-ai.glm-5.3-flash"
    assert f.prompt_profile == "technical_figure"
    assert f.images_scale == 2.0
    assert f.min_area_fraction == 0.02
    assert f.skip_classes == ["logo", "signature", "icon"]
    assert f.max_figures_per_file == 200
    assert f.max_completion_tokens == 600
    assert f.concurrency == 4
    assert f.timeout_s == 90


@pytest.mark.parametrize(
    "field, bad",
    [
        ("images_scale", 0.5), ("images_scale", 4.5),
        ("min_area_fraction", -0.1), ("min_area_fraction", 1.5),
        ("max_figures_per_file", -1),
        ("max_completion_tokens", 10), ("max_completion_tokens", 5000),
        ("concurrency", 0), ("concurrency", 17),
        ("timeout_s", 1), ("timeout_s", 601),
        ("prompt_profile", "poetry"),
    ],
)
def test_constraints_are_contract(field: str, bad: object) -> None:
    with pytest.raises(ValidationError):
        IndexingFiguresConfig(**{field: bad})


def test_round_trips_through_json_and_scoped_merge() -> None:
    cfg = TriBridConfig()
    payload = cfg.model_dump(mode="json")
    payload["indexing"]["figures"]["enabled"] = True
    payload["indexing"]["figures"]["vision_model"] = "google.gemini-3.7-flash"
    again = TriBridConfig.model_validate(payload)
    assert again.indexing.figures.enabled is True
    assert again.indexing.figures.vision_model == "google.gemini-3.7-flash"


def test_every_field_has_a_glossary_term_in_both_copies() -> None:
    keys = {f"FIGURES_{name.upper()}" for name in IndexingFiguresConfig.model_fields}
    for rel in ("data/glossary.json", "web/public/glossary.json"):
        terms = {t.get("key") for t in json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))["terms"]}
        missing = sorted(keys - terms)
        assert not missing, f"{rel} lacks glossary terms: {missing}"
    assert (REPO_ROOT / "data/glossary.json").read_bytes() == (REPO_ROOT / "web/public/glossary.json").read_bytes()
