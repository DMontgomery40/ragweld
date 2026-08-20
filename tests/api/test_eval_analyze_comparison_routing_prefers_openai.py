from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.requires_postgres


@pytest.mark.asyncio
async def test_eval_analyze_comparison_uses_only_litellm_alias(client, tmp_path) -> None:

    corpus_id = f"test_eval_ai_route_{int(time.time() * 1000)}"

    create = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(tmp_path), "description": None},
    )
    assert create.status_code == 200

    old_key = os.environ.get("LITELLM_API_KEY")
    old_url = os.environ.get("LITELLM_BASE_URL")

    try:
        os.environ["LITELLM_API_KEY"] = "sk-test"
        os.environ["LITELLM_BASE_URL"] = "http://127.0.0.1:9/v1"

        patch_generation = await client.request(
            "PATCH",
            "/api/config/generation",
            params={"corpus_id": corpus_id},
            json={"gen_model": "analysis-alias"},
        )
        assert patch_generation.status_code == 200

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

        assert data.get("model_used") == "analysis-alias"

        err = str(data.get("error") or "")
        assert "Selected route: litellm" in err
        assert "Selected model: analysis-alias" in err
    finally:
        if old_key is None:
            os.environ.pop("LITELLM_API_KEY", None)
        else:
            os.environ["LITELLM_API_KEY"] = old_key
        if old_url is None:
            os.environ.pop("LITELLM_BASE_URL", None)
        else:
            os.environ["LITELLM_BASE_URL"] = old_url

        await client.delete(f"/api/corpora/{corpus_id}")
