from __future__ import annotations

import json
import os
import random
import re
from collections import Counter, defaultdict
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from server.chat.generation import generate_chat_text
from server.chat.provider_router import ProviderRoute, select_provider_route
from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import (
    Chunk,
    ChunkSummary,
    EvalDatasetItem,
    SyntheticArtifactKind,
    SyntheticRecipeKind,
    SyntheticRunStartRequest,
    SyntheticRunSummary,
    TriBridConfig,
)
from server.synthetic.layering import infer_layer_from_path

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,63}")
_DEF_RE = re.compile(r"^\s*(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([A-Za-z0-9_\.]+)", re.MULTILINE)
_ROUTE_RE = re.compile(r"(?:/api/[A-Za-z0-9_./-]+)")


def synthetic_generation_model_category(model: str) -> str:
    raw = str(model or "").strip().lower()
    if not raw:
        return "unknown"
    if raw.startswith("litellm:"):
        return "litellm"
    if raw.startswith("openrouter:"):
        return "openrouter"
    if raw.startswith("local:"):
        return "local"
    if raw.startswith("ragweld:"):
        return "ragweld"
    if raw.startswith("openai/"):
        return "openai"
    if raw.startswith("gpt-") or raw.startswith("o1") or raw.startswith("o3") or raw.startswith("o4"):
        return "openai"
    if "/" in raw:
        return raw.split("/", 1)[0]
    return "auto"


def _is_allowed_branch_synthetic_model(model: str) -> bool:
    raw = str(model or "").strip().lower()
    if not raw:
        return False
    for prefix in ("openrouter:", "litellm:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    if raw.startswith("openai/"):
        raw = raw.split("/", 1)[1]
    if raw.startswith(("gpt-", "o1", "o3", "o4")):
        return raw.startswith("gpt-5")
    return True


def resolve_synthetic_route(*, cfg: TriBridConfig, model: str) -> ProviderRoute:
    model_name = str(model or "").strip()
    if not model_name:
        raise RuntimeError("Missing model name")
    try:
        return select_provider_route(config=cfg, model_override=model_name)
    except Exception as e:
        category = synthetic_generation_model_category(model_name)
        raise RuntimeError(f"Unable to resolve model route for {model_name!r} (category={category}): {e}") from e


def resolve_available_synthetic_generation_model(cfg: TriBridConfig) -> str | None:
    candidates: list[str] = []

    if os.getenv("OPENAI_API_KEY", "").strip():
        candidates.append("openai/gpt-5.4-mini")
    litellm_default = str(getattr(cfg.chat.litellm, "default_model", "") or "").strip()
    litellm_enabled = bool(getattr(cfg.chat.litellm, "enabled", False))
    litellm_base = str(getattr(cfg.chat.litellm, "base_url", "") or "").strip()
    if litellm_enabled and litellm_base and litellm_default and _is_allowed_branch_synthetic_model(litellm_default):
        candidates.append(f"litellm:{litellm_default}")
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        candidates.append("openrouter:openai/gpt-5.4-mini")

    local_default = str(cfg.chat.local_models.default_chat_model or "").strip()
    if local_default:
        candidates.append(f"local:{local_default}")

    ragweld_base = str(cfg.training.ragweld_agent_base_model or "").strip()
    if ragweld_base:
        candidates.append(f"ragweld:{ragweld_base}")

    for model in candidates:
        if not _is_allowed_branch_synthetic_model(model):
            continue
        try:
            _ = resolve_synthetic_route(cfg=cfg, model=model)
            return model
        except Exception:
            continue
    return None


def _path_matches_any_pattern(file_path: str, patterns: list[str]) -> bool:
    fp = (file_path or "").replace("\\", "/")
    base = fp.split("/")[-1]
    for pat in patterns:
        p = str(pat or "").strip()
        if not p:
            continue
        if fnmatch(fp, p) or fnmatch(base, p):
            return True
    return False


def _path_contains_excluded_dir(file_path: str, exclude_dirs: list[str]) -> bool:
    fp = (file_path or "").replace("\\", "/").lstrip("/")
    parts = [p for p in fp.split("/") if p]
    excluded = {str(d).strip().strip("/").lower() for d in exclude_dirs if str(d).strip()}
    return any(p.lower() in excluded for p in parts)


def _content_contains_excluded_keyword(content: str, exclude_keywords: list[str]) -> bool:
    haystack = (content or "").lower()
    for kw in exclude_keywords:
        needle = str(kw or "").strip().lower()
        if needle and needle in haystack:
            return True
    return False


def _round_robin_chunks(chunks: list[Chunk], limit: int, rng: random.Random) -> list[Chunk]:
    grouped: dict[str, list[Chunk]] = defaultdict(list)
    for ch in chunks:
        grouped[str(ch.file_path)].append(ch)
    for fp in grouped:
        grouped[fp].sort(key=lambda c: (int(c.start_line or 0), str(c.chunk_id)))

    file_paths = list(grouped.keys())
    rng.shuffle(file_paths)

    out: list[Chunk] = []
    while len(out) < limit and file_paths:
        next_round: list[str] = []
        for fp in file_paths:
            items = grouped.get(fp) or []
            if not items:
                continue
            out.append(items.pop(0))
            if items:
                next_round.append(fp)
            if len(out) >= limit:
                break
        file_paths = next_round
    return out


async def select_source_chunks(
    *,
    repo_id: str,
    cfg: TriBridConfig,
    request: SyntheticRunStartRequest,
) -> list[Chunk]:
    max_source_chunks = int(request.max_source_chunks or 150)
    candidate_limit = min(max_source_chunks * 8, 50000)

    chunks: list[Chunk] = []
    pg = PostgresClient(cfg.indexing.postgres_url)
    try:
        await pg.connect()
        chunks = await pg.list_chunks_for_repo(repo_id, limit=candidate_limit)
    except Exception:
        chunks = []
    finally:
        try:
            await pg.disconnect()
        except Exception:
            pass

    filtered: list[Chunk] = []
    for ch in chunks:
        if _path_contains_excluded_dir(ch.file_path, list(cfg.chunk_summaries.exclude_dirs or [])):
            continue
        if _path_matches_any_pattern(ch.file_path, list(cfg.chunk_summaries.exclude_patterns or [])):
            continue
        if _content_contains_excluded_keyword(ch.content, list(cfg.chunk_summaries.exclude_keywords or [])):
            continue
        filtered.append(ch)

    rng = random.Random(int(request.seed or 1337))
    return _round_robin_chunks(filtered, max_source_chunks, rng)


def _chunk_to_summary(chunk: Chunk, *, card_source: str = "deterministic") -> ChunkSummary:
    content = str(chunk.content or "")

    purpose: str | None = None
    m = _DEF_RE.search(content)
    if m:
        purpose = f"Defines {m.group(1)} {m.group(2)}."
    else:
        for line in content.splitlines():
            t = line.strip()
            if t:
                purpose = t[:240]
                break

    symbols: list[str] = []
    seen: set[str] = set()
    for tok in _TOKEN_RE.findall(content):
        if tok in seen:
            continue
        seen.add(tok)
        symbols.append(tok)
        if len(symbols) >= 24:
            break

    routes = sorted(set(_ROUTE_RE.findall(content)))[:20]
    dependencies = sorted(set(_IMPORT_RE.findall(content)))[:20]
    patterns: list[str] = []
    lower = content.lower()
    if "async def " in lower:
        patterns.append("async_io")
    if "class " in lower:
        patterns.append("oop")
    if "select " in lower or "insert " in lower or "update " in lower or "delete " in lower:
        patterns.append("sql")
    if "http" in lower or "request" in lower or "response" in lower:
        patterns.append("http")
    if "pytest" in lower or "assert " in lower:
        patterns.append("testing")

    technical_details = f"Symbols: {', '.join(symbols[:12])}" if symbols else None
    domain_concepts = symbols[:12]

    return ChunkSummary(
        chunk_id=chunk.chunk_id,
        file_path=chunk.file_path,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        purpose=purpose,
        symbols=symbols,
        technical_details=technical_details,
        domain_concepts=domain_concepts,
        routes=routes,
        dependencies=dependencies,
        patterns=patterns,
        card_source="llm" if str(card_source).lower() == "llm" else "deterministic",
        card_score=None,
    )


def _infer_source_kind(file_path: str, content: str) -> str:
    fp = str(file_path or "").lower()
    if fp.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".c", ".cpp", ".cs")):
        return "code"
    if any(tok in fp for tok in ("transcript", "oversight", "hearing", "deposition", "images-")):
        return "transcript"
    if any(tok in fp for tok in (".md", ".txt", ".rst", ".adoc", ".pdf")):
        return "document"
    if re.search(r"\b(q:|a:|testimony|witness|exhibit)\b", str(content or "").lower()):
        return "transcript"
    return "document"


def _clean_llm_json_payload(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return raw
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", raw)
        raw = raw[:-3].strip() if raw.endswith("```") else raw
    if raw.startswith("["):
        end = raw.rfind("]")
        if end >= 0:
            return raw[: end + 1]
    if raw.startswith("{"):
        end = raw.rfind("}")
        if end >= 0:
            return raw[: end + 1]
    arr_start = raw.find("[")
    arr_end = raw.rfind("]")
    if arr_start >= 0 and arr_end > arr_start:
        return raw[arr_start : arr_end + 1]
    obj_start = raw.find("{")
    obj_end = raw.rfind("}")
    if obj_start >= 0 and obj_end > obj_start:
        return raw[obj_start : obj_end + 1]
    return raw


def _normalize_eval_candidate_payload(parsed: Any) -> list[dict[str, Any]]:
    """Normalize varied model JSON payloads into a list of row objects."""
    if isinstance(parsed, dict):
        maybe_rows = parsed.get("items")
        if isinstance(maybe_rows, list):
            parsed = maybe_rows
        elif "question" in parsed:
            # Some models return a single row object instead of an array.
            parsed = [parsed]
    if not isinstance(parsed, list):
        return []
    return [row for row in parsed if isinstance(row, dict)]


def _fallback_eval_candidates_for_chunk(
    *,
    chunk: Chunk,
    pairs_per_source: int,
    include_expected_answer: bool,
) -> list[dict[str, str]]:
    file_path = str(chunk.file_path or "").strip()
    if not file_path:
        return []

    lines = [ln.strip() for ln in str(chunk.content or "").splitlines() if ln.strip()]
    if not lines:
        return []

    max_rows = max(1, int(pairs_per_source or 1))
    out: list[dict[str, str]] = []
    file_name = Path(file_path).name or "source file"

    for idx in range(min(max_rows, len(lines))):
        evidence_quote = lines[idx][:200]
        if not evidence_quote:
            continue
        question = f'In "{file_name}", what does this line state: "{evidence_quote[:80]}"?'
        row: dict[str, str] = {
            "question": question[:180],
            "evidence_quote": evidence_quote,
        }
        if include_expected_answer:
            row["expected_answer"] = evidence_quote[:400]
        else:
            row["expected_answer"] = ""
        out.append(row)
    return out


async def _generate_eval_candidates_for_chunk(
    *,
    cfg: TriBridConfig,
    route: ProviderRoute,
    chunk: Chunk,
    pairs_per_source: int,
    include_expected_answer: bool,
) -> list[dict[str, str]]:
    file_path = str(chunk.file_path or "")
    if not file_path:
        return []

    gen_cfg = cfg.synthetic.generator
    source_excerpt = "\n".join((chunk.content or "").splitlines()[:gen_cfg.source_excerpt_max_lines])
    source_kind = _infer_source_kind(file_path, source_excerpt)
    answer_mode = "required" if include_expected_answer else "optional"

    system_prompt = (
        "You generate high-quality retrieval evaluation rows grounded to one source file. "
        "Return JSON only. Output must be an array of objects with keys: question, expected_answer, evidence_quote. "
        "Questions must be specific, discriminative, and answerable from the source excerpt. "
        "Do not use generic coding-template phrasing like 'What does X implement?' or 'Where should I edit logic?'."
    )
    user_message = (
        f"Generate exactly {max(1, int(pairs_per_source))} rows.\\n"
        f"SOURCE_KIND: {source_kind}\\n"
        f"SOURCE_FILE_PATH: {file_path}\\n"
        f"EXPECTED_ANSWER_MODE: {answer_mode}\\n"
        "Rules:\\n"
        "- Each question must target factual content present in SOURCE_EXCERPT\\n"
        "- Use concrete entities, events, claims, or APIs from the text\\n"
        "- Keep question length <= 180 chars\\n"
        "- expected_answer must be concise and directly supported by SOURCE_EXCERPT\\n"
        "- evidence_quote should be a short supporting quote <= 200 chars\\n"
        "- JSON only\\n"
        f"SOURCE_EXCERPT:\\n{source_excerpt}"
    )

    response = await generate_chat_text(
        route=route,
        openrouter_cfg=cfg.chat.openrouter,
        system_prompt=system_prompt,
        user_message=user_message,
        images=[],
        image_detail="auto",
        temperature=gen_cfg.temperature,
        max_tokens=gen_cfg.max_tokens,
        context_text=source_excerpt,
        context_chunks=[],
        timeout_s=float(cfg.generation.gen_timeout or 60),
    )

    payload = _clean_llm_json_payload(response.text)
    parsed = json.loads(payload)
    rows: list[dict[str, str]] = []
    for item in _normalize_eval_candidate_payload(parsed):
        question = str(item.get("question") or "").strip()
        expected_answer = str(item.get("expected_answer") or "").strip()
        evidence_quote = str(item.get("evidence_quote") or "").strip()
        if not question:
            continue
        if "what does" in question.lower() and "implement" in question.lower():
            continue
        if "where should i edit" in question.lower():
            continue
        rows.append(
            {
                "question": question[:gen_cfg.question_max_chars],
                "expected_answer": expected_answer[:gen_cfg.expected_answer_max_chars] if expected_answer else "",
                "evidence_quote": evidence_quote[:gen_cfg.evidence_quote_max_chars] if evidence_quote else "",
            }
        )
    return rows


def _strict_bool_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value) == 1.0:
            return True
        if float(value) == 0.0:
            return False
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no", ""}:
            return False
    return False


async def _judge_eval_item(
    *,
    cfg: TriBridConfig,
    route: ProviderRoute,
    item: EvalDatasetItem,
    source_excerpt: str,
    source_file_path: str,
    threshold: float,
) -> tuple[float, bool, str]:
    system_prompt = str(cfg.system_prompts.synthetic_judge or "").strip()
    if not system_prompt:
        system_prompt = "Return JSON only with score (0-10), keep (bool), reason (short)."

    payload = {
        "question": item.question,
        "expected_paths": list(item.expected_paths or []),
        "expected_answer": item.expected_answer,
        "source_file_path": source_file_path,
        "source_excerpt": source_excerpt[:2500],
    }
    user_message = json.dumps(payload, ensure_ascii=False)

    judge_cfg = cfg.synthetic.judge
    response = await generate_chat_text(
        route=route,
        openrouter_cfg=cfg.chat.openrouter,
        system_prompt=system_prompt,
        user_message=user_message,
        images=[],
        image_detail="auto",
        temperature=judge_cfg.temperature,
        max_tokens=judge_cfg.max_tokens,
        context_text=source_excerpt[:2500],
        context_chunks=[],
        timeout_s=float(cfg.generation.gen_timeout or 60),
    )

    parsed = json.loads(_clean_llm_json_payload(response.text))
    if not isinstance(parsed, dict):
        return 0.0, False, "judge returned non-object"

    score_raw = parsed.get("score")
    score = 0.0
    if isinstance(score_raw, (int, float, str)):
        try:
            score = float(score_raw)
        except Exception:
            score = 0.0
    score = max(0.0, min(10.0, score))
    keep_flag = _strict_bool_flag(parsed.get("keep", False))
    reason = str(parsed.get("reason") or "").strip()[:200]
    keep = bool(keep_flag and score >= float(threshold))
    return score, keep, reason


async def _make_eval_items_with_llm(
    *,
    cfg: TriBridConfig,
    generator_route: ProviderRoute,
    judge_route: ProviderRoute,
    chunks: list[Chunk],
    pairs_per_source: int,
    max_pairs: int,
    include_expected_answer: bool,
    include_tags: bool,
    curate_enabled: bool,
    curate_threshold: float,
    summary: SyntheticRunSummary,
) -> tuple[list[EvalDatasetItem], int, int, float | None]:
    generated_rows: list[tuple[EvalDatasetItem, Chunk]] = []
    generator_failed = False

    for ch in chunks:
        if len(generated_rows) >= max_pairs:
            break
        if generator_failed:
            candidates = _fallback_eval_candidates_for_chunk(
                chunk=ch,
                pairs_per_source=max(1, pairs_per_source),
                include_expected_answer=include_expected_answer,
            )
        else:
            try:
                candidates = await _generate_eval_candidates_for_chunk(
                    cfg=cfg,
                    route=generator_route,
                    chunk=ch,
                    pairs_per_source=max(1, pairs_per_source),
                    include_expected_answer=include_expected_answer,
                )
            except Exception as gen_exc:
                if cfg.synthetic.generator.fail_on_error:
                    raise RuntimeError(
                        f"Generator LLM unreachable: {gen_exc}"
                    ) from gen_exc
                generator_failed = True
                if not summary.degradation.generator_fallback_used:
                    summary.degradation.generator_fallback_used = True
                    summary.degradation.degraded = True
                    summary.degradation.reasons.append(
                        f"Generator LLM failed ({type(gen_exc).__name__}); fell back to deterministic extraction."
                    )
                candidates = _fallback_eval_candidates_for_chunk(
                    chunk=ch,
                    pairs_per_source=max(1, pairs_per_source),
                    include_expected_answer=include_expected_answer,
                )
        if not candidates:
            candidates = _fallback_eval_candidates_for_chunk(
                chunk=ch,
                pairs_per_source=max(1, pairs_per_source),
                include_expected_answer=include_expected_answer,
            )

        file_path = str(ch.file_path or "").strip()
        if not file_path:
            continue
        layer = infer_layer_from_path(file_path)
        for row in candidates:
            tags = ["synthetic", f"layer:{layer}", "source:llm"] if include_tags else []
            expected_answer = row.get("expected_answer") if include_expected_answer else None
            if include_expected_answer and not str(expected_answer or "").strip():
                eq = str(row.get("evidence_quote") or "").strip()
                expected_answer = eq if eq else None
            item = EvalDatasetItem(
                question=str(row.get("question") or "").strip(),
                expected_paths=[file_path],
                expected_answer=(str(expected_answer).strip() if expected_answer else None),
                tags=tags,
            )
            generated_rows.append((item, ch))
            if len(generated_rows) >= max_pairs:
                break

    curated_in = len(generated_rows)
    if not curate_enabled:
        return [item for item, _ch in generated_rows], curated_in, 0, None

    kept: list[EvalDatasetItem] = []
    curated_out = 0
    scores: list[float] = []
    threshold = float(curate_threshold)
    judge_failed = False

    for item, ch in generated_rows:
        excerpt = "\n".join((ch.content or "").splitlines()[:cfg.synthetic.generator.source_excerpt_max_lines])
        if judge_failed:
            score = float(threshold)
            keep = True
        else:
            try:
                score, keep, _reason = await _judge_eval_item(
                    cfg=cfg,
                    route=judge_route,
                    item=item,
                    source_excerpt=excerpt,
                    source_file_path=str(ch.file_path or ""),
                    threshold=threshold,
                )
            except Exception as judge_exc:
                if cfg.synthetic.judge.fail_on_error:
                    raise RuntimeError(
                        f"Judge LLM unreachable: {judge_exc}"
                    ) from judge_exc
                judge_failed = True
                if not summary.degradation.judge_fallback_used:
                    summary.degradation.judge_fallback_used = True
                    summary.degradation.degraded = True
                    summary.degradation.reasons.append(
                        f"Judge LLM failed ({type(judge_exc).__name__}); auto-passing all remaining items."
                    )
                score = float(threshold)
                keep = True
        scores.append(score)
        if keep:
            kept.append(item)
        else:
            curated_out += 1

    avg = float(sum(scores) / len(scores)) if scores else None
    return kept, curated_in, curated_out, avg


def _derive_keywords(summaries: list[ChunkSummary], max_keywords: int = 80) -> list[str]:
    counter: Counter[str] = Counter()
    for s in summaries:
        for bucket in (s.symbols, s.domain_concepts, s.dependencies, s.patterns):
            for item in bucket or []:
                tok = str(item).strip().lower()
                if len(tok) < 3:
                    continue
                counter[tok] += 1
        for route in s.routes or []:
            for tok in route.replace("/", " ").replace("-", " ").split():
                t = tok.strip().lower()
                if len(t) >= 3:
                    counter[t] += 1
        stem = Path(str(s.file_path or "")).stem.strip().lower()
        if len(stem) >= 3:
            counter[stem] += 1
    items = sorted(counter.items(), key=lambda x: (-x[1], x[0]))
    return [tok for tok, _n in items[:max_keywords]]


def _build_triplets(
    *,
    eval_items: list[EvalDatasetItem],
    candidate_paths: list[str],
    max_pairs: int,
) -> list[dict[str, str]]:
    all_paths = [str(p).strip() for p in candidate_paths if str(p).strip()]
    out: list[dict[str, str]] = []
    for item in eval_items:
        positive = str((item.expected_paths or [""])[0]).strip()
        if not positive:
            continue
        parent = str(Path(positive).parent)
        expected = {str(p).strip() for p in (item.expected_paths or []) if str(p).strip()}
        same_dir = [p for p in all_paths if p not in expected and str(Path(p).parent) == parent]
        fallback = [p for p in all_paths if p not in expected]
        negative = (same_dir[0] if same_dir else (fallback[0] if fallback else ""))
        if not negative:
            continue
        out.append({"query": item.question, "positive": positive, "negative": negative})
        if len(out) >= max_pairs:
            break
    return out


def _autotune_patch(
    *,
    cfg: TriBridConfig,
    eval_items: list[EvalDatasetItem],
    keywords: list[str],
) -> dict[str, Any]:
    layer_counts: Counter[str] = Counter()
    for item in eval_items:
        for path in item.expected_paths or []:
            layer_counts[infer_layer_from_path(path)] += 1

    patch: dict[str, Any] = {}
    layer_patch: dict[str, float] = {}

    if layer_counts.get("gui", 0) > 0:
        layer_patch["gui"] = min(0.5, float(cfg.layer_bonus.gui) + 0.02)
    if layer_counts.get("retrieval", 0) > 0:
        layer_patch["retrieval"] = min(0.5, float(cfg.layer_bonus.retrieval) + 0.03)
    if layer_counts.get("indexing", 0) > 0:
        layer_patch["indexer"] = min(0.5, float(cfg.layer_bonus.indexer) + 0.02)
    if layer_patch:
        patch["layer_bonus"] = layer_patch

    patch["scoring"] = {
        "filename_boost_exact": min(5.0, float(cfg.scoring.filename_boost_exact) + 0.1),
        "filename_boost_partial": min(3.0, float(cfg.scoring.filename_boost_partial) + 0.05),
    }

    if keywords:
        patch["keywords"] = {
            "keywords_boost": min(3.0, max(1.0, float(cfg.keywords.keywords_boost))),
        }

    return patch


async def generate_recipe_payloads(
    *,
    recipe: SyntheticRecipeKind,
    cfg: TriBridConfig,
    request: SyntheticRunStartRequest,
    chunks: list[Chunk],
) -> tuple[dict[SyntheticArtifactKind, Any], SyntheticRunSummary]:
    generator_route = resolve_synthetic_route(cfg=cfg, model=str(request.generator_model or ""))
    judge_route = resolve_synthetic_route(cfg=cfg, model=str(request.judge_model or ""))
    _ = (generator_route, judge_route)

    summary = SyntheticRunSummary()
    summaries = [_chunk_to_summary(ch, card_source="deterministic") for ch in chunks]

    eval_items: list[EvalDatasetItem] = []
    curated_in = 0
    curated_out = 0
    avg_judge_score: float | None = None

    if recipe in {"eval_dataset", "triplets", "autotune_retrieval", "full_stack"}:
        eval_items, curated_in, curated_out, avg_judge_score = await _make_eval_items_with_llm(
            cfg=cfg,
            generator_route=generator_route,
            judge_route=judge_route,
            chunks=chunks,
            pairs_per_source=int(request.pairs_per_source or 1),
            max_pairs=int(request.max_pairs or 150),
            include_expected_answer=bool(request.include_expected_answer),
            include_tags=bool(request.include_tags),
            curate_enabled=bool(request.curate_enabled),
            curate_threshold=float(request.curate_threshold or 7.0),
            summary=summary,
        )

    keywords = _derive_keywords(summaries, max_keywords=int(cfg.keywords.keywords_max_per_repo or 80))
    all_paths = [str(ch.file_path or "") for ch in chunks if str(ch.file_path or "").strip()]
    triplets = _build_triplets(
        eval_items=eval_items,
        candidate_paths=all_paths,
        max_pairs=int(request.max_pairs or 150),
    )
    patch = _autotune_patch(cfg=cfg, eval_items=eval_items, keywords=keywords)

    artifacts: dict[SyntheticArtifactKind, Any] = {}
    if recipe in {"semantic_cards", "full_stack"}:
        artifacts["semantic_cards_jsonl"] = summaries
    if recipe in {"eval_dataset", "triplets", "autotune_retrieval", "full_stack"}:
        artifacts["eval_dataset_json"] = eval_items
    if recipe in {"keywords", "full_stack"}:
        artifacts["keywords_json"] = keywords
    if recipe in {"triplets", "full_stack"}:
        artifacts["triplets_jsonl"] = triplets
    if recipe in {"autotune_retrieval", "full_stack"}:
        artifacts["config_patch_json"] = patch

    if recipe == "autotune_retrieval":
        report = "Autotune patch generated from synthetic evaluation data.\n"
    else:
        report = (
            f"Synthetic run generated from {len(chunks)} source chunks.\n"
            f"Summaries: {len(summaries)}\n"
            f"Eval items: {len(eval_items)}\n"
            f"Triplets: {len(triplets)}\n"
            f"Keywords: {len(keywords)}\n"
            f"Curated in: {curated_in}\n"
            f"Curated out: {curated_out}\n"
        )
    artifacts["report_md"] = report

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
