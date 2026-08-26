from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import logging
import multiprocessing
import os
import platform
import queue
import re
import sys
import threading
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from server.api.dependency_errors import (
    dependency_unavailable_http_exception,
    raise_postgres_unavailable_if_applicable,
)
from server.chat.provider_router import ProviderRoute, select_provider_route
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.chunker import Chunker
from server.indexing.embedder import Embedder, configure_postgres_embedding_cache_backend
from server.indexing.generations import (
    DeletionIncompleteError,
    FenceClaim,
    GenerationManifest,
    IndexFenceCorruptError,
    IndexFenceHeldError,
    IndexFenceLostError,
    IndexRunFence,
    PersistedStateCorruptError,
    ReclaimEntry,
    TombstoneCleanupError,
    drop_tombstoned_stores,
    fence_owner,
    generation_from_corpus_row,
    heartbeat_interval_seconds,
    qdrant_collection_of,
    reclaim_backlog_from_meta,
    reclaim_stale_run,
    staging_repo_id,
)
from server.indexing.loader import FileLoader
from server.indexing.official_graphrag import (
    extract_semantic_kg_with_graphrag,
    write_lexical_graph_with_graphrag,
)
from server.indexing.text_extractors import extract_text_for_path, extraction_method_for_path
from server.models.index import (
    Chunk,
    IndexDeletionIncompleteResponse,
    IndexEstimate,
    IndexFenceCorruptDetail,
    IndexRequest,
    IndexRunConflictDetail,
    IndexRunConflictResponse,
    IndexRunEvent,
    IndexRunSummary,
    IndexStats,
    IndexStatus,
    PersistedStateCorruptResponse,
)
from server.models.tribrid_config_model import (
    CorpusScope,
    DashboardEmbeddingConfigSummary,
    DashboardIndexCosts,
    DashboardIndexStatsResponse,
    DashboardIndexStatusMetadata,
    DashboardIndexStatusResponse,
    DashboardIndexStorageBreakdown,
    DependencyUnavailableResponse,
    TriBridConfig,
)
from server.observability.metrics import (
    CHUNKS_INDEXED_CURRENT,
    GRAPH_ENTITIES_CURRENT,
    GRAPH_RELATIONSHIPS_CURRENT,
    INDEX_CHUNKS_CREATED_TOTAL,
    INDEX_DURATION_SECONDS,
    INDEX_ERRORS_TOTAL,
    INDEX_FILES_PROCESSED_TOTAL,
    INDEX_RUNS_TOTAL,
    INDEX_STAGE_ERRORS_TOTAL,
    INDEX_STAGE_LATENCY_SECONDS,
    INDEX_TOKENS_TOTAL,
)
from server.retrieval.qdrant_store import QdrantChunkStore
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["index"])

# Ruff B008: avoid function calls in argument defaults (FastAPI Depends()).
_CORPUS_SCOPE_DEP = Depends()

_STATUS: dict[str, IndexStatus] = {}
_STATS: dict[str, IndexStats] = {}
_TASKS: dict[str, asyncio.Task[None]] = {}
_EVENT_QUEUES: dict[str, asyncio.Queue[dict[str, Any]]] = {}
_LAST_STARTED_REPO: str | None = None

_MODELS_JSON_PATH = Path(__file__).parent.parent.parent / "data" / "models.json"
_INDEX_RUNS_DIR = Path(__file__).parent.parent.parent / "data" / "index_runs"

_ACTIVE_RUNS: dict[str, str] = {}
_UNKNOWN_COMMITS: dict[str, str] = {}  # runs whose promotion outcome awaits manifest reconciliation
_STATUS_RUN_ID: dict[str, str] = {}  # the run each process-local terminal status describes
_CANCELLED_AFTER_COMMIT: dict[str, str] = {}  # runs whose cancellation landed after their commit
_QUEUE_RUN_CONTEXT: dict[int, tuple[str, str]] = {}

# Index estimate heuristics (intentionally rough).
_EST_BYTES_PER_TOKEN = 4.0  # common rule-of-thumb for English-ish text
_EST_TOKENS_PER_SECOND_CLOUD = 50_000
_EST_TOKENS_PER_SECOND_DETERMINISTIC = 120_000
_EST_OVERHEAD_SECONDS = 12.0
_EST_RANGE_LOW_MULT = 0.6
_EST_RANGE_HIGH_MULT = 1.9

# Local embedding throughput heuristics (tokens/sec) by hardware class.
_LOCAL_EMBED_TPS_TABLE: dict[str, dict[str, int]] = {
    "apple_silicon_mlx": {
        "mlx": 60_000,
        "huggingface": 12_000,
        "local": 10_000,
        "_default": 12_000,
    },
    "apple_silicon_cpu": {"mlx": 18_000, "huggingface": 9_000, "local": 8_000, "_default": 8_000},
    "cuda_gpu": {"mlx": 25_000, "huggingface": 40_000, "local": 35_000, "_default": 32_000},
    "cpu_only": {"mlx": 6_000, "huggingface": 5_000, "local": 4_000, "_default": 4_500},
}

# Semantic KG LLM extraction throughput heuristic (calls/sec) by provider.
_SEMANTIC_KG_CALLS_PER_SECOND: dict[str, float] = {
    "litellm": 1.0,
}


def _idle_status(repo_id: str) -> IndexStatus:
    return IndexStatus(
        repo_id=repo_id,
        status="idle",
        progress=0.0,
        current_file=None,
        error=None,
        started_at=None,
        completed_at=None,
    )


def _clear_runtime_state_for_repo(
    repo_id: str, *, queue: asyncio.Queue[dict[str, Any]] | None = None
) -> None:
    # Remove task only when this cleanup corresponds to the currently-registered task.
    cur_task = _TASKS.get(repo_id)
    if cur_task is not None and (queue is None or _EVENT_QUEUES.get(repo_id) is queue):
        if cur_task.done():
            _TASKS.pop(repo_id, None)

    # Remove queue only when this cleanup corresponds to the currently-registered queue.
    if queue is None:
        _EVENT_QUEUES.pop(repo_id, None)
    elif _EVENT_QUEUES.get(repo_id) is queue:
        _EVENT_QUEUES.pop(repo_id, None)

    _ACTIVE_RUNS.pop(repo_id, None)
    if queue is not None:
        _QUEUE_RUN_CONTEXT.pop(id(queue), None)


def _sanitize_fs_component(value: str) -> str:
    v = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    v = re.sub(r"_+", "_", v).strip("_")
    return v or "unknown"


def _repo_runs_dir(repo_id: str) -> Path:
    return _INDEX_RUNS_DIR / _sanitize_fs_component(repo_id)


def _run_dir(repo_id: str, run_id: str) -> Path:
    return _repo_runs_dir(repo_id) / _sanitize_fs_component(run_id)


def _run_summary_path(repo_id: str, run_id: str) -> Path:
    return _run_dir(repo_id, run_id) / "summary.json"


def _run_events_path(repo_id: str, run_id: str) -> Path:
    return _run_dir(repo_id, run_id) / "events.jsonl"


def _persist_run_summary(summary: IndexRunSummary) -> None:
    """Queue an atomic replace of the run summary (off the event loop, in order with its events)."""
    path = _run_summary_path(summary.repo_id, summary.run_id)
    _ensure_event_writer()
    _EVENT_WRITE_QUEUE.put(
        ("replace", path, summary.model_dump_json(by_alias=True, exclude_none=False, indent=2))
    )


def _load_run_summary(repo_id: str, run_id: str) -> IndexRunSummary | None:
    path = _run_summary_path(repo_id, run_id)
    if not path.exists():
        return None
    try:
        return IndexRunSummary.model_validate_json(path.read_text())
    except Exception:
        return None


def _load_latest_run_summary(repo_id: str) -> IndexRunSummary | None:
    repo_dir = _repo_runs_dir(repo_id)
    if not repo_dir.exists():
        return None
    candidates = sorted(
        [p for p in repo_dir.glob("*/summary.json") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in candidates:
        try:
            return IndexRunSummary.model_validate_json(p.read_text())
        except Exception:
            continue
    return None


async def _manifest_names_run(repo_id: str, run_id: str) -> bool | None:
    """Whether the corpus manifest names ``run_id`` (None when the manifest cannot be read)."""
    try:
        cfg = await load_scoped_config(repo_id=repo_id)
        pg = PostgresClient(cfg.indexing.postgres_url)
        await pg.connect()
        try:
            generation = await pg.get_generation(repo_id)
        finally:
            with contextlib.suppress(Exception):
                await pg.disconnect()
    except CorpusNotFoundError:
        # No such corpus any more: nothing can name the run (definitive, not unknown).
        return False
    except DeletionIncompleteError:
        # Being de-indexed: no live generation names any run.
        return False
    except PersistedStateCorruptError:
        raise  # malformed state is a typed, repairable 409, never "unknown"
    except Exception:
        logger.warning("could not read the generation manifest of %s", repo_id, exc_info=True)
        return None
    return generation is not None and generation.run_id == run_id


async def _live_fence(repo_id: str, *, cfg: TriBridConfig | None = None) -> IndexRunFence | None:
    """The corpus's durable fence if it is fresh; None when absent or stale.

    A Postgres outage or a malformed fence propagates (the route answers the
    typed 503/409); durable truth is never silently downgraded to "idle".
    """
    try:
        cfg = cfg or await load_scoped_config(repo_id=repo_id)
    except CorpusNotFoundError:
        return None
    pg = PostgresClient(cfg.indexing.postgres_url)
    try:
        await pg.connect()
        fence = await pg.get_index_fence(repo_id)
        if fence is None:
            return None
        db_now = await pg.database_now()
    except IndexFenceCorruptError:
        raise
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary="Index status")
        raise
    finally:
        with contextlib.suppress(Exception):
            await pg.disconnect()
    if fence.is_stale(now=db_now, lease_seconds=cfg.indexing.index_run_lease_seconds):
        return None
    return fence


async def _finalize_interrupted_run(repo_id: str, run: IndexRunSummary) -> IndexRunSummary:
    """Finalize a persisted ``indexing`` run no active task owns (process restart or worker crash).

    The manifest is the durable terminal state: a run it names committed, so it
    is complete even if its summary was never rewritten; anything else is an
    interrupted run.
    """
    if str(getattr(run, "status", "") or "").strip().lower() != "indexing":
        return run

    task = _TASKS.get(repo_id)
    if task is not None and not task.done():
        return run

    named = await _manifest_names_run(repo_id, run.run_id)
    if named is None:
        # The manifest could not be read (Postgres outage): the run's outcome is
        # unknown right now, never an error. It is reconsidered on the next read.
        return run
    if _UNKNOWN_COMMITS.get(repo_id) == run.run_id:
        _UNKNOWN_COMMITS.pop(repo_id, None)
    if named:
        finalized = run.model_copy(
            update={"status": "complete", "progress": 1.0, "completed_at": datetime.now(UTC)}
        )
        with contextlib.suppress(Exception):
            _persist_run_summary(finalized)
        return finalized
    live = await _live_fence(repo_id)
    if live is not None and live.run_id == run.run_id:
        # Another worker holds a fresh fence for this very run: it is still indexing.
        return run

    await _flush_run_events()
    msg = (
        "Indexing interrupted before completion (server restart or worker crash). "
        "Start a new indexing run."
    )
    finalized = run.model_copy(
        update={
            "status": "error",
            "completed_at": datetime.now(UTC),
            "error": str(run.error or msg),
        }
    )
    with contextlib.suppress(Exception):
        _persist_run_summary(finalized)

    # Append one terminal event if one has not been recorded yet.
    with contextlib.suppress(Exception):
        tail = _load_run_events(repo_id, run.run_id, limit=5)
        has_terminal = any(ev.type in {"complete", "error", "cancelled"} for ev in tail)
        if not has_terminal:
            _append_run_event(
                repo_id,
                run.run_id,
                {
                    "type": "error",
                    "message": finalized.error,
                    "percent": int(max(0.0, min(1.0, float(finalized.progress or 0.0))) * 100),
                },
            )
    return finalized


def _allow_parallel_chunk_batches(
    *, indexing_workers: int, batch_count: int, has_graph_upserts: bool
) -> bool:
    """Whether chunk upsert batches can safely run concurrently.

    Neo4j chunk/document writes can deadlock under concurrent per-file batch
    upserts. Keep those writes serialized even when indexing_workers > 1.
    """
    if int(batch_count or 0) <= 1:
        return False
    if int(indexing_workers or 0) <= 1:
        return False
    if has_graph_upserts:
        return False
    return True


def _allow_cross_file_chunk_batching(
    *,
    has_graph_upserts: bool,
    semantic_kg_enabled: bool,
) -> bool:
    """Whether small-file chunks can be batched across files before embedding/upsert.

    Cross-file batching is only safe when we do not need per-file graph writes
    or per-file semantic KG extraction queues.
    """
    if has_graph_upserts:
        return False
    if semantic_kg_enabled:
        return False
    return True


def _to_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


_EVENT_WRITE_QUEUE: queue.Queue[tuple[str, Path, str] | None] = queue.Queue()
_EVENT_WRITER_LOCK = threading.Lock()
_EVENT_WRITER: threading.Thread | None = None


def _event_writer_loop() -> None:
    """Single FIFO writer: appends event lines, replaces summaries atomically; nothing is dropped."""
    while True:
        item = _EVENT_WRITE_QUEUE.get()
        try:
            if item is None:
                return
            kind, path, payload = item
            path.parent.mkdir(parents=True, exist_ok=True)
            if kind == "append":
                with path.open("a", encoding="utf-8") as f:
                    f.write(payload)
            else:
                tmp = path.with_name(path.name + ".tmp")
                tmp.write_text(payload, encoding="utf-8")
                os.replace(tmp, path)
        except Exception:
            logger.warning("index run persistence failed", exc_info=True)
        finally:
            _EVENT_WRITE_QUEUE.task_done()


async def stop_index_runs() -> None:
    """Cancel and await every index run of this process (their terminal handlers still persist)."""
    for repo_id, task in list(_TASKS.items()):
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
        _TASKS.pop(repo_id, None)


async def shutdown_event_writer() -> None:
    """Flush every queued record and stop the writer (called from the app lifespan shutdown)."""
    global _EVENT_WRITER
    with _EVENT_WRITER_LOCK:
        writer = _EVENT_WRITER
        _EVENT_WRITER = None
    if writer is None or not writer.is_alive():
        return
    _EVENT_WRITE_QUEUE.put(None)
    await asyncio.to_thread(writer.join)


def _ensure_event_writer() -> None:
    global _EVENT_WRITER
    with _EVENT_WRITER_LOCK:
        if _EVENT_WRITER is None or not _EVENT_WRITER.is_alive():
            _EVENT_WRITER = threading.Thread(
                target=_event_writer_loop, name="index-event-writer", daemon=True
            )
            _EVENT_WRITER.start()


def _flush_run_events_sync() -> None:
    """Block until every queued event line is on disk (readers call this off the loop)."""
    _EVENT_WRITE_QUEUE.join()


async def _flush_run_events() -> None:
    await asyncio.to_thread(_flush_run_events_sync)


def _append_run_event(repo_id: str, run_id: str, event: dict[str, Any]) -> None:
    """Queue one JSONL event for the writer thread; never touches the disk on the event loop."""
    event_type = str(event.get("type") or "").strip()
    if not event_type:
        return
    evt = IndexRunEvent(
        run_id=run_id,
        ts=datetime.now(UTC),
        type=event_type,
        message=str(event.get("message")) if event.get("message") is not None else None,
        percent=_to_optional_int(event.get("percent")),
        current_file=str(event.get("current_file"))
        if event.get("current_file") is not None
        else None,
        meta={
            k: v
            for k, v in event.items()
            if k not in {"type", "message", "percent", "current_file"}
        },
    )
    path = _run_events_path(repo_id, run_id)
    line = evt.model_dump_json(by_alias=True, exclude_none=True) + "\n"
    _ensure_event_writer()
    _EVENT_WRITE_QUEUE.put(("append", path, line))


def _load_run_events(repo_id: str, run_id: str, *, limit: int) -> list[IndexRunEvent]:
    path = _run_events_path(repo_id, run_id)
    if not path.exists():
        return []
    out: list[IndexRunEvent] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(IndexRunEvent.model_validate_json(line))
            except Exception:
                continue
    except Exception:
        return []
    lim = max(1, min(int(limit or 200), 5000))
    return out[-lim:]


def _build_staging_repo_id(repo_id: str, run_id: str) -> str:
    return staging_repo_id(repo_id, run_id)


async def _clear_semantic_cache_for_repo(repo_id: str) -> None:
    """Best-effort corpus cache invalidation used by indexing terminal paths."""
    cfg = await load_scoped_config(repo_id=repo_id)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    try:
        await postgres.semantic_cache_clear_for_corpus(repo_id)
    finally:
        with contextlib.suppress(Exception):
            await postgres.disconnect()


async def _cancel_index_run(repo_id: str) -> IndexStatus:
    repo_id = str(repo_id or "").strip()
    if not repo_id:
        raise HTTPException(status_code=422, detail="repo_id is required")

    task = _TASKS.get(repo_id)
    if task is None:
        return await _stop_without_local_task(repo_id)

    event_queue = _EVENT_QUEUES.get(repo_id)
    # The background task owns terminal publication: a run whose manifest is
    # already committed ends `complete` even when cancelled during retirement.
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task

    _TASKS.pop(repo_id, None)
    current = _STATUS.get(repo_id)
    if _UNKNOWN_COMMITS.get(repo_id):
        # The run's promotion outcome is unknown until the manifest is read back:
        # the operator's cancellation must not rewrite that as "cancelled".
        pass
    elif current is None or current.status == "indexing":
        # The task ended without publishing a terminal state (it never reached its
        # handlers): the operator's cancellation is the outcome.
        _STATUS[repo_id] = IndexStatus(
            repo_id=repo_id,
            status="cancelled",
            progress=float(current.progress) if current else 0.0,
            current_file=current.current_file if current else None,
            error=None,
            started_at=current.started_at if current else None,
            completed_at=datetime.now(UTC),
        )
        if event_queue is not None:
            _emit_event(
                event_queue,
                {"type": "cancelled", "message": "⚠ Indexing cancelled"},
                guarantee=True,
            )
    _clear_runtime_state_for_repo(repo_id, queue=event_queue)
    return _STATUS.get(repo_id) or _idle_status(repo_id)


async def _reclaim_own_staged(
    repo_id: str, run_id: str, staged_collection: str | None, staged_graph: str | None
) -> bool:
    """A failed/cancelled run cleans its own staged inventory through the durable backlog.

    Returns True once the inventory is durably on the backlog (whether or not
    the reclaim itself completed: an entry left behind is retried by the next
    claim). False means the handoff could not be recorded: the caller must keep
    the fence, which names the same inventory, for the stale takeover. The
    ids are the EXACT ones recorded on the fence (never rebuilt from current
    feature flags or from a client response that may have been lost).
    """
    if staged_collection is None and staged_graph is None:
        return True  # nothing was ever staged
    cfg = await load_scoped_config(repo_id=repo_id)
    pg = PostgresClient(cfg.indexing.postgres_url)
    try:
        await pg.connect()
        entry = ReclaimEntry(
            run_id=run_id,
            staged_qdrant_collection=staged_collection,
            staged_graph_repo_id=staged_graph,
            recorded_at=await pg.database_now(),
        )
        await pg.push_reclaim_entry(repo_id, entry)
    except Exception:
        logger.warning(
            "run %s on %s could not record its staged inventory on the reclaim backlog",
            run_id,
            repo_id,
            exc_info=True,
        )
        return False
    finally:
        with contextlib.suppress(Exception):
            await pg.disconnect()
    if not await reclaim_stale_run(cfg, repo_id, entry):
        logger.warning(
            "run %s on %s could not fully reclaim its staged resources; they stay on the backlog",
            run_id,
            repo_id,
        )
    return True


async def _reclaim_own_staged_shielded(
    repo_id: str, run_id: str, staged_collection: str | None, staged_graph: str | None
) -> bool:
    """`_reclaim_own_staged` shielded from cancellation; an interrupted wait reads as unrecorded."""
    fut = asyncio.ensure_future(
        _reclaim_own_staged(repo_id, run_id, staged_collection, staged_graph)
    )
    try:
        return await asyncio.shield(fut)
    except BaseException:
        # A second cancellation interrupted the wait: the shielded work continues
        # in the background, but we cannot know it recorded the handoff.
        if fut.done() and not fut.cancelled() and fut.exception() is None:
            return bool(fut.result())
        return False


async def _drain_reclaim_backlog(cfg: TriBridConfig, repo_id: str) -> None:
    """Reclaim every dead run recorded on the corpus row; entries survive until confirmed."""
    pg = PostgresClient(cfg.indexing.postgres_url)
    try:
        await pg.connect()
        entries = await pg.reclaim_backlog(repo_id)
    finally:
        with contextlib.suppress(Exception):
            await pg.disconnect()
    for entry in entries:
        if not await reclaim_stale_run(cfg, repo_id, entry):
            logger.warning(
                "reclaim of dead run %s on %s incomplete; it stays on the backlog",
                entry.run_id,
                repo_id,
            )


async def _finalize_dead_committed_run(repo_id: str, run_id: str) -> None:
    """A run whose manifest is live but whose summary still says indexing is complete."""
    await _flush_run_events()
    summary = await asyncio.to_thread(_load_run_summary, repo_id, run_id)
    if summary is None or str(summary.status) != "indexing":
        return
    finalized = summary.model_copy(
        update={"status": "complete", "progress": 1.0, "completed_at": datetime.now(UTC)}
    )
    with contextlib.suppress(Exception):
        _persist_run_summary(finalized)


async def _stop_without_local_task(repo_id: str) -> IndexStatus:
    """Stop for a corpus this process is not indexing: act on the durable fence.

    A stale fence (crashed worker) is released and reported as cancelled; a live
    fence belongs to another worker and is a typed 409 (cancel it there).
    """
    cfg = await load_scoped_config(repo_id=repo_id)
    pg = PostgresClient(cfg.indexing.postgres_url)
    try:
        await pg.connect()
        fence = await pg.get_index_fence(repo_id)
        if fence is None:
            return _STATUS.get(repo_id) or _idle_status(repo_id)
        if not fence.is_stale(
            now=await pg.database_now(), lease_seconds=cfg.indexing.index_run_lease_seconds
        ):
            raise _index_run_conflict(repo_id, fence)
        manifest = await pg.get_generation(repo_id)
        # Only the manifest's run id proves the dead run committed (a collection id
        # among the retained ones is not ownership); reclaim itself never drops a
        # resource the manifest names.
        committed = manifest is not None and manifest.run_id == fence.run_id
        if not committed and (fence.staged_qdrant_collection or fence.staged_graph_repo_id):
            # The dead run's staged inventory goes to the durable backlog BEFORE the
            # fence (its only other record of those ids) is released.
            await pg.push_reclaim_entry(
                repo_id,
                ReclaimEntry(
                    run_id=fence.run_id,
                    staged_qdrant_collection=fence.staged_qdrant_collection,
                    staged_graph_repo_id=fence.staged_graph_repo_id,
                    recorded_at=await pg.database_now(),
                ),
            )
        released = await pg.release_index_fence(repo_id, fence.run_id)
        if not committed:
            await _drain_reclaim_backlog(cfg, repo_id)
    except IndexFenceCorruptError as exc:
        raise _fence_corrupt_conflict(repo_id, exc) from exc
    except CorpusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary="Index stop")
        raise
    finally:
        with contextlib.suppress(Exception):
            await pg.disconnect()
    if committed:
        # The dead run committed before it died: it is complete, its index is live.
        await _finalize_dead_committed_run(repo_id, fence.run_id)
        status = IndexStatus(
            repo_id=repo_id,
            status="complete",
            progress=1.0,
            current_file=None,
            error=None,
            started_at=fence.started_at,
            completed_at=datetime.now(UTC),
        )
    else:
        status = IndexStatus(
            repo_id=repo_id,
            status="cancelled",
            progress=0.0,
            current_file=None,
            error=(
                f"Stale index run {fence.run_id} (owner {fence.owner}) released"
                if released
                else f"Stale index run {fence.run_id} was already released"
            ),
            started_at=fence.started_at,
            completed_at=datetime.now(UTC),
        )
    _STATUS[repo_id] = status
    return status


async def _manifest_is_newer_than_local(
    repo_id: str, cfg: TriBridConfig, local: IndexStatus
) -> bool:
    """Whether durable state moved on from the run this process's terminal status describes.

    Identity, never clocks: the status is stale when the manifest is gone (another
    worker de-indexed the corpus) or names a run other than the one this status
    came from.
    """
    pg = PostgresClient(cfg.indexing.postgres_url)
    try:
        await pg.connect()
        manifest = await pg.get_generation(repo_id)
    finally:
        with contextlib.suppress(Exception):
            await pg.disconnect()
    local_run = _STATUS_RUN_ID.get(repo_id)
    if local.status == "complete":
        return manifest is None or manifest.run_id != local_run
    # error/cancelled: stale once any later run promoted
    return manifest is not None and manifest.run_id != local_run


async def _read_index_state(repo_id: str, cfg: TriBridConfig) -> GenerationManifest | None:
    """The strict read of EVERY persisted index key of a corpus row; returns its live manifest.

    Mid-de-index -> typed 503; a malformed manifest, tombstone, fence or reclaim
    backlog -> typed 409; a Postgres outage -> typed 503. Every status/stats/
    latest-run read goes through here so no reader answers 200 from a row it
    could not validate.
    """
    pg = PostgresClient(cfg.indexing.postgres_url)
    try:
        await pg.connect()
        row = await pg.get_corpus(repo_id)
        meta = row.get("meta") if row and isinstance(row.get("meta"), dict) else {}
        reclaim_backlog_from_meta(meta, repo_id=repo_id)
        raw_fence = meta.get("index_run")
        if raw_fence is not None:
            try:
                IndexRunFence.model_validate(raw_fence)
            except Exception as exc:
                raise IndexFenceCorruptError(repo_id, raw_fence) from exc
        return generation_from_corpus_row(row)
    except (
        IndexFenceCorruptError,
        PersistedStateCorruptError,
        DeletionIncompleteError,
        CorpusNotFoundError,
    ):
        raise
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary="Index status")
        raise
    finally:
        with contextlib.suppress(Exception):
            await pg.disconnect()


def _fence_corrupt_conflict(repo_id: str, exc: IndexFenceCorruptError) -> HTTPException:
    detail = IndexFenceCorruptDetail(
        corpus_id=repo_id,
        message=f"Corpus {repo_id} carries a malformed index-run fence.",
        operator_hint=(
            "De-index the corpus (DELETE /api/index/{corpus_id}) to clear the fence, then re-index. "
            f"Stored value: {exc.raw!r}"
        ),
    )
    return HTTPException(status_code=409, detail=detail.model_dump(mode="json"))


def _index_run_conflict(repo_id: str, fence: IndexRunFence) -> HTTPException:
    detail = IndexRunConflictDetail(
        corpus_id=repo_id,
        run_id=fence.run_id,
        owner=fence.owner,
        started_at=fence.started_at,
        heartbeat_at=fence.heartbeat_at,
        message=f"Corpus {repo_id} is fenced by index run {fence.run_id}.",
        operator_hint=(
            "Wait for that run to finish or stop it on the worker that owns it "
            f"({fence.owner}); a fence whose heartbeat is older than "
            "indexing.index_run_lease_seconds is taken over automatically."
        ),
    )
    return HTTPException(status_code=409, detail=detail.model_dump(mode="json"))


def _estimate_tokens_from_bytes(total_bytes: int) -> int:
    b = max(0, int(total_bytes or 0))
    return int(float(b) / float(_EST_BYTES_PER_TOKEN)) if b > 0 else 0


def _estimate_chunks_from_tokens(*, tokens: int, target_tokens: int, overlap_tokens: int) -> int:
    t = max(0, int(tokens or 0))
    target = max(1, int(target_tokens or 0))
    overlap = max(0, int(overlap_tokens or 0))
    stride = max(1, target - min(overlap, target - 1))
    # Ceiling division
    return int((t + stride - 1) // stride) if t > 0 else 0


def _looks_cloud_provider(provider: str) -> bool:
    p = (provider or "").strip().lower()
    return p in {"openai", "voyage", "cohere", "google", "mistral", "jina", "deepseek"}


def _norm_key(s: str | None) -> str:
    return str(s or "").strip().lower()


def _to_float(x: Any) -> float | None:
    try:
        v = float(x)
    except Exception:
        return None
    if v != v:  # NaN guard
        return None
    return v


def _model_has_component(spec: dict[str, Any], component: str) -> bool:
    comps = spec.get("components")
    if not isinstance(comps, list):
        return False
    target = str(component or "").strip().upper()
    return any(str(c or "").strip().upper() == target for c in comps)


def _find_model_spec(
    models: list[dict[str, Any]], *, provider: str | None, model: str | None
) -> dict[str, Any] | None:
    """Best-effort model lookup (provider+model, then model, then provider)."""
    prov = _norm_key(provider)
    mdl = _norm_key(model)

    if prov and mdl:
        for m in models:
            if _norm_key(m.get("provider")) == prov and _norm_key(m.get("model")) == mdl:
                return m

    if mdl:
        for m in models:
            if _norm_key(m.get("model")) == mdl:
                return m

    # No provider-only fallback: returning the first model for a provider
    # when the requested model is missing would silently price the wrong model.
    return None


def _semantic_kg_model_override(cfg: TriBridConfig) -> str:
    alias = str(
        cfg.graph_indexing.semantic_kg_llm_model or cfg.chat.litellm.default_model or ""
    ).strip()
    if re.fullmatch(r"[A-Za-z0-9._-]+", alias) is None:
        raise ValueError("GraphRAG semantic model must be a configured LiteLLM alias.")
    return alias


def _resolve_semantic_kg_route(cfg: TriBridConfig) -> ProviderRoute:
    route = select_provider_route(config=cfg, model_override=_semantic_kg_model_override(cfg))
    if route.kind != "litellm":
        raise ValueError(f"GraphRAG semantic model must resolve through LiteLLM, got {route.kind}.")
    if not str(route.base_url or "").strip():
        raise ValueError("GraphRAG semantic model resolved without a base URL.")
    if not str(route.model or "").strip():
        raise ValueError("GraphRAG semantic model resolved without a model id.")
    return route


def _detect_local_hardware_class() -> str:
    machine = str(platform.machine() or "").strip().lower()
    is_apple_silicon = sys.platform == "darwin" and machine in {"arm64", "aarch64"}

    has_mlx = importlib.util.find_spec("mlx") is not None
    has_cuda = False
    if importlib.util.find_spec("torch") is not None:
        with contextlib.suppress(Exception):
            import torch  # type: ignore[import-not-found,unused-ignore]

            has_cuda = bool(torch.cuda.is_available())

    if is_apple_silicon and has_mlx:
        return "apple_silicon_mlx"
    if is_apple_silicon:
        return "apple_silicon_cpu"
    if has_cuda:
        return "cuda_gpu"
    return "cpu_only"


def _estimate_local_tokens_per_second(*, cfg: TriBridConfig, provider: str) -> int:
    override = getattr(cfg.indexing, "estimated_tokens_per_second_local", None)
    if override is not None:
        with contextlib.suppress(Exception):
            ov = int(override)
            if ov > 0:
                return ov

    hw_class = _detect_local_hardware_class()
    table = _LOCAL_EMBED_TPS_TABLE.get(hw_class, _LOCAL_EMBED_TPS_TABLE["cpu_only"])
    p = _norm_key(provider)
    est = int(
        table.get(p) or table.get("_default") or _LOCAL_EMBED_TPS_TABLE["cpu_only"]["_default"]
    )
    if hw_class == "cpu_only":
        cores = max(1, multiprocessing.cpu_count())
        if cores >= 24:
            est = max(est, 8_000)
        elif cores >= 12:
            est = max(est, 6_000)
    return est


def _resolve_semantic_kg_model_and_provider(cfg: TriBridConfig) -> tuple[str, str]:
    return _semantic_kg_model_override(cfg), "litellm"


def _estimate_semantic_kg_cost_usd(
    *,
    provider_hint: str,
    model: str,
    chunks_in_scope: int,
    enrich_max_chars: int,
) -> float | None:
    """Estimate semantic KG LLM extraction cost from models.json GEN pricing."""
    count = max(0, int(chunks_in_scope or 0))
    if count <= 0:
        return 0.0
    mname = str(model or "").strip()
    if not mname:
        return None

    # Per chunk heuristic: fixed prompt overhead + bounded chunk text + concise JSON output.
    input_tokens_per_chunk = max(0, 500 + int(max(0, enrich_max_chars) / 4))
    output_tokens_per_chunk = 100
    total_input_tokens = count * input_tokens_per_chunk
    total_output_tokens = count * output_tokens_per_chunk

    spec = _find_model_spec(_load_models_json(), provider=provider_hint, model=mname)
    if not spec or not _model_has_component(spec, "GEN"):
        return None
    if str(spec.get("unit") or "").strip() != "1k_tokens":
        return None

    in_rate = _to_float(spec.get("input_per_1k"))
    out_rate = _to_float(spec.get("output_per_1k"))
    if in_rate is None and out_rate is None:
        return None
    return ((float(total_input_tokens) / 1000.0) * float(in_rate or 0.0)) + (
        (float(total_output_tokens) / 1000.0) * float(out_rate or 0.0)
    )


def _estimate_semantic_kg_seconds(
    *,
    provider: str,
    chunks_in_scope: int,
    indexing_workers: int,
) -> float:
    count = max(0, int(chunks_in_scope or 0))
    if count <= 0:
        return 0.0
    p = _norm_key(provider)
    calls_per_second = float(_SEMANTIC_KG_CALLS_PER_SECOND.get(p, 1.0))
    workers = max(1, int(indexing_workers or 1))
    # Runtime executes semantic extraction in batches up to indexing_workers.
    effective_calls_per_second = max(0.1, calls_per_second * float(min(workers, 8)))
    return float(count) / effective_calls_per_second


@lru_cache(maxsize=1)
def _load_models_json() -> list[dict[str, Any]]:
    """Load models.json (THE LAW for model pricing/metadata)."""
    try:
        raw = json.loads(_MODELS_JSON_PATH.read_text())
    except Exception:
        return []
    if isinstance(raw, dict) and isinstance(raw.get("models"), list):
        return [m for m in raw["models"] if isinstance(m, dict)]
    if isinstance(raw, list):
        return [m for m in raw if isinstance(m, dict)]
    return []


def _estimate_embedding_cost_usd(*, provider: str, model: str, total_tokens: int) -> float | None:
    """Estimate embedding cost from models.json (if pricing is available)."""
    if total_tokens <= 0:
        return 0.0
    p = (provider or "").strip().lower()
    mname = (model or "").strip()
    if not p or not mname:
        return None

    for m in _load_models_json():
        if str(m.get("provider", "")).strip().lower() != p:
            continue
        if str(m.get("model", "")).strip() != mname:
            continue
        comps = m.get("components") or []
        if "EMB" not in comps:
            continue
        unit = str(m.get("unit") or "").strip()
        embed_per_1k = m.get("embed_per_1k")
        if unit != "1k_tokens" or embed_per_1k is None:
            return None
        try:
            price = float(embed_per_1k)
        except Exception:
            return None
        return (float(total_tokens) / 1000.0) * price
    return None


async def _resolve_dashboard_repo_id(scope: CorpusScope) -> str:
    """Resolve a corpus_id for dashboard endpoints.

    Priority:
    1) explicit scope (corpus_id/repo_id/repo)
    2) last started repo (legacy UX)
    3) only-corpus in Postgres (best-effort for single-corpus setups)
    """
    repo_id = (scope.resolved_repo_id or _LAST_STARTED_REPO or "").strip()
    if repo_id:
        return repo_id

    # Best-effort fallback: only allow implicit selection when there is exactly one corpus.
    cfg = await load_scoped_config(repo_id=None)
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        corpora = await pg.list_corpora()
    finally:
        await pg.disconnect()

    if corpora:
        # If multiple corpora exist, never guess — callers must pass corpus_id explicitly.
        if len(corpora) > 1:
            raise HTTPException(
                status_code=400,
                detail="Missing corpus_id (or legacy repo/repo_id) query parameter. "
                "Multiple corpora exist; select a corpus explicitly.",
            )
        rid = str(corpora[0].get("repo_id") or "").strip()
        if rid:
            return rid

    raise HTTPException(
        status_code=400,
        detail="Missing corpus_id (or legacy repo/repo_id) query parameter and no corpora exist yet. Create a corpus first.",
    )


async def _compute_dashboard_storage_breakdown(*, repo_id: str) -> DashboardIndexStorageBreakdown:
    """Compute a dashboard-friendly storage breakdown (bytes) for a corpus."""
    cfg = await load_scoped_config(repo_id=repo_id)

    # Postgres (chunk rows + chunk_summaries)
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        breakdown = await pg.get_dashboard_storage_breakdown(repo_id)
        generation = await pg.get_generation(repo_id)
    finally:
        await pg.disconnect()

    # Qdrant (points + estimated dense bytes); unreachable Qdrant reads as zero, never as healthy.
    qdrant_points = 0
    qdrant_dense_vector_bytes = 0
    try:
        status = await QdrantChunkStore(cfg).status(
            repo_id, physical=qdrant_collection_of(generation)
        )
        if status is not None:
            qdrant_points = int(status.points)
            qdrant_dense_vector_bytes = int(status.dense_points) * int(status.dense_dimensions) * 4
    except Exception:
        qdrant_points = 0
        qdrant_dense_vector_bytes = 0

    # Neo4j (store size via JMX)
    neo4j_store_bytes = 0
    try:
        db_name = cfg.graph_storage.resolve_database(repo_id)
        neo4j = Neo4jClient(
            cfg.graph_storage.neo4j_uri,
            cfg.graph_storage.neo4j_user,
            cfg.graph_storage.resolve_password(),
            database=db_name,
        )
        await neo4j.connect()
        try:
            neo4j_store_bytes = int(await neo4j.get_store_size_bytes())
        finally:
            await neo4j.disconnect()
    except Exception:
        # Graph layer is optional; never fail dashboard rendering for missing graph.
        neo4j_store_bytes = 0

    chunks_bytes = int(breakdown.get("chunks_bytes") or 0)
    chunk_summaries_bytes = int(breakdown.get("chunk_summaries_bytes") or 0)
    postgres_total = chunks_bytes + chunk_summaries_bytes
    total_storage = postgres_total + qdrant_dense_vector_bytes + int(neo4j_store_bytes or 0)

    return DashboardIndexStorageBreakdown(
        chunks_bytes=chunks_bytes,
        chunk_summaries_bytes=chunk_summaries_bytes,
        qdrant_points=qdrant_points,
        qdrant_dense_vector_bytes=qdrant_dense_vector_bytes,
        neo4j_store_bytes=int(neo4j_store_bytes or 0),
        postgres_total_bytes=postgres_total,
        total_storage_bytes=total_storage,
    )


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

    ctx = _QUEUE_RUN_CONTEXT.get(id(queue))
    if ctx is not None:
        repo_id, run_id = ctx
        with contextlib.suppress(Exception):
            _append_run_event(repo_id, run_id, event)

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


async def _run_index(
    repo_id: str,
    repo_path: str,
    force_reindex: bool,
    *,
    event_queue: asyncio.Queue[dict[str, Any]] | None = None,
    run_id: str,
    write_repo_id: str | None = None,
    qdrant: QdrantChunkStore,
    qdrant_generation: str,
    cfg: TriBridConfig,
) -> IndexStats:
    # ONE config snapshot per run (the caller's): what the fence recorded, what is
    # built here and what the commit names must come from the same decision.
    target_repo_id = str(write_repo_id or repo_id)

    # Every run writes a fresh staging corpus and promotes it; a non-forced run
    # is a full rebuild guarded by the embedding-mismatch check below, never a
    # cache hit (returning cached stats here left the staging corpus unwritten
    # and the promotion failed with "Staging corpus not found").

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

    chunker = Chunker(cfg.chunking, cfg.tokenization)
    # Enforce a strict max file size before reading/chunking.
    # LAW sources:
    # - cfg.chunking.max_indexable_file_size (bytes)
    # - cfg.indexing.index_max_file_size_mb (MB)
    max_indexable_bytes = min(
        int(cfg.chunking.max_indexable_file_size),
        int(cfg.indexing.index_max_file_size_mb) * 1024 * 1024,
    )
    skip_dense = cfg.indexing.skip_dense
    embedder = None if skip_dense else Embedder(cfg.embedding, cfg.tokenization)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    active_corpus = await postgres.get_corpus(repo_id)
    active_meta = (active_corpus.get("meta") or {}) if active_corpus else {}
    active_name = str((active_corpus or {}).get("name") or repo_id)
    active_description = (active_corpus or {}).get("description")
    await postgres.upsert_corpus(
        target_repo_id,
        name=active_name,
        root_path=repo_path,
        description=str(active_description) if active_description is not None else None,
        meta={**active_meta, "internal_staging": target_repo_id != repo_id},
    )
    if embedder is not None:
        configure_postgres_embedding_cache_backend(embedder, postgres)

    # Corpus-level exclude paths (stored in Postgres corpora.meta.exclude_paths)
    extra_gitignore_patterns: list[str] = []
    corpus: dict[str, Any] | None = None
    try:
        corpus = await postgres.get_corpus(repo_id)
        meta = (corpus.get("meta") or {}) if corpus else {}
        raw = meta.get("exclude_paths") if isinstance(meta, dict) else None
        if isinstance(raw, list):
            extra_gitignore_patterns = [str(x).strip() for x in raw if str(x).strip()]
    except Exception:
        extra_gitignore_patterns = []

    # ---- Embedding mismatch guard ----
    # Detect when the current embedding config differs from what was used to
    # build the existing index and block the run unless force_reindex is set,
    # so an operator never replaces a corpus under a different vector space by
    # accident. Only guard when the corpus still has dense vectors in Qdrant:
    # after a delete, embedding metadata lingers on the corpora row.
    if corpus and not force_reindex and not skip_dense and embedder is not None:
        meta = corpus.get("meta") if isinstance(corpus.get("meta"), dict) else {}
        stored_backend = str((meta or {}).get("embedding_backend") or "").strip().lower()
        if not stored_backend:
            # Legacy corpora did not persist backend identity. Treat as deterministic
            # to avoid silently mixing deterministic and provider vectors.
            stored_backend = "deterministic"
        stored_model = str(corpus.get("embedding_model") or "").strip()
        stored_dim = int(corpus.get("embedding_dimensions") or 0)
        stored_provider = str(corpus.get("embedding_provider") or "").strip()

        # Only check if the corpus has been indexed before (non-empty metadata)
        # AND still contains embedded vectors. If vectors were deleted but
        # metadata was not cleared, there is nothing to protect.
        has_embeddings = False
        if stored_model and stored_dim > 0:
            live = await qdrant.status(
                repo_id, physical=qdrant_collection_of(generation_from_corpus_row(corpus))
            )
            has_embeddings = bool(live is not None and live.dense_points > 0)
        if stored_model and stored_dim > 0 and has_embeddings:
            current_model = str(cfg.embedding.effective_model or "").strip()
            current_dim = int(embedder.dim)
            current_backend = (
                str(cfg.embedding.embedding_backend or "").strip().lower() or "deterministic"
            )
            current_provider = str(cfg.embedding.embedding_type or "").strip()
            both_deterministic = (
                current_backend == "deterministic" and stored_backend == "deterministic"
            )

            mismatches: list[str] = []
            if stored_dim != current_dim:
                mismatches.append(f"dimensions: stored={stored_dim}, config={current_dim}")
            if not both_deterministic and stored_model != current_model:
                mismatches.append(f"model: stored={stored_model}, config={current_model}")
            if stored_backend != current_backend:
                mismatches.append(f"backend: stored={stored_backend}, config={current_backend}")
            if not both_deterministic and stored_provider != current_provider:
                mismatches.append(f"provider: stored={stored_provider}, config={current_provider}")

            if mismatches:
                detail = "; ".join(mismatches)
                msg = (
                    f"Embedding configuration mismatch for corpus '{repo_id}': {detail}. "
                    "Re-indexing without force_reindex would mix incompatible vectors. "
                    "Set force_reindex=true to clear the existing index first, "
                    "or restore the embedding config to match the current index."
                )
                if event_queue is not None:
                    _emit_event(
                        event_queue,
                        {"type": "error", "message": msg},
                        guarantee=True,
                    )
                raise RuntimeError(msg)

    loader = FileLoader(
        ignore_patterns=ignore_patterns, extra_gitignore_patterns=extra_gitignore_patterns
    )

    neo4j: Neo4jClient | None = None
    try:
        if cfg.graph_indexing.enabled:
            db_name = cfg.graph_storage.resolve_database(repo_id)
            neo4j = Neo4jClient(
                cfg.graph_storage.neo4j_uri,
                cfg.graph_storage.neo4j_user,
                cfg.graph_storage.resolve_password(),
                database=db_name,
            )
            await neo4j.connect()
            try:
                await neo4j.ensure_schema()
            except Exception as exc:
                _emit_event(
                    event_queue,
                    {"type": "error", "message": f"Neo4j schema initialization failed: {exc}"},
                    guarantee=True,
                )
                raise RuntimeError(f"Neo4j schema initialization failed: {exc}") from exc
            # Lexical chunk vector index (Neo4j native vector indexes)
            if (
                cfg.graph_indexing.build_lexical_graph
                and cfg.graph_indexing.store_chunk_embeddings
                and not skip_dense
            ):
                try:
                    assert embedder is not None
                    online = await neo4j.ensure_vector_index(
                        index_name=cfg.graph_indexing.chunk_vector_index_name,
                        label="Chunk",
                        embedding_property=cfg.graph_indexing.chunk_embedding_property,
                        dimensions=int(embedder.dim),
                        similarity_function=cfg.graph_indexing.vector_similarity_function,
                        wait_online=cfg.graph_indexing.wait_vector_index_online,
                        timeout_s=float(cfg.graph_indexing.vector_index_online_timeout_s),
                    )
                    if not online:
                        raise RuntimeError(
                            "Neo4j chunk vector index did not reach ONLINE state "
                            f"({cfg.graph_indexing.chunk_vector_index_name}); chunk-mode graph "
                            "retrieval would be unable to query this corpus, so the run fails closed"
                        )
                except Exception as exc:
                    # Chunk embeddings are stored for chunk-mode graph retrieval: an
                    # index that cannot serve them is a promotion prerequisite, not a warning.
                    _emit_event(
                        event_queue,
                        {
                            "type": "error",
                            "message": f"Neo4j chunk vector index setup failed: {exc}",
                        },
                        guarantee=True,
                    )
                    raise RuntimeError(f"Neo4j chunk vector index setup failed: {exc}") from exc
    except Exception as exc:
        # Explicitly fail when graph indexing was requested but cannot initialize.
        logger.warning(
            "Neo4j graph initialization failed for repo_id=%s: %s", repo_id, exc, exc_info=True
        )
        if neo4j is not None:
            with contextlib.suppress(Exception):
                await neo4j.disconnect()
        raise

    try:
        return await _run_index_body(
            repo_id=repo_id,
            repo_path=repo_path,
            force_reindex=force_reindex,
            run_id=run_id,
            cfg=cfg,
            chunker=chunker,
            max_indexable_bytes=max_indexable_bytes,
            skip_dense=skip_dense,
            embedder=embedder,
            postgres=postgres,
            neo4j=neo4j,
            loader=loader,
            event_queue=event_queue,
            write_repo_id=target_repo_id,
            qdrant=qdrant,
            qdrant_generation=qdrant_generation,
        )
    finally:
        if neo4j is not None:
            with contextlib.suppress(Exception):
                await neo4j.disconnect()


async def _run_index_body(
    *,
    repo_id: str,
    repo_path: str,
    force_reindex: bool,
    run_id: str,
    cfg: TriBridConfig,
    chunker: Chunker,
    max_indexable_bytes: int,
    skip_dense: bool,
    embedder: Embedder | None,
    postgres: PostgresClient,
    neo4j: Neo4jClient | None,
    loader: FileLoader,
    event_queue: asyncio.Queue[dict[str, Any]] | None,
    write_repo_id: str,
    qdrant: QdrantChunkStore,
    qdrant_generation: str,
) -> IndexStats:
    """Core indexing loop -- extracted to allow _run_index() to guarantee Neo4j cleanup via finally.

    Chunk rows go to Postgres under `write_repo_id`; dense + sparse vectors go
    to the staged Qdrant generation `qdrant_generation`. Neither is visible to
    retrieval until the caller promotes both.
    """
    vector_dim = (
        int(embedder.dim) if embedder is not None else int(cfg.embedding.embedding_dim or 0)
    )
    total_files = 0
    total_chunks = 0
    total_tokens = 0
    file_breakdown: dict[str, int] = defaultdict(int)

    prev_status = _STATUS.get(repo_id)
    started_at = (
        prev_status.started_at if prev_status and prev_status.started_at else datetime.now(UTC)
    )

    # Collect file paths once so we can report progress deterministically,
    # without loading every file's contents into memory.
    with INDEX_STAGE_LATENCY_SECONDS.labels(stage="collect_file_paths").time():
        file_entries = list(loader.iter_repo_files(repo_path))
    total_files = len(file_entries)
    if total_files == 0:
        # An index with nothing in it must never be staged and promoted over a
        # populated one; tell the operator what was scanned.
        raise RuntimeError(
            f"No indexable files under {repo_path} (check exclude patterns, file size limits and the path itself); "
            "refusing to build an empty index"
        )

    if force_reindex:
        await postgres.delete_chunks(write_repo_id)
        if neo4j is not None:
            await neo4j.delete_graph(write_repo_id)
        if event_queue is not None:
            _emit_event(
                event_queue,
                {"type": "log", "message": "🧹 Cleared existing index (force_reindex=1)"},
                drop_oldest=True,
            )

    if skip_dense and event_queue is not None:
        _emit_event(
            event_queue,
            {
                "type": "log",
                "message": "⚡ skip_dense=1 → sparse-only vectors; no dense embeddings this run",
            },
            drop_oldest=True,
        )

    semantic_budget = (
        int(cfg.graph_indexing.semantic_kg_max_chunks)
        if cfg.graph_indexing.semantic_kg_enabled
        else 0
    )
    semantic_processed = 0
    semantic_entities_total = 0
    semantic_relations_total = 0
    semantic_empty_chunks = 0
    contextual_mode = (
        str(getattr(cfg.embedding, "contextual_chunk_embeddings", "off") or "off").strip().lower()
    )
    indexing_workers = max(1, int(getattr(cfg.indexing, "indexing_workers", 1) or 1))
    has_graph_upserts = bool(neo4j is not None and cfg.graph_indexing.build_lexical_graph)
    cross_file_chunk_batching = _allow_cross_file_chunk_batching(
        has_graph_upserts=has_graph_upserts,
        semantic_kg_enabled=bool(neo4j is not None and cfg.graph_indexing.semantic_kg_enabled),
    )
    pending_cross_file_chunks: list[Chunk] = []
    indexing_batch = max(10, int(getattr(cfg.indexing, "indexing_batch_size", 100) or 100))
    cross_file_flush_size = max(indexing_batch, indexing_batch * max(1, indexing_workers))

    async def _upsert_chunk_batch(chunks: list[Chunk]) -> list[Chunk]:
        nonlocal total_chunks, total_tokens
        if not chunks:
            return []
        total_chunks += len(chunks)
        chunk_tokens = sum(int(c.token_count or 0) for c in chunks)
        total_tokens += chunk_tokens
        INDEX_CHUNKS_CREATED_TOTAL.inc(len(chunks))
        INDEX_TOKENS_TOTAL.inc(chunk_tokens)

        if skip_dense:
            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="postgres_upsert_chunks").time():
                await postgres.upsert_chunks(write_repo_id, chunks)
            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="qdrant_write_chunks").time():
                await qdrant.write_chunks(
                    repo_id, qdrant_generation, chunks, embedding_dim=vector_dim
                )
            if neo4j is not None and cfg.graph_indexing.build_lexical_graph:
                batch_paths = {str(ch.file_path or "") for ch in chunks}
                if len(batch_paths) != 1:
                    raise RuntimeError("Lexical graph upserts require a single-file chunk batch")
                with INDEX_STAGE_LATENCY_SECONDS.labels(
                    stage="neo4j_upsert_document_chunks"
                ).time():
                    graph, lexical_graph_config = await write_lexical_graph_with_graphrag(
                        repo_id=write_repo_id,
                        run_id=run_id,
                        file_path=next(iter(batch_paths)),
                        chunks=chunks,
                    )
                    await neo4j.upsert_graphrag_graph(
                        write_repo_id,
                        graph,
                        lexical_graph_config=lexical_graph_config,
                    )
            return chunks

        assert embedder is not None
        if all(c.embedding is not None for c in chunks):
            embedded = chunks
        else:
            contextual_inputs: list[str] | None = None
            if contextual_mode == "prepend_context":
                contextual_inputs = [
                    (
                        f"[file_path={c.file_path}] [line_range={int(c.start_line)}-{int(c.end_line)}]\n"
                        f"{c.content}"
                    )
                    for c in chunks
                ]
            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="embed_chunks").time():
                embedded = await embedder.embed_chunks(chunks, embed_texts=contextual_inputs)
        with INDEX_STAGE_LATENCY_SECONDS.labels(stage="postgres_upsert_chunks").time():
            await postgres.upsert_chunks(write_repo_id, embedded)
        with INDEX_STAGE_LATENCY_SECONDS.labels(stage="qdrant_write_chunks").time():
            await qdrant.write_chunks(
                repo_id, qdrant_generation, embedded, embedding_dim=vector_dim
            )
        if neo4j is not None and cfg.graph_indexing.build_lexical_graph:
            batch_paths = {str(ch.file_path or "") for ch in embedded}
            if len(batch_paths) != 1:
                raise RuntimeError("Lexical graph upserts require a single-file chunk batch")
            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="neo4j_upsert_document_chunks").time():
                graph, lexical_graph_config = await write_lexical_graph_with_graphrag(
                    repo_id=write_repo_id,
                    run_id=run_id,
                    file_path=next(iter(batch_paths)),
                    chunks=embedded,
                )
                await neo4j.upsert_graphrag_graph(
                    write_repo_id,
                    graph,
                    lexical_graph_config=lexical_graph_config,
                )
        return embedded

    async def _upsert_chunk_batches(
        chunks: list[Chunk],
        *,
        _indexing_batch: int = indexing_batch,
        _indexing_workers: int = indexing_workers,
    ) -> list[Chunk]:
        if not chunks:
            return []
        batches = [
            chunks[i0 : i0 + _indexing_batch] for i0 in range(0, len(chunks), _indexing_batch)
        ]
        if not _allow_parallel_chunk_batches(
            indexing_workers=_indexing_workers,
            batch_count=len(batches),
            has_graph_upserts=has_graph_upserts,
        ):
            out: list[Chunk] = []
            for b in batches:
                out.extend(await _upsert_chunk_batch(b))
            return out

        sem = asyncio.Semaphore(_indexing_workers)
        results: list[list[Chunk] | None] = [None] * len(batches)

        async def _run_batch(i: int, batch: list[Chunk]) -> None:
            async with sem:
                results[i] = await _upsert_chunk_batch(batch)

        await asyncio.gather(*(_run_batch(i, batch) for i, batch in enumerate(batches)))
        merged: list[Chunk] = []
        for r in results:
            if r:
                merged.extend(r)
        return merged

    async def _flush_pending_cross_file_chunks(*, force: bool = False) -> None:
        nonlocal pending_cross_file_chunks
        if not cross_file_chunk_batching or not pending_cross_file_chunks:
            return
        while pending_cross_file_chunks and (
            force or len(pending_cross_file_chunks) >= cross_file_flush_size
        ):
            batch_len = len(pending_cross_file_chunks) if force else cross_file_flush_size
            batch = pending_cross_file_chunks[:batch_len]
            pending_cross_file_chunks = pending_cross_file_chunks[batch_len:]
            await _upsert_chunk_batches(batch)

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
                {
                    "type": "progress",
                    "percent": int((_STATUS[repo_id].progress) * 100),
                    "message": rel_path,
                    "current_file": rel_path,
                },
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

        # Large text files: allow a streaming ingestion mode to avoid loading the entire file into memory.
        ext_lower = abs_path.suffix.lower()
        stream_mode = (
            str(getattr(cfg.indexing, "large_file_mode", "read_all") or "read_all").strip().lower()
        )
        stream_block_chars = int(
            getattr(cfg.indexing, "large_file_stream_chunk_chars", 2_000_000) or 2_000_000
        )
        use_stream = (
            stream_mode == "stream"
            and ext_lower in {".txt", ".md", ".rst", ".log"}
            and size_bytes is not None
            and size_bytes >= stream_block_chars
        )

        # Chunks queued for semantic KG extraction during this file iteration.
        # Keep this as a per-iteration queue; reprocessing prior chunks on every
        # file causes quadratic work and makes indexing appear stalled.
        semantic_pending_chunks: list[Chunk] = []

        if use_stream:
            await _flush_pending_cross_file_chunks(force=True)

        if use_stream:
            base_char = 0
            base_line = 1
            ordinal = 0
            try:
                INDEX_FILES_PROCESSED_TOTAL.inc()
                with INDEX_STAGE_LATENCY_SECONDS.labels(stage="file_read_stream").time():
                    with abs_path.open("r", encoding="utf-8", errors="ignore") as f:
                        while True:
                            block = f.read(stream_block_chars)
                            if not block:
                                break
                            if "\x00" in block:
                                break
                            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="chunk").time():
                                chunks = chunker.chunk_text(
                                    rel_path,
                                    block,
                                    base_char_offset=base_char,
                                    base_line=base_line,
                                    starting_ordinal=ordinal,
                                )
                            ordinal += len(chunks)
                            base_char += len(block)
                            base_line += block.count("\n")
                            if not chunks:
                                continue
                            embedded_batches = await _upsert_chunk_batches(chunks)
                            if (
                                semantic_budget > 0
                                and semantic_processed < semantic_budget
                                and cfg.graph_indexing.semantic_kg_enabled
                                and neo4j is not None
                            ):
                                remaining = max(0, semantic_budget - semantic_processed)
                                semantic_pending_chunks.extend(embedded_batches[:remaining])
            except Exception as exc:
                INDEX_STAGE_ERRORS_TOTAL.labels(stage="file_read_stream").inc()
                _emit_event(
                    event_queue,
                    {
                        "type": "warning",
                        "message": f"Skipping file due to stream read/chunk failure: {rel_path} ({exc})",
                        "current_file": rel_path,
                    },
                    drop_oldest=True,
                )
                continue
        else:
            try:
                with INDEX_STAGE_LATENCY_SECONDS.labels(stage="file_read").time():
                    content = extract_text_for_path(
                        abs_path,
                        parquet_max_rows=int(
                            getattr(cfg.indexing, "parquet_extract_max_rows", 5000) or 5000
                        ),
                        parquet_max_chars=int(
                            getattr(cfg.indexing, "parquet_extract_max_chars", 2_000_000)
                            or 2_000_000
                        ),
                        parquet_max_cell_chars=int(
                            getattr(cfg.indexing, "parquet_extract_max_cell_chars", 20_000)
                            or 20_000
                        ),
                        parquet_text_columns_only=bool(
                            getattr(cfg.indexing, "parquet_extract_text_columns_only", True)
                        ),
                        parquet_include_column_names=bool(
                            getattr(cfg.indexing, "parquet_extract_include_column_names", True)
                        ),
                    )
                    if content is None:
                        content = abs_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as exc:
                INDEX_STAGE_ERRORS_TOTAL.labels(stage="file_read").inc()
                _emit_event(
                    event_queue,
                    {
                        "type": "warning",
                        "message": f"Skipping file due to read/extract failure: {rel_path} ({exc})",
                        "current_file": rel_path,
                    },
                    drop_oldest=True,
                )
                continue
            if "\x00" in content:
                continue

            # Local-only "late chunking": embed the full doc segment once, then pool per chunk span.
            # This is experimental and only applies when explicitly enabled via config.
            late_mode = (
                not skip_dense
                and str(
                    getattr(cfg.embedding, "embedding_backend", "deterministic") or "deterministic"
                )
                .strip()
                .lower()
                == "provider"
                and str(getattr(cfg.embedding, "contextual_chunk_embeddings", "off") or "off")
                .strip()
                .lower()
                == "late_chunking_local_only"
            )
            if late_mode:
                await _flush_pending_cross_file_chunks(force=True)
                from server.indexing.late_chunking import late_chunk_document

                strat = str(getattr(cfg.chunking, "chunking_strategy", "") or "").strip().lower()
                if strat not in {"fixed_tokens"}:
                    raise RuntimeError(
                        "late_chunking_local_only requires chunking.chunking_strategy='fixed_tokens'"
                    )
                with INDEX_STAGE_LATENCY_SECONDS.labels(stage="late_chunking").time():
                    chunks = late_chunk_document(
                        rel_path, content, chunking=cfg.chunking, embedding=cfg.embedding
                    )
                INDEX_FILES_PROCESSED_TOTAL.inc()
                if not chunks:
                    continue
                embedded_batches = await _upsert_chunk_batches(chunks)
                if (
                    semantic_budget > 0
                    and semantic_processed < semantic_budget
                    and cfg.graph_indexing.semantic_kg_enabled
                    and neo4j is not None
                ):
                    remaining = max(0, semantic_budget - semantic_processed)
                    semantic_pending_chunks.extend(embedded_batches[:remaining])
                continue

            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="chunk").time():
                chunks = chunker.chunk_file(rel_path, content)
            INDEX_FILES_PROCESSED_TOTAL.inc()
            if not chunks:
                continue
            extraction = extraction_method_for_path(abs_path)
            for chunk in chunks:
                chunk.metadata["extraction"] = extraction
            if cross_file_chunk_batching:
                pending_cross_file_chunks.extend(chunks)
                await _flush_pending_cross_file_chunks(force=False)
                continue
            embedded_batches = await _upsert_chunk_batches(chunks)
            if (
                semantic_budget > 0
                and semantic_processed < semantic_budget
                and cfg.graph_indexing.semantic_kg_enabled
                and neo4j is not None
            ):
                remaining = max(0, semantic_budget - semantic_processed)
                semantic_pending_chunks.extend(embedded_batches[:remaining])

        # Optional semantic KG extraction (typed entities + relations linked to chunk_ids).
        if (
            neo4j is not None
            and cfg.graph_indexing.semantic_kg_enabled
            and semantic_budget > 0
            and semantic_processed < semantic_budget
        ):
            try:
                remaining_budget = max(0, semantic_budget - semantic_processed)
                chunks_for_semantic = semantic_pending_chunks[:remaining_budget]
                if chunks_for_semantic:
                    semantic_processed += len(chunks_for_semantic)
                    semantic_route = _resolve_semantic_kg_route(cfg)
                    graphrag_result = await extract_semantic_kg_with_graphrag(
                        repo_id=write_repo_id,
                        run_id=run_id,
                        cfg=cfg,
                        chunks=chunks_for_semantic,
                        route_model=str(semantic_route.model or "").strip(),
                        route_base_url=str(semantic_route.base_url or "").strip(),
                        route_api_key=str(semantic_route.api_key or "").strip() or None,
                    )

                    with INDEX_STAGE_LATENCY_SECONDS.labels(
                        stage="neo4j_upsert_semantic_graph"
                    ).time():
                        await neo4j.upsert_graphrag_graph(
                            write_repo_id,
                            graphrag_result.graph,
                            lexical_graph_config=graphrag_result.lexical_graph_config,
                        )

                    semantic_entities_total += graphrag_result.entity_count
                    semantic_relations_total += graphrag_result.relationship_count
                    semantic_empty_chunks += graphrag_result.empty_chunks

                    if event_queue is not None:
                        _emit_event(
                            event_queue,
                            {
                                "type": "log",
                                "message": (
                                    "🧠 GraphRAG semantic batch: "
                                    f"chunks={graphrag_result.processed_chunks} "
                                    f"entities={graphrag_result.entity_count} "
                                    f"relations={graphrag_result.relationship_count} "
                                    f"empty_chunks={graphrag_result.empty_chunks}"
                                ),
                            },
                            drop_oldest=True,
                        )
            except Exception as exc:
                INDEX_STAGE_ERRORS_TOTAL.labels(stage="semantic_kg").inc()
                if bool(cfg.graph_indexing.semantic_kg_require_llm_success):
                    raise
                logger.warning(
                    "GraphRAG semantic extraction failed for repo_id=%s run_id=%s: %s",
                    repo_id,
                    run_id,
                    exc,
                    exc_info=True,
                )
                if event_queue is not None:
                    _emit_event(
                        event_queue,
                        {
                            "type": "warning",
                            "message": f"GraphRAG semantic extraction failed: {exc}",
                        },
                        drop_oldest=True,
                    )
            finally:
                # Important: only process each queued chunk once.
                semantic_pending_chunks.clear()

    await _flush_pending_cross_file_chunks(force=True)

    if neo4j is not None and cfg.graph_indexing.semantic_kg_enabled:
        # A semantic-KG build without communities is an incomplete graph; fail the
        # run (the staging resources are cleaned up) instead of promoting it.
        communities = await neo4j.detect_communities(write_repo_id)
        if event_queue is not None:
            _emit_event(
                event_queue,
                {"type": "log", "message": f"🧩 Graph communities detected: {len(communities)}"},
                drop_oldest=True,
            )

    if skip_dense:
        await postgres.update_corpus_embedding_meta(
            write_repo_id,
            backend="deterministic",
            provider="",
            model="",
            dimensions=0,
            sparse_contract=qdrant.sparse_contract,
        )
    else:
        assert embedder is not None
        await postgres.update_corpus_embedding_meta(
            write_repo_id,
            backend=str(cfg.embedding.embedding_backend or "deterministic"),
            provider=str(cfg.embedding.embedding_type or ""),
            model=str(cfg.embedding.effective_model or ""),
            dimensions=int(embedder.dim),
            sparse_contract=qdrant.sparse_contract,
        )
    # Invalidate semantic cache for this corpus after indexing to prevent stale
    # retrieval/generation payloads from pre-index content.
    try:
        await postgres.semantic_cache_clear_for_corpus(repo_id)
    except Exception:
        pass

    if event_queue is not None and cfg.graph_indexing.semantic_kg_enabled:
        _emit_event(
            event_queue,
            {
                "type": "log",
                "message": (
                    "🧠 GraphRAG summary: "
                    f"processed_chunks={semantic_processed} "
                    f"entities={semantic_entities_total} "
                    f"relations={semantic_relations_total} "
                    f"empty_chunks={semantic_empty_chunks}"
                ),
            },
            drop_oldest=True,
        )

    if total_chunks == 0:
        raise RuntimeError(
            f"{total_files} files were scanned under {repo_path} but produced no chunks; refusing to build an empty index"
        )
    stats = IndexStats(
        repo_id=repo_id,
        total_files=total_files,
        total_chunks=total_chunks,
        total_tokens=total_tokens,
        embedding_provider="" if skip_dense else str(cfg.embedding.embedding_type or ""),
        embedding_model="" if skip_dense else cfg.embedding.effective_model,
        embedding_dimensions=0 if skip_dense else (embedder.dim if embedder is not None else 0),
        last_indexed=datetime.now(UTC),
        file_breakdown=dict(file_breakdown),
    )
    # Not published to _STATS here: the caller publishes after the staged
    # Postgres/Qdrant/Neo4j resources have all been promoted, so a failed run
    # never reports staging numbers as the active index.
    return stats


async def _release_fence(repo_id: str, run_id: str) -> bool:
    cfg_release = await load_scoped_config(repo_id=repo_id)
    pg_release = PostgresClient(cfg_release.indexing.postgres_url)
    await pg_release.connect()
    try:
        return await pg_release.release_index_fence(repo_id, run_id)
    finally:
        with contextlib.suppress(Exception):
            await pg_release.disconnect()


def _classify_commit_outcome(
    *,
    promote_done: bool,
    promote_cancelled: bool,
    promote_exception: BaseException | None,
    manifest_names_run: bool | None,
) -> tuple[bool, bool]:
    """(committed, unknown) after the promotion await was interrupted.

    - The transaction task still pending: UNKNOWN (nothing read now is definitive).
    - It returned: committed.
    - It refused before writing (fence lost, tombstone, corrupt manifest): definitive negative.
    - Otherwise the manifest decides: True -> committed, False -> negative, None -> unknown.
    """
    if not promote_done:
        return False, True
    if not promote_cancelled and promote_exception is None:
        return True, False
    if isinstance(
        promote_exception,
        IndexFenceLostError | DeletionIncompleteError | PersistedStateCorruptError,
    ):
        return False, False
    if manifest_names_run is True:
        return True, False
    if manifest_names_run is False:
        return False, False
    return False, True


class _FenceHeartbeat(threading.Thread):
    """Heartbeats the durable fence from its own thread and event loop.

    Indexing work that blocks the API event loop (Docling extraction, large
    reads, CPU-heavy chunking) must never let a live run look dead to another
    worker, so the heartbeat does not share that loop.
    """

    def __init__(self, cfg: TriBridConfig, repo_id: str, run_id: str) -> None:
        super().__init__(name=f"index-fence-heartbeat:{repo_id}", daemon=True)
        self._cfg = cfg
        self._repo_id = repo_id
        self._run_id = run_id
        # NOT `_stop`: threading.Thread owns a private `_stop()` used by join().
        self._halt = threading.Event()
        self.fence_lost = threading.Event()

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        interval = heartbeat_interval_seconds(self._cfg.indexing.index_run_lease_seconds)
        while not self._halt.wait(interval):
            try:
                alive = asyncio.run(self._beat())
            except Exception as exc:
                logger.warning(
                    "fence heartbeat for %s run %s failed: %s", self._repo_id, self._run_id, exc
                )
                continue
            if not alive:
                logger.error(
                    "index run %s lost the fence on %s (released, taken over after a stale heartbeat, "
                    "or cleared by a deletion); it will not commit",
                    self._run_id,
                    self._repo_id,
                )
                self.fence_lost.set()
                return

    async def _beat(self) -> bool:
        # The process-wide asyncpg pool belongs to the API loop; this thread's loop
        # opens its own short-lived connection instead.
        return await PostgresClient.heartbeat_index_fence_standalone(
            self._cfg.indexing.postgres_url, self._repo_id, self._run_id
        )


def _publish_commit_unknown(
    *, repo_id: str, run_id: str, started_at: datetime, queue: asyncio.Queue[dict[str, Any]]
) -> None:
    """The promotion was interrupted and the manifest could not be read back: say so, touch nothing."""
    message = (
        f"Index run {run_id}: the promotion was interrupted and the corpus manifest could not be "
        "read back, so the commit outcome is not known yet. Staged resources were left in place; "
        "the run stays non-terminal and is reconciled against the manifest on the next status read."
    )
    prev = _STATUS.get(repo_id)
    _STATUS_RUN_ID[repo_id] = run_id
    _STATUS[repo_id] = IndexStatus(
        repo_id=repo_id,
        status="indexing",
        progress=float(prev.progress) if prev else 0.0,
        current_file=None,
        error=message,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
    summary = IndexRunSummary(
        run_id=run_id,
        repo_id=repo_id,
        status="indexing",
        started_at=started_at,
        completed_at=None,
        progress=float(prev.progress) if prev else 0.0,
        error=message,
        total_files=0,
        total_chunks=0,
        total_tokens=0,
        embedding_provider=None,
        embedding_model=None,
        embedding_dimensions=None,
    )
    _UNKNOWN_COMMITS[repo_id] = run_id
    with contextlib.suppress(Exception):
        _persist_run_summary(summary)
    _emit_event(queue, {"type": "warning", "message": message}, guarantee=True)


async def _retire_due_generations(
    cfg: TriBridConfig,
    repo_id: str,
    run_id: str,
    generation: GenerationManifest,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    """Drop retired generations whose grace elapsed (exact ids), then prune them from the manifest.

    Best-effort: a failure leaves the entry on the manifest for the next commit
    to retry, never an inconsistent index.
    """
    pg_now = PostgresClient(cfg.indexing.postgres_url)
    try:
        await pg_now.connect()
        db_now = await pg_now.database_now()
    finally:
        with contextlib.suppress(Exception):
            await pg_now.disconnect()
    due = generation.due_for_retirement(
        now=db_now, grace_seconds=cfg.indexing.generation_retention_seconds
    )
    if not due:
        return
    qdrant = QdrantChunkStore(cfg)
    neo4j: Neo4jClient | None = None
    dropped = []
    try:
        for entry in due:
            ok = True
            if entry.qdrant_collection:
                try:
                    await qdrant.drop_generation(entry.qdrant_collection)
                except Exception as exc:
                    ok = False
                    logger.warning(
                        "retiring Qdrant generation %s of %s failed: %s",
                        entry.qdrant_collection,
                        repo_id,
                        exc,
                    )
            if entry.graph_repo_id:
                try:
                    if neo4j is None:
                        neo4j = Neo4jClient(
                            cfg.graph_storage.neo4j_uri,
                            cfg.graph_storage.neo4j_user,
                            cfg.graph_storage.resolve_password(),
                            database=cfg.graph_storage.resolve_database(repo_id),
                        )
                        await neo4j.connect()
                    await neo4j.delete_graph(entry.graph_repo_id)
                except Exception as exc:
                    ok = False
                    logger.warning(
                        "retiring graph generation %s of %s failed: %s",
                        entry.graph_repo_id,
                        repo_id,
                        exc,
                    )
            if ok:
                dropped.append(entry)
                _emit_event(
                    queue,
                    {
                        "type": "log",
                        "message": (
                            f"🧹 Retired generation {entry.run_id} "
                            f"(qdrant={entry.qdrant_collection or '-'} graph={entry.graph_repo_id or '-'})"
                        ),
                    },
                    drop_oldest=True,
                )
    finally:
        if neo4j is not None:
            with contextlib.suppress(Exception):
                await neo4j.disconnect()
    if not dropped:
        return
    pg = PostgresClient(cfg.indexing.postgres_url)
    try:
        await pg.connect()
        await pg.prune_retired_generations(repo_id, run_id, dropped=dropped)
    except Exception as exc:
        logger.warning("pruning retired generations of %s failed: %s", repo_id, exc)
    finally:
        with contextlib.suppress(Exception):
            await pg.disconnect()


def _publish_complete(
    *,
    repo_id: str,
    run_id: str,
    started_at: datetime,
    stats: IndexStats,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    """The manifest is committed: this run IS the live index, whatever happens afterwards."""
    _STATS[repo_id] = stats
    _STATUS_RUN_ID[repo_id] = run_id
    _STATUS[repo_id] = IndexStatus(
        repo_id=repo_id,
        status="complete",
        progress=1.0,
        current_file=None,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
    summary = IndexRunSummary(
        run_id=run_id,
        repo_id=repo_id,
        status="complete",
        started_at=started_at,
        completed_at=datetime.now(UTC),
        progress=1.0,
        error=None,
        total_files=int(getattr(stats, "total_files", 0) or 0),
        total_chunks=int(getattr(stats, "total_chunks", 0) or 0),
        total_tokens=int(getattr(stats, "total_tokens", 0) or 0),
        embedding_provider=str(getattr(stats, "embedding_provider", "") or ""),
        embedding_model=str(getattr(stats, "embedding_model", "") or ""),
        embedding_dimensions=int(getattr(stats, "embedding_dimensions", 0) or 0),
    )
    with contextlib.suppress(Exception):
        _persist_run_summary(summary)
    _emit_event(queue, {"type": "complete", "message": "✓ Indexing complete"}, guarantee=True)


async def _background_index_job(
    request: IndexRequest, queue: asyncio.Queue[dict[str, Any]], *, run_id: str
) -> None:
    """One index run; ``run_id`` is the fence this run holds on the corpus row (released in ``finally``)."""
    repo_id = request.repo_id
    staging_repo_id = _build_staging_repo_id(repo_id, run_id)
    started_at = datetime.now(UTC)
    this_task = asyncio.current_task()
    _ACTIVE_RUNS[repo_id] = run_id
    _UNKNOWN_COMMITS.pop(repo_id, None)  # any earlier unknown run is now the takeover's business
    _QUEUE_RUN_CONTEXT[id(queue)] = (repo_id, run_id)

    summary = IndexRunSummary(
        run_id=run_id,
        repo_id=repo_id,
        status="indexing",
        started_at=started_at,
        completed_at=None,
        progress=0.0,
        error=None,
        total_files=0,
        total_chunks=0,
        total_tokens=0,
        embedding_provider=None,
        embedding_model=None,
        embedding_dimensions=None,
    )
    with contextlib.suppress(Exception):
        _persist_run_summary(summary)

    qdrant: QdrantChunkStore | None = None
    qdrant_generation: str | None = None
    committed = False  # once the manifest is written, staged resources are the live ones
    commit_unknown = False  # promotion interrupted and the manifest unreadable: touch nothing
    stats: IndexStats | None = None
    complete_published = False
    heartbeat: _FenceHeartbeat | None = None
    staged_collection: str | None = None  # the name recorded on the fence BEFORE creation
    staged_graph_recorded: str | None = None  # the graph id recorded on the fence
    cleanup_recorded = True  # False only when an uncommitted run could not record its handoff

    def _publish_complete_once() -> None:
        nonlocal complete_published
        if complete_published or stats is None:
            return
        complete_published = True
        _publish_complete(
            repo_id=repo_id, run_id=run_id, started_at=started_at, stats=stats, queue=queue
        )

    try:
        INDEX_RUNS_TOTAL.inc()
        _emit_event(
            queue,
            {"type": "log", "message": f"🚀 Indexing started: {repo_id} (run_id={run_id})"},
            drop_oldest=True,
        )
        cfg = await load_scoped_config(repo_id=repo_id)
        heartbeat = _FenceHeartbeat(cfg, repo_id, run_id)
        heartbeat.start()
        # Every claim drains the durable reclaim backlog (a failed reclaim from an
        # earlier takeover is retried by the next normal run, never forgotten).
        await _drain_reclaim_backlog(cfg, repo_id)
        qdrant = QdrantChunkStore(cfg)
        vector_dim = (
            int(cfg.embedding.embedding_dim or 0)
            if cfg.indexing.skip_dense
            else int(Embedder(cfg.embedding, cfg.tokenization).dim)
        )
        # The fence names what this run is about to build BEFORE it exists, so a
        # crash at any later point can be reclaimed exactly.
        staged_collection = qdrant.generation_name(repo_id)
        staged_graph_recorded = staging_repo_id if cfg.graph_indexing.enabled else None
        pg_fence = PostgresClient(cfg.indexing.postgres_url)
        await pg_fence.connect()
        try:
            recorded = await pg_fence.record_fence_staging(
                repo_id,
                run_id,
                qdrant_collection=staged_collection,
                graph_repo_id=staged_graph_recorded,
            )
        finally:
            with contextlib.suppress(Exception):
                await pg_fence.disconnect()
        if not recorded:
            raise IndexFenceLostError(repo_id, run_id, None)
        qdrant_generation = await qdrant.create_generation(
            repo_id, embedding_dim=vector_dim, physical=staged_collection
        )
        _emit_event(
            queue,
            {
                "type": "log",
                "message": f"📦 Staged Qdrant generation {qdrant_generation} (dense + sparse)",
            },
            drop_oldest=True,
        )
        with INDEX_DURATION_SECONDS.time():
            stats = await _run_index(
                repo_id,
                request.repo_path,
                request.force_reindex,
                event_queue=queue,
                run_id=run_id,
                write_repo_id=staging_repo_id,
                qdrant=qdrant,
                qdrant_generation=qdrant_generation,
                cfg=cfg,
            )
        # Verify every staged resource BEFORE the commit: a partial vector index
        # or an empty staged graph must never become the active generation.
        staged_points = await qdrant.count_points(qdrant_generation)
        expected_points = int(getattr(stats, "total_chunks", 0) or 0)
        if staged_points != expected_points:
            raise RuntimeError(
                f"Staged Qdrant generation {qdrant_generation} holds {staged_points} points but the run "
                f"indexed {expected_points} chunks; refusing to promote a partial vector index"
            )
        # Graph participation is the decision recorded on the fence at the start
        # (the same config snapshot the build used), never a re-read flag: a flag
        # flipped mid-run can neither orphan a built graph nor demand an unbuilt one.
        graph_generation_id: str | None = None
        if staged_graph_recorded is not None:
            neo4j_verify = Neo4jClient(
                cfg.graph_storage.neo4j_uri,
                cfg.graph_storage.neo4j_user,
                cfg.graph_storage.resolve_password(),
                database=cfg.graph_storage.resolve_database(repo_id),
            )
            await neo4j_verify.connect()
            try:
                staged_graph = await neo4j_verify.get_graph_stats(staging_repo_id)
            finally:
                await neo4j_verify.disconnect()
            if (
                cfg.graph_indexing.build_lexical_graph
                and int(staged_graph.total_chunks or 0) != expected_points
            ):
                raise RuntimeError(
                    f"Staged graph {staging_repo_id} holds {staged_graph.total_chunks} chunk nodes but the run "
                    f"indexed {expected_points} chunks; refusing to promote a partial graph"
                )
            graph_generation_id = staging_repo_id

        # THE commit: one Postgres transaction swaps the chunk rows and writes
        # the generation manifest (Qdrant collection + Neo4j graph id) after
        # re-checking, under the row lock, that this run still holds the fence.
        # Readers resolve both stores from the manifest, so there is no per-store
        # swap and no window where new chunk rows pair with old vectors or graph.
        # The generation being replaced joins the manifest's retired list and
        # stays readable for indexing.generation_retention_seconds.
        if heartbeat is not None and heartbeat.fence_lost.is_set():
            raise IndexFenceLostError(repo_id, run_id, None)
        postgres = PostgresClient(cfg.indexing.postgres_url)
        await postgres.connect()
        try:
            active_corpus = await postgres.get_corpus(repo_id)
            active_name = str((active_corpus or {}).get("name") or repo_id)
            active_description = (active_corpus or {}).get("description")
            # The manifest is built INSIDE the promotion, from the row-locked
            # previous one, so nothing that appeared after this snapshot is lost.
            promote = asyncio.ensure_future(
                postgres.promote_staging_index(
                    active_repo_id=repo_id,
                    staging_repo_id=staging_repo_id,
                    active_name=active_name,
                    active_root_path=request.repo_path,
                    active_description=str(active_description)
                    if active_description is not None
                    else None,
                    run_id=run_id,
                    qdrant_collection=qdrant_generation,
                    graph_repo_id=graph_generation_id,
                )
            )
            try:
                with INDEX_STAGE_LATENCY_SECONDS.labels(stage="generation_commit").time():
                    generation = await asyncio.shield(promote)
                # Committed the instant the transaction returned: a cancellation
                # delivered anywhere after this (the disconnect below, the phase
                # write, retirement) must never read as "uncommitted".
                committed = True
                promoted_collection = qdrant_generation
                qdrant_generation = None  # owned by the manifest now; never dropped as "staged"
            except BaseException:
                # The transaction may have committed although this await did not
                # return normally (cancellation delivered on the way back, or the
                # connection lost after COMMIT). Never clean staged resources on
                # a guess: the outcome is UNKNOWN from this instant, and only a
                # definitive negative (the manifest read back and does not name
                # this run) clears that. A second cancellation delivered during
                # the reconciliation leaves the run unknown, never "staged".
                commit_unknown = True
                if not promote.done():
                    with contextlib.suppress(BaseException):
                        await asyncio.shield(promote)
                outcome: bool | None = None
                if promote.done() and (
                    promote.cancelled()
                    or (
                        promote.exception() is not None
                        and not isinstance(
                            promote.exception(),
                            IndexFenceLostError
                            | DeletionIncompleteError
                            | PersistedStateCorruptError,
                        )
                    )
                ):
                    try:
                        outcome = await asyncio.shield(_manifest_names_run(repo_id, run_id))
                    except PersistedStateCorruptError:
                        outcome = False  # promotion refuses a corrupt manifest: nothing was written
                    except BaseException:
                        outcome = None
                committed, commit_unknown = _classify_commit_outcome(
                    promote_done=promote.done(),
                    promote_cancelled=promote.done() and promote.cancelled(),
                    promote_exception=(
                        promote.exception() if promote.done() and not promote.cancelled() else None
                    ),
                    manifest_names_run=outcome,
                )
                # A second cancellation interrupted the wait while the transaction is
                # STILL running: unknown (resources and fence are kept; the fence
                # expires into a manifest-aware takeover).
                raise
        finally:
            with contextlib.suppress(Exception):
                await postgres.disconnect()
        _emit_event(
            queue,
            {
                "type": "log",
                "message": (
                    f"⚡ Generation {run_id} committed: chunks={expected_points} "
                    f"qdrant={promoted_collection} graph={graph_generation_id or 'off'} "
                    f"retained={len(generation.retired)}"
                ),
                "meta": {"stage": "generation_commit", "points": expected_points},
            },
            drop_oldest=True,
        )
        # The run is complete the moment the manifest is committed: publish it
        # before any best-effort retirement so a failure or cancellation there
        # can never report a live generation as failed or cancelled.
        _publish_complete_once()
        # Durable phase: anyone watching the fence sees "retiring" (the commit is
        # done; only best-effort retirement remains).
        with contextlib.suppress(Exception):
            pg_phase = PostgresClient(cfg.indexing.postgres_url)
            await pg_phase.connect()
            try:
                await pg_phase.record_fence_phase(repo_id, run_id, "retiring")
            finally:
                await pg_phase.disconnect()
        await _retire_due_generations(cfg, repo_id, run_id, generation, queue)
        # Update process-level “size” gauges (best-effort; no per-corpus labels).
        try:
            CHUNKS_INDEXED_CURRENT.set(int(getattr(stats, "total_chunks", 0) or 0))
        except Exception:
            pass
        try:
            if not graph_generation_id:
                # No graph in this generation: never read a stale legacy graph
                # stored under the corpus id as if it were current.
                GRAPH_ENTITIES_CURRENT.set(0)
                GRAPH_RELATIONSHIPS_CURRENT.set(0)
            else:
                db_name = cfg.graph_storage.resolve_database(repo_id)
                neo4j = Neo4jClient(
                    cfg.graph_storage.neo4j_uri,
                    cfg.graph_storage.neo4j_user,
                    cfg.graph_storage.resolve_password(),
                    database=db_name,
                )
                await neo4j.connect()
                try:
                    gstats = await neo4j.get_graph_stats(graph_generation_id)
                    GRAPH_ENTITIES_CURRENT.set(int(getattr(gstats, "total_entities", 0) or 0))
                    GRAPH_RELATIONSHIPS_CURRENT.set(
                        int(getattr(gstats, "total_relationships", 0) or 0)
                    )
                finally:
                    await neo4j.disconnect()
        except Exception:
            # Never fail indexing due to gauge update issues.
            pass
    except asyncio.CancelledError:
        if committed:
            # The manifest already names this run's generation: the index is live
            # and the cancellation only interrupted best-effort retirement. The
            # run's terminal state is complete, whatever the caller wrote.
            _CANCELLED_AFTER_COMMIT[repo_id] = run_id
            _publish_complete_once()
            _emit_event(
                queue,
                {"type": "log", "message": "Cancellation after commit: the new generation is live"},
                drop_oldest=True,
            )
            return
        if commit_unknown:
            _publish_commit_unknown(
                repo_id=repo_id, run_id=run_id, started_at=started_at, queue=queue
            )
            raise
        # Staged cleanup is durable: the run's EXACT recorded inventory goes to the
        # reclaim backlog first, then the exact reclaim runs (shielded: a second
        # cancellation cannot leave half-cleaned resources unrecorded). If the
        # handoff itself could not be recorded, the fence (which names the same
        # inventory) is kept for the stale takeover.
        cleanup_recorded = await _reclaim_own_staged_shielded(
            repo_id, run_id, staged_collection, staged_graph_recorded
        )
        # Cancelled tasks cannot rely on direct awaits for cleanup, so shield
        # invalidation to let it continue even while this task is cancelled.
        try:
            await asyncio.shield(_clear_semantic_cache_for_repo(repo_id))
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        prev = _STATUS.get(repo_id)
        _STATUS[repo_id] = IndexStatus(
            repo_id=repo_id,
            status="cancelled",
            progress=float(prev.progress) if prev else 0.0,
            current_file=prev.current_file if prev else None,
            error=None,
            started_at=prev.started_at if prev else started_at,
            completed_at=datetime.now(UTC),
        )
        summary = IndexRunSummary(
            run_id=run_id,
            repo_id=repo_id,
            status="cancelled",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            progress=float(prev.progress) if prev else 0.0,
            error=None,
            total_files=0,
            total_chunks=0,
            total_tokens=0,
            embedding_provider=None,
            embedding_model=None,
            embedding_dimensions=None,
        )
        with contextlib.suppress(Exception):
            _persist_run_summary(summary)
        _emit_event(queue, {"type": "cancelled", "message": "⚠ Indexing cancelled"}, guarantee=True)
        raise
    except Exception as e:
        if committed:
            logger.warning(
                "post-commit step failed for %s run %s (index is live): %s",
                repo_id,
                run_id,
                e,
                exc_info=True,
            )
            _publish_complete_once()
            _emit_event(
                queue,
                {"type": "warning", "message": f"Post-commit cleanup failed (index is live): {e}"},
                drop_oldest=True,
            )
            return
        if commit_unknown:
            _publish_commit_unknown(
                repo_id=repo_id, run_id=run_id, started_at=started_at, queue=queue
            )
            return
        # Staged cleanup is durable (backlog entry first, exact reclaim, cleared
        # only on confirmed success); an unrecorded handoff keeps the fence.
        cleanup_recorded = await _reclaim_own_staged_shielded(
            repo_id, run_id, staged_collection, staged_graph_recorded
        )
        # If indexing failed after deleting/updating chunks, stale cache entries can
        # point to content that no longer exists. Best-effort clear on errors.
        with contextlib.suppress(Exception):
            await _clear_semantic_cache_for_repo(repo_id)
        INDEX_ERRORS_TOTAL.inc()
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
        summary = IndexRunSummary(
            run_id=run_id,
            repo_id=repo_id,
            status="error",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            progress=float(prev.progress) if prev else 0.0,
            error=str(e),
            total_files=0,
            total_chunks=0,
            total_tokens=0,
            embedding_provider=None,
            embedding_model=None,
            embedding_dimensions=None,
        )
        with contextlib.suppress(Exception):
            _persist_run_summary(summary)
        _emit_event(queue, {"type": "error", "message": str(e)}, guarantee=True)
    finally:
        if heartbeat is not None:
            heartbeat.stop()
        # The release must survive a cancellation delivered while this `finally`
        # is awaiting (a stop that lands after the commit): shield it, and never
        # let it raise out of the cleanup. An unknown commit outcome keeps its
        # fence: it expires into a manifest-aware takeover that either finalizes
        # the run (it had committed) or reclaims its staged resources exactly.
        try:
            if commit_unknown:
                logger.warning(
                    "index run %s on %s keeps its fence: commit outcome unknown until the manifest is read",
                    run_id,
                    repo_id,
                )
                released = True
            elif not committed and not cleanup_recorded:
                logger.warning(
                    "index run %s on %s keeps its fence: its staged inventory could not be handed to the "
                    "reclaim backlog, so the fence stays the durable record until a takeover reclaims it",
                    run_id,
                    repo_id,
                )
                released = True
            else:
                released = await asyncio.shield(_release_fence(repo_id, run_id))
            if not released:
                logger.warning(
                    "index run %s did not hold the fence on %s at release (taken over or cleared)",
                    run_id,
                    repo_id,
                )
        except BaseException:
            logger.warning(
                "releasing the index-run fence of %s (run %s) was interrupted or failed; "
                "it expires after the lease",
                repo_id,
                run_id,
                exc_info=True,
            )
        # Avoid clearing a newer task/queue for the same repo if a new run already started.
        if _TASKS.get(repo_id) is this_task:
            _TASKS.pop(repo_id, None)
        _clear_runtime_state_for_repo(repo_id, queue=queue)


@router.post("/index/estimate", response_model=IndexEstimate)
async def estimate_index(request: IndexRequest) -> IndexEstimate:
    """Estimate indexing cost/time for a corpus before running the indexer."""
    repo_id = str(request.repo_id or "").strip()
    repo_path = str(request.repo_path or "").strip()
    if not repo_id:
        raise HTTPException(status_code=422, detail="repo_id is required")

    if not repo_path:
        # Best-effort: resolve from corpus registry.
        cfg_global = await load_scoped_config(repo_id=None)
        pg = PostgresClient(cfg_global.indexing.postgres_url)
        await pg.connect()
        try:
            corpus = await pg.get_corpus(repo_id)
            if corpus is not None:
                repo_path = str(corpus.get("path") or "").strip()
        finally:
            await pg.disconnect()

    if not repo_path:
        raise HTTPException(
            status_code=422, detail="repo_path is required (or create corpus first)"
        )

    cfg = await load_scoped_config(repo_id=repo_id)

    # Build ignore patterns from config (same as indexer).
    ignore_patterns: list[str] = []
    exts = (cfg.indexing.index_excluded_exts or "").split(",")
    for ext in exts:
        ext = ext.strip()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        ignore_patterns.append(f"*{ext}")

    # Enforce a strict max file size before reading/chunking (same as indexer).
    max_indexable_bytes = min(
        int(cfg.chunking.max_indexable_file_size),
        int(cfg.indexing.index_max_file_size_mb) * 1024 * 1024,
    )

    # Corpus-level exclude paths (stored in Postgres corpora.meta.exclude_paths).
    extra_gitignore_patterns: list[str] = []
    try:
        pg2 = PostgresClient(cfg.indexing.postgres_url)
        await pg2.connect()
        try:
            corpus = await pg2.get_corpus(repo_id)
            meta = (corpus.get("meta") or {}) if corpus else {}
            raw = meta.get("exclude_paths") if isinstance(meta, dict) else None
            if isinstance(raw, list):
                extra_gitignore_patterns = [str(x).strip() for x in raw if str(x).strip()]
        finally:
            await pg2.disconnect()
    except Exception:
        extra_gitignore_patterns = []

    loader = FileLoader(
        ignore_patterns=ignore_patterns, extra_gitignore_patterns=extra_gitignore_patterns
    )

    total_files = 0
    total_bytes = 0
    skipped_large_files = 0

    root = Path(repo_path).expanduser().resolve()
    if not root.exists():
        raise HTTPException(status_code=422, detail=f"repo_path not found: {repo_path}")

    for _rel, p in loader.iter_repo_files(str(root)):
        try:
            size_bytes = int(p.stat().st_size)
        except Exception:
            size_bytes = 0
        if size_bytes > max_indexable_bytes:
            skipped_large_files += 1
            continue
        total_files += 1
        total_bytes += max(0, size_bytes)

    est_tokens = _estimate_tokens_from_bytes(total_bytes)
    est_chunks = _estimate_chunks_from_tokens(
        tokens=est_tokens,
        target_tokens=int(getattr(cfg.chunking, "target_tokens", 512) or 512),
        overlap_tokens=int(getattr(cfg.chunking, "overlap_tokens", 64) or 64),
    )

    skip_dense = bool(getattr(cfg.indexing, "skip_dense", False))
    embedding_backend = str(
        getattr(cfg.embedding, "embedding_backend", "deterministic") or "deterministic"
    ).strip()
    embedding_provider = str(getattr(cfg.embedding, "embedding_type", "") or "").strip()
    embedding_model = str(getattr(cfg.embedding, "effective_model", "") or "").strip()

    semantic_kg_enabled = bool(cfg.graph_indexing.semantic_kg_enabled)
    semantic_kg_chunks = (
        min(est_chunks, max(0, int(cfg.graph_indexing.semantic_kg_max_chunks or 0)))
        if semantic_kg_enabled
        else 0
    )
    semantic_model, semantic_provider_hint = _resolve_semantic_kg_model_and_provider(cfg)

    # Pricing (models.json): deterministic backend and skip_dense imply $0 external embedding cost.
    embedding_cost: float | None
    if skip_dense or embedding_backend != "provider":
        embedding_cost = 0.0
    else:
        embedding_cost = _estimate_embedding_cost_usd(
            provider=embedding_provider,
            model=embedding_model,
            total_tokens=est_tokens,
        )

    semantic_kg_cost: float | None = None
    if semantic_kg_enabled:
        semantic_kg_cost = _estimate_semantic_kg_cost_usd(
            provider_hint=semantic_provider_hint,
            model=semantic_model,
            chunks_in_scope=semantic_kg_chunks,
            enrich_max_chars=int(cfg.enrichment.enrich_max_chars or 1000),
        )

    total_cost: float | None
    if semantic_kg_enabled:
        total_cost = (
            None
            if embedding_cost is None or semantic_kg_cost is None
            else float(embedding_cost) + float(semantic_kg_cost)
        )
    else:
        total_cost = embedding_cost

    # Time estimate (rough): embedding throughput + optional semantic KG extraction phase + overhead.
    est_low: float | None = None
    est_high: float | None = None
    estimated_seconds_semantic_kg: float | None = None
    assumptions: list[str] = [
        f"tokens≈bytes/{_EST_BYTES_PER_TOKEN:g}",
        "time range is a heuristic (very rough)",
    ]
    if skipped_large_files > 0:
        assumptions.append(f"skips files > {max_indexable_bytes} bytes")

    if skip_dense:
        tps = _EST_TOKENS_PER_SECOND_DETERMINISTIC
        assumptions.append("skip_dense=1 → dense embedding phase skipped")
    elif embedding_backend != "provider":
        tps = _EST_TOKENS_PER_SECOND_DETERMINISTIC
        assumptions.append("embedding_backend=deterministic → $0 external cost")
    else:
        if _looks_cloud_provider(embedding_provider):
            tps = _EST_TOKENS_PER_SECOND_CLOUD
            assumptions.append(f"embedding tokens/sec≈{tps:,} (cloud heuristic)")
        else:
            tps = _estimate_local_tokens_per_second(cfg=cfg, provider=embedding_provider)
            override_tps = getattr(cfg.indexing, "estimated_tokens_per_second_local", None)
            if override_tps is not None and int(override_tps or 0) > 0:
                assumptions.append(
                    f"embedding tokens/sec≈{tps:,} (indexing.estimated_tokens_per_second_local override)"
                )
            else:
                assumptions.append(
                    f"embedding tokens/sec≈{tps:,} (local hardware={_detect_local_hardware_class()} provider={embedding_provider or 'local'})"
                )

    if est_tokens > 0 and tps > 0:
        base_embedding_seconds = float(est_tokens) / float(tps)
        base_total_seconds = base_embedding_seconds
        if semantic_kg_enabled and semantic_kg_chunks > 0:
            semantic_provider_for_time = semantic_provider_hint
            resolved_semantic_spec = _find_model_spec(
                _load_models_json(),
                provider=semantic_provider_hint,
                model=semantic_model,
            )
            if resolved_semantic_spec is not None:
                semantic_provider_for_time = str(
                    resolved_semantic_spec.get("provider") or semantic_provider_for_time
                )
            estimated_seconds_semantic_kg = _estimate_semantic_kg_seconds(
                provider=semantic_provider_for_time,
                chunks_in_scope=semantic_kg_chunks,
                indexing_workers=int(getattr(cfg.indexing, "indexing_workers", 1) or 1),
            )
            base_total_seconds += float(estimated_seconds_semantic_kg)
            assumptions.append(
                f"semantic_graphrag≈{semantic_kg_chunks:,} chunks using {semantic_provider_for_time or 'unknown'}"
            )
        est_low = max(
            0.0, (base_total_seconds * _EST_RANGE_LOW_MULT) + float(_EST_OVERHEAD_SECONDS)
        )
        est_high = max(
            est_low,
            (base_total_seconds * _EST_RANGE_HIGH_MULT) + float(_EST_OVERHEAD_SECONDS) * 2.0,
        )

    return IndexEstimate(
        repo_id=repo_id,
        repo_path=str(root),
        total_files=int(total_files),
        total_size_bytes=int(total_bytes),
        skipped_large_files=int(skipped_large_files),
        estimated_total_tokens=int(est_tokens),
        estimated_total_chunks=int(est_chunks),
        embedding_backend="provider" if embedding_backend == "provider" else "deterministic",
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        skip_dense=bool(skip_dense),
        embedding_cost_usd=embedding_cost,
        semantic_kg_cost_usd=semantic_kg_cost,
        total_cost_usd=total_cost,
        estimated_seconds_low=est_low,
        estimated_seconds_high=est_high,
        estimated_seconds_semantic_kg=estimated_seconds_semantic_kg,
        assumptions=assumptions,
    )


@router.post(
    "/index",
    response_model=IndexStatus,
    responses={
        404: {"description": "Unknown corpus"},
        409: {
            "model": IndexRunConflictResponse | PersistedStateCorruptResponse,
            "description": (
                "An index run already holds this corpus (durable per-corpus run fence), or its "
                "persisted index state is malformed (de-index to repair)."
            ),
        },
        503: {
            "model": DependencyUnavailableResponse | IndexDeletionIncompleteResponse,
            "description": "Postgres is unavailable, or the corpus is being de-indexed.",
        },
    },
)
async def start_index(request: IndexRequest) -> IndexStatus:
    # Fail closed on a path the API cannot read: the loader yields nothing for a
    # missing root and the run would otherwise "complete" with zero files.
    root = Path(str(request.repo_path or "")).expanduser()
    if not str(request.repo_path or "").strip() or not root.is_dir():
        raise HTTPException(
            status_code=400, detail=f"repo_path is not a readable directory: {request.repo_path}"
        )
    global _LAST_STARTED_REPO

    started_at = datetime.now(UTC)
    run_id = f"{started_at.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:10]}"
    # Durable per-corpus run fence (compare-and-set on the corpus row): a second
    # worker or process cannot build and retire against the same corpus.
    cfg = await load_scoped_config(repo_id=request.repo_id)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    claim: FenceClaim | None = None
    try:
        try:
            await postgres.connect()
            claim = await postgres.acquire_index_fence(
                request.repo_id,
                run_id,
                started_at=started_at,
                owner=fence_owner(),
                lease_seconds=cfg.indexing.index_run_lease_seconds,
            )
        except CorpusNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except IndexFenceCorruptError as exc:
            raise _fence_corrupt_conflict(request.repo_id, exc) from exc
        except DeletionIncompleteError:
            raise
        except Exception as exc:
            raise_postgres_unavailable_if_applicable(exc, boundary="Index run fence")
            raise
        finally:
            with contextlib.suppress(Exception):
                await postgres.disconnect()
        if claim.held_by is not None:
            raise _index_run_conflict(request.repo_id, claim.held_by)
        if claim.taken_over is not None and claim.taken_over_committed:
            # The previous holder committed and then died before releasing: its
            # staged resources ARE the live generation. Finalize its run record;
            # never reclaim.
            await _finalize_dead_committed_run(request.repo_id, claim.taken_over.run_id)
        # A dead run's staged inventory (moved to the durable backlog by the takeover
        # transaction, or left by an earlier failed reclaim) is drained by the
        # background job itself, after its heartbeat is running.
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

        task = asyncio.create_task(_background_index_job(request, queue, run_id=run_id))
        _TASKS[request.repo_id] = task
    except BaseException:
        # Anything failing (or a request cancelled) between a successful claim and
        # the job's start releases the fence again: no orphan claim that holds the
        # corpus until the lease expires. Shielded, so a cancellation delivered
        # here cannot interrupt the release itself.
        if claim is not None and claim.acquired:
            with contextlib.suppress(BaseException):
                await asyncio.shield(_release_fence(request.repo_id, run_id))
        raise
    return _STATUS[request.repo_id]


@router.post("/index/{corpus_id}/stop", response_model=IndexStatus)
async def stop_index_for_corpus(corpus_id: str) -> IndexStatus:
    """Cancel an active indexing run for a specific corpus."""
    repo_id = str(corpus_id or "").strip()
    if not repo_id:
        raise HTTPException(status_code=422, detail="corpus_id is required")
    return await _cancel_index_run(repo_id)


@router.get(
    "/index/status",
    response_model=DashboardIndexStatusResponse,
    responses={
        409: {
            "model": IndexRunConflictResponse | PersistedStateCorruptResponse,
            "description": "A malformed fence (index_fence_corrupt) or malformed persisted index state: manifest, tombstone, fence or reclaim backlog (persisted_state_corrupt).",
        },
        503: {
            "model": DependencyUnavailableResponse | IndexDeletionIncompleteResponse,
            "description": "Postgres is unavailable, or the corpus is being de-indexed.",
        },
    },
)
async def get_dashboard_index_status(
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> DashboardIndexStatusResponse:
    """Dashboard index summary (legacy-compatible endpoint).

    This endpoint exists for the Dashboard System tab's full index summary panel.
    It is distinct from the corpus-scoped `/api/index/{corpus_id}/status` endpoint.
    """
    repo_id = await _resolve_dashboard_repo_id(scope)

    # Durable first: the row's index state must validate (typed 409/503 otherwise),
    # then a fresh fence held anywhere means the corpus is being indexed; this
    # process's state only refines it.
    s = _STATUS.get(repo_id)
    try:
        with contextlib.suppress(CorpusNotFoundError):
            await _read_index_state(repo_id, await load_scoped_config(repo_id=repo_id))
        live = await _live_fence(repo_id)
    except IndexFenceCorruptError as exc:
        raise _fence_corrupt_conflict(repo_id, exc) from exc
    # A fresh fence anywhere means running; this process's state refines it only
    # for the run the fence names.
    running = live is not None
    progress = float(s.progress) if s is not None else None
    current_file = s.current_file if s is not None else None

    # Corpus metadata (name/branch/keywords)
    cfg_global = await load_scoped_config(repo_id=None)
    pg = PostgresClient(cfg_global.indexing.postgres_url)
    await pg.connect()
    try:
        corpus = await pg.get_corpus(repo_id)
    finally:
        await pg.disconnect()

    current_repo = str((corpus or {}).get("name") or repo_id)
    meta = (corpus or {}).get("meta") or {}
    current_branch = str(meta.get("branch") or "") or None
    keywords = meta.get("keywords") if isinstance(meta, dict) else None
    keywords_count = len(keywords) if isinstance(keywords, list) else 0

    # Config + costs + storage breakdown (best-effort)
    cfg = await load_scoped_config(repo_id=repo_id)
    embedding_model = cfg.embedding.effective_model
    embedding_provider = cfg.embedding.embedding_type
    embedding_dim = int(cfg.embedding.embedding_dim)
    skip_dense = bool(getattr(cfg.indexing, "skip_dense", False))
    embedding_backend = str(
        getattr(cfg.embedding, "embedding_backend", "deterministic") or "deterministic"
    ).strip()
    total_tokens = 0
    total_chunks = 0
    try:
        pg2 = PostgresClient(cfg.indexing.postgres_url)
        await pg2.connect()
        try:
            stats = await pg2.get_index_stats(repo_id)
            total_chunks = int(stats.total_chunks or 0)
            total_tokens = int(stats.total_tokens or 0)
        finally:
            await pg2.disconnect()
    except Exception:
        total_chunks = 0
        total_tokens = 0

    embedding_cost: float | None
    if skip_dense or embedding_backend != "provider":
        embedding_cost = 0.0
    else:
        embedding_cost = _estimate_embedding_cost_usd(
            provider=embedding_provider,
            model=embedding_model,
            total_tokens=total_tokens,
        )

    semantic_kg_cost: float | None = None
    total_cost: float | None = embedding_cost
    semantic_kg_enabled = bool(cfg.graph_indexing.semantic_kg_enabled)
    if semantic_kg_enabled:
        semantic_model, semantic_provider_hint = _resolve_semantic_kg_model_and_provider(cfg)
        semantic_chunks = min(
            total_chunks, max(0, int(cfg.graph_indexing.semantic_kg_max_chunks or 0))
        )
        semantic_kg_cost = _estimate_semantic_kg_cost_usd(
            provider_hint=semantic_provider_hint,
            model=semantic_model,
            chunks_in_scope=semantic_chunks,
            enrich_max_chars=int(cfg.enrichment.enrich_max_chars or 1000),
        )
        total_cost = (
            None
            if embedding_cost is None or semantic_kg_cost is None
            else float(embedding_cost) + float(semantic_kg_cost)
        )

    storage_breakdown = await _compute_dashboard_storage_breakdown(repo_id=repo_id)

    metadata = DashboardIndexStatusMetadata(
        repo_id=repo_id,
        current_repo=current_repo,
        current_branch=current_branch,
        timestamp=datetime.now(UTC),
        embedding_config=DashboardEmbeddingConfigSummary(
            provider=embedding_provider,
            model=embedding_model,
            dimensions=embedding_dim,
            precision="float32",
        ),
        costs=DashboardIndexCosts(
            total_tokens=total_tokens,
            embedding_cost=embedding_cost,
            semantic_kg_cost=semantic_kg_cost,
            total_cost=total_cost,
        ),
        storage_breakdown=storage_breakdown,
        keywords_count=keywords_count,
        total_storage=int(storage_breakdown.total_storage_bytes),
    )

    lines: list[str] = []
    if s is not None and s.status == "error":
        lines = [f"Index error: {s.error or 'unknown error'}"]
    elif running:
        pct = int((progress or 0.0) * 100)
        lines = [f"Indexing… {pct}%"]
        if current_file:
            lines.append(current_file)
    elif s is not None and s.status == "complete":
        lines = ["✓ Indexing complete"]
    else:
        lines = ["Ready to index…"]

    return DashboardIndexStatusResponse(
        lines=lines,
        metadata=metadata,
        running=running,
        progress=progress,
        current_file=current_file,
    )


@router.get(
    "/index/stats",
    response_model=DashboardIndexStatsResponse,
    responses={
        409: {
            "model": IndexRunConflictResponse | PersistedStateCorruptResponse,
            "description": "A malformed fence (index_fence_corrupt) or malformed persisted index state: manifest, tombstone, fence or reclaim backlog (persisted_state_corrupt).",
        },
        503: {
            "model": DependencyUnavailableResponse | IndexDeletionIncompleteResponse,
            "description": "Postgres is unavailable, or the corpus is being de-indexed.",
        },
    },
)
async def get_dashboard_index_stats(
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> DashboardIndexStatsResponse:
    """Dashboard storage metrics (legacy-compatible endpoint)."""
    repo_id = await _resolve_dashboard_repo_id(scope)

    # The row's index state must validate before any storage figure is served.
    try:
        with contextlib.suppress(CorpusNotFoundError):
            await _read_index_state(repo_id, await load_scoped_config(repo_id=repo_id))
    except IndexFenceCorruptError as exc:
        raise _fence_corrupt_conflict(repo_id, exc) from exc

    cfg_global = await load_scoped_config(repo_id=None)
    pg = PostgresClient(cfg_global.indexing.postgres_url)
    await pg.connect()
    try:
        corpus = await pg.get_corpus(repo_id)
    finally:
        await pg.disconnect()

    meta = (corpus or {}).get("meta") or {}
    keywords = meta.get("keywords") if isinstance(meta, dict) else None
    keywords_count = len(keywords) if isinstance(keywords, list) else 0

    storage_breakdown = await _compute_dashboard_storage_breakdown(repo_id=repo_id)

    return DashboardIndexStatsResponse(
        repo_id=repo_id,
        storage_breakdown=storage_breakdown,
        keywords_count=keywords_count,
        total_storage=int(storage_breakdown.total_storage_bytes),
    )


@router.get(
    "/index/{corpus_id}/runs/latest",
    response_model=IndexRunSummary,
    responses={
        409: {
            "model": IndexRunConflictResponse | PersistedStateCorruptResponse,
            "description": "A malformed fence (index_fence_corrupt) or malformed persisted index state: manifest, tombstone, fence or reclaim backlog (persisted_state_corrupt).",
        },
        503: {
            "model": DependencyUnavailableResponse | IndexDeletionIncompleteResponse,
            "description": "Postgres is unavailable, or the corpus is being de-indexed.",
        },
    },
)
async def get_latest_index_run(corpus_id: str) -> IndexRunSummary:
    repo_id = str(corpus_id or "").strip()
    if not repo_id:
        raise HTTPException(status_code=422, detail="corpus_id is required")
    # The row's index state must validate BEFORE any answer, the 404 included: a
    # malformed row is a typed 409 whether or not a summary exists.
    try:
        with contextlib.suppress(CorpusNotFoundError):
            await _read_index_state(repo_id, await load_scoped_config(repo_id=repo_id))
    except IndexFenceCorruptError as exc:
        raise _fence_corrupt_conflict(repo_id, exc) from exc
    await _flush_run_events()
    run = await asyncio.to_thread(_load_latest_run_summary, repo_id)
    if run is None:
        raise HTTPException(
            status_code=404, detail=f"No persisted index runs found for repo_id={repo_id}"
        )
    return await _finalize_interrupted_run(repo_id, run)


@router.get("/index/{corpus_id}/runs/{run_id}/events", response_model=list[IndexRunEvent])
async def get_index_run_events(
    corpus_id: str, run_id: str, limit: int = Query(default=200, ge=1, le=5000)
) -> list[IndexRunEvent]:
    repo_id = str(corpus_id or "").strip()
    rid = str(run_id or "").strip()
    if not repo_id:
        raise HTTPException(status_code=422, detail="corpus_id is required")
    if not rid:
        raise HTTPException(status_code=422, detail="run_id is required")
    await _flush_run_events()
    events = await asyncio.to_thread(_load_run_events, repo_id, rid, limit=limit)
    return events


@router.get(
    "/index/{corpus_id}/status",
    response_model=IndexStatus,
    responses={
        409: {
            "model": IndexRunConflictResponse | PersistedStateCorruptResponse,
            "description": "A malformed fence (index_fence_corrupt) or malformed persisted index state: manifest, tombstone, fence or reclaim backlog (persisted_state_corrupt).",
        },
        503: {
            "model": DependencyUnavailableResponse | IndexDeletionIncompleteResponse,
            "description": "Postgres is unavailable, or the corpus is being de-indexed.",
        },
    },
)
async def get_index_status(corpus_id: str) -> IndexStatus:
    """Durable truth first: tombstone, then the fence, then this process's state, then persisted runs."""
    repo_id = corpus_id
    try:
        cfg: TriBridConfig | None = await load_scoped_config(repo_id=repo_id)
    except CorpusNotFoundError:
        cfg = None  # persisted run summaries can outlive the corpus registration
    live: IndexRunFence | None = None
    current_manifest: GenerationManifest | None = None
    if cfg is not None:
        try:
            current_manifest = await _read_index_state(repo_id, cfg)
            live = await _live_fence(repo_id, cfg=cfg)
        except IndexFenceCorruptError as exc:
            raise _fence_corrupt_conflict(repo_id, exc) from exc
    local = _STATUS.get(repo_id)
    if live is not None:
        if (
            local is not None
            and local.status == "indexing"
            and repo_id in _TASKS
            and _ACTIVE_RUNS.get(repo_id) == live.run_id
        ):
            return local  # this process runs THAT run: progress is known
        # Another worker is indexing this corpus: the durable fence is the truth.
        return IndexStatus(
            repo_id=repo_id,
            status="indexing",
            progress=0.0,
            current_file=f"run {live.run_id} on {live.owner}",
            error=None,
            started_at=live.started_at,
            completed_at=None,
        )
    if local is not None and local.status != "indexing":
        # A terminal state this process remembers is only current while the
        # durable manifest still belongs to the run it describes.
        if cfg is not None and await _manifest_is_newer_than_local(repo_id, cfg, local):
            _STATUS.pop(repo_id, None)
            _STATUS_RUN_ID.pop(repo_id, None)
        else:
            return local
    await _flush_run_events()
    persisted_run = await asyncio.to_thread(_load_latest_run_summary, repo_id)
    if persisted_run is not None:
        persisted_run = await _finalize_interrupted_run(repo_id, persisted_run)
        if persisted_run.status == "complete" and cfg is not None and current_manifest is None:
            # A completed run is history, not current state, once another worker
            # de-indexed the corpus (no manifest): report idle, never a stale complete.
            return _idle_status(repo_id)
        return IndexStatus(
            repo_id=repo_id,
            status=persisted_run.status,
            progress=float(persisted_run.progress or 0.0),
            current_file=None,
            error=persisted_run.error,
            started_at=persisted_run.started_at,
            completed_at=persisted_run.completed_at,
        )
    # No run record: infer "complete" from the DURABLE index stats only (a
    # process-cached IndexStats could outlive another worker's de-index).
    try:
        if cfg is None:
            raise CorpusNotFoundError(f"Corpus not found: {repo_id}")
        postgres = PostgresClient(cfg.indexing.postgres_url)
        await postgres.connect()
        try:
            persisted = await postgres.get_index_stats(repo_id)
        finally:
            await postgres.disconnect()
        if int(getattr(persisted, "total_chunks", 0) or 0) > 0:
            return IndexStatus(
                repo_id=repo_id,
                status="complete",
                progress=1.0,
                current_file=None,
                error=None,
                started_at=None,
                completed_at=getattr(persisted, "last_indexed", None),
            )
    except Exception:
        pass
    return _idle_status(repo_id)


@router.get(
    "/index/{corpus_id}/stats",
    response_model=IndexStats,
    responses={
        409: {
            "model": IndexRunConflictResponse | PersistedStateCorruptResponse,
            "description": "A malformed fence (index_fence_corrupt) or malformed persisted index state: manifest, tombstone, fence or reclaim backlog (persisted_state_corrupt).",
        },
        503: {
            "model": DependencyUnavailableResponse | IndexDeletionIncompleteResponse,
            "description": "Postgres is unavailable, or the corpus is being de-indexed.",
        },
    },
)
async def get_index_stats(corpus_id: str) -> IndexStats:
    repo_id = corpus_id
    # Durable truth first: a corpus mid-de-index never serves cached stats, a
    # malformed row never serves stats at all, and a cached IndexStats from this
    # process never outlives another worker's promotion.
    try:
        await _read_index_state(repo_id, await load_scoped_config(repo_id=repo_id))
    except CorpusNotFoundError:
        pass
    except IndexFenceCorruptError as exc:
        raise _fence_corrupt_conflict(repo_id, exc) from exc
    if repo_id in _STATS and repo_id in _TASKS:
        return _STATS[repo_id]
    # Read from Postgres (source of truth)
    cfg = await load_scoped_config(repo_id=None)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    stats = await postgres.get_index_stats(repo_id)
    if stats.total_chunks == 0:
        raise HTTPException(status_code=404, detail=f"No index found for repo_id={repo_id}")
    return stats


@router.delete(
    "/index/{corpus_id}",
    responses={
        409: {
            "model": IndexRunConflictResponse | PersistedStateCorruptResponse,
            "description": "A live index run holds this corpus (index_run_in_progress), or its persisted index state is malformed (index_fence_corrupt / persisted_state_corrupt).",
        },
        503: {
            "model": DependencyUnavailableResponse | IndexDeletionIncompleteResponse,
            "description": (
                "External cleanup failed; the deletion tombstone stays and the next delete retries "
                "exactly its targets."
            ),
        },
    },
)
async def delete_index(corpus_id: str) -> dict[str, Any]:
    repo_id = corpus_id
    if repo_id in _TASKS:
        await _cancel_index_run(repo_id)
    cfg = await load_scoped_config(repo_id=repo_id)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    try:
        # Postgres first, in one transaction (chunk rows + manifest + contracts):
        # the exact Qdrant collections and Neo4j graphs to drop are recorded as a
        # tombstone on the row, so a failure in the external stores below leaves a
        # corpus that reads as never indexed AND a retryable cleanup list, never a
        # manifest naming a dropped collection or an orphan nobody remembers.
        try:
            deleted_rows, tombstone = await postgres.delete_index_state(
                repo_id, lease_seconds=cfg.indexing.index_run_lease_seconds
            )
        except IndexFenceHeldError as exc:
            raise _index_run_conflict(repo_id, exc.fence) from exc
        except IndexFenceCorruptError as exc:
            raise _fence_corrupt_conflict(repo_id, exc) from exc
        except Exception as exc:
            raise_postgres_unavailable_if_applicable(exc, boundary="Index deletion")
            raise
        # This process's state for the corpus goes now, while the tombstone still
        # blocks any new start (a run claimed after the tombstone clears below must
        # never have its task/queue/markers erased by this request).
        _STATUS.pop(repo_id, None)
        _STATS.pop(repo_id, None)
        _TASKS.pop(repo_id, None)
        _EVENT_QUEUES.pop(repo_id, None)
        _STATUS_RUN_ID.pop(repo_id, None)
        _UNKNOWN_COMMITS.pop(repo_id, None)
        _CANCELLED_AFTER_COMMIT.pop(repo_id, None)
        with contextlib.suppress(Exception):
            await postgres.semantic_cache_clear_for_corpus(repo_id)
        try:
            deleted_collections = await drop_tombstoned_stores(cfg, repo_id, tombstone)
        except TombstoneCleanupError as exc:
            # The tombstone stays on the row: the next delete retries exactly these targets.
            raise dependency_unavailable_http_exception(
                exc.dependency, boundary="Index deletion", exc=exc
            ) from exc
        if not await postgres.clear_index_tombstone(repo_id, tombstone):
            # A concurrent deletion replaced the tombstone while this cleanup ran:
            # the corpus is still tombstoned, so this request did not complete it.
            newer = await postgres.get_index_tombstone(repo_id)
            if newer is not None:
                raise DeletionIncompleteError(repo_id, newer)
    finally:
        with contextlib.suppress(Exception):
            await postgres.disconnect()
    # Best-effort gauges (process-level; no per-corpus labels).
    # Reset to zero to avoid stale dashboards in single-corpus dev flows.
    try:
        CHUNKS_INDEXED_CURRENT.set(0)
        GRAPH_ENTITIES_CURRENT.set(0)
        GRAPH_RELATIONSHIPS_CURRENT.set(0)
    except Exception:
        pass
    return {
        "ok": True,
        "deleted_chunks": deleted_rows,
        "deleted_vector_collections": deleted_collections,
    }


@router.get("/stream/operations/index")
async def stream_index_operation(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> StreamingResponse:
    """SSE stream for indexing logs/progress (TerminalService.streamOperation compatibility)."""
    repo_id = (scope.resolved_repo_id or _LAST_STARTED_REPO or "").strip()
    if not repo_id:
        raise HTTPException(status_code=400, detail="Missing repo query parameter")
    queue = _EVENT_QUEUES.get(repo_id)
    task = _TASKS.get(repo_id)
    if queue is None or task is None or task.done():
        raise HTTPException(status_code=404, detail=f"No active stream for repo_id={repo_id}")

    async def _gen() -> AsyncGenerator[str, None]:
        # Immediately emit a status snapshot
        if repo_id in _STATUS:
            s = _STATUS[repo_id]
            yield f"data: {json.dumps({'type': 'progress', 'percent': int(s.progress * 100), 'message': s.current_file or ''})}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                active = _TASKS.get(repo_id)
                if active is None or active.done():
                    break
                continue
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") in {"complete", "error", "cancelled"}:
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
