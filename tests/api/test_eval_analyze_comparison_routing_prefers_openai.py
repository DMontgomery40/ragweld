from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.requires_postgres


_COMPARISON_PAYLOAD = {
    "current_run": {"run_id": "current", "top1_accuracy": 0.5, "topk_accuracy": 0.6, "total": 10, "duration_secs": 1.0},
    "compare_run": {"run_id": "baseline", "top1_accuracy": 0.4, "topk_accuracy": 0.5, "total": 10, "duration_secs": 1.0},
    "config_diffs": [],
    "topk_regressions": [],
    "topk_improvements": [],
    "top1_regressions_count": 0,
    "top1_improvements_count": 0,
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gen_model", "expected_fragments", "forbidden_fragments"),
    [
        pytest.param(
            # A real catalog alias: the LiteLLM route is selected, then the unreachable
            # gateway fails the call. No direct-provider route may ever be substituted.
            "ragweld-local",
            ("Eval AI analysis failed", "Selected route: litellm", "Selected model: ragweld-local"),
            ("openai", "anthropic"),
            id="catalog-alias-routes-through-litellm-only",
        ),
        pytest.param(
            # An alias the catalog does not serve fails closed before any route exists.
            "analysis-alias",
            ("Generation model_override 'analysis-alias' is not a gateway alias in data/models.json",),
            ("Selected route:",),
            id="non-catalog-alias-fails-closed",
        ),
    ],
)
async def test_eval_analyze_comparison_uses_only_litellm_alias(
    client,
    tmp_path,
    gen_model: str,
    expected_fragments: tuple[str, ...],
    forbidden_fragments: tuple[str, ...],
) -> None:
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
        # Deployment wiring wins over persisted config; port 9 refuses connections.
        os.environ["LITELLM_BASE_URL"] = "http://127.0.0.1:9/v1"

        patch_generation = await client.request(
            "PATCH",
            "/api/config/generation",
            params={"corpus_id": corpus_id},
            json={"gen_model": gen_model},
        )
        assert patch_generation.status_code == 200

        res = await client.post("/api/eval/analyze_comparison", params={"corpus_id": corpus_id}, json=_COMPARISON_PAYLOAD)
        assert res.status_code == 200
        data = res.json()
        assert data.get("ok") is False
        assert data.get("analysis") is None
        assert data.get("model_used") == gen_model

        err = str(data.get("error") or "")
        for fragment in expected_fragments:
            assert fragment in err, f"missing {fragment!r} in: {err}"
        for fragment in forbidden_fragments:
            assert fragment not in err, f"unexpected {fragment!r} in: {err}"
        assert "Generation setup checklist:" in err
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
