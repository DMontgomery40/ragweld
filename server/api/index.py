from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.chunker import Chunker
from server.indexing.embedder import Embedder
from server.indexing.graph_builder import GraphBuilder
from server.indexing.loader import FileLoader
from server.models.graph import Entity, Relationship
from server.models.index import IndexRequest, IndexStats, IndexStatus
from server.models.tribrid_config_model import CorpusScope, VocabPreviewResponse
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(tags=["index"])

_STATUS: dict[str, IndexStatus] = {}
_STATS: dict[str, IndexStats] = {}
_TASKS: dict[str, asyncio.Task[None]] = {}
_EVENT_QUEUES: dict[str, asyncio.Queue[dict[str, Any]]] = {}
_LAST_STARTED_REPO: str | None = None

_SEM_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,63}")
_SEM_STOPWORDS: set[str] = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "return",
    "true",
    "false",
    "none",
    "null",
    "import",
    "export",
    "class",
    "function",
    "const",
    "let",
    "var",
    "async",
    "await",
}


def _emit_event(
    queue: asyncio.Queue[dict[str, Any]] | None,
    event: dict[str, Any],
    *,
    drop_oldest: bool = False,
    guarantee: bool = False,
) -> None:
    """Best-effort event emission without blocking indexing.

    Indexing can run for many thousands of files. If no SSE client is consuming
    events, a bounded asyncio.Queue will fill and `await queue.put(...)` will
    deadlock the indexing task. We always emit events non-blockingly and drop
    old events when requested.
    """
    if queue is None:
        return

    if guarantee:
        # Ensure this event is delivered by dropping older events until there is room.
        while True:
            try:
                queue.put_nowait(event)
                return
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    return

    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        if not drop_oldest:
            return
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            return


def _extract_semantic_concepts(text: str, *, min_len: int, max_terms: int) -> list[str]:
    """Deterministic concept extraction (fallback for tests/offline)."""
    if max_terms <= 0:
        return []
    toks = [t.lower() for t in _SEM_TOKEN_RE.findall(text or "")]
    freq: dict[str, int] = defaultdict(int)
    for t in toks:
        if len(t) < min_len:
            continue
        if t in _SEM_STOPWORDS:
            continue
        freq[t] += 1
    # Stable ordering: by frequency desc, then token asc.
    items = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [k for k, _v in items[:max_terms]]


async def _extract_semantic_kg_llm(
    text: str,
    *,
    prompt: str,
    model: str,
    timeout_s: float,
) -> tuple[list[str], list[dict[str, str]]]:
    """LLM-assisted semantic KG extraction (best-effort).

    Returns:
    - concepts: list[str]
    - relations: list[dict] with keys: source, target, relation_type
    """
    try:
        from openai import AsyncOpenAI
    except Exception:
        return ([], [])

    client = AsyncOpenAI()
    resp = await client.responses.create(
        model=model,
        instructions=prompt,
        input=text,
        temperature=0,
        text={"format": {"type": "json_object"}},
        timeout=float(timeout_s),
    )
    raw = str(getattr(resp, "output_text", "") or "").strip()
    if not raw:
        return ([], [])
    try:
        data = json.loads(raw)
    except Exception:
        return ([], [])

    concepts_raw = data.get("concepts") if isinstance(data, dict) else None
    relations_raw = data.get("relations") if isinstance(data, dict) else None
    concepts: list[str] = [str(x) for x in (concepts_raw or [])] if isinstance(concepts_raw, list) else []
    relations: list[dict[str, str]] = []
    if isinstance(relations_raw, list):
        for r in relations_raw:
            if isinstance(r, dict):
                relations.append({str(k): str(v) for k, v in r.items()})
    return (concepts, relations)


async def _run_index(
    repo_id: str,
    repo_path: str,
    force_reindex: bool,
    *,
    event_queue: asyncio.Queue[dict[str, Any]] | None = None,
) -> IndexStats:
    cfg = await load_scoped_config(repo_id=repo_id)

    if not force_reindex and repo_id in _STATS:
        return _STATS[repo_id]

    # Build ignore patterns from config
    ignore_patterns: list[str] = []
    exts = (cfg.indexing.index_excluded_exts or "").split(",")
    for ext in exts:
        ext = ext.strip()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        ignore_patterns.append(f"*{ext}")

    chunker = Chunker(cfg.chunking)
    # Enforce a strict max file size before reading/chunking.
    # LAW sources:
    # - cfg.chunking.max_indexable_file_size (bytes)
    # - cfg.indexing.index_max_file_size_mb (MB)
    max_indexable_bytes = min(
        int(cfg.chunking.max_indexable_file_size),
        int(cfg.indexing.index_max_file_size_mb) * 1024 * 1024,
    )
    skip_dense = bool(int(cfg.indexing.skip_dense or 0) == 1)
    embedder = None if skip_dense else Embedder(cfg.embedding)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    await postgres.upsert_corpus(repo_id, name=repo_id, root_path=repo_path)

    # Corpus-level exclude paths (stored in Postgres corpora.meta.exclude_paths)
    extra_gitignore_patterns: list[str] = []
    try:
        corpus = await postgres.get_corpus(repo_id)
        meta = (corpus.get("meta") or {}) if corpus else {}
        raw = meta.get("exclude_paths") if isinstance(meta, dict) else None
        if isinstance(raw, list):
            extra_gitignore_patterns = [str(x).strip() for x in raw if str(x).strip()]
    except Exception:
        extra_gitignore_patterns = []

    loader = FileLoader(ignore_patterns=ignore_patterns, extra_gitignore_patterns=extra_gitignore_patterns)

    neo4j: Neo4jClient | None = None
    graph_builder: GraphBuilder | None = None
    try:
        if cfg.graph_indexing.enabled:
            db_name = cfg.graph_storage.resolve_database(repo_id)
            neo4j = Neo4jClient(
                cfg.graph_storage.neo4j_uri,
                cfg.graph_storage.neo4j_user,
                cfg.graph_storage.neo4j_password,
                database=db_name,
            )
            await neo4j.connect()
            graph_builder = GraphBuilder(neo4j)

            # Lexical chunk vector index (Neo4j native vector indexes)
            if cfg.graph_indexing.build_lexical_graph and cfg.graph_indexing.store_chunk_embeddings and not skip_dense:
                try:
                    assert embedder is not None
                    await neo4j.ensure_vector_index(
                        index_name=cfg.graph_indexing.chunk_vector_index_name,
                        label="Chunk",
                        embedding_property=cfg.graph_indexing.chunk_embedding_property,
                        dimensions=int(embedder.dim),
                        similarity_function=cfg.graph_indexing.vector_similarity_function,
                        wait_online=cfg.graph_indexing.wait_vector_index_online,
                        timeout_s=float(cfg.graph_indexing.vector_index_online_timeout_s),
                    )
                except Exception:
                    # Graph indexing should never block dense/sparse indexing.
                    pass
    except Exception:
        # Graph layer is optional at runtime; vector + sparse indexing should still work.
        neo4j = None
        graph_builder = None

    total_files = 0
    total_chunks = 0
    total_tokens = 0
    file_breakdown: dict[str, int] = defaultdict(int)

    prev_status = _STATUS.get(repo_id)
    started_at = prev_status.started_at if prev_status and prev_status.started_at else datetime.now(UTC)

    # Collect file paths once so we can report progress deterministically,
    # without loading every file's contents into memory.
    file_entries = list(loader.iter_repo_files(repo_path))
    total_files = len(file_entries)

    # GraphBuilder consumes (path, content) and currently only supports Python AST.
    graph_files: list[tuple[str, str]] = []

    if force_reindex:
        await postgres.delete_chunks(repo_id)
        if neo4j is not None:
            await neo4j.delete_graph(repo_id)
        if event_queue is not None:
            _emit_event(
                event_queue,
                {"type": "log", "message": "🧹 Cleared existing index (force_reindex=1)"},
                drop_oldest=True,
            )

    # If skip_dense is enabled, ensure no stale embeddings remain from previous runs.
    # This makes graph-only / sparse-only workflows deterministic.
    if skip_dense:
        deleted = await postgres.delete_embeddings(repo_id)
        await postgres.update_corpus_embedding_meta(repo_id, model="", dimensions=0)
        if event_queue is not None:
            _emit_event(
                event_queue,
                {"type": "log", "message": f"⚡ skip_dense=1 → skipping embeddings (cleared {deleted} existing vectors)"},
                drop_oldest=True,
            )

    semantic_budget = int(cfg.graph_indexing.semantic_kg_max_chunks) if cfg.graph_indexing.semantic_kg_enabled else 0
    semantic_processed = 0

    for idx, (rel_path, abs_path) in enumerate(file_entries, start=1):
        ext = "." + rel_path.split(".")[-1] if "." in rel_path else ""
        file_breakdown[ext] += 1

        _STATUS[repo_id] = IndexStatus(
            repo_id=repo_id,
            status="indexing",
            progress=idx / max(1, total_files),
            current_file=rel_path,
            started_at=started_at,
        )
        if event_queue is not None:
            _emit_event(
                event_queue,
                {"type": "progress", "percent": int((_STATUS[repo_id].progress) * 100), "message": rel_path},
                drop_oldest=True,
            )

        try:
            size_bytes = int(abs_path.stat().st_size)
        except Exception:
            size_bytes = None
        if size_bytes is not None and size_bytes > max_indexable_bytes:
            if event_queue is not None:
                _emit_event(
                    event_queue,
                    {
                        "type": "log",
                        "message": (
                            f"⏭️ Skipping large file ({size_bytes} bytes > {max_indexable_bytes} bytes): {rel_path}"
                        ),
                    },
                    drop_oldest=True,
                )
            continue

        try:
            content = abs_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # Postgres TEXT cannot store NUL bytes; treat as binary and skip.
        if "\x00" in content:
            continue

        if graph_builder is not None and rel_path.lower().endswith(".py"):
            graph_files.append((rel_path, content))

        chunks = chunker.chunk_file(rel_path, content)
        chunks_for_semantic = chunks
        total_chunks += len(chunks)
        total_tokens += sum(int(c.token_count or 0) for c in chunks)

        if skip_dense:
            await postgres.upsert_fts(repo_id, chunks, ts_config=cfg.indexing.postgres_ts_config)
            if neo4j is not None and cfg.graph_indexing.build_lexical_graph:
                try:
                    await neo4j.upsert_document_and_chunks(
                        repo_id,
                        rel_path,
                        chunks,
                        store_embeddings=False,
                        embedding_property=cfg.graph_indexing.chunk_embedding_property,
                    )
                except Exception:
                    pass
        else:
            assert embedder is not None
            embedded = await embedder.embed_chunks(chunks)
            chunks_for_semantic = embedded
            await postgres.upsert_embeddings(repo_id, embedded)
            await postgres.upsert_fts(repo_id, embedded, ts_config=cfg.indexing.postgres_ts_config)
            if neo4j is not None and cfg.graph_indexing.build_lexical_graph:
                try:
                    await neo4j.upsert_document_and_chunks(
                        repo_id,
                        rel_path,
                        embedded,
                        store_embeddings=bool(cfg.graph_indexing.store_chunk_embeddings),
                        embedding_property=cfg.graph_indexing.chunk_embedding_property,
                    )
                except Exception:
                    pass

        # Optional semantic KG extraction (concept entities + related_to edges linked to chunk_ids).
        if (
            neo4j is not None
            and cfg.graph_indexing.build_lexical_graph
            and cfg.graph_indexing.semantic_kg_enabled
            and semantic_budget > 0
            and semantic_processed < semantic_budget
        ):
            try:
                mode = str(cfg.graph_indexing.semantic_kg_mode or "heuristic").strip().lower()
                max_terms = int(cfg.graph_indexing.semantic_kg_max_concepts_per_chunk)
                min_len = int(cfg.graph_indexing.semantic_kg_min_concept_len)
                max_rels_per_chunk = int(cfg.graph_indexing.semantic_kg_max_relations_per_chunk)
                llm_model = str(cfg.graph_indexing.semantic_kg_llm_model or "").strip() or str(cfg.generation.enrich_model)
                llm_prompt = str(cfg.system_prompts.semantic_kg_extraction or "").strip()
                llm_timeout_s = float(cfg.graph_indexing.semantic_kg_llm_timeout_s)
                llm_max_chars = int(cfg.enrichment.enrich_max_chars)

                def _norm_concept(name: str) -> str | None:
                    v = (name or "").strip().lower()
                    v = re.sub(r"[^a-z0-9_]+", "_", v).strip("_")
                    if len(v) < min_len:
                        return None
                    if v in _SEM_STOPWORDS:
                        return None
                    if not _SEM_TOKEN_RE.fullmatch(v):
                        return None
                    return v

                concept_entities: dict[str, Entity] = {}
                rels: list[Relationship] = []
                link_set: set[tuple[str, str]] = set()

                for ch in chunks_for_semantic:
                    if semantic_processed >= semantic_budget:
                        break
                    semantic_processed += 1

                    concepts_raw: list[str]
                    relations_raw: list[dict[str, str]]
                    if mode == "llm" and llm_prompt:
                        concepts_raw, relations_raw = await _extract_semantic_kg_llm(
                            (ch.content or "")[: max(0, llm_max_chars)],
                            prompt=llm_prompt,
                            model=llm_model,
                            timeout_s=llm_timeout_s,
                        )
                    else:
                        concepts_raw = _extract_semantic_concepts(ch.content, min_len=min_len, max_terms=max_terms)
                        relations_raw = []

                    concepts: list[str] = []
                    seen_concepts: set[str] = set()
                    for name in concepts_raw:
                        n = _norm_concept(name)
                        if not n or n in seen_concepts:
                            continue
                        seen_concepts.add(n)
                        concepts.append(n)
                        if len(concepts) >= max_terms:
                            break
                    if not concepts:
                        continue

                    concept_ids: list[str] = []
                    for name in concepts:
                        ent_id = GraphBuilder._stable_id(repo_id, "", "concept", name)
                        concept_ids.append(ent_id)
                        if ent_id not in concept_entities:
                            concept_entities[ent_id] = Entity(
                                entity_id=ent_id,
                                name=name,
                                entity_type="concept",
                                file_path=None,
                                description=None,
                                properties={"source": "semantic"},
                            )
                        link_set.add((ent_id, ch.chunk_id))

                    if max_rels_per_chunk > 0:
                        # LLM mode: use suggested relations if present, otherwise fall back.
                        rels_added = 0
                        if mode == "llm" and relations_raw:
                            name_to_id = {n: GraphBuilder._stable_id(repo_id, "", "concept", n) for n in concepts}
                            for r in relations_raw:
                                if rels_added >= max_rels_per_chunk:
                                    break
                                src = _norm_concept(str(r.get("source") or ""))
                                tgt = _norm_concept(str(r.get("target") or ""))
                                rel_type = str(r.get("relation_type") or "related_to").strip().lower()
                                if not src or not tgt or src == tgt:
                                    continue
                                if rel_type not in {"related_to", "references"}:
                                    continue
                                # Ensure entities exist even if relation mentions a concept not in concepts list.
                                for nm in (src, tgt):
                                    if nm not in name_to_id:
                                        eid = GraphBuilder._stable_id(repo_id, "", "concept", nm)
                                        name_to_id[nm] = eid
                                        if eid not in concept_entities:
                                            concept_entities[eid] = Entity(
                                                entity_id=eid,
                                                name=nm,
                                                entity_type="concept",
                                                file_path=None,
                                                description=None,
                                                properties={"source": "semantic", "mode": "llm"},
                                            )
                                        link_set.add((eid, ch.chunk_id))
                                rels.append(
                                    Relationship(
                                        source_id=name_to_id[src],
                                        target_id=name_to_id[tgt],
                                        relation_type=rel_type,  # type: ignore[arg-type]
                                        weight=0.7,
                                        properties={"source": "semantic", "mode": "llm"},
                                    )
                                )
                                rels_added += 1
                        # Heuristic fallback: star graph around the top concept in this chunk.
                        if rels_added == 0 and len(concept_ids) >= 2:
                            root = concept_ids[0]
                            for tgt in concept_ids[1:]:
                                rels.append(
                                    Relationship(
                                        source_id=root,
                                        target_id=tgt,
                                        relation_type="related_to",
                                        weight=0.5,
                                        properties={"source": "semantic", "mode": "heuristic"},
                                    )
                                )
                                rels_added += 1
                                if rels_added >= max_rels_per_chunk:
                                    break

                if concept_entities:
                    await neo4j.upsert_entities(repo_id, list(concept_entities.values()))
                if rels:
                    await neo4j.upsert_relationships(repo_id, rels)
                if link_set:
                    await neo4j.link_entities_to_chunks(
                        repo_id,
                        links=[{"entity_id": eid, "chunk_id": cid} for (eid, cid) in sorted(link_set)],
                    )
            except Exception:
                # Semantic KG is optional; never block baseline indexing.
                pass

    if graph_builder is not None:
        try:
            if event_queue is not None:
                _emit_event(
                    event_queue,
                    {"type": "log", "message": "🧠 Building Neo4j graph (entities + relationships)..."},
                    drop_oldest=True,
                )
            await graph_builder.build_graph_for_files(
                repo_id,
                graph_files,
                batch_size=int(cfg.indexing.indexing_batch_size),
            )
            # Link entities to chunk_ids so the graph leg can hydrate deterministically.
            if neo4j is not None and cfg.graph_indexing.build_lexical_graph:
                await neo4j.rebuild_entity_chunk_links(repo_id)
        except Exception:
            # Do not fail indexing if graph extraction is partial.
            pass

    if not skip_dense:
        assert embedder is not None
        await postgres.update_corpus_embedding_meta(repo_id, cfg.embedding.effective_model, embedder.dim)

    stats = IndexStats(
        repo_id=repo_id,
        total_files=total_files,
        total_chunks=total_chunks,
        total_tokens=total_tokens,
        embedding_model="" if skip_dense else cfg.embedding.effective_model,
        embedding_dimensions=0 if skip_dense else (embedder.dim if embedder is not None else 0),
        last_indexed=datetime.now(UTC),
        file_breakdown=dict(file_breakdown),
    )
    _STATS[repo_id] = stats
    return stats


async def _background_index_job(request: IndexRequest, queue: asyncio.Queue[dict[str, Any]]) -> None:
    repo_id = request.repo_id
    started_at = datetime.now(UTC)
    try:
        _emit_event(queue, {"type": "log", "message": f"🚀 Indexing started: {repo_id}"}, drop_oldest=True)
        await _run_index(
            repo_id,
            request.repo_path,
            request.force_reindex,
            event_queue=queue,
        )
        _STATUS[repo_id] = IndexStatus(
            repo_id=repo_id,
            status="complete",
            progress=1.0,
            current_file=None,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        _emit_event(queue, {"type": "complete", "message": "✓ Indexing complete"}, guarantee=True)
    except Exception as e:
        prev = _STATUS.get(repo_id)
        _STATUS[repo_id] = IndexStatus(
            repo_id=repo_id,
            status="error",
            progress=float(prev.progress) if prev else 0.0,
            current_file=prev.current_file if prev else None,
            error=str(e),
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        _emit_event(queue, {"type": "error", "message": str(e)}, guarantee=True)
    finally:
        _TASKS.pop(repo_id, None)


@router.post("/index", response_model=IndexStatus)
async def start_index(request: IndexRequest) -> IndexStatus:
    global _LAST_STARTED_REPO

    # If already running, return current status.
    if request.repo_id in _TASKS and request.repo_id in _STATUS:
        return _STATUS[request.repo_id]

    started_at = datetime.now(UTC)
    _STATUS[request.repo_id] = IndexStatus(
        repo_id=request.repo_id,
        status="indexing",
        progress=0.0,
        current_file=None,
        started_at=started_at,
    )

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2000)
    _EVENT_QUEUES[request.repo_id] = queue
    _LAST_STARTED_REPO = request.repo_id

    task = asyncio.create_task(_background_index_job(request, queue))
    _TASKS[request.repo_id] = task
    return _STATUS[request.repo_id]


@router.post("/index/start", response_model=IndexStatus)
async def start_index_compat(payload: dict[str, Any] | None = None) -> IndexStatus:
    """Compatibility endpoint for legacy dashboard UI.

    Expected payload: {"repo_id": "...", "repo_path": "...", "force_reindex": bool}
    """
    payload = payload or {}
    repo_id = str(payload.get("repo_id") or payload.get("repo") or "").strip()
    repo_path = str(payload.get("repo_path") or payload.get("path") or "").strip()
    if not repo_id:
        raise HTTPException(status_code=422, detail="repo_id is required")
    if not repo_path:
        # Try to resolve from corpus registry
        cfg = await load_scoped_config(repo_id=None)
        pg = PostgresClient(cfg.indexing.postgres_url)
        await pg.connect()
        corpus = await pg.get_corpus(repo_id)
        if corpus is not None:
            repo_path = str(corpus.get("path") or "")
    if not repo_path:
        raise HTTPException(status_code=422, detail="repo_path is required (or create corpus first)")
    force_reindex = bool(payload.get("force_reindex") or payload.get("force") or False)
    return await start_index(IndexRequest(repo_id=repo_id, repo_path=repo_path, force_reindex=force_reindex))


@router.get("/index/{corpus_id}/status", response_model=IndexStatus)
async def get_index_status(corpus_id: str) -> IndexStatus:
    repo_id = corpus_id
    if repo_id in _STATUS:
        return _STATUS[repo_id]
    return IndexStatus(
        repo_id=repo_id,
        status="idle",
        progress=0.0,
        current_file=None,
        error=None,
        started_at=None,
        completed_at=None,
    )


@router.get("/index/{corpus_id}/stats", response_model=IndexStats)
async def get_index_stats(corpus_id: str) -> IndexStats:
    repo_id = corpus_id
    if repo_id in _STATS:
        return _STATS[repo_id]
    # Read from Postgres (source of truth)
    cfg = await load_scoped_config(repo_id=None)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    stats = await postgres.get_index_stats(repo_id)
    if stats.total_chunks == 0:
        raise HTTPException(status_code=404, detail=f"No index found for repo_id={repo_id}")
    return stats


@router.delete("/index/{corpus_id}")
async def delete_index(corpus_id: str) -> dict[str, Any]:
    repo_id = corpus_id
    cfg = await load_scoped_config(repo_id=repo_id)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    deleted_vec = await postgres.delete_embeddings(repo_id)
    deleted_fts = await postgres.delete_fts(repo_id)
    deleted_rows = await postgres.delete_chunks(repo_id)

    try:
        db_name = cfg.graph_storage.resolve_database(repo_id)
        neo4j = Neo4jClient(
            cfg.graph_storage.neo4j_uri,
            cfg.graph_storage.neo4j_user,
            cfg.graph_storage.neo4j_password,
            database=db_name,
        )
        await neo4j.connect()
        await neo4j.delete_graph(repo_id)
        await neo4j.disconnect()
    except Exception:
        # Graph layer optional
        pass
    _STATUS.pop(repo_id, None)
    _STATS.pop(repo_id, None)
    return {
        "ok": True,
        "deleted_chunks": deleted_rows,
        "deleted_embeddings": deleted_vec,
        "deleted_fts": deleted_fts,
    }


@router.get("/index/vocab-preview", response_model=VocabPreviewResponse)
async def get_vocab_preview(
    scope: CorpusScope = Depends(),
    top_n: int = Query(default=100, ge=10, le=500, description="Number of top terms to return"),
) -> VocabPreviewResponse:
    """Return a vocabulary preview from Postgres FTS (chunks.tsv).

    This powers the Indexing tab “Vocabulary Preview” tooling.
    """
    repo_id = (scope.resolved_repo_id or "").strip()
    if not repo_id:
        raise HTTPException(status_code=400, detail="Missing corpus_id (or legacy repo/repo_id) query parameter")

    cfg = await load_scoped_config(repo_id=repo_id)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    terms, total_terms = await postgres.vocab_preview(repo_id, top_n=top_n)

    # Config-derived Postgres text search configuration label (LAW).
    tokenizer = str(cfg.indexing.bm25_tokenizer or "").strip() or "stemmer"
    ts_config = cfg.indexing.postgres_ts_config

    return VocabPreviewResponse(
        repo_id=repo_id,
        top_n=int(top_n),
        tokenizer=tokenizer,
        stemmer_lang=str(cfg.indexing.bm25_stemmer_lang or "") or None,
        stopwords_lang=str(cfg.indexing.bm25_stopwords_lang or "") or None,
        ts_config=ts_config,
        total_terms=int(total_terms),
        terms=terms,
    )


@router.get("/stream/operations/index")
async def stream_index_operation(scope: CorpusScope = Depends()) -> StreamingResponse:
    """SSE stream for indexing logs/progress (TerminalService.streamOperation compatibility)."""
    repo_id = (scope.resolved_repo_id or _LAST_STARTED_REPO or "").strip()
    if not repo_id:
        raise HTTPException(status_code=400, detail="Missing repo query parameter")
    if repo_id not in _EVENT_QUEUES:
        raise HTTPException(status_code=404, detail=f"No active stream for repo_id={repo_id}")

    queue = _EVENT_QUEUES[repo_id]

    async def _gen() -> AsyncGenerator[str, None]:
        # Immediately emit a status snapshot
        if repo_id in _STATUS:
            s = _STATUS[repo_id]
            yield f"data: {json.dumps({'type': 'progress', 'percent': int(s.progress * 100), 'message': s.current_file or ''})}\n\n"
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") in {"complete", "error"}:
                break

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
