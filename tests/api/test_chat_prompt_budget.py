"""Chat refuses requests that cannot fit the selected alias's context window, on both transports."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from server.api.chat import set_config, set_fusion
from server.chat.prompt_budget import plan_prompt_budget
from server.chat.prompt_builder import get_system_prompt
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import FusionConfig, TriBridConfig

# The local row's 32k window now exceeds the chat.max_tokens boundary ceiling
# (16384), so window-saturation scenarios use a catalog alias whose window the
# config can actually reach: rekaai.reka-edge (16,384-token window).
BUDGET_ALIAS = "rekaai.reka-edge"
BUDGET_WINDOW = 16384
QUESTION = "Which flights or plane management did Jeffrey Epstein discuss with Barry Cohen in October 2017?"
EVIDENCE = (
    "Thinking of switching from Jet Aviation to EJM. EJM is more expensive. Do you have a point of view?\n\n"
    "Email metaBarry J. Cohen emailed Jeffrey Epstein on 2017-10-02 14:33:00. Subject: \"Plane management\".\n"
)


class _RetrievedEvidence:
    """Returns the one real Epstein chunk so the request carries RAG evidence (no store round-trip)."""

    def __init__(self) -> None:
        self.last_debug: dict[str, object] = {}

    async def search(
        self,
        corpus_ids: list[str],
        query: str,
        config: FusionConfig,
        *,
        include_vector: bool = True,
        include_sparse: bool = True,
        include_graph: bool = True,
        top_k: int | None = None,
    ) -> list[ChunkMatch]:
        _ = (query, config, include_vector, include_sparse, include_graph, top_k)
        self.last_debug = {"fusion_corpora": list(corpus_ids), "fusion_vector_results": 1, "fusion_sparse_results": 0}
        return [
            ChunkMatch(
                chunk_id="HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt:1-4:0",
                content=EVIDENCE,
                file_path="HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt",
                start_line=1,
                end_line=4,
                language=None,
                score=0.029,
                source="vector",
                metadata={"corpus_id": "epstein-files-1"},
            )
        ]


def _config(max_tokens: int, *, alias: str = "ragweld-local", vision_override: str = "") -> TriBridConfig:
    cfg = TriBridConfig()
    cfg.chat.max_tokens = max_tokens
    cfg.chat.recall.enabled = False
    cfg.chat.litellm.default_model = alias
    cfg.chat.multimodal.vision_model_override = vision_override
    return cfg


# 1x1 PNG, inline: the attachment carries real pixel dimensions.
TINY_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


def _events(body: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in body.split("\n\n"):
        part = block.strip()
        if part.startswith("data:"):
            raw = part[len("data:") :].strip()
            if raw:
                events.append(json.loads(raw))
    return events


@pytest.mark.asyncio
async def test_output_allowance_at_the_window_is_refused_with_413_on_both_transports(client: AsyncClient) -> None:
    try:
        set_config(_config(BUDGET_WINDOW, alias=BUDGET_ALIAS))
        set_fusion(_RetrievedEvidence())
        payload = {"message": QUESTION, "sources": {"corpus_ids": ["epstein-files-1"]}}

        response = await client.post("/api/chat", json=payload)
        assert response.status_code == 413
        detail = response.json()["detail"]
        assert detail["code"] == "prompt_budget_exceeded"
        assert detail["alias"] == BUDGET_ALIAS
        assert detail["context_window"] == BUDGET_WINDOW
        assert detail["max_tokens"] == BUDGET_WINDOW
        assert detail["retryable"] is False
        assert "leaves no room for input" in detail["message"]

        stream = await client.post("/api/chat/stream", json={**payload, "stream": True})
        assert stream.status_code == 413
        assert stream.json()["detail"]["code"] == "prompt_budget_exceeded"
    finally:
        set_config(None)
        set_fusion(None)


@pytest.mark.asyncio
async def test_request_is_refused_instead_of_dropping_all_retrieved_evidence(client: AsyncClient) -> None:
    """When the only retrieved chunk cannot fit, chat must not silently answer without sources."""
    probe = _config(512)
    system_prompt = get_system_prompt(has_rag_context=True, has_recall_context=False, config=probe.chat)
    fixed = plan_prompt_budget(
        alias=BUDGET_ALIAS, system_prompt=system_prompt, user_message=QUESTION, max_tokens=512, context_window=BUDGET_WINDOW
    ).fixed_tokens
    # Leave ~20 tokens for context: the evidence chunk needs more than that.
    max_tokens = BUDGET_WINDOW - fixed - 20
    try:
        set_config(_config(max_tokens, alias=BUDGET_ALIAS))
        set_fusion(_RetrievedEvidence())
        payload = {"message": QUESTION, "sources": {"corpus_ids": ["epstein-files-1"]}}

        response = await client.post("/api/chat", json=payload)
        assert response.status_code == 413
        detail = response.json()["detail"]
        assert "none of the retrieved evidence fits" in detail["message"]
        assert detail["max_tokens"] == max_tokens

        stream = await client.post("/api/chat/stream", json={**payload, "stream": True})
        assert stream.status_code == 413
        assert "none of the retrieved evidence fits" in stream.json()["detail"]["message"]
    finally:
        set_config(None)
        set_fusion(None)


@pytest.mark.asyncio
async def test_openapi_keeps_fastapi_validation_errors_separate_from_budget_refusals(client: AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    responses = spec["paths"]["/api/chat"]["post"]["responses"]
    assert "413" in responses
    assert "PromptBudgetExceededResponse" in json.dumps(responses["413"])
    stream_responses = spec["paths"]["/api/chat/stream"]["post"]["responses"]
    assert "PromptBudgetExceededResponse" in json.dumps(stream_responses["413"])
    assert "422" in responses
    assert "HTTPValidationError" in json.dumps(responses["422"])

    malformed = await client.post("/api/chat", json={"sources": {"corpus_ids": ["epstein-files-1"]}})
    assert malformed.status_code == 422
    assert isinstance(malformed.json()["detail"], list)


@pytest.mark.asyncio
async def test_images_are_refused_when_the_selected_alias_has_no_vision_route(client: AsyncClient) -> None:
    """No vision override configured and the picker chose the text-only local row: refuse before generation."""
    try:
        set_config(_config(512))
        set_fusion(_RetrievedEvidence())
        payload = {
            "message": QUESTION,
            "model_override": "litellm:ragweld-local",
            "sources": {"corpus_ids": ["epstein-files-1"]},
            "images": [{"mime_type": "image/png", "base64": TINY_PNG}],
        }
        for path, extra in (("/api/chat", {}), ("/api/chat/stream", {"stream": True})):
            response = await client.post(path, json={**payload, **extra})
            assert response.status_code == 413, response.text
            detail = response.json()["detail"]
            assert detail["code"] == "prompt_budget_exceeded"
            assert detail["alias"] == "ragweld-local"
            # The HTTP path resolved the local alias against the live catalog:
            # the refusal carries the ragweld-local 32k context window.
            assert detail["context_window"] == 32768
            assert "does not accept image attachments" in detail["message"]
    finally:
        set_config(None)
        set_fusion(None)


@pytest.mark.asyncio
async def test_configured_vision_override_forces_the_route_when_images_are_attached(client: AsyncClient) -> None:
    """`chat.multimodal.vision_model_override` wins over the picker's model for image requests."""
    # rekaai.reka-edge is a vision alias with a 16,384-token window; max_tokens at the window makes the
    # budget refusal name the alias that was actually selected.
    try:
        set_config(_config(16384, vision_override="rekaai.reka-edge"))
        set_fusion(_RetrievedEvidence())
        payload = {
            "message": QUESTION,
            "model_override": "litellm:ragweld-local",
            "sources": {"corpus_ids": ["epstein-files-1"]},
            "images": [{"mime_type": "image/png", "base64": TINY_PNG}],
        }
        for path, extra in (("/api/chat", {}), ("/api/chat/stream", {"stream": True})):
            response = await client.post(path, json={**payload, **extra})
            assert response.status_code == 413, response.text
            detail = response.json()["detail"]
            assert detail["alias"] == "rekaai.reka-edge"
            assert detail["context_window"] == 16384
            assert "leaves no room for input" in detail["message"]
    finally:
        set_config(None)
        set_fusion(None)
