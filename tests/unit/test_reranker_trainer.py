"""Unit tests for triplet materialization + shared metrics helpers (no mocks)."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.training.reranker_trainer import (
    Triplet,
    _pair_metrics_from_scores,
    materialize_triplets,
)


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


def test_pair_metrics_from_scores_handles_ties_and_mismatched_lengths() -> None:
    assert _pair_metrics_from_scores([], []) == {"mrr": 0.0, "ndcg": 0.0, "map": 0.0}
    assert _pair_metrics_from_scores([1.0], []) == {"mrr": 0.0, "ndcg": 0.0, "map": 0.0}

    tied = _pair_metrics_from_scores([0.0], [0.0])
    assert tied["mrr"] == pytest.approx(1.0 / 1.5, rel=1e-6)
    assert 0.0 <= tied["ndcg"] <= 1.0
    assert tied["map"] == pytest.approx(1.0 / 1.5, rel=1e-6)
