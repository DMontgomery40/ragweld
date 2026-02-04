"""Unit tests for learning reranker trainer (no mocks, CPU-only)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from server.training.reranker_trainer import (
    Triplet,
    evaluate_pairwise_reranker,
    materialize_triplets,
    train_pairwise_reranker,
)


def _build_tiny_base_model(out_dir: Path, *, num_labels: int = 1) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    import torch
    from transformers import BertConfig, BertForSequenceClassification, BertTokenizerFast

    torch.manual_seed(0)

    vocab = [
        "[PAD]",
        "[UNK]",
        "[CLS]",
        "[SEP]",
        "[MASK]",
        "auth",
        "login",
        "token",
        "flow",
        "good",
        "bad",
    ]
    (out_dir / "vocab.txt").write_text("\n".join(vocab) + "\n", encoding="utf-8")
    tok = BertTokenizerFast(vocab_file=str(out_dir / "vocab.txt"), do_lower_case=True)
    tok.save_pretrained(str(out_dir))

    cfg = BertConfig(
        vocab_size=len(vocab),
        hidden_size=32,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=64,
        max_position_embeddings=128,
        type_vocab_size=2,
        num_labels=int(num_labels),
    )
    model = BertForSequenceClassification(cfg)
    model.eval()
    model.save_pretrained(str(out_dir))

    return out_dir


def test_materialize_triplets_rejects_paths_outside_corpus_root(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir(parents=True, exist_ok=True)
    (corpus_root / "good.txt").write_text("auth login token flow good", encoding="utf-8")
    (corpus_root / "bad.txt").write_text("bad bad bad", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("top secret", encoding="utf-8")

    triplets = [
        Triplet(query="auth login flow", positive="good.txt", negative="bad.txt"),
        Triplet(query="auth login flow", positive="../secret.txt", negative="bad.txt"),
        Triplet(query="auth login flow", positive="good.txt", negative=str((tmp_path / "secret.txt").resolve())),
    ]

    mats, stats = materialize_triplets(triplets, corpus_root=corpus_root, snippet_chars=2000)
    assert len(mats) == 1
    assert stats["triplets_in"] == 3
    assert stats["triplets_out"] == 1
    assert stats["missing_positive"] == 1
    assert stats["missing_negative"] == 1


@pytest.mark.asyncio
async def test_train_pairwise_reranker_writes_artifact_and_evaluates(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir(parents=True, exist_ok=True)
    (corpus_root / "good.txt").write_text("auth login token flow good", encoding="utf-8")
    (corpus_root / "bad.txt").write_text("bad bad bad", encoding="utf-8")

    base = _build_tiny_base_model(tmp_path / "base_model")

    triplets = [
        Triplet(query="auth login flow", positive="good.txt", negative="bad.txt")
        for _ in range(12)
    ]

    mats, stats = materialize_triplets(triplets, corpus_root=corpus_root, snippet_chars=2000)
    assert stats["triplets_out"] == 12
    assert len(mats) == 12

    out_dir = tmp_path / "trained_model"
    events: list[tuple[str, dict]] = []

    def emit(t: str, payload: dict) -> None:
        events.append((t, dict(payload)))

    res = await asyncio.to_thread(
        train_pairwise_reranker,
        base_model=str(base),
        output_dir=out_dir,
        triplets=mats,
        epochs=1,
        batch_size=4,
        lr=2e-4,
        warmup_ratio=0.0,
        max_length=64,
        dev_split=0.25,
        seed=0,
        emit=emit,
    )

    assert res["ok"] is True
    assert out_dir.exists()
    assert (out_dir / "config.json").exists()
    assert (out_dir / "tokenizer_config.json").exists() or (out_dir / "tokenizer.json").exists()
    assert (out_dir / "pytorch_model.bin").exists() or (out_dir / "model.safetensors").exists()
    assert any(t == "progress" for t, _ in events)
    assert any(t == "metrics" for t, _ in events)

    metrics = await asyncio.to_thread(evaluate_pairwise_reranker, model_dir=out_dir, triplets=mats, max_length=64)
    assert 0.0 <= metrics["mrr"] <= 1.0
    assert 0.0 <= metrics["ndcg"] <= 1.0
    assert 0.0 <= metrics["map"] <= 1.0


@pytest.mark.asyncio
async def test_train_pairwise_reranker_supports_two_logit_heads(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir(parents=True, exist_ok=True)
    (corpus_root / "good.txt").write_text("auth login token flow good", encoding="utf-8")
    (corpus_root / "bad.txt").write_text("bad bad bad", encoding="utf-8")

    base = _build_tiny_base_model(tmp_path / "base_model_2logit", num_labels=2)

    triplets = [
        Triplet(query="auth login flow", positive="good.txt", negative="bad.txt")
        for _ in range(12)
    ]
    mats, stats = materialize_triplets(triplets, corpus_root=corpus_root, snippet_chars=2000)
    assert stats["triplets_out"] == 12

    out_dir = tmp_path / "trained_model_2logit"
    res = await asyncio.to_thread(
        train_pairwise_reranker,
        base_model=str(base),
        output_dir=out_dir,
        triplets=mats,
        epochs=1,
        batch_size=4,
        lr=2e-4,
        warmup_ratio=0.0,
        max_length=64,
        dev_split=0.25,
        seed=0,
        emit=None,
    )
    assert res["ok"] is True

    metrics = await asyncio.to_thread(evaluate_pairwise_reranker, model_dir=out_dir, triplets=mats, max_length=64)
    assert 0.0 <= metrics["mrr"] <= 1.0
    assert 0.0 <= metrics["ndcg"] <= 1.0
    assert 0.0 <= metrics["map"] <= 1.0
