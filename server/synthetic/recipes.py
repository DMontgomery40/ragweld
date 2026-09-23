from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Protocol, TypeVar

from server.chat.provider_router import ProviderRoute, select_provider_route
from server.db.postgres import PostgresClient
from server.models.index import (
    Chunk,
)
from server.models.tribrid_config_model import (
    ChunkSummary,
    EvalDatasetItem,
    SyntheticRunStartRequest,
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
    return "litellm" if raw.startswith("litellm:") else "litellm_alias"


def resolve_synthetic_route(*, cfg: TriBridConfig, model: str) -> ProviderRoute:
    model_name = str(model or "").strip()
    if not model_name:
        raise RuntimeError("Missing model name")
    try:
        return select_provider_route(config=cfg, model_override=model_name)
    except Exception as e:
        category = synthetic_generation_model_category(model_name)
        raise RuntimeError(f"Unable to resolve model route for {model_name!r} (category={category}): {e}") from e



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


class _Positioned(Protocol):
    @property
    def chunk_id(self) -> str: ...

    @property
    def file_path(self) -> str: ...

    @property
    def start_line(self) -> int: ...


_P = TypeVar("_P", bound=_Positioned)


def _spread_order(count: int, rng: random.Random) -> list[int]:
    """Positions ``0..count-1`` ordered so every prefix is spread across the whole range.

    A base-2 radical-inverse (van der Corput) sequence rotated by a seeded offset: the first
    draw lands at a seeded point, the next in the opposite half, then the remaining quarters,
    and so on. However few chunks a file contributes, they come from across the document
    instead of its head (cover page, front matter).
    """
    if count <= 0:
        return []
    bits = max(1, (count - 1).bit_length())
    size = 1 << bits
    offset = rng.random()
    order: list[int] = []
    seen: set[int] = set()
    for k in range(size):
        inverse = int(format(k, f"0{bits}b")[::-1], 2) / size
        position = min(count - 1, int(((inverse + offset) % 1.0) * count))
        if position not in seen:
            seen.add(position)
            order.append(position)
    order.extend(position for position in range(count) if position not in seen)
    return order


def _sample_order(chunks: Sequence[_P], rng: random.Random) -> list[_P]:
    """Seeded whole-corpus draw order: files interleaved round-robin in a seeded order, each
    file's chunks in a position-spread order (see ``_spread_order``)."""
    grouped: dict[str, list[_P]] = defaultdict(list)
    for ch in chunks:
        grouped[str(ch.file_path)].append(ch)
    queues: dict[str, list[_P]] = {}
    for fp in sorted(grouped):
        items = sorted(grouped[fp], key=lambda c: (int(c.start_line or 0), str(c.chunk_id)))
        queues[fp] = [items[position] for position in _spread_order(len(items), rng)]

    file_paths = sorted(queues)
    rng.shuffle(file_paths)
    cursors = dict.fromkeys(file_paths, 0)
    out: list[_P] = []
    active = file_paths
    while active:
        next_round: list[str] = []
        for fp in active:
            queue = queues[fp]
            cursor = cursors[fp]
            out.append(queue[cursor])
            cursors[fp] = cursor + 1
            if cursor + 1 < len(queue):
                next_round.append(fp)
        active = next_round
    return out


def _round_robin_chunks(chunks: Sequence[_P], limit: int, rng: random.Random) -> list[_P]:
    return _sample_order(chunks, rng)[: max(0, int(limit))]


async def select_source_chunks(
    *,
    repo_id: str,
    cfg: TriBridConfig,
    request: SyntheticRunStartRequest,
) -> list[Chunk]:
    """Seeded source chunks drawn from the whole corpus (every file, every position in it).

    Positions are listed without content so no file or document head is truncated away;
    content is fetched in draw order and the keyword exclusions apply to it.
    """
    max_source_chunks = int(request.max_source_chunks or 150)
    exclude_dirs = list(cfg.chunk_summaries.exclude_dirs or [])
    exclude_patterns = list(cfg.chunk_summaries.exclude_patterns or [])
    exclude_keywords = list(cfg.chunk_summaries.exclude_keywords or [])

    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        positions = await pg.list_chunk_positions(repo_id)
        eligible = [
            p
            for p in positions
            if not _path_contains_excluded_dir(p.file_path, exclude_dirs)
            and not _path_matches_any_pattern(p.file_path, exclude_patterns)
        ]
        ordered = _sample_order(eligible, random.Random(int(request.seed or 1337)))
        selected: list[Chunk] = []
        batch_size = max(1, max_source_chunks)
        for start in range(0, len(ordered), batch_size):
            batch = await pg.get_chunks(repo_id, [p.chunk_id for p in ordered[start : start + batch_size]])
            for ch in batch:
                if _content_contains_excluded_keyword(ch.content, exclude_keywords):
                    continue
                selected.append(ch)
                if len(selected) >= max_source_chunks:
                    return selected
        return selected
    finally:
        await pg.disconnect()


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
