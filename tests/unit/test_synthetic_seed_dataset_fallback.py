from __future__ import annotations

import json
import shutil
import uuid

from server.api.dataset import _dataset_path_for_corpus
from server.models.tribrid_config_model import SyntheticRunStartRequest, SyntheticRunSummary
from server.synthetic.orchestrator import _hydrate_eval_dataset_from_seed
from server.synthetic.storage import run_dir


def _write_seed_dataset(corpus_id: str, rows: list[dict[str, object]]) -> None:
    path = _dataset_path_for_corpus(corpus_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")


def test_seed_dataset_fallback_hydrates_eval_items_for_eval_recipes() -> None:
    corpus_id = f"pytest_seed_fallback_{uuid.uuid4().hex[:8]}"
    run_id = f"{corpus_id}__run"
    request = SyntheticRunStartRequest(
        corpus_id=corpus_id,
        provider="synthetic_data_kit",
        recipe="eval_dataset",
        generator_model="litellm:synthetic-quality",
        judge_model="litellm:synthetic-quality",
        max_pairs=10,
        seed=42,
    )
    summary = SyntheticRunSummary(items_generated=0)
    artifacts_payloads: dict[str, object] = {"eval_dataset_json": []}
    rows = [{"question": f"q{i}", "expected_paths": [f"{i}.py"], "tags": ["seed"]} for i in range(12)]
    dataset_path = _dataset_path_for_corpus(corpus_id)
    synthetic_run_path = run_dir(run_id)

    _write_seed_dataset(corpus_id, rows)
    try:
        hydrated = _hydrate_eval_dataset_from_seed(
            run_id=run_id,
            repo_id=corpus_id,
            request=request,
            artifacts_payloads=artifacts_payloads,
            summary=summary,
        )
        hydrated_rows = artifacts_payloads.get("eval_dataset_json")
        assert hydrated == 10
        assert isinstance(hydrated_rows, list)
        assert len(hydrated_rows) == 10
        assert summary.items_generated == 10
        assert "report_md" in artifacts_payloads
    finally:
        dataset_path.unlink(missing_ok=True)
        shutil.rmtree(synthetic_run_path, ignore_errors=True)


def test_seed_dataset_fallback_skips_non_eval_recipes() -> None:
    corpus_id = f"pytest_seed_skip_{uuid.uuid4().hex[:8]}"
    run_id = f"{corpus_id}__run"
    request = SyntheticRunStartRequest(
        corpus_id=corpus_id,
        provider="synthetic_data_kit",
        recipe="keywords",
        generator_model="litellm:synthetic-quality",
        judge_model="litellm:synthetic-quality",
    )
    summary = SyntheticRunSummary(items_generated=0)
    artifacts_payloads: dict[str, object] = {"eval_dataset_json": []}
    rows = [{"question": "q1", "expected_paths": ["a.py"], "tags": ["seed"]}]
    dataset_path = _dataset_path_for_corpus(corpus_id)
    synthetic_run_path = run_dir(run_id)

    _write_seed_dataset(corpus_id, rows)
    try:
        hydrated = _hydrate_eval_dataset_from_seed(
            run_id=run_id,
            repo_id=corpus_id,
            request=request,
            artifacts_payloads=artifacts_payloads,
            summary=summary,
        )
        assert hydrated == 0
        assert artifacts_payloads["eval_dataset_json"] == []
        assert summary.items_generated == 0
    finally:
        dataset_path.unlink(missing_ok=True)
        shutil.rmtree(synthetic_run_path, ignore_errors=True)
