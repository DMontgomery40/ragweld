from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.requires_postgres


@pytest.mark.asyncio
async def test_eval_analyze_comparison_returns_verbose_error_when_no_provider(client, tmp_path) -> None:
    corpus_id = f"test_eval_ai_{int(time.time() * 1000)}"

    create = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(tmp_path), "description": None},
    )
    assert create.status_code == 200

    old_litellm = os.environ.pop("LITELLM_API_KEY", None)

    try:
        # Disable the sole generation gateway.
        patch = await client.request(
            "PATCH",
            "/api/config/chat",
            params={"corpus_id": corpus_id},
            json={
                "litellm": {"enabled": False},
            },
        )
        assert patch.status_code == 200

        payload = {
            "current_run": {"run_id": "current", "top1_accuracy": 0.5, "topk_accuracy": 0.6, "total": 10, "duration_secs": 1.0},
            "compare_run": {"run_id": "baseline", "top1_accuracy": 0.4, "topk_accuracy": 0.5, "total": 10, "duration_secs": 1.0},
            "config_diffs": [],
            "topk_regressions": [],
            "topk_improvements": [],
            "top1_regressions_count": 0,
            "top1_improvements_count": 0,
        }
        res = await client.post("/api/eval/analyze_comparison", params={"corpus_id": corpus_id}, json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data.get("ok") is False

        err = str(data.get("error") or "")
        assert "Generation setup checklist" in err
        assert "LITELLM_API_KEY" in err
        assert "LiteLLM" in err
    finally:
        # Restore env vars so other tests / local runs are unaffected.
        if old_litellm is not None:
            os.environ["LITELLM_API_KEY"] = old_litellm
        else:
            os.environ.pop("LITELLM_API_KEY", None)

        await client.delete(f"/api/corpora/{corpus_id}")
