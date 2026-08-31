"""Real Ragas scoring for eval runs.

Answers are generated through the LiteLLM gateway, judged by a LiteLLM alias,
and embedded with the operator's local sentence-transformers model. Nothing
here substitutes heuristics for Ragas: if the substrate cannot execute, it
raises ``RagasUnavailableError`` so callers fail closed.

``langchain_openai.ChatOpenAI`` is the adapter type Ragas requires for an
OpenAI-compatible judge; it is confined to this module.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import SecretStr

from server.chat.gateway_runtime import resolve_litellm_api_key, resolve_litellm_base_url
from server.models.tribrid_config_model import TriBridConfig

SUPPORTED_METRICS: tuple[str, ...] = ("faithfulness", "answer_relevancy")


class RagasUnavailableError(RuntimeError):
    """Raised when Ragas scoring cannot execute for a real, named reason."""


@dataclass(frozen=True)
class RagasSample:
    user_input: str
    retrieved_contexts: list[str]
    response: str


def ragas_importable() -> bool:
    return importlib.util.find_spec("ragas") is not None


def _judge_alias(cfg: TriBridConfig) -> str:
    alias = str(cfg.evaluation.ragas_judge_model or "").strip()
    if alias:
        return alias
    return str(cfg.chat.litellm.default_model or "").strip()


def _gateway(cfg: TriBridConfig) -> tuple[str, str]:
    """Resolve the authenticated LiteLLM gateway (deployment wiring wins over config)."""
    base_url = resolve_litellm_base_url(configured_url=str(cfg.chat.litellm.base_url or ""))
    api_key = resolve_litellm_api_key()
    return base_url, api_key


def preflight(cfg: TriBridConfig) -> None:
    """Verify every Ragas prerequisite with real probes; raise on the first gap."""
    if not ragas_importable():
        raise RagasUnavailableError("ragas package is not installed")
    metrics = [str(m).strip().lower() for m in (cfg.evaluation.ragas_metrics or []) if str(m).strip()]
    unsupported = sorted(set(metrics) - set(SUPPORTED_METRICS))
    if unsupported:
        raise RagasUnavailableError(f"unsupported ragas metrics configured: {', '.join(unsupported)}")
    if not metrics:
        raise RagasUnavailableError("evaluation.ragas_metrics is empty")
    provider = str(cfg.embedding.embedding_type or "").strip().lower()
    if provider not in {"local", "huggingface"}:
        raise RagasUnavailableError(
            f"ragas answer relevancy needs a local sentence-transformers embedding provider; configured: {provider!r}"
        )
    alias = _judge_alias(cfg)
    if not alias:
        raise RagasUnavailableError("no LiteLLM judge alias configured (evaluation.ragas_judge_model / chat default)")
    try:
        base_url, api_key = _gateway(cfg)
    except RuntimeError as exc:
        raise RagasUnavailableError(str(exc)) from exc
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(5.0, connect=2.0),
        )
    except Exception as exc:
        raise RagasUnavailableError(f"LiteLLM judge gateway unreachable at {base_url}: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        raise RagasUnavailableError(f"LiteLLM judge gateway rejected the client key (HTTP {response.status_code})")
    try:
        ids = {str(item.get("id") or "") for item in (response.json().get("data") or [])}
    except Exception:
        ids = set()
    if alias not in ids:
        raise RagasUnavailableError(f"judge alias {alias!r} is not exposed by the LiteLLM gateway")


def score_samples(cfg: TriBridConfig, samples: list[RagasSample]) -> list[dict[str, float]]:
    """Run Ragas over the samples and return per-sample metric maps (same order)."""
    preflight(cfg)
    if not samples:
        return []

    from langchain_openai import ChatOpenAI
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import BaseRagasEmbeddings
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import AnswerRelevancy, Faithfulness
    from ragas.run_config import RunConfig
    from sentence_transformers import SentenceTransformer

    class _LocalEmbeddings(BaseRagasEmbeddings):  # type: ignore[misc]  # ragas ships untyped; its base is Any to mypy
        def __init__(self, model_name: str) -> None:
            super().__init__()
            self._model = SentenceTransformer(model_name)

        def embed_query(self, text: str) -> list[float]:
            return [float(x) for x in self._model.encode(text, normalize_embeddings=True).tolist()]

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [
                [float(x) for x in row]
                for row in self._model.encode(list(texts), normalize_embeddings=True).tolist()
            ]

        async def aembed_query(self, text: str) -> list[float]:
            return self.embed_query(text)

        async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
            return self.embed_documents(texts)

    base_url, api_key = _gateway(cfg)
    # langchain-openai lru_caches one async httpx client per (base_url, timeout)
    # PROCESS-WIDE (_client_utils._cached_async_httpx_client). Ragas runs each
    # scoring call on its own event loop, so a cached client born on an earlier
    # loop fails with "Event is bound to a different event loop" surfaced as
    # APIConnectionError. Explicit per-call clients bypass the cache and die
    # with this call's loop.
    judge_timeout = float(cfg.evaluation.ragas_judge_timeout_s)
    http_client = httpx.Client(timeout=judge_timeout)
    http_async_client = httpx.AsyncClient(timeout=judge_timeout)
    judge = LangchainLLMWrapper(
        ChatOpenAI(
            base_url=base_url,
            api_key=SecretStr(api_key),
            model=_judge_alias(cfg),
            temperature=0,
            timeout=judge_timeout,
            max_retries=0,
            http_client=http_client,
            http_async_client=http_async_client,
            # Judges must return structured verdicts; cap output at the eval judge budget
            # (faithfulness statement lists outgrow a chat answer budget).
            max_completion_tokens=int(cfg.evaluation.judge_max_tokens),
        )
    )
    # Local serving is single-stream; serialize judge calls and honor the
    # configured per-call timeout instead of ragas's default 180s.
    run_config = RunConfig(timeout=int(cfg.evaluation.ragas_judge_timeout_s), max_workers=1, max_retries=0)
    embeddings = _LocalEmbeddings(str(cfg.embedding.effective_model or ""))

    wanted = [str(m).strip().lower() for m in (cfg.evaluation.ragas_metrics or [])]
    metrics: list[Any] = []
    if "faithfulness" in wanted:
        metrics.append(Faithfulness(llm=judge))
    if "answer_relevancy" in wanted:
        metrics.append(AnswerRelevancy(llm=judge, embeddings=embeddings))

    dataset = EvaluationDataset.from_list(
        [
            {
                "user_input": sample.user_input,
                "retrieved_contexts": list(sample.retrieved_contexts),
                "response": sample.response,
            }
            for sample in samples
        ]
    )
    try:
        result = evaluate(
            dataset,
            metrics=metrics,
            llm=judge,
            embeddings=embeddings,
            raise_exceptions=True,
            show_progress=False,
            run_config=run_config,
        )
        frame = result.to_pandas()
    except Exception as exc:
        raise RagasUnavailableError(f"ragas evaluation failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    finally:
        http_client.close()
        # The async client's pool is bound to the event loop ragas just tore
        # down; aclose() on a new loop would trip the same cross-loop error.
        # Dropping the reference lets GC reclaim the sockets.
        del http_async_client

    rows: list[dict[str, float]] = []
    for _, row in frame.iterrows():
        scores: dict[str, float] = {}
        for metric in wanted:
            value = row.get(metric)
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number == number:  # not NaN
                scores[metric] = number
        rows.append(scores)
    return rows
