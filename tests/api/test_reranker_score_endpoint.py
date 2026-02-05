from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_reranker_score_endpoint_shape_without_scoped_config(client: AsyncClient) -> None:
    """The debug endpoint must be stable even when corpus-scoped config is unavailable."""
    res = await client.post(
        "/api/reranker/score",
        json={
            "corpus_id": "does-not-exist",
            "query": "auth flow",
            "document": "OAuth2 authorization code exchange",
            "include_logits": 0,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, dict)
    assert "ok" in body
    assert "backend" in body
    assert "score" in body
    assert "error" in body
    assert body["ok"] in {True, False}


@pytest.mark.asyncio
async def test_reranker_score_endpoint_reflects_on_disk_model_changes(client: AsyncClient, tmp_path: Path) -> None:
    """Debug scoring must reflect promoted/updated weights (no stale in-process cache)."""
    corpus_id = f"test-score-reload-{tmp_path.name}"
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir(parents=True, exist_ok=True)

    # Create corpus scope so we can patch training config to point at temp model dirs.
    r = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_root)},
    )
    assert r.status_code == 200

    try:
        src = Path(".tests/reranker_proof/tiny_cross_encoder").resolve()
        assert src.exists()

        # Build two distinct local model directories (same tokenizer, slightly different weights).
        model_a = tmp_path / "model_a"
        model_b = tmp_path / "model_b"

        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(str(src), use_fast=True)  # type: ignore[no-untyped-call]

        model = AutoModelForSequenceClassification.from_pretrained(str(src))
        model.save_pretrained(str(model_a))
        tokenizer.save_pretrained(str(model_a))

        model2 = AutoModelForSequenceClassification.from_pretrained(str(src))
        try:
            import torch

            with torch.no_grad():
                # Nudge a classification bias so scores change predictably.
                target = None
                for name, p in model2.named_parameters():
                    if name.endswith("classifier.bias") or name.endswith("score.bias") or name.endswith("out_proj.bias"):
                        target = p
                        break
                if target is None:
                    target = list(model2.parameters())[-1]
                target.add_(0.5)
        except Exception:
            # Best-effort: if torch is unavailable, we still proceed (but the assertion may fail).
            pass
        model2.save_pretrained(str(model_b))
        tokenizer.save_pretrained(str(model_b))

        # Point learning reranker scoring at model_a (transformers backend).
        r = await client.request(
            "PATCH",
            f"/api/config/training?corpus_id={corpus_id}",
            json={
                "learning_reranker_backend": "transformers",
                "tribrid_reranker_model_path": str(model_a),
            },
        )
        assert r.status_code == 200

        payload = {
            "corpus_id": corpus_id,
            "query": "auth login flow",
            "document": "auth login token flow good",
            "include_logits": 0,
        }

        r = await client.post("/api/reranker/score", json=payload)
        assert r.status_code == 200
        score1 = r.json().get("score")
        assert isinstance(score1, (int, float))

        # Simulate an atomic-ish promotion by replacing the on-disk directory contents in-place.
        shutil.rmtree(model_a, ignore_errors=True)
        shutil.copytree(model_b, model_a)

        r = await client.post("/api/reranker/score", json=payload)
        assert r.status_code == 200
        score2 = r.json().get("score")
        assert isinstance(score2, (int, float))

        assert float(score2) != float(score1)
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
