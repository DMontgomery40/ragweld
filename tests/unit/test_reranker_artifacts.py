from __future__ import annotations

from pathlib import Path

import pytest

from server.models.tribrid_config_model import ChunkMatch, RerankingConfig, TrainingConfig
from server.reranker.artifacts import has_transformers_weights
from server.retrieval.rerank import Reranker


def test_has_transformers_weights_false_when_only_config_present(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    assert has_transformers_weights(model_dir) is False


def test_has_transformers_weights_true_for_model_safetensors(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"")
    assert has_transformers_weights(model_dir) is True


@pytest.mark.asyncio
async def test_learning_rerank_skips_when_trained_dir_missing_weights(tmp_path: Path) -> None:
    model_dir = tmp_path / "trained_model"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")

    cfg = RerankingConfig(reranker_mode="learning")
    train_cfg = TrainingConfig(learning_reranker_backend="transformers")
    reranker = Reranker(cfg, training_config=train_cfg, trained_model_path=str(model_dir))

    chunks = [
        ChunkMatch(
            chunk_id="c1",
            content="alpha",
            file_path="a.txt",
            start_line=1,
            end_line=1,
            language="text",
            score=0.1,
            source="vector",
            metadata={"corpus_id": "faxbot"},
        )
    ]
    res = await reranker.try_rerank("query", chunks)
    assert res.ok is True
    assert res.applied is False
    assert res.skipped_reason == "missing_trained_model"
    assert res.chunks == chunks

