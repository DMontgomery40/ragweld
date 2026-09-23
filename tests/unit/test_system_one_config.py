"""System One config and the synthetic judge thresholds are typed, documented tunables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from server.models.system_one import SystemOneConfig
from server.models.tribrid_config_model import SyntheticJudgeConfig, TriBridConfig

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_defaults_name_the_hosted_jev_and_the_local_laya_port() -> None:
    cfg = TriBridConfig().system_one
    assert cfg.provider == "typesafe"
    assert cfg.typesafe_base_url == "https://api.typesafe.ai"
    assert cfg.laya_base_url == "http://127.0.0.1:58180"
    assert cfg.model == "jev-latest"
    assert cfg.timeout_s == 30.0
    assert cfg.max_concurrency == 16
    assert cfg.max_retries == 3


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("provider", "openai"),
        ("provider", "litellm"),
        ("typesafe_base_url", ""),
        ("laya_base_url", ""),
        ("model", ""),
        ("timeout_s", 0.5),
        ("timeout_s", 121.0),
        ("max_concurrency", 0),
        ("max_concurrency", 65),
        ("max_retries", -1),
        ("max_retries", 9),
    ],
)
def test_constraints_are_contract(field: str, bad: Any) -> None:
    with pytest.raises(ValidationError):
        SystemOneConfig(**{field: bad})


def test_round_trips_through_json_as_a_config_section() -> None:
    payload = TriBridConfig().model_dump(mode="json")
    payload["system_one"]["provider"] = "laya"
    payload["system_one"]["model"] = "english"
    payload["synthetic"]["judge"]["reader_question_min"] = 0.8
    again = TriBridConfig.model_validate(payload)
    assert again.system_one.provider == "laya"
    assert again.system_one.model == "english"
    assert again.synthetic.judge.reader_question_min == 0.8


def test_every_field_has_a_glossary_term_in_both_copies() -> None:
    keys = {f"SYSTEM_ONE_{name.upper()}" for name in SystemOneConfig.model_fields}
    keys |= {f"SYNTHETIC_JUDGE_{name.upper()}" for name in SyntheticJudgeConfig.model_fields}
    for rel in ("data/glossary.json", "web/public/glossary.json"):
        terms = {t.get("key") for t in json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))["terms"]}
        missing = sorted(keys - terms)
        assert not missing, f"{rel} lacks glossary terms: {missing}"
    assert (REPO_ROOT / "data/glossary.json").read_bytes() == (REPO_ROOT / "web/public/glossary.json").read_bytes()
