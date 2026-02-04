from __future__ import annotations

import os
import time

import pytest


@pytest.mark.asyncio
async def test_eval_analyze_comparison_prefers_openai_cloud_direct_when_openai_key_set(client, tmp_path) -> None:
    """Regression: Eval drill-down analysis should not get stuck on OpenRouter when OpenAI is configured.

    If OPENAI_API_KEY is set and generation.gen_model looks like an OpenAI model (e.g. "gpt-5.1"),
    the provider router should select cloud-direct OpenAI even if OpenRouter is enabled.
    """

    corpus_id = f"test_eval_ai_route_{int(time.time() * 1000)}"

    create = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(tmp_path), "description": None},
    )
    assert create.status_code == 200

    old_openai = os.environ.get("OPENAI_API_KEY")
    old_openrouter = os.environ.get("OPENROUTER_API_KEY")

    try:
        # Fake keys: we do not want real network calls in tests. Force OpenAI to a dead URL so it fails fast,
        # but still report the selected route/model in the error string.
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ["OPENROUTER_API_KEY"] = "or-invalid"

        patch_generation = await client.request(
            "PATCH",
            "/api/config/generation",
            params={"corpus_id": corpus_id},
            json={"gen_model": "gpt-5.1", "openai_base_url": "http://127.0.0.1:9/v1"},
        )
        assert patch_generation.status_code == 200

        patch_chat = await client.request(
            "PATCH",
            "/api/config/chat",
            params={"corpus_id": corpus_id},
            json={"openrouter": {"enabled": True}},
        )
        assert patch_chat.status_code == 200

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

        assert data.get("model_used") == "gpt-5.1"

        err = str(data.get("error") or "")
        assert "Selected route: cloud_direct" in err
        assert "Selected model: gpt-5.1" in err
        assert "Selected route: openrouter" not in err
    finally:
        if old_openai is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = old_openai
        if old_openrouter is None:
            os.environ.pop("OPENROUTER_API_KEY", None)
        else:
            os.environ["OPENROUTER_API_KEY"] = old_openrouter

        await client.delete(f"/api/corpora/{corpus_id}")

