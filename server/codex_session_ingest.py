from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import http.server
import json
import os
import re
import resource
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import torch
import yaml
from prometheus_client import (
    CollectorRegistry,
    Counter as PromCounter,
    Gauge,
    Histogram,
    ProcessCollector,
    PlatformCollector,
    generate_latest,
)
from sentence_transformers import SentenceTransformer

from server.db.postgres import PostgresClient
from server.indexing.tokenizer import TextTokenizer
from server.models.index import Chunk
from server.models.tribrid_config_model import TokenizationConfig


DEFAULT_POSTGRES_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/tribrid_rag"
DEFAULT_REMOTE_HOST = "192.168.68.173"
DEFAULT_REMOTE_LXC = 103
DEFAULT_GRAFANA_URL = "http://192.168.68.89:3000"
DEFAULT_METRICS_PORT = 9487
DEFAULT_METRICS_BIND = "0.0.0.0"
DEFAULT_STATE_DIR = Path("output/codex_session_ingest")
DEFAULT_MODEL = "nomic-ai/nomic-embed-text-v1.5"
DEFAULT_DIMENSIONS = 768
DEFAULT_TOKENIZER_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_TS_CONFIG = "english"
DEFAULT_JOB_NAME = "codex-session-ingest"
DEFAULT_DASHBOARD_UID = "codex-session-ingest"

ENCRYPTED_BLOB_RE = re.compile(r"\bgAAAAA[A-Za-z0-9_-]{32,}\b")
ABSOLUTE_PATH_RE = re.compile(r"(/Users/[^\s\"']+)")
EXIT_CODE_RE = re.compile(r"Process exited with code\s+(\d+)")
ERROR_SIGNAL_RE = re.compile(
    r"(traceback|exception|error:|failed|process exited with code [1-9]|http 4\d\d|http 5\d\d|unauthorized|forbidden|denied|timed out)",
    re.IGNORECASE,
)
TOOL_NAME_RE = re.compile(r"^[a-z0-9_.-]{2,128}$", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"[ \t]+")
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-9;]*[A-Za-z]")


class IngestFatalError(RuntimeError):
    def __init__(self, message: str, *, operator_hint: str, phase: str):
        super().__init__(message)
        self.operator_hint = operator_hint
        self.phase = phase


@dataclass
class RunConfig:
    session_root: Path
    state_dir: Path
    postgres_dsn: str
    year_filter: str
    semantic_repo_id: str
    artifact_repo_id: str
    metrics_bind: str
    metrics_port: int
    log_path: Path
    status_path: Path
    state_db_path: Path
    dead_letter_path: Path
    batch_size_semantic: int = 24
    batch_size_artifact: int = 96
    embedding_batch_size: int = 8
    embedding_model: str = DEFAULT_MODEL
    embedding_dimensions: int = DEFAULT_DIMENSIONS
    tokenizer_name: str = DEFAULT_TOKENIZER_NAME
    ts_config: str = DEFAULT_TS_CONFIG
    max_semantic_tokens: int = 256
    max_artifact_tokens: int = 384
    overlap_tokens: int = 32
    max_output_chars: int = 3000
    max_summary_paths: int = 10
    metrics_refresh_seconds: float = 5.0
    mps_batch_cooldown_ms: int = 80
    nice: int = 10
    torch_threads: int = 6
    force: bool = False
    limit_files: int = 0


@dataclass
class RemoteTelemetryConfig:
    remote_host: str
    remote_password: str
    lxc_id: int
    local_target_host: str
    local_target_port: int
    job_name: str
    grafana_url: str
    grafana_user: str
    grafana_password: str
    dashboard_uid: str = DEFAULT_DASHBOARD_UID
    dashboard_title: str = "Codex Session Ingest"


@dataclass
class NormalizedChunk:
    stream: str
    chunk: Chunk
    needs_embedding: bool


@dataclass
class StatusState:
    run_id: str
    mode: str
    started_at: str
    current_file: str = ""
    current_line: int = 0
    current_file_size_bytes: int = 0
    current_file_bytes_read: int = 0
    discovered_files: int = 0
    completed_files: int = 0
    skipped_files: int = 0
    semantic_chunks_written: int = 0
    artifact_chunks_written: int = 0
    summary_chunks_written: int = 0
    dead_letter_chunks: int = 0
    events_seen: int = 0
    errors: int = 0
    phase: str = "starting"
    shutdown_requested: bool = False
    last_error: str = ""
    operator_hint: str = ""
    model_name: str = DEFAULT_MODEL
    device: str = "unknown"
    last_updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "started_at": self.started_at,
            "current_file": self.current_file,
            "current_line": self.current_line,
            "current_file_size_bytes": self.current_file_size_bytes,
            "current_file_bytes_read": self.current_file_bytes_read,
            "current_file_progress_ratio": (
                float(self.current_file_bytes_read) / float(self.current_file_size_bytes)
                if self.current_file_size_bytes > 0
                else 0.0
            ),
            "discovered_files": self.discovered_files,
            "completed_files": self.completed_files,
            "skipped_files": self.skipped_files,
            "semantic_chunks_written": self.semantic_chunks_written,
            "artifact_chunks_written": self.artifact_chunks_written,
            "summary_chunks_written": self.summary_chunks_written,
            "dead_letter_chunks": self.dead_letter_chunks,
            "events_seen": self.events_seen,
            "errors": self.errors,
            "phase": self.phase,
            "shutdown_requested": self.shutdown_requested,
            "last_error": self.last_error,
            "operator_hint": self.operator_hint,
            "model_name": self.model_name,
            "device": self.device,
            "last_updated_at": self.last_updated_at,
        }


class JsonLogger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, level: str, event: str, **fields: Any) -> None:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": level,
            "event": event,
            **fields,
        }
        line = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        print(line, flush=True)


class MetricsRegistry:
    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        ProcessCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)

        self.service_up = Gauge(
            "codex_session_ingest_service_up",
            "Process health for the Codex session ingest worker.",
            registry=self.registry,
        )
        self.files_discovered_total = PromCounter(
            "codex_session_ingest_files_discovered_total",
            "Files discovered for ingestion.",
            registry=self.registry,
        )
        self.files_completed_total = PromCounter(
            "codex_session_ingest_files_completed_total",
            "Files fully processed.",
            registry=self.registry,
        )
        self.files_skipped_total = PromCounter(
            "codex_session_ingest_files_skipped_total",
            "Files skipped because they were unchanged or filtered.",
            ["reason"],
            registry=self.registry,
        )
        self.events_seen_total = PromCounter(
            "codex_session_ingest_events_seen_total",
            "Raw JSONL records seen by top-level type.",
            ["kind"],
            registry=self.registry,
        )
        self.events_indexed_total = PromCounter(
            "codex_session_ingest_events_indexed_total",
            "Normalized chunks emitted by stream and kind.",
            ["stream", "kind"],
            registry=self.registry,
        )
        self.events_skipped_total = PromCounter(
            "codex_session_ingest_events_skipped_total",
            "Records or text fragments skipped during normalization.",
            ["reason"],
            registry=self.registry,
        )
        self.chunks_written_total = PromCounter(
            "codex_session_ingest_chunks_written_total",
            "Chunks written to Postgres by stream.",
            ["stream"],
            registry=self.registry,
        )
        self.embedding_batches_total = PromCounter(
            "codex_session_ingest_embedding_batches_total",
            "Embedding batches executed.",
            registry=self.registry,
        )
        self.embedding_texts_total = PromCounter(
            "codex_session_ingest_embedding_texts_total",
            "Texts sent through the embedding model.",
            registry=self.registry,
        )
        self.db_writes_total = PromCounter(
            "codex_session_ingest_db_writes_total",
            "Postgres write phases executed.",
            ["phase"],
            registry=self.registry,
        )
        self.retries_total = PromCounter(
            "codex_session_ingest_retries_total",
            "Retries issued by phase.",
            ["phase"],
            registry=self.registry,
        )
        self.errors_total = PromCounter(
            "codex_session_ingest_errors_total",
            "Errors raised by phase and class.",
            ["phase", "kind"],
            registry=self.registry,
        )
        self.phase_seconds = Histogram(
            "codex_session_ingest_phase_seconds",
            "Latency by ingest phase.",
            ["phase"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
            registry=self.registry,
        )
        self.current_file_progress_ratio = Gauge(
            "codex_session_ingest_current_file_progress_ratio",
            "Progress through the currently active source file.",
            registry=self.registry,
        )
        self.current_file_size_bytes = Gauge(
            "codex_session_ingest_current_file_size_bytes",
            "Size of the currently active file.",
            registry=self.registry,
        )
        self.current_file_bytes_read = Gauge(
            "codex_session_ingest_current_file_bytes_read",
            "Bytes read from the current file.",
            registry=self.registry,
        )
        self.current_file_line = Gauge(
            "codex_session_ingest_current_file_line",
            "Current source line number.",
            registry=self.registry,
        )
        self.pending_files = Gauge(
            "codex_session_ingest_pending_files",
            "Files remaining in the current run plan.",
            registry=self.registry,
        )
        self.process_rss_bytes = Gauge(
            "codex_session_ingest_process_rss_bytes",
            "Resident set size of the ingest worker process.",
            registry=self.registry,
        )
        self.process_cpu_seconds = Gauge(
            "codex_session_ingest_process_cpu_seconds",
            "Process CPU time consumed by the ingest worker.",
            registry=self.registry,
        )
        self.embedding_model_info = Gauge(
            "codex_session_ingest_embedding_model_info",
            "Static marker for the embedding model and device in use.",
            ["provider", "model", "device"],
            registry=self.registry,
        )
        self.summary_files_referenced = Gauge(
            "codex_session_ingest_summary_files_referenced",
            "Count of unique file paths referenced in the active session summary.",
            registry=self.registry,
        )
        self.dead_letter_chunks_total = PromCounter(
            "codex_session_ingest_dead_letter_chunks_total",
            "Chunks dropped to a dead-letter file after all recovery attempts failed.",
            ["stream", "reason"],
            registry=self.registry,
        )


class StatusHandler(http.server.BaseHTTPRequestHandler):
    registry: MetricsRegistry
    status_ref: StatusState
    status_lock: threading.Lock

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/metrics":
            data = generate_latest(self.registry.registry)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if self.path in {"/healthz", "/status"}:
            with self.status_lock:
                payload = self.status_ref.to_json()
            body = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()


class MetricsHttpServer:
    def __init__(self, bind: str, port: int, registry: MetricsRegistry, status_ref: StatusState):
        self.status_lock = threading.Lock()
        self._server = http.server.ThreadingHTTPServer((bind, port), StatusHandler)
        StatusHandler.registry = registry
        StatusHandler.status_ref = status_ref
        StatusHandler.status_lock = self.status_lock
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class CheckpointStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ingest_runs (
              run_id TEXT PRIMARY KEY,
              mode TEXT NOT NULL,
              started_at TEXT NOT NULL,
              completed_at TEXT,
              status TEXT NOT NULL,
              config_json TEXT NOT NULL,
              discovered_files INTEGER NOT NULL DEFAULT 0,
              completed_files INTEGER NOT NULL DEFAULT 0,
              semantic_chunks INTEGER NOT NULL DEFAULT 0,
              artifact_chunks INTEGER NOT NULL DEFAULT 0,
              errors INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS source_files (
              path TEXT PRIMARY KEY,
              size_bytes INTEGER NOT NULL,
              mtime_ns INTEGER NOT NULL,
              status TEXT NOT NULL,
              processed_at TEXT,
              raw_events INTEGER NOT NULL DEFAULT 0,
              semantic_chunks INTEGER NOT NULL DEFAULT 0,
              artifact_chunks INTEGER NOT NULL DEFAULT 0,
              error_text TEXT NOT NULL DEFAULT ''
            );
            """
        )
        self._conn.commit()

    def start_run(self, run_id: str, mode: str, config_json: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO ingest_runs (run_id, mode, started_at, status, config_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, mode, datetime.now(UTC).isoformat(), "running", json.dumps(config_json, sort_keys=True)),
        )
        self._conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        discovered_files: int,
        completed_files: int,
        semantic_chunks: int,
        artifact_chunks: int,
        errors: int,
    ) -> None:
        self._conn.execute(
            """
            UPDATE ingest_runs
            SET completed_at = ?, status = ?, discovered_files = ?, completed_files = ?,
                semantic_chunks = ?, artifact_chunks = ?, errors = ?
            WHERE run_id = ?
            """,
            (
                datetime.now(UTC).isoformat(),
                status,
                int(discovered_files),
                int(completed_files),
                int(semantic_chunks),
                int(artifact_chunks),
                int(errors),
                run_id,
            ),
        )
        self._conn.commit()

    def file_is_fresh(self, path: Path, *, size_bytes: int, mtime_ns: int) -> bool:
        row = self._conn.execute(
            "SELECT size_bytes, mtime_ns, status FROM source_files WHERE path = ?",
            (str(path),),
        ).fetchone()
        if row is None:
            return False
        return (
            int(row["size_bytes"]) == int(size_bytes)
            and int(row["mtime_ns"]) == int(mtime_ns)
            and str(row["status"]) == "complete"
        )

    def mark_file_result(
        self,
        path: Path,
        *,
        size_bytes: int,
        mtime_ns: int,
        status: str,
        raw_events: int,
        semantic_chunks: int,
        artifact_chunks: int,
        error_text: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO source_files (
              path, size_bytes, mtime_ns, status, processed_at, raw_events, semantic_chunks, artifact_chunks, error_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
              size_bytes = excluded.size_bytes,
              mtime_ns = excluded.mtime_ns,
              status = excluded.status,
              processed_at = excluded.processed_at,
              raw_events = excluded.raw_events,
              semantic_chunks = excluded.semantic_chunks,
              artifact_chunks = excluded.artifact_chunks,
              error_text = excluded.error_text
            """,
            (
                str(path),
                int(size_bytes),
                int(mtime_ns),
                status,
                datetime.now(UTC).isoformat(),
                int(raw_events),
                int(semantic_chunks),
                int(artifact_chunks),
                error_text,
            ),
        )
        self._conn.commit()


class SentenceTransformerEmbedder:
    def __init__(
        self,
        *,
        model_name: str,
        dimensions: int,
        batch_size: int,
        max_tokens: int,
        logger: JsonLogger,
        metrics: MetricsRegistry,
        mps_batch_cooldown_ms: int,
        torch_threads: int,
    ):
        self.model_name = model_name
        self.dimensions = int(dimensions)
        self.batch_size = max(1, int(batch_size))
        self.max_tokens = int(max_tokens)
        self.logger = logger
        self.metrics = metrics
        self.mps_batch_cooldown_ms = max(0, int(mps_batch_cooldown_ms))
        self.torch_threads = max(1, int(torch_threads))
        self.device = "cpu"
        self._model: SentenceTransformer | None = None
        self._fallback_used = False

    def load(self) -> None:
        torch.set_num_threads(self.torch_threads)
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        self._model = self._load_model(device)
        self.device = device
        self.metrics.embedding_model_info.labels("local", self.model_name, self.device).set(1)
        self.logger.log(
            "info",
            "embedder_loaded",
            model=self.model_name,
            device=self.device,
            operatorHint="Embedding runtime loaded successfully; if throughput stalls, reduce embedding batch size before changing the model.",
        )

    def _load_model(self, device: str) -> SentenceTransformer:
        extra_kwargs: dict[str, Any] = {}
        if self.model_name.startswith("nomic-ai/"):
            extra_kwargs["trust_remote_code"] = True
        model = SentenceTransformer(self.model_name, device=device, **extra_kwargs)
        try:
            model.max_seq_length = int(self.max_tokens)
        except Exception:
            pass
        return model

    async def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._model is None:
            self.load()
        assert self._model is not None
        self.metrics.embedding_batches_total.inc()
        self.metrics.embedding_texts_total.inc(len(texts))
        with self.metrics.phase_seconds.labels("embed_batch").time():
            try:
                vectors = await asyncio.to_thread(self._encode_sync, texts)
            except Exception as exc:
                if self.device == "mps":
                    self.logger.log(
                        "warning",
                        "embedder_retry_cpu",
                        error=str(exc),
                        operatorHint="MPS embedding batch failed; the worker is falling back to CPU for the remaining run to avoid repeated device resets.",
                    )
                    self._model = self._load_model("cpu")
                    self.device = "cpu"
                    self._fallback_used = True
                    vectors = await asyncio.to_thread(self._encode_sync, texts)
                else:
                    raise
        if self.mps_batch_cooldown_ms > 0:
            await asyncio.sleep(float(self.mps_batch_cooldown_ms) / 1000.0)
        return vectors

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        assert self._model is not None
        out = self._model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if hasattr(out, "tolist"):
            rows = out.tolist()
        else:
            rows = list(out)
        vectors: list[list[float]] = []
        for row in rows:
            vec = [float(v) for v in row]
            if len(vec) != self.dimensions:
                raise IngestFatalError(
                    f"Embedding dimension mismatch ({len(vec)} != {self.dimensions})",
                    operator_hint=(
                        "The selected embedding model returned a different vector size than the configured corpus dimension; "
                        "fix the dimension or choose a matching model before continuing."
                    ),
                    phase="embed_batch",
                )
            vectors.append(vec)
        try:
            if self.device == "mps":
                torch.mps.empty_cache()
        except Exception:
            pass
        return vectors


class SessionFileContext:
    def __init__(
        self,
        *,
        file_path: Path,
        root_path: Path,
        tokenizer: TextTokenizer,
        max_semantic_tokens: int,
        max_artifact_tokens: int,
        overlap_tokens: int,
        max_output_chars: int,
        max_summary_paths: int,
    ):
        self.file_path = file_path
        self.root_path = root_path
        self.relative_path = str(file_path.relative_to(root_path.parent))
        self.tokenizer = tokenizer
        self.max_semantic_tokens = max_semantic_tokens
        self.max_artifact_tokens = max_artifact_tokens
        self.overlap_tokens = overlap_tokens
        self.max_output_chars = max_output_chars
        self.max_summary_paths = max_summary_paths
        self.session_id = file_path.stem.replace("rollout-", "")
        self.cwd = ""
        self.cli_version = ""
        self.source = ""
        self.originator = ""
        self.first_user_text = ""
        self.last_user_text = ""
        self.user_messages = 0
        self.assistant_messages = 0
        self.tool_calls = 0
        self.error_events = 0
        self.referenced_paths: Counter[str] = Counter()
        self.tools_used: Counter[str] = Counter()
        self._paired_counter = 0

    def ingest_paths(self, text: str) -> None:
        for match in ABSOLUTE_PATH_RE.findall(text):
            self.referenced_paths[match] += 1

    def update_meta(self, payload: dict[str, Any]) -> None:
        self.session_id = str(payload.get("id") or self.session_id)
        self.cwd = str(payload.get("cwd") or self.cwd)
        self.cli_version = str(payload.get("cli_version") or self.cli_version)
        self.source = str(payload.get("source") or self.source)
        self.originator = str(payload.get("originator") or self.originator)

    def next_pair_variant(self) -> str:
        self._paired_counter += 1
        return f"qa_pair_{self._paired_counter}"


class SessionNormalizer:
    def __init__(self, tokenizer: TextTokenizer, logger: JsonLogger, metrics: MetricsRegistry):
        self.tokenizer = tokenizer
        self.logger = logger
        self.metrics = metrics

    def process_record(
        self,
        ctx: SessionFileContext,
        record: dict[str, Any],
        *,
        line_no: int,
    ) -> list[NormalizedChunk]:
        top_type = str(record.get("type") or "").strip() or "unknown"
        self.metrics.events_seen_total.labels(top_type).inc()

        payload = record.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        if top_type == "session_meta":
            ctx.update_meta(payload)
            return []

        out: list[NormalizedChunk] = []
        timestamp = str(record.get("timestamp") or payload.get("timestamp") or "")
        if top_type == "response_item":
            response_type = str(payload.get("type") or "").strip()
            if response_type == "message":
                role = str(payload.get("role") or "assistant").strip()
                text = extract_response_text(payload.get("content"))
                if not text:
                    self.metrics.events_skipped_total.labels("empty_message").inc()
                    return []
                out.extend(self._message_chunks(ctx, role=role, text=text, timestamp=timestamp, line_no=line_no))
            elif response_type == "function_call":
                out.extend(self._function_call_chunks(ctx, payload=payload, timestamp=timestamp, line_no=line_no))
            elif response_type == "function_call_output":
                out.extend(self._function_output_chunks(ctx, payload=payload, timestamp=timestamp, line_no=line_no))
            elif response_type == "reasoning":
                summary_text = extract_reasoning_summary(payload)
                if summary_text:
                    out.extend(
                        self._semantic_chunks(
                            ctx,
                            text=f"Reasoning summary\n\n{summary_text}",
                            variant="reasoning_summary",
                            role="assistant_reasoning_summary",
                            line_no=line_no,
                            timestamp=timestamp,
                        )
                    )
                else:
                    self.metrics.events_skipped_total.labels("opaque_reasoning").inc()
            else:
                self.metrics.events_skipped_total.labels("unsupported_response_item").inc()
            return out

        if top_type == "event_msg":
            event_type = str(payload.get("type") or "").strip()
            if event_type == "agent_message":
                message = clean_text(str(payload.get("message") or ""))
                if message:
                    out.extend(
                        self._semantic_chunks(
                            ctx,
                            text=message,
                            variant="agent_commentary",
                            role="assistant_commentary",
                            line_no=line_no,
                            timestamp=timestamp,
                        )
                    )
                else:
                    self.metrics.events_skipped_total.labels("empty_agent_message").inc()
            else:
                self.metrics.events_skipped_total.labels("unsupported_event_msg").inc()
            return out

        self.metrics.events_skipped_total.labels("unhandled_top_type").inc()
        return out

    def finalize(self, ctx: SessionFileContext, *, line_no: int) -> list[NormalizedChunk]:
        top_paths = [path for path, _count in ctx.referenced_paths.most_common(ctx.max_summary_paths)]
        top_tools = [name for name, _count in ctx.tools_used.most_common(8)]
        summary_lines = [
            f"Session id: {ctx.session_id}",
            f"Relative path: {ctx.relative_path}",
        ]
        if ctx.cwd:
            summary_lines.append(f"CWD: {ctx.cwd}")
        if ctx.cli_version:
            summary_lines.append(f"CLI version: {ctx.cli_version}")
        if ctx.source:
            summary_lines.append(f"Source: {ctx.source}")
        if ctx.originator:
            summary_lines.append(f"Originator: {ctx.originator}")
        summary_lines.append(f"User messages: {ctx.user_messages}")
        summary_lines.append(f"Assistant messages: {ctx.assistant_messages}")
        summary_lines.append(f"Tool calls: {ctx.tool_calls}")
        summary_lines.append(f"Error events: {ctx.error_events}")
        if top_tools:
            summary_lines.append("Top tools: " + ", ".join(top_tools))
        if top_paths:
            summary_lines.append("Referenced paths:")
            summary_lines.extend(f"- {path}" for path in top_paths)
        if ctx.first_user_text:
            summary_lines.append("")
            summary_lines.append("First user request excerpt:")
            summary_lines.append(truncate_chars(ctx.first_user_text, 800))

        summary_text = "\n".join(summary_lines)
        self.metrics.summary_files_referenced.set(len(top_paths))
        return self._semantic_chunks(
            ctx,
            text=summary_text,
            variant="session_summary",
            role="session_summary",
            line_no=line_no,
            timestamp="",
        )

    def _message_chunks(
        self,
        ctx: SessionFileContext,
        *,
        role: str,
        text: str,
        timestamp: str,
        line_no: int,
    ) -> list[NormalizedChunk]:
        clean = clean_text(text)
        if not clean or ENCRYPTED_BLOB_RE.search(clean):
            self.metrics.events_skipped_total.labels("message_noise").inc()
            return []
        if role == "user":
            ctx.user_messages += 1
            ctx.last_user_text = clean
            if not ctx.first_user_text:
                ctx.first_user_text = clean
        else:
            ctx.assistant_messages += 1
        ctx.ingest_paths(clean)

        chunks = self._semantic_chunks(
            ctx,
            text=clean,
            variant=role,
            role=role,
            line_no=line_no,
            timestamp=timestamp,
        )
        if role == "assistant" and ctx.last_user_text:
            pair_text = f"User request\n\n{ctx.last_user_text}\n\nAssistant response\n\n{clean}"
            chunks.extend(
                self._semantic_chunks(
                    ctx,
                    text=pair_text,
                    variant=ctx.next_pair_variant(),
                    role="qa_pair",
                    line_no=line_no,
                    timestamp=timestamp,
                )
            )
            ctx.last_user_text = ""
        return chunks

    def _function_call_chunks(
        self,
        ctx: SessionFileContext,
        *,
        payload: dict[str, Any],
        timestamp: str,
        line_no: int,
    ) -> list[NormalizedChunk]:
        name = str(payload.get("name") or "").strip()
        if not TOOL_NAME_RE.match(name):
            self.metrics.events_skipped_total.labels("bad_tool_name").inc()
            return []
        arguments = pretty_jsonish(payload.get("arguments"))
        ctx.tool_calls += 1
        ctx.tools_used[name] += 1
        text = f"Tool call: {name}\n\nArguments\n{arguments}"
        return self._artifact_chunks(
            ctx,
            text=text,
            variant=f"tool_call_{name}",
            kind="tool_call",
            line_no=line_no,
            timestamp=timestamp,
            important=name in {"exec_command", "web.search_query", "open", "click"},
        )

    def _function_output_chunks(
        self,
        ctx: SessionFileContext,
        *,
        payload: dict[str, Any],
        timestamp: str,
        line_no: int,
    ) -> list[NormalizedChunk]:
        output = clean_text(str(payload.get("output") or ""))
        if not output:
            self.metrics.events_skipped_total.labels("empty_tool_output").inc()
            return []
        if ENCRYPTED_BLOB_RE.search(output):
            self.metrics.events_skipped_total.labels("opaque_tool_output").inc()
            return []
        important = bool(ERROR_SIGNAL_RE.search(output))
        if important:
            ctx.error_events += 1
        ctx.ingest_paths(output)
        trimmed = trim_output(output, max_chars=self.max_output_chars_for(important))
        out = self._artifact_chunks(
            ctx,
            text=f"Tool output\n\n{trimmed}",
            variant="tool_output",
            kind="tool_output",
            line_no=line_no,
            timestamp=timestamp,
            important=important,
        )
        if important:
            summary = summarize_error_output(output)
            out.extend(
                self._semantic_chunks(
                    ctx,
                    text=summary,
                    variant="tool_error_summary",
                    role="tool_error_summary",
                    line_no=line_no,
                    timestamp=timestamp,
                )
            )
        return out

    def max_output_chars_for(self, important: bool) -> int:
        return self.tokenizer.config.max_tokens_per_chunk_hard * 8 if important else 3000

    def _semantic_chunks(
        self,
        ctx: SessionFileContext,
        *,
        text: str,
        variant: str,
        role: str,
        line_no: int,
        timestamp: str,
    ) -> list[NormalizedChunk]:
        windows = split_text_windows(
            text=text,
            tokenizer=self.tokenizer,
            target_tokens=ctx.max_semantic_tokens,
            overlap_tokens=ctx.overlap_tokens,
        )
        out: list[NormalizedChunk] = []
        for idx, window in enumerate(windows):
            chunk_id = stable_chunk_id(ctx.session_id, "semantic", line_no, variant, idx)
            meta = {
                "system_kind": "codex_session_ingest",
                "stream": "semantic",
                "role": role,
                "session_id": ctx.session_id,
                "source_jsonl": str(ctx.file_path),
                "relative_source_jsonl": ctx.relative_path,
                "timestamp": timestamp,
                "variant": variant,
            }
            chunk = Chunk(
                chunk_id=chunk_id,
                content=window,
                file_path=str(ctx.file_path),
                start_line=line_no,
                end_line=line_no,
                language=None,
                token_count=self.tokenizer.count_tokens(window),
                metadata=meta,
            )
            self.metrics.events_indexed_total.labels("semantic", role).inc()
            out.append(NormalizedChunk(stream="semantic", chunk=chunk, needs_embedding=True))
        return out

    def _artifact_chunks(
        self,
        ctx: SessionFileContext,
        *,
        text: str,
        variant: str,
        kind: str,
        line_no: int,
        timestamp: str,
        important: bool,
    ) -> list[NormalizedChunk]:
        windows = split_text_windows(
            text=text,
            tokenizer=self.tokenizer,
            target_tokens=ctx.max_artifact_tokens,
            overlap_tokens=ctx.overlap_tokens,
        )
        out: list[NormalizedChunk] = []
        for idx, window in enumerate(windows):
            chunk_id = stable_chunk_id(ctx.session_id, "artifact", line_no, variant, idx)
            meta = {
                "system_kind": "codex_session_ingest",
                "stream": "artifact",
                "kind": kind,
                "important": bool(important),
                "session_id": ctx.session_id,
                "source_jsonl": str(ctx.file_path),
                "relative_source_jsonl": ctx.relative_path,
                "timestamp": timestamp,
                "variant": variant,
            }
            exit_code = extract_exit_code(window)
            if exit_code is not None:
                meta["exit_code"] = int(exit_code)
            chunk = Chunk(
                chunk_id=chunk_id,
                content=window,
                file_path=str(ctx.file_path),
                start_line=line_no,
                end_line=line_no,
                language=None,
                token_count=self.tokenizer.count_tokens(window),
                metadata=meta,
            )
            self.metrics.events_indexed_total.labels("artifact", kind).inc()
            out.append(NormalizedChunk(stream="artifact", chunk=chunk, needs_embedding=False))
        return out


class CorpusWriter:
    def __init__(
        self,
        *,
        pg: PostgresClient,
        config: RunConfig,
        embedder: SentenceTransformerEmbedder,
        logger: JsonLogger,
        metrics: MetricsRegistry,
    ):
        self.pg = pg
        self.config = config
        self.embedder = embedder
        self.logger = logger
        self.metrics = metrics
        self.dead_letter_path = config.dead_letter_path

    async def ensure_corpora(self) -> None:
        await self.pg.connect()
        await self.pg.upsert_corpus(
            self.config.semantic_repo_id,
            name=self.config.semantic_repo_id,
            root_path=str(self.config.session_root),
            description="Semantic Codex session memory corpus",
            meta={"system_kind": "codex_session_ingest", "stream": "semantic"},
        )
        await self.pg.upsert_corpus(
            self.config.artifact_repo_id,
            name=self.config.artifact_repo_id,
            root_path=str(self.config.session_root),
            description="Artifact and tool-output Codex session corpus",
            meta={"system_kind": "codex_session_ingest", "stream": "artifact"},
        )
        await self.pg.update_corpus_embedding_meta(
            self.config.semantic_repo_id,
            backend="provider",
            provider="local",
            model=self.config.embedding_model,
            dimensions=self.config.embedding_dimensions,
            ts_config=self.config.ts_config,
        )
        await self.pg.update_corpus_embedding_meta(
            self.config.artifact_repo_id,
            backend="fts_only",
            provider="",
            model="",
            dimensions=0,
            ts_config=self.config.ts_config,
        )

    async def flush_semantic(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        sanitized = [sanitize_chunk_for_storage(chunk) for chunk in chunks]
        texts = [chunk.content for chunk in sanitized]
        vectors = await self.embedder.encode(texts)
        embedded = [
            chunk.model_copy(update={"embedding": vector})
            for chunk, vector in zip(sanitized, vectors, strict=True)
        ]
        return await self._flush_semantic_resilient(embedded)

    async def flush_artifact(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        sanitized = [sanitize_chunk_for_storage(chunk) for chunk in chunks]
        return await self._flush_artifact_resilient(sanitized)

    async def _flush_semantic_resilient(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        try:
            with self.metrics.phase_seconds.labels("pg_upsert_semantic").time():
                await self.pg.upsert_embeddings(self.config.semantic_repo_id, chunks)
                self.metrics.db_writes_total.labels("semantic_embeddings").inc()
                await self.pg.upsert_fts(self.config.semantic_repo_id, chunks, ts_config=self.config.ts_config)
                self.metrics.db_writes_total.labels("semantic_fts").inc()
            self.metrics.chunks_written_total.labels("semantic").inc(len(chunks))
            return len(chunks)
        except Exception as exc:
            if len(chunks) == 1:
                self._dead_letter("semantic", chunks[0], exc)
                return 0
            mid = max(1, len(chunks) // 2)
            self.logger.log(
                "warning",
                "semantic_batch_split",
                batch_size=len(chunks),
                error=str(exc),
                operatorHint=(
                    "A semantic write batch failed, so the worker is bisecting the batch to isolate the bad chunk instead of aborting the whole run."
                ),
            )
            left = await self._flush_semantic_resilient(chunks[:mid])
            right = await self._flush_semantic_resilient(chunks[mid:])
            return left + right

    async def _flush_artifact_resilient(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        try:
            with self.metrics.phase_seconds.labels("pg_upsert_artifact").time():
                await self.pg.upsert_fts(self.config.artifact_repo_id, chunks, ts_config=self.config.ts_config)
                self.metrics.db_writes_total.labels("artifact_fts").inc()
            self.metrics.chunks_written_total.labels("artifact").inc(len(chunks))
            return len(chunks)
        except Exception as exc:
            if len(chunks) == 1:
                self._dead_letter("artifact", chunks[0], exc)
                return 0
            mid = max(1, len(chunks) // 2)
            self.logger.log(
                "warning",
                "artifact_batch_split",
                batch_size=len(chunks),
                error=str(exc),
                operatorHint=(
                    "An artifact write batch failed, so the worker is bisecting the batch to isolate the bad chunk instead of aborting the whole run."
                ),
            )
            left = await self._flush_artifact_resilient(chunks[:mid])
            right = await self._flush_artifact_resilient(chunks[mid:])
            return left + right

    def _dead_letter(self, stream: str, chunk: Chunk, exc: Exception) -> None:
        reason = type(exc).__name__
        self.metrics.dead_letter_chunks_total.labels(stream, reason).inc()
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "stream": stream,
            "reason": reason,
            "error": str(exc),
            "chunk_id": chunk.chunk_id,
            "file_path": chunk.file_path,
            "start_line": int(chunk.start_line),
            "end_line": int(chunk.end_line),
            "metadata": chunk.metadata,
            "content": chunk.content,
        }
        self.dead_letter_path.parent.mkdir(parents=True, exist_ok=True)
        with self.dead_letter_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
        self.logger.log(
            "error",
            "chunk_dead_lettered",
            stream=stream,
            chunk_id=chunk.chunk_id,
            error=str(exc),
            operatorHint=(
                "A single chunk was quarantined to the dead-letter log after batch isolation failed; the main run will continue and this row can be repaired later."
            ),
        )


class IngestRunner:
    def __init__(self, config: RunConfig):
        self.config = config
        self.logger = JsonLogger(config.log_path)
        self.metrics = MetricsRegistry()
        self.run_id = uuid.uuid4().hex
        self.status = StatusState(
            run_id=self.run_id,
            mode="ingest",
            started_at=datetime.now(UTC).isoformat(),
            model_name=config.embedding_model,
        )
        self.metrics_server = MetricsHttpServer(config.metrics_bind, config.metrics_port, self.metrics, self.status)
        self.status_lock = self.metrics_server.status_lock
        self.checkpoints = CheckpointStore(config.state_db_path)
        self.tokenizer = TextTokenizer(
            TokenizationConfig(
                strategy="huggingface",
                hf_tokenizer_name=config.tokenizer_name,
                normalize_unicode=True,
                lowercase=False,
                max_tokens_per_chunk_hard=max(config.max_artifact_tokens * 4, 2048),
                estimate_only=False,
            )
        )
        self.normalizer = SessionNormalizer(self.tokenizer, self.logger, self.metrics)
        self.embedder = SentenceTransformerEmbedder(
            model_name=config.embedding_model,
            dimensions=config.embedding_dimensions,
            batch_size=config.embedding_batch_size,
            max_tokens=max(config.max_semantic_tokens, config.max_artifact_tokens),
            logger=self.logger,
            metrics=self.metrics,
            mps_batch_cooldown_ms=config.mps_batch_cooldown_ms,
            torch_threads=config.torch_threads,
        )
        self.pg = PostgresClient(config.postgres_dsn)
        self.writer = CorpusWriter(
            pg=self.pg,
            config=config,
            embedder=self.embedder,
            logger=self.logger,
            metrics=self.metrics,
        )
        self.shutdown = asyncio.Event()

    async def run(self) -> None:
        self._apply_process_tuning()
        self.metrics.service_up.set(1)
        self.metrics_server.start()
        self.checkpoints.start_run(self.run_id, "ingest", self._config_snapshot())
        self._install_signal_handlers()
        self._write_status()
        self.logger.log(
            "info",
            "ingest_run_started",
            run_id=self.run_id,
            session_root=str(self.config.session_root),
            postgres_dsn=redact_dsn(self.config.postgres_dsn),
            operatorHint="If the run exits before any files complete, check local Postgres reachability and the embedding model cache before changing batch sizes.",
        )

        try:
            await self.writer.ensure_corpora()
            files = discover_session_files(self.config.session_root, self.config.year_filter)
            if self.config.limit_files > 0:
                files = files[: self.config.limit_files]
            self.status.discovered_files = len(files)
            self.metrics.pending_files.set(len(files))
            self.metrics.files_discovered_total.inc(len(files))
            self._write_status()

            for index, path in enumerate(files, start=1):
                if self.shutdown.is_set():
                    break
                stat = path.stat()
                if not self.config.force and self.checkpoints.file_is_fresh(
                    path,
                    size_bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                ):
                    self.status.skipped_files += 1
                    self.metrics.files_skipped_total.labels("unchanged").inc()
                    self.metrics.pending_files.set(max(0, len(files) - index))
                    self._write_status()
                    continue

                await self._process_file(path)
                self.metrics.pending_files.set(max(0, len(files) - index))

            final_status = "cancelled" if self.shutdown.is_set() else "complete"
            self.checkpoints.finish_run(
                self.run_id,
                status=final_status,
                discovered_files=self.status.discovered_files,
                completed_files=self.status.completed_files,
                semantic_chunks=self.status.semantic_chunks_written + self.status.summary_chunks_written,
                artifact_chunks=self.status.artifact_chunks_written,
                errors=self.status.errors,
            )
            self.status.phase = final_status
            self._write_status()
        except Exception as exc:
            operator_hint = getattr(exc, "operator_hint", "") or (
                "The ingest worker failed outside a guarded phase; inspect the JSONL run log and the last current_file in /status before restarting."
            )
            self.status.errors += 1
            self.status.last_error = str(exc)
            self.status.operator_hint = operator_hint
            self.status.phase = "error"
            self.metrics.errors_total.labels(getattr(exc, "phase", "run"), type(exc).__name__).inc()
            self.logger.log(
                "error",
                "ingest_run_failed",
                error=str(exc),
                operatorHint=operator_hint,
                phase=getattr(exc, "phase", "run"),
            )
            self.checkpoints.finish_run(
                self.run_id,
                status="error",
                discovered_files=self.status.discovered_files,
                completed_files=self.status.completed_files,
                semantic_chunks=self.status.semantic_chunks_written + self.status.summary_chunks_written,
                artifact_chunks=self.status.artifact_chunks_written,
                errors=self.status.errors,
            )
            self._write_status()
            raise
        finally:
            self.metrics.service_up.set(0)
            self.metrics.process_cpu_seconds.set(time.process_time())
            self.metrics.process_rss_bytes.set(current_rss_bytes())
            self.metrics_server.stop()

    async def _process_file(self, path: Path) -> None:
        stat = path.stat()
        ctx = SessionFileContext(
            file_path=path,
            root_path=self.config.session_root,
            tokenizer=self.tokenizer,
            max_semantic_tokens=self.config.max_semantic_tokens,
            max_artifact_tokens=self.config.max_artifact_tokens,
            overlap_tokens=self.config.overlap_tokens,
            max_output_chars=self.config.max_output_chars,
            max_summary_paths=self.config.max_summary_paths,
        )
        self.status.current_file = str(path)
        self.status.current_line = 0
        self.status.current_file_size_bytes = int(stat.st_size)
        self.status.current_file_bytes_read = 0
        self.status.phase = "scan_file"
        self._write_status()
        self.logger.log(
            "info",
            "process_file_start",
            path=str(path),
            size_bytes=int(stat.st_size),
            operatorHint="If a single file dominates runtime, inspect that file's tool-output density before increasing batch sizes.",
        )

        semantic_buffer: list[Chunk] = []
        artifact_buffer: list[Chunk] = []
        raw_events = 0
        semantic_written = 0
        artifact_written = 0

        with self.metrics.phase_seconds.labels("scan_file").time():
            with path.open("r", encoding="utf-8") as fh:
                for line_no, raw_line in enumerate(fh, start=1):
                    if self.shutdown.is_set():
                        break
                    self.status.current_line = line_no
                    self.status.current_file_bytes_read += len(raw_line.encode("utf-8"))
                    self.status.last_updated_at = datetime.now(UTC).isoformat()
                    self.metrics.current_file_size_bytes.set(int(stat.st_size))
                    self.metrics.current_file_bytes_read.set(int(self.status.current_file_bytes_read))
                    self.metrics.current_file_line.set(int(line_no))
                    self.metrics.current_file_progress_ratio.set(
                        float(self.status.current_file_bytes_read) / float(stat.st_size)
                        if stat.st_size > 0
                        else 0.0
                    )

                    record = parse_json_line(raw_line)
                    if record is None:
                        self.metrics.events_skipped_total.labels("invalid_json").inc()
                        continue
                    raw_events += 1
                    self.status.events_seen += 1
                    chunks = self.normalizer.process_record(ctx, record, line_no=line_no)
                    for normalized in chunks:
                        if normalized.stream == "semantic":
                            semantic_buffer.append(normalized.chunk)
                        else:
                            artifact_buffer.append(normalized.chunk)
                    if len(semantic_buffer) >= self.config.batch_size_semantic:
                        semantic_written += await retry_async(
                            "semantic_flush",
                            self.logger,
                            self.metrics,
                            lambda batch=list(semantic_buffer): self.writer.flush_semantic(batch),
                        )
                        self.status.device = self.embedder.device
                        semantic_buffer.clear()
                    if len(artifact_buffer) >= self.config.batch_size_artifact:
                        artifact_written += await retry_async(
                            "artifact_flush",
                            self.logger,
                            self.metrics,
                            lambda batch=list(artifact_buffer): self.writer.flush_artifact(batch),
                        )
                        artifact_buffer.clear()

        summary_chunks = self.normalizer.finalize(ctx, line_no=max(self.status.current_line, 1))
        semantic_buffer.extend(item.chunk for item in summary_chunks if item.stream == "semantic")
        if semantic_buffer:
            written = await retry_async(
                "semantic_flush",
                self.logger,
                self.metrics,
                lambda batch=list(semantic_buffer): self.writer.flush_semantic(batch),
            )
            semantic_written += written
            self.status.device = self.embedder.device
        self.status.summary_chunks_written += len(summary_chunks)
        if artifact_buffer:
            artifact_written += await retry_async(
                "artifact_flush",
                self.logger,
                self.metrics,
                lambda batch=list(artifact_buffer): self.writer.flush_artifact(batch),
            )

        self.status.completed_files += 1
        self.status.semantic_chunks_written += max(0, semantic_written - len(summary_chunks))
        self.status.artifact_chunks_written += artifact_written
        self.status.dead_letter_chunks = current_dead_letter_count(self.config.dead_letter_path)
        self.status.current_file = ""
        self.status.last_updated_at = datetime.now(UTC).isoformat()
        self.checkpoints.mark_file_result(
            path,
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            status="complete",
            raw_events=raw_events,
            semantic_chunks=semantic_written,
            artifact_chunks=artifact_written,
        )
        self.metrics.files_completed_total.inc()
        self.metrics.process_rss_bytes.set(current_rss_bytes())
        self.metrics.process_cpu_seconds.set(time.process_time())
        self._write_status()
        self.logger.log(
            "info",
            "process_file_complete",
            path=str(path),
            raw_events=raw_events,
            semantic_chunks=semantic_written,
            artifact_chunks=artifact_written,
            operatorHint="If artifact volume is much higher than semantic volume, tighten the tool-output importance filter before scaling out the run.",
        )

    def _config_snapshot(self) -> dict[str, Any]:
        return {
            "session_root": str(self.config.session_root),
            "year_filter": self.config.year_filter,
            "semantic_repo_id": self.config.semantic_repo_id,
            "artifact_repo_id": self.config.artifact_repo_id,
            "embedding_model": self.config.embedding_model,
            "embedding_dimensions": self.config.embedding_dimensions,
            "tokenizer_name": self.config.tokenizer_name,
            "metrics_bind": self.config.metrics_bind,
            "metrics_port": self.config.metrics_port,
        }

    def _write_status(self) -> None:
        with self.status_lock:
            self.status.last_updated_at = datetime.now(UTC).isoformat()
            payload = json.dumps(self.status.to_json(), ensure_ascii=True, indent=2, sort_keys=True)
        self.config.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.status_path.write_text(payload, encoding="utf-8")

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()

        def _set_shutdown() -> None:
            self.status.shutdown_requested = True
            self.shutdown.set()
            self.logger.log(
                "warning",
                "shutdown_requested",
                operatorHint="The worker received a termination signal; wait for the current batch flush to finish before restarting.",
            )

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _set_shutdown)
            except NotImplementedError:
                signal.signal(sig, lambda *_args: _set_shutdown())

    def _apply_process_tuning(self) -> None:
        if self.config.nice > 0:
            try:
                os.nice(self.config.nice)
            except Exception:
                self.logger.log(
                    "warning",
                    "nice_failed",
                    operatorHint="Nice adjustment failed; if the machine feels noisy during ingest, rerun with a higher shell-level niceness instead of raising concurrency.",
                )


def discover_session_files(root: Path, year_filter: str) -> list[Path]:
    if year_filter and root.name != year_filter and (root / year_filter).exists():
        scan_root = root / year_filter
    else:
        scan_root = root
    files = sorted(scan_root.rglob("*.jsonl"))
    return [path for path in files if path.name.startswith("rollout-")]


def stable_chunk_id(session_id: str, stream: str, line_no: int, variant: str, index: int) -> str:
    raw = f"{session_id}|{stream}|{line_no}|{variant}|{index}"
    return f"{stream}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()}"


def clean_text(text: str) -> str:
    stripped = sanitize_pg_text(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [WHITESPACE_RE.sub(" ", line).rstrip() for line in stripped.split("\n")]
    return "\n".join(line for line in lines if line or len(lines) == 1).strip()


def sanitize_pg_text(text: str) -> str:
    if not text:
        return ""
    return str(text).replace("\x00", " ")


def sanitize_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_pg_text(value)
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            sanitize_pg_text(str(key)): sanitize_json_value(item)
            for key, item in value.items()
        }
    return value


def sanitize_chunk_for_storage(chunk: Chunk) -> Chunk:
    return chunk.model_copy(
        update={
            "content": sanitize_pg_text(chunk.content),
            "file_path": sanitize_pg_text(chunk.file_path),
            "language": sanitize_pg_text(chunk.language) if chunk.language is not None else None,
            "metadata": sanitize_json_value(chunk.metadata),
        }
    )


def truncate_chars(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 16].rstrip() + "\n...[truncated]..."


def trim_output(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head - 32
    return f"{text[:head].rstrip()}\n\n...[truncated]...\n\n{text[-tail:].lstrip()}"


def extract_exit_code(text: str) -> int | None:
    match = EXIT_CODE_RE.search(text)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def pretty_jsonish(value: Any) -> str:
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return "(empty)"
        try:
            parsed = json.loads(raw)
            return json.dumps(parsed, ensure_ascii=True, indent=2, sort_keys=True)
        except Exception:
            return truncate_chars(raw, 2000)
    try:
        return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True)
    except Exception:
        return truncate_chars(str(value), 2000)


def extract_response_text(content: Any) -> str:
    if isinstance(content, str):
        return clean_text(content)
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
            continue
        if item.get("type") == "output_text" and isinstance(item.get("text"), str):
            parts.append(str(item["text"]).strip())
    return clean_text("\n\n".join(parts))


def extract_reasoning_summary(payload: dict[str, Any]) -> str:
    summary = payload.get("summary")
    if not isinstance(summary, list):
        return ""
    parts: list[str] = []
    for item in summary:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(str(item["text"]).strip())
        elif isinstance(item, str):
            parts.append(item.strip())
    return clean_text("\n".join(part for part in parts if part))


def split_text_windows(
    *,
    text: str,
    tokenizer: TextTokenizer,
    target_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    normalized = clean_text(text)
    if not normalized:
        return []
    tokenized = tokenizer.tokenize_with_offsets(normalized)
    starts = tokenized.token_starts
    if not starts:
        return [normalized]
    if len(starts) <= int(target_tokens):
        return [normalized]
    windows: list[str] = []
    start_idx = 0
    token_count = len(starts)
    target_tokens = max(32, int(target_tokens))
    overlap_tokens = max(0, min(int(overlap_tokens), target_tokens - 1))
    while start_idx < token_count:
        end_idx = min(token_count, start_idx + target_tokens)
        start_char = starts[start_idx]
        end_char = starts[end_idx] if end_idx < token_count else len(normalized)
        window = normalized[start_char:end_char].strip()
        if window:
            windows.append(window)
        if end_idx >= token_count:
            break
        start_idx = max(0, end_idx - overlap_tokens)
    return windows


def summarize_error_output(text: str) -> str:
    lines = [line.strip() for line in clean_text(text).splitlines() if line.strip()]
    interesting: list[str] = []
    for line in lines:
        lowered = line.lower()
        if "process exited with code" in lowered or "error" in lowered or "exception" in lowered or "traceback" in lowered:
            interesting.append(line)
        if len(interesting) >= 6:
            break
    if not interesting:
        interesting = lines[:6]
    return "Tool failure summary\n\n" + "\n".join(interesting[:6])


def parse_json_line(line: str) -> dict[str, Any] | None:
    raw = line.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def current_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = int(usage.ru_maxrss)
    if os.uname().sysname == "Darwin":
        return rss
    return rss * 1024


def current_dead_letter_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            return sum(1 for _ in fh)
    except Exception:
        return 0


async def retry_async(
    phase: str,
    logger: JsonLogger,
    metrics: MetricsRegistry,
    fn: Any,
    *,
    attempts: int = 4,
) -> Any:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            metrics.retries_total.labels(phase).inc()
            logger.log(
                "warning",
                "retry_scheduled",
                phase=phase,
                attempt=attempt,
                error=str(exc),
                operatorHint=(
                    f"The {phase} phase failed but is retrying; if the same phase repeats, inspect the immediately previous log line before widening retries."
                ),
            )
            await asyncio.sleep(min(10.0, 0.5 * (2 ** (attempt - 1))))
    if last_exc is None:
        raise IngestFatalError(
            f"{phase} failed without an exception",
            operator_hint=f"The {phase} phase reported failure without an exception object; inspect the caller and add a concrete raised error before re-running.",
            phase=phase,
        )
    raise last_exc


def redact_dsn(dsn: str) -> str:
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", dsn)


def local_lan_ip() -> str:
    for device in ("en0", "en1"):
        proc = subprocess.run(
            ["ipconfig", "getifaddr", device],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return "127.0.0.1"


def build_prometheus_job(job_name: str, target_host: str, target_port: int) -> dict[str, Any]:
    return {
        "job_name": job_name,
        "scrape_interval": "15s",
        "scrape_timeout": "10s",
        "metrics_path": "/metrics",
        "scheme": "http",
        "static_configs": [
            {
                "targets": [f"{target_host}:{int(target_port)}"],
                "labels": {
                    "service": "codex-session-ingest",
                    "host": target_host,
                },
            }
        ],
    }


def upsert_prometheus_job(config_text: str, job_name: str, target_host: str, target_port: int) -> str:
    parsed = yaml.safe_load(config_text) or {}
    scrape_configs = list(parsed.get("scrape_configs") or [])
    new_job = build_prometheus_job(job_name, target_host, target_port)
    replaced = False
    for idx, item in enumerate(scrape_configs):
        if isinstance(item, dict) and str(item.get("job_name") or "") == job_name:
            scrape_configs[idx] = new_job
            replaced = True
            break
    if not replaced:
        scrape_configs.append(new_job)
    parsed["scrape_configs"] = scrape_configs
    return yaml.safe_dump(parsed, sort_keys=False)


def extract_prometheus_config_text(raw_text: str) -> str:
    cleaned = ANSI_ESCAPE_RE.sub("", raw_text or "")
    if "global:" in cleaned:
        return cleaned[cleaned.index("global:") :]
    return cleaned


def ssh_run(remote_host: str, remote_password: str, command: str) -> subprocess.CompletedProcess[str]:
    if not shutil.which("sshpass"):
        raise IngestFatalError(
            "sshpass is required for remote telemetry bootstrap",
            operator_hint="Remote bootstrap needs sshpass in PATH; install it locally or run the remote provisioning steps by hand before retrying.",
            phase="remote_bootstrap",
        )
    return subprocess.run(
        [
            "sshpass",
            "-p",
            remote_password,
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"root@{remote_host}",
            command,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def bootstrap_remote_observability(cfg: RemoteTelemetryConfig, logger: JsonLogger) -> None:
    read_cmd = (
        f"pct exec {int(cfg.lxc_id)} -- sh -lc 'cat /etc/prometheus/prometheus.yml'"
    )
    read_proc = ssh_run(cfg.remote_host, cfg.remote_password, read_cmd)
    if read_proc.returncode != 0:
        raise IngestFatalError(
            f"Failed to read remote Prometheus config: {read_proc.stderr.strip()}",
            operator_hint="Remote bootstrap could not read /etc/prometheus/prometheus.yml inside the Grafana LXC; verify the LXC id and root SSH access before retrying.",
            phase="remote_bootstrap",
        )

    patched = upsert_prometheus_job(
        extract_prometheus_config_text(read_proc.stdout),
        cfg.job_name,
        cfg.local_target_host,
        cfg.local_target_port,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    escaped = base64.b64encode(patched.encode("utf-8")).decode("ascii")
    write_cmd = (
        f"pct exec {int(cfg.lxc_id)} -- sh -lc "
        f"\"cp /etc/prometheus/prometheus.yml /etc/prometheus/prometheus.yml.bak.{timestamp} "
        f"&& printf '%s' '{escaped}' | base64 -d > /etc/prometheus/prometheus.yml "
        f"&& (systemctl reload prometheus || systemctl restart prometheus)\""
    )
    write_proc = ssh_run(cfg.remote_host, cfg.remote_password, write_cmd)
    if write_proc.returncode != 0:
        raise IngestFatalError(
            f"Failed to update remote Prometheus config: {write_proc.stderr.strip()}",
            operator_hint="Prometheus config write or reload failed on the Grafana LXC; compare the backup file and the generated scrape job before trying again.",
            phase="remote_bootstrap",
        )
    logger.log(
        "info",
        "prometheus_job_upserted",
        job_name=cfg.job_name,
        target=f"{cfg.local_target_host}:{cfg.local_target_port}",
        operatorHint="If the dashboard stays empty after the worker starts, query Prometheus targets first before touching Grafana.",
    )

    datasource = grafana_api_json(
        cfg.grafana_url,
        cfg.grafana_user,
        cfg.grafana_password,
        "GET",
        "/api/datasources",
    )
    prometheus_uid = next(
        (
            str(item.get("uid") or "")
            for item in datasource
            if isinstance(item, dict) and str(item.get("type") or "") == "prometheus" and str(item.get("name") or "")
        ),
        "",
    )
    if not prometheus_uid:
        raise IngestFatalError(
            "No Prometheus datasource found in Grafana",
            operator_hint="Grafana has no Prometheus datasource configured; add one or fix datasource permissions before importing the dashboard.",
            phase="grafana_dashboard",
        )
    dashboard = build_dashboard(prometheus_uid, cfg.job_name, cfg.dashboard_uid, cfg.dashboard_title)
    grafana_api_json(
        cfg.grafana_url,
        cfg.grafana_user,
        cfg.grafana_password,
        "POST",
        "/api/dashboards/db",
        {"dashboard": dashboard, "folderId": 0, "overwrite": True},
    )
    logger.log(
        "info",
        "grafana_dashboard_upserted",
        uid=cfg.dashboard_uid,
        title=cfg.dashboard_title,
        operatorHint="If the dashboard imports but panels are empty, test the Prometheus datasource with the job name before editing panel queries.",
    )


def grafana_api_json(
    base_url: str,
    user: str,
    password: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    url = base_url.rstrip("/") + path
    headers = {
        "Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii"),
        "Accept": "application/json",
    }
    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise IngestFatalError(
            f"Grafana API call failed ({exc.code}): {detail}",
            operator_hint="Grafana rejected the API request; verify the admin password and datasource state before retrying the dashboard import.",
            phase="grafana_dashboard",
        ) from exc
    except URLError as exc:
        raise IngestFatalError(
            f"Grafana API unreachable: {exc}",
            operator_hint="Grafana could not be reached over HTTP; verify the container IP and port 3000 before retrying the dashboard import.",
            phase="grafana_dashboard",
        ) from exc


def build_dashboard(prometheus_uid: str, job_name: str, dashboard_uid: str, title: str) -> dict[str, Any]:
    def panel(panel_id: int, title_text: str, expr: str, *, x: int, y: int, w: int, h: int, panel_type: str = "timeseries") -> dict[str, Any]:
        return {
            "id": panel_id,
            "type": panel_type,
            "title": title_text,
            "datasource": {"type": "prometheus", "uid": prometheus_uid},
            "targets": [{"expr": expr, "legendFormat": "__auto"}],
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "fieldConfig": {"defaults": {}, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
        }

    panels = [
        panel(1, "Service Up", f'codex_session_ingest_service_up{{job="{job_name}"}}', x=0, y=0, w=4, h=4, panel_type="stat"),
        panel(2, "Pending Files", f'codex_session_ingest_pending_files{{job="{job_name}"}}', x=4, y=0, w=4, h=4, panel_type="stat"),
        panel(3, "Current File Progress", f'codex_session_ingest_current_file_progress_ratio{{job="{job_name}"}}', x=8, y=0, w=4, h=4, panel_type="stat"),
        panel(4, "RSS Bytes", f'codex_session_ingest_process_rss_bytes{{job="{job_name}"}}', x=12, y=0, w=4, h=4, panel_type="stat"),
        panel(5, "Files / Minute", f'sum(rate(codex_session_ingest_files_completed_total{{job="{job_name}"}}[5m])) * 60', x=0, y=4, w=8, h=7),
        panel(6, "Chunks / Minute", f'sum by (stream) (rate(codex_session_ingest_chunks_written_total{{job="{job_name}"}}[5m])) * 60', x=8, y=4, w=8, h=7),
        panel(7, "Embedding Throughput", f'rate(codex_session_ingest_embedding_texts_total{{job="{job_name}"}}[5m])', x=0, y=11, w=8, h=7),
        panel(
            8,
            "Phase Latency P95",
            f'histogram_quantile(0.95, sum by (le, phase) (rate(codex_session_ingest_phase_seconds_bucket{{job="{job_name}"}}[5m])))',
            x=8,
            y=11,
            w=8,
            h=7,
        ),
        panel(
            9,
            "Skipped Events (1h)",
            f'sum by (reason) (increase(codex_session_ingest_events_skipped_total{{job="{job_name}"}}[1h]))',
            x=0,
            y=18,
            w=8,
            h=7,
            panel_type="barchart",
        ),
        panel(
            10,
            "Errors (1h)",
            f'sum by (phase, kind) (increase(codex_session_ingest_errors_total{{job="{job_name}"}}[1h]))',
            x=8,
            y=18,
            w=8,
            h=7,
            panel_type="barchart",
        ),
        panel(
            11,
            "Event Mix (1h)",
            f'sum by (kind) (increase(codex_session_ingest_events_seen_total{{job="{job_name}"}}[1h]))',
            x=0,
            y=25,
            w=8,
            h=7,
            panel_type="barchart",
        ),
        panel(12, "DB Writes", f'sum by (phase) (rate(codex_session_ingest_db_writes_total{{job="{job_name}"}}[5m]))', x=8, y=25, w=8, h=7),
    ]
    return {
        "uid": dashboard_uid,
        "title": title,
        "tags": ["codex", "ingest", "telemetry"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "10s",
        "panels": panels,
    }


def make_run_config(args: argparse.Namespace) -> RunConfig:
    state_dir = Path(args.state_dir or DEFAULT_STATE_DIR)
    year_filter = str(args.year or "2026")
    semantic_repo_id = args.semantic_repo_id or f"codex-sessions-{year_filter}-semantic"
    artifact_repo_id = args.artifact_repo_id or f"codex-sessions-{year_filter}-artifacts"
    return RunConfig(
        session_root=Path(args.session_root).expanduser(),
        state_dir=state_dir,
        postgres_dsn=args.postgres_dsn,
        year_filter=year_filter,
        semantic_repo_id=semantic_repo_id,
        artifact_repo_id=artifact_repo_id,
        metrics_bind=args.metrics_bind,
        metrics_port=int(args.metrics_port),
        log_path=state_dir / "ingest.jsonl",
        status_path=state_dir / "status.json",
        state_db_path=state_dir / "state.sqlite3",
        dead_letter_path=state_dir / "dead_letters.jsonl",
        batch_size_semantic=int(args.semantic_batch_size),
        batch_size_artifact=int(args.artifact_batch_size),
        embedding_batch_size=int(args.embedding_batch_size),
        embedding_model=str(args.embedding_model),
        embedding_dimensions=int(args.embedding_dimensions),
        tokenizer_name=str(args.tokenizer_name),
        max_semantic_tokens=int(args.max_semantic_tokens),
        max_artifact_tokens=int(args.max_artifact_tokens),
        overlap_tokens=int(args.overlap_tokens),
        max_output_chars=int(args.max_output_chars),
        mps_batch_cooldown_ms=int(args.mps_batch_cooldown_ms),
        nice=int(args.nice),
        torch_threads=int(args.torch_threads),
        force=bool(args.force),
        limit_files=int(args.limit_files),
    )


def make_remote_config(args: argparse.Namespace) -> RemoteTelemetryConfig:
    return RemoteTelemetryConfig(
        remote_host=str(args.remote_host),
        remote_password=str(args.remote_password),
        lxc_id=int(args.remote_lxc_id),
        local_target_host=str(args.local_target_host),
        local_target_port=int(args.local_target_port),
        job_name=str(args.job_name),
        grafana_url=str(args.grafana_url),
        grafana_user=str(args.grafana_user),
        grafana_password=str(args.grafana_password),
        dashboard_uid=str(args.dashboard_uid),
        dashboard_title=str(args.dashboard_title),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex session ingest + telemetry bootstrap")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Run the local ingest worker")
    ingest.add_argument("--session-root", default=str(Path.home() / ".codex" / "sessions"))
    ingest.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    ingest.add_argument("--postgres-dsn", default=DEFAULT_POSTGRES_DSN)
    ingest.add_argument("--year", default="2026")
    ingest.add_argument("--semantic-repo-id", default="")
    ingest.add_argument("--artifact-repo-id", default="")
    ingest.add_argument("--metrics-bind", default=DEFAULT_METRICS_BIND)
    ingest.add_argument("--metrics-port", type=int, default=DEFAULT_METRICS_PORT)
    ingest.add_argument("--semantic-batch-size", type=int, default=24)
    ingest.add_argument("--artifact-batch-size", type=int, default=96)
    ingest.add_argument("--embedding-batch-size", type=int, default=8)
    ingest.add_argument("--embedding-model", default=DEFAULT_MODEL)
    ingest.add_argument("--embedding-dimensions", type=int, default=DEFAULT_DIMENSIONS)
    ingest.add_argument("--tokenizer-name", default=DEFAULT_TOKENIZER_NAME)
    ingest.add_argument("--max-semantic-tokens", type=int, default=256)
    ingest.add_argument("--max-artifact-tokens", type=int, default=384)
    ingest.add_argument("--overlap-tokens", type=int, default=32)
    ingest.add_argument("--max-output-chars", type=int, default=3000)
    ingest.add_argument("--mps-batch-cooldown-ms", type=int, default=80)
    ingest.add_argument("--nice", type=int, default=10)
    ingest.add_argument("--torch-threads", type=int, default=6)
    ingest.add_argument("--limit-files", type=int, default=0)
    ingest.add_argument("--force", action="store_true")

    bootstrap = sub.add_parser("bootstrap-observability", help="Install Prometheus scrape job and Grafana dashboard")
    bootstrap.add_argument("--remote-host", default=DEFAULT_REMOTE_HOST)
    bootstrap.add_argument("--remote-password", required=True)
    bootstrap.add_argument("--remote-lxc-id", type=int, default=DEFAULT_REMOTE_LXC)
    bootstrap.add_argument("--local-target-host", default=local_lan_ip())
    bootstrap.add_argument("--local-target-port", type=int, default=DEFAULT_METRICS_PORT)
    bootstrap.add_argument("--job-name", default=DEFAULT_JOB_NAME)
    bootstrap.add_argument("--grafana-url", default=DEFAULT_GRAFANA_URL)
    bootstrap.add_argument("--grafana-user", default="admin")
    bootstrap.add_argument("--grafana-password", required=True)
    bootstrap.add_argument("--dashboard-uid", default=DEFAULT_DASHBOARD_UID)
    bootstrap.add_argument("--dashboard-title", default="Codex Session Ingest")
    bootstrap.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))

    e2e = sub.add_parser("e2e", help="Bootstrap telemetry then run ingest")
    for action in ingest._actions[1:]:
        if action.dest in {"command"}:
            continue
        e2e._add_action(action)
    for action in bootstrap._actions[1:]:
        if action.dest in {"command", "state_dir"}:
            continue
        if not any(existing.dest == action.dest for existing in e2e._actions):
            e2e._add_action(action)
    return parser


async def main_async(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "bootstrap-observability":
        state_dir = Path(args.state_dir or DEFAULT_STATE_DIR)
        logger = JsonLogger(state_dir / "bootstrap.jsonl")
        bootstrap_remote_observability(make_remote_config(args), logger)
        return 0

    if args.command == "e2e":
        state_dir = Path(args.state_dir or DEFAULT_STATE_DIR)
        logger = JsonLogger(state_dir / "bootstrap.jsonl")
        bootstrap_remote_observability(make_remote_config(args), logger)
        runner = IngestRunner(make_run_config(args))
        await runner.run()
        return 0

    runner = IngestRunner(make_run_config(args))
    await runner.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(argv))
