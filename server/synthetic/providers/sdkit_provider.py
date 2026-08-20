from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from importlib import metadata
from pathlib import Path
from typing import Any

from server.chat.generation import generate_chat_text
from server.chat.provider_router import ProviderRoute
from server.models.tribrid_config_model import (
    EvalDatasetItem,
    SyntheticArtifactKind,
    SyntheticRunStartRequest,
    SyntheticRunSummary,
    TriBridConfig,
)
from server.synthetic.recipes import (
    _autotune_patch,
    _build_triplets,
    _chunk_to_summary,
    _derive_keywords,
    _infer_source_kind,
    resolve_synthetic_route,
    select_source_chunks,
)
from server.synthetic.storage import run_dir


def _stage_sdkit_inputs(*, run_id: str, chunks: list[Any]) -> Path:
    base = run_dir(run_id) / "sdkit_input"
    base.mkdir(parents=True, exist_ok=True)
    for ch in chunks:
        chunk_id = str(getattr(ch, "chunk_id", "chunk"))
        file_path = str(getattr(ch, "file_path", ""))
        content = str(getattr(ch, "content", ""))
        p = base / f"{chunk_id}.txt"
        body = f"FILE_PATH: {file_path}\n\n{content}\n"
        p.write_text(body, encoding="utf-8")
    return base


def _import_sdkit_qagenerator() -> type[Any]:
    try:
        from synthetic_data_kit.generators.qa_generator import QAGenerator
    except Exception as e:  # pragma: no cover - exercised through runtime path
        raise RuntimeError(
            "synthetic_data_kit provider is unavailable: install `synthetic-data-kit` "
            "in the backend environment and restart the API."
        ) from e
    return QAGenerator


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n\n".join(parts).strip()
    return str(content or "").strip()


def _messages_to_prompt(messages: list[dict[str, Any]]) -> tuple[str, str]:
    normalized: list[tuple[str, str]] = []
    for message in messages:
        role = str(message.get("role") or "user").strip().lower() or "user"
        text = _extract_text_content(message.get("content"))
        if text:
            normalized.append((role, text))

    if not normalized:
        return ("Follow the user request exactly.", "Proceed.")

    if len(normalized) == 1:
        return (
            "Follow the user request exactly and return only the requested output.",
            normalized[0][1],
        )

    system_parts = [text for role, text in normalized if role == "system"]
    user_parts = [text for role, text in normalized if role != "system"]
    system_prompt = "\n\n".join(system_parts).strip() or "Follow the user request exactly."
    user_message = "\n\n".join(user_parts).strip() or "Proceed."
    return (system_prompt, user_message)


class _RouteBackedSdkitClient:
    """Bridge synthetic-data-kit prompts onto ragweld's routed generation stack."""

    def __init__(
        self,
        *,
        cfg: TriBridConfig,
        route: ProviderRoute,
        default_max_tokens: int,
        timeout_s: float,
    ) -> None:
        self.cfg = cfg
        self.route = route
        self.default_max_tokens = max(1, int(default_max_tokens))
        self.timeout_s = max(1.0, float(timeout_s))

    async def _chat_async(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None,
        max_tokens: int | None,
    ) -> str:
        system_prompt, user_message = _messages_to_prompt(messages)
        result = await generate_chat_text(
            route=self.route,
            system_prompt=system_prompt,
            user_message=user_message,
            images=[],
            image_detail="auto",
            temperature=float(temperature if temperature is not None else 0.0),
            max_tokens=int(max_tokens if max_tokens is not None else self.default_max_tokens),
            context_text="",
            context_chunks=[],
            timeout_s=self.timeout_s,
        )
        return str(result.text or "")

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
    ) -> str:
        _ = top_p
        return asyncio.run(
            self._chat_async(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )

    async def _batch_async(
        self,
        message_batches: list[list[dict[str, Any]]],
        *,
        temperature: float | None,
        max_tokens: int | None,
    ) -> list[str]:
        return await asyncio.gather(
            *[
                self._chat_async(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                for messages in message_batches
            ]
        )

    def batch_completion(
        self,
        message_batches: list[list[dict[str, Any]]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        batch_size: int | None = None,
    ) -> list[str]:
        _ = (top_p, batch_size)
        return asyncio.run(
            self._batch_async(
                message_batches,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )


def _match_curated_pairs(
    *,
    generated_pairs: list[dict[str, Any]],
    rated_pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    index: dict[tuple[str, str], deque[dict[str, Any]]] = defaultdict(deque)
    for pair in generated_pairs:
        key = (str(pair.get("question") or ""), str(pair.get("answer") or ""))
        index[key].append(pair)

    out: list[dict[str, Any]] = []
    for rated in rated_pairs:
        key = (str(rated.get("question") or ""), str(rated.get("answer") or ""))
        bucket = index.get(key)
        if not bucket:
            continue
        matched = dict(bucket.popleft())
        rating = rated.get("rating")
        if isinstance(rating, (int, float)):
            matched["rating"] = float(rating)
        out.append(matched)
    return out


def _build_eval_items_from_sdkit_pairs(
    *,
    pairs: list[dict[str, Any]],
    include_expected_answer: bool,
    include_tags: bool,
) -> list[EvalDatasetItem]:
    out: list[EvalDatasetItem] = []
    for pair in pairs:
        question = str(pair.get("question") or "").strip()
        answer = str(pair.get("answer") or "").strip()
        source_path = str(pair.get("source_path") or "").strip()
        source_kind = str(pair.get("source_kind") or "").strip()
        if not question or not source_path:
            continue
        tags: list[str] = []
        if include_tags:
            tags = ["synthetic", "synthetic_data_kit"]
            if source_kind:
                tags.append(source_kind)
        out.append(
            EvalDatasetItem(
                question=question,
                expected_paths=[source_path],
                expected_answer=answer if include_expected_answer else "",
                tags=tags,
            )
        )
    return out


def _sdkit_version_label() -> str:
    try:
        return str(metadata.version("synthetic-data-kit"))
    except Exception:
        return "unknown"


def _run_sdkit_pipeline_sync(
    *,
    cfg: TriBridConfig,
    request: SyntheticRunStartRequest,
    chunks: list[Any],
) -> tuple[list[EvalDatasetItem], int, int, float | None]:
    QAGenerator = _import_sdkit_qagenerator()

    generator_route = resolve_synthetic_route(cfg=cfg, model=str(request.generator_model or ""))
    judge_route = resolve_synthetic_route(cfg=cfg, model=str(request.judge_model or ""))

    timeout_s = float(cfg.generation.gen_timeout or 120.0)
    generator_client = _RouteBackedSdkitClient(
        cfg=cfg,
        route=generator_route,
        default_max_tokens=int(cfg.synthetic.generator.max_tokens or 1200),
        timeout_s=timeout_s,
    )
    judge_client = _RouteBackedSdkitClient(
        cfg=cfg,
        route=judge_route,
        default_max_tokens=int(cfg.synthetic.judge.max_tokens or 400),
        timeout_s=timeout_s,
    )

    generator = QAGenerator(generator_client)
    judge = QAGenerator(judge_client)

    max_pairs = max(1, int(request.max_pairs or 150))
    pairs_per_source = max(1, int(request.pairs_per_source or 1))

    generated_pairs: list[dict[str, Any]] = []
    for chunk in chunks:
        if len(generated_pairs) >= max_pairs:
            break
        file_path = str(getattr(chunk, "file_path", "") or "").strip()
        content = str(getattr(chunk, "content", "") or "").strip()
        if not file_path or not content:
            continue

        remaining = max_pairs - len(generated_pairs)
        requested_pairs = min(pairs_per_source, remaining)
        result = generator.process_document(
            content,
            num_pairs=requested_pairs,
            verbose=False,
        )
        qa_pairs = result.get("qa_pairs") if isinstance(result, dict) else None
        if not isinstance(qa_pairs, list):
            continue

        source_kind = _infer_source_kind(file_path, content)
        for pair in qa_pairs:
            if len(generated_pairs) >= max_pairs:
                break
            if not isinstance(pair, dict):
                continue
            question = str(pair.get("question") or "").strip()
            answer = str(pair.get("answer") or "").strip()
            if not question or not answer:
                continue
            generated_pairs.append(
                {
                    "question": question,
                    "answer": answer,
                    "source_path": file_path,
                    "source_kind": source_kind,
                }
            )

    curated_in = len(generated_pairs)
    if curated_in == 0:
        return ([], 0, 0, None)

    if not bool(request.curate_enabled):
        eval_items = _build_eval_items_from_sdkit_pairs(
            pairs=generated_pairs,
            include_expected_answer=bool(request.include_expected_answer),
            include_tags=bool(request.include_tags),
        )
        return (eval_items, curated_in, len(eval_items), None)

    rated_pairs, metrics = judge.rate_qa_pairs(
        [{"question": str(pair["question"]), "answer": str(pair["answer"])} for pair in generated_pairs],
        summary="",
        threshold=float(request.curate_threshold or 7.0),
    )
    matched_pairs = _match_curated_pairs(generated_pairs=generated_pairs, rated_pairs=rated_pairs)
    eval_items = _build_eval_items_from_sdkit_pairs(
        pairs=matched_pairs,
        include_expected_answer=bool(request.include_expected_answer),
        include_tags=bool(request.include_tags),
    )
    avg_score_raw = metrics.get("avg_score") if isinstance(metrics, dict) else None
    avg_score = float(avg_score_raw) if isinstance(avg_score_raw, (int, float)) else None
    return (eval_items, curated_in, len(eval_items), avg_score)


async def run_sdkit_provider(
    *,
    run_id: str,
    repo_id: str,
    cfg: TriBridConfig,
    request: SyntheticRunStartRequest,
) -> tuple[dict[SyntheticArtifactKind, Any], SyntheticRunSummary]:
    chunks = await select_source_chunks(repo_id=repo_id, cfg=cfg, request=request)
    staged = _stage_sdkit_inputs(run_id=run_id, chunks=chunks)

    eval_items: list[EvalDatasetItem] = []
    curated_in = 0
    curated_out = 0
    avg_judge_score: float | None = None
    if request.recipe in {"eval_dataset", "triplets", "autotune_retrieval", "full_stack"}:
        eval_items, curated_in, curated_out, avg_judge_score = await asyncio.to_thread(
            _run_sdkit_pipeline_sync,
            cfg=cfg,
            request=request,
            chunks=chunks,
        )

    summaries = [_chunk_to_summary(ch, card_source="deterministic") for ch in chunks]
    keywords = _derive_keywords(summaries, max_keywords=int(cfg.keywords.keywords_max_per_repo or 80))
    all_paths = [str(getattr(ch, "file_path", "") or "") for ch in chunks if str(getattr(ch, "file_path", "") or "").strip()]
    triplets = _build_triplets(
        eval_items=eval_items,
        candidate_paths=all_paths,
        max_pairs=int(request.max_pairs or 150),
    )
    patch = _autotune_patch(cfg=cfg, eval_items=eval_items, keywords=keywords)

    artifacts: dict[SyntheticArtifactKind, Any] = {}
    if request.recipe in {"semantic_cards", "full_stack"}:
        artifacts["semantic_cards_jsonl"] = summaries
    if request.recipe in {"eval_dataset", "triplets", "autotune_retrieval", "full_stack"}:
        artifacts["eval_dataset_json"] = eval_items
    if request.recipe in {"keywords", "full_stack"}:
        artifacts["keywords_json"] = keywords
    if request.recipe in {"triplets", "full_stack"}:
        artifacts["triplets_jsonl"] = triplets
    if request.recipe in {"autotune_retrieval", "full_stack"}:
        artifacts["config_patch_json"] = patch

    report = (
        f"Synthetic Data Kit { _sdkit_version_label() } generated eval rows through the real provider stack.\n"
        f"Generator model: {request.generator_model}\n"
        f"Judge model: {request.judge_model}\n"
        f"Sources used: {len(chunks)}\n"
        f"Eval items: {len(eval_items)}\n"
        f"Triplets: {len(triplets)}\n"
        f"Keywords: {len(keywords)}\n"
        f"Curated in: {curated_in}\n"
        f"Curated out: {curated_out}\n"
        f"SDKit staging directory: {staged}\n"
    )
    artifacts["report_md"] = report

    summary = SyntheticRunSummary()
    summary.sources_used = len(chunks)
    summary.items_generated = sum(
        [
            len(eval_items),
            len(summaries),
            len(triplets),
            len(keywords),
        ]
    )
    summary.items_curated_in = curated_in
    summary.items_curated_out = curated_out
    summary.avg_judge_score = avg_judge_score
    return artifacts, summary
