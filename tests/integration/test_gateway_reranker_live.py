"""Fifty real candidates through the real LiteLLM gateway with reasoning-capable aliases.

Defect D26: the listwise reranker sent one chat completion whose output budget a reasoning
model spent thinking about the candidates, so the verdict came back empty or truncated and
every such alias failed with a parse error (openai.gpt-5.6-luna 1 in 3 at 50 candidates,
google.gemini-3.7-flash 3 in 3, deepseek.deepseek-v4-flash every time). The candidates are
the top 60 fused results the live deployment returned for a real Epstein-corpus question
(``tests/fixtures/gateway_rerank_candidates.json``); the query is the one the unit suite
uses, whose answer (EJM) is in candidate text. Paid spend: one request per alias.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import httpx
import pytest

from server.chat.gateway_runtime import resolve_litellm_base_url
from server.gateway_catalog import warm_gateway_catalog
from server.models.tribrid_config_model import TriBridConfig
from server.retrieval.gateway_reranker import resolve_rerank_route, score_candidates

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.getenv("RAGWELD_LIVE_GATEWAY"),
        reason="set RAGWELD_LIVE_GATEWAY=1 on LXC100 to run against the real LiteLLM gateway",
    ),
]

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gateway_rerank_candidates.json"
_QUERY = "Which plane management company did Barry Cohen consider switching to from Jet Aviation in October 2017?"
_CANDIDATES = 50
# Reasoning-capable aliases from three provider families with different reasoning protocols
# (OpenAI accepts effort "none"; Google only "minimal"; DeepSeek ignores anything but "none"),
# plus the operator's configured non-reasoning reranker, which must keep answering with the
# control attached.
_ALIASES = [
    "openai.gpt-5.6-luna",
    "google.gemini-3.7-flash",
    "deepseek.deepseek-v4-flash",
    "openai.gpt-4.1-nano",
]
# One request per alias; this bound only guards against a stalled OpenRouter provider. The
# operator's reranking.reranker_timeout (30 s by default) stays the production bound.
_TIMEOUT_S = 60.0


async def _gateway_serves(cfg: TriBridConfig, alias: str) -> str | None:
    key = os.environ.get("LITELLM_API_KEY", "")
    if not key:
        return "LITELLM_API_KEY is not set"
    base = resolve_litellm_base_url(configured_url=cfg.chat.litellm.base_url)
    try:
        async with httpx.AsyncClient(timeout=3.0) as probe:
            response = await probe.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
    except Exception as exc:
        return f"LiteLLM gateway not reachable at {base}: {exc}"
    if response.status_code != 200:
        return f"LiteLLM gateway at {base} answered HTTP {response.status_code} to /models"
    served = {str(item.get("id")) for item in (response.json().get("data") or [])}
    return None if alias in served else f"gateway does not serve {alias!r}"


def _real_candidates(cfg: TriBridConfig) -> list[str]:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    snippet_chars = int(cfg.reranking.rerank_input_snippet_chars)
    docs = [str(candidate["content"])[:snippet_chars] for candidate in fixture["candidates"][:_CANDIDATES]]
    assert len(docs) == _CANDIDATES, f"fixture holds {len(docs)} candidates, need {_CANDIDATES}"
    return docs


@pytest.mark.parametrize("alias", _ALIASES)
async def test_reasoning_capable_alias_scores_fifty_real_candidates(alias: str) -> None:
    warm_gateway_catalog()
    cfg = TriBridConfig()
    skip_reason = await _gateway_serves(cfg, alias)
    if skip_reason:
        pytest.skip(skip_reason)
    docs = _real_candidates(cfg)
    route = resolve_rerank_route(cfg, alias)

    scores = await score_candidates(
        route=route,
        system_prompt=cfg.system_prompts.gateway_rerank,
        query=_QUERY,
        docs=docs,
        timeout_s=_TIMEOUT_S,
    )

    assert len(scores) == _CANDIDATES
    assert all(math.isfinite(score) and 0.0 <= score <= 10.0 for score in scores)
    best = max(range(_CANDIDATES), key=scores.__getitem__)
    print(f"{alias}: best={best} score={scores[best]} text={docs[best][:120]!r}")
    assert "EJM" in docs[best], f"{alias} ranked a candidate without the answer first: {docs[best][:200]!r}"
    unrelated = [index for index, doc in enumerate(docs) if "S&P" in doc or "XLF" in doc]
    assert unrelated, "the fixture must keep its off-topic market-research candidates"
    assert all(scores[index] < scores[best] for index in unrelated)
