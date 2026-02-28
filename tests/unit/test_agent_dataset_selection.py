from __future__ import annotations

from pathlib import Path

from server.api.agent import _resolve_training_dataset_path


def test_dataset_selection_prefers_request_override(tmp_path: Path) -> None:
    corpus_id = "unit_agent_req_override"
    req = tmp_path / "req.json"
    req.write_text("[]", encoding="utf-8")
    cfg = tmp_path / "cfg.json"
    cfg.write_text("[]", encoding="utf-8")

    selected, _messages = _resolve_training_dataset_path(
        corpus_id=corpus_id,
        request_override=str(req),
        config_default=str(cfg),
        evaluation_default="data/evaluation_dataset.json",
    )
    assert selected is not None
    assert selected == req


def test_dataset_selection_uses_eval_non_default_before_corpus(tmp_path: Path) -> None:
    corpus_id = "unit_agent_eval_non_default"
    eval_path = tmp_path / "eval_custom.json"
    eval_path.write_text("[]", encoding="utf-8")

    selected, _messages = _resolve_training_dataset_path(
        corpus_id=corpus_id,
        request_override="",
        config_default="",
        evaluation_default=str(eval_path),
    )
    assert selected is not None
    assert selected == eval_path


def test_dataset_selection_falls_back_to_corpus_dataset_when_legacy_default_missing() -> None:
    corpus_id = "unit_agent_corpus_fallback"
    corpus_dataset = Path(__file__).resolve().parents[2] / "data" / "eval_datasets" / f"{corpus_id}.json"
    corpus_dataset.parent.mkdir(parents=True, exist_ok=True)
    corpus_dataset.write_text("[]", encoding="utf-8")
    try:
        selected, messages = _resolve_training_dataset_path(
            corpus_id=corpus_id,
            request_override="",
            config_default="",
            evaluation_default="data/evaluation_dataset.json",
        )
        assert selected is not None
        assert selected == corpus_dataset
        assert any("Skipping missing legacy default dataset path" in m for m in messages)
    finally:
        corpus_dataset.unlink(missing_ok=True)


def test_dataset_selection_returns_none_when_all_missing() -> None:
    corpus_id = "unit_agent_none_missing"
    selected, messages = _resolve_training_dataset_path(
        corpus_id=corpus_id,
        request_override="",
        config_default="",
        evaluation_default="data/evaluation_dataset.json",
    )
    assert selected is None
    assert any("Dataset path not found" in m for m in messages)
