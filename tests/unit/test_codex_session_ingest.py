from __future__ import annotations

from pathlib import Path

import pytest
from prometheus_client import generate_latest

from server.codex_session_ingest import (
    CorpusWriter,
    JsonLogger,
    MetricsRegistry,
    SessionFileContext,
    SessionNormalizer,
    RunConfig,
    build_dashboard,
    current_dead_letter_count,
    extract_prometheus_config_text,
    extract_exit_code,
    parse_verify_query,
    sanitize_chunk_for_storage,
    split_text_windows,
    upsert_prometheus_job,
)
from server.indexing.tokenizer import TextTokenizer
from server.models.index import Chunk
from server.models.tribrid_config_model import TokenizationConfig


def _tokenizer() -> TextTokenizer:
    return TextTokenizer(
        TokenizationConfig(
            strategy="huggingface",
            hf_tokenizer_name="sentence-transformers/all-MiniLM-L6-v2",
            normalize_unicode=True,
            lowercase=False,
            max_tokens_per_chunk_hard=2048,
            estimate_only=False,
        )
    )


def test_upsert_prometheus_job_adds_and_replaces_target() -> None:
    original = """
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: [localhost:9090]
""".strip()

    first = upsert_prometheus_job(original, "codex-session-ingest", "192.168.68.123", 9487)
    assert "job_name: codex-session-ingest" in first
    assert "192.168.68.123:9487" in first

    second = upsert_prometheus_job(first, "codex-session-ingest", "192.168.68.124", 9490)
    assert second.count("job_name: codex-session-ingest") == 1
    assert "192.168.68.124:9490" in second
    assert "192.168.68.123:9487" not in second


def test_extract_prometheus_config_text_skips_banner() -> None:
    raw = "\x1b[1mGrafana LXC Container\x1b[0m\nrandom banner\nglobal:\n  scrape_interval: 15s\n"
    cleaned = extract_prometheus_config_text(raw)
    assert cleaned.startswith("global:")


def test_message_pairing_emits_user_assistant_and_pair_chunks(tmp_path: Path) -> None:
    tokenizer = _tokenizer()
    logger = JsonLogger(tmp_path / "ingest.jsonl")
    metrics = MetricsRegistry()
    normalizer = SessionNormalizer(tokenizer, logger, metrics)
    ctx = SessionFileContext(
        file_path=tmp_path / "rollout-1.jsonl",
        root_path=tmp_path,
        tokenizer=tokenizer,
        max_semantic_tokens=256,
        max_artifact_tokens=384,
        overlap_tokens=32,
        max_output_chars=3000,
        max_summary_paths=10,
    )

    user_chunks = normalizer.process_record(
        ctx,
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "output_text", "text": "Why did the validation workflow fail?"}],
            },
        },
        line_no=1,
    )
    assistant_chunks = normalizer.process_record(
        ctx,
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "The run failed because the API returned 401."}],
            },
        },
        line_no=2,
    )

    assert len(user_chunks) == 1
    assert len(assistant_chunks) == 2
    assert any(chunk.chunk.metadata["role"] == "assistant" for chunk in assistant_chunks)
    assert any(chunk.chunk.metadata["role"] == "qa_pair" for chunk in assistant_chunks)


def test_function_output_error_generates_artifact_and_error_summary(tmp_path: Path) -> None:
    tokenizer = _tokenizer()
    logger = JsonLogger(tmp_path / "ingest.jsonl")
    metrics = MetricsRegistry()
    normalizer = SessionNormalizer(tokenizer, logger, metrics)
    ctx = SessionFileContext(
        file_path=tmp_path / "rollout-2.jsonl",
        root_path=tmp_path,
        tokenizer=tokenizer,
        max_semantic_tokens=256,
        max_artifact_tokens=384,
        overlap_tokens=32,
        max_output_chars=3000,
        max_summary_paths=10,
    )

    chunks = normalizer.process_record(
        ctx,
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "output": "Process exited with code 1\nTraceback (most recent call last):\nValueError: boom",
            },
        },
        line_no=7,
    )

    assert any(chunk.stream == "artifact" for chunk in chunks)
    assert any(chunk.stream == "semantic" for chunk in chunks)
    artifact = next(chunk for chunk in chunks if chunk.stream == "artifact")
    assert extract_exit_code(artifact.chunk.content) == 1
    assert artifact.chunk.metadata["important"] is True


def test_split_text_windows_makes_progress() -> None:
    tokenizer = _tokenizer()
    text = " ".join(f"token{i}" for i in range(0, 400))
    windows = split_text_windows(text=text, tokenizer=tokenizer, target_tokens=64, overlap_tokens=8)
    assert len(windows) >= 4
    assert all(window.strip() for window in windows)
    assert windows[0] != windows[1]


def test_sanitize_chunk_for_storage_replaces_nul_in_content_and_metadata() -> None:
    chunk = Chunk(
        chunk_id="c1",
        content="hello\x00world",
        file_path="/tmp/a\x00b.jsonl",
        start_line=1,
        end_line=1,
        language="text\x00plain",
        token_count=2,
        metadata={"bad\x00key": "value\x00x", "nested": ["a\x00b"]},
    )

    sanitized = sanitize_chunk_for_storage(chunk)

    assert "\x00" not in sanitized.content
    assert "\x00" not in sanitized.file_path
    assert sanitized.language is not None and "\x00" not in sanitized.language
    assert all("\x00" not in key for key in sanitized.metadata.keys())
    assert "\x00" not in str(sanitized.metadata)


def test_current_dead_letter_count_counts_lines(tmp_path: Path) -> None:
    path = tmp_path / "dead_letters.jsonl"
    path.write_text('{"a":1}\n{"b":2}\n', encoding="utf-8")
    assert current_dead_letter_count(path) == 2


def test_parse_verify_query_accepts_known_streams_and_rejects_bad_input() -> None:
    parsed = parse_verify_query("semantic:why did the github action fail")
    assert parsed.stream == "semantic"
    assert parsed.text == "why did the github action fail"

    with pytest.raises(Exception):
        parse_verify_query("wrongprefix:hello")

    with pytest.raises(Exception):
        parse_verify_query("missing separator")


def test_metrics_registry_summary_and_verification_metrics_render() -> None:
    registry = MetricsRegistry()
    registry.update_from_status(
        {
            "phase": "complete",
            "discovered_files": 100,
            "completed_files": 92,
            "skipped_files": 8,
            "semantic_chunks_written": 250,
            "summary_chunks_written": 5,
            "artifact_chunks_written": 400,
            "events_seen": 1234,
            "errors": 0,
            "dead_letter_chunks": 1,
            "started_at": "2026-03-13T12:00:00+00:00",
            "last_updated_at": "2026-03-13T13:00:00+00:00",
            "current_file_size_bytes": 10,
            "current_file_bytes_read": 10,
            "current_line": 4,
            "current_file_progress_ratio": 1.0,
        }
    )
    registry.update_from_verification(
        {
            "verified_at": "2026-03-13T13:05:00+00:00",
            "overall_passed": True,
            "total_queries": 3,
            "passed_queries": 3,
            "corpora": {
                "semantic": {"persist_ratio": 0.97},
                "artifact": {"persist_ratio": 0.96},
            },
            "queries": [
                {
                    "stream": "semantic",
                    "text": "why did the github action fail",
                    "merged_hits": [{"score": 0.81}],
                    "legs": {"vector": {"latency_ms": 12.3}, "sparse": {"latency_ms": 6.4}},
                }
            ],
        }
    )

    rendered = generate_latest(registry.registry).decode("utf-8")
    assert 'codex_session_ingest_run_files{kind="completed"} 92.0' in rendered
    assert 'codex_session_ingest_run_chunks{stream="semantic_total"} 255.0' in rendered
    assert "codex_session_ingest_verification_overall_pass 1.0" in rendered
    assert 'codex_session_ingest_verification_query_hits{query="why did the github action fail",stream="semantic"} 1.0' in rendered


def test_build_dashboard_includes_summary_and_retrieval_panels() -> None:
    dashboard = build_dashboard("prom", "codex-session-ingest", "codex-session-ingest", "Codex Session Ingest")
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert "Completion Ratio" in titles
    assert "Verify Pass" in titles
    assert "Retrieval Hits" in titles
    assert dashboard["style"] == "dark"


class _FakeArtifactPg:
    def __init__(self) -> None:
        self.successful_writes: list[list[str]] = []

    async def upsert_chunks(self, _repo_id: str, chunks: list[Chunk]) -> int:
        if any(bool(chunk.metadata.get("poison")) for chunk in chunks):
            raise RuntimeError("poison chunk")
        self.successful_writes.append([chunk.chunk_id for chunk in chunks])
        return len(chunks)


class _FakeArtifactQdrant:
    sparse_contract = {"engine": "qdrant_sparse_idf", "model": "Qdrant/bm25"}

    def __init__(self) -> None:
        self.successful_writes: list[list[str]] = []

    async def upsert_chunks(self, _repo_id: str, chunks: list[Chunk], *, embedding_dim: int) -> int:
        assert embedding_dim > 0
        assert all(chunk.embedding is None for chunk in chunks)
        self.successful_writes.append([chunk.chunk_id for chunk in chunks])
        return len(chunks)


class _UnusedEmbedder:
    async def encode(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - artifact path should not call this
        raise AssertionError(f"embedder should not be used for artifact-only flushes: {texts!r}")


@pytest.mark.asyncio
async def test_artifact_flush_isolates_bad_chunk_and_dead_letters_it(tmp_path: Path) -> None:
    pg = _FakeArtifactPg()
    qdrant = _FakeArtifactQdrant()
    config = RunConfig(
        session_root=tmp_path,
        state_dir=tmp_path / "state",
        postgres_dsn="postgresql://postgres:postgres@127.0.0.1:5432/tribrid_rag",
        year_filter="2026",
        semantic_repo_id="semantic",
        artifact_repo_id="artifact",
        metrics_bind="127.0.0.1",
        metrics_port=9487,
        log_path=tmp_path / "ingest.jsonl",
        status_path=tmp_path / "status.json",
        state_db_path=tmp_path / "state.sqlite3",
        dead_letter_path=tmp_path / "dead_letters.jsonl",
    )
    writer = CorpusWriter(
        pg=pg,  # type: ignore[arg-type]
        config=config,
        embedder=_UnusedEmbedder(),  # type: ignore[arg-type]
        logger=JsonLogger(tmp_path / "events.jsonl"),
        metrics=MetricsRegistry(),
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    good = Chunk(
        chunk_id="good",
        content="safe artifact chunk",
        file_path=str(tmp_path / "good.jsonl"),
        start_line=1,
        end_line=1,
        token_count=3,
        metadata={},
    )
    bad = Chunk(
        chunk_id="bad",
        content="poison artifact chunk",
        file_path=str(tmp_path / "bad.jsonl"),
        start_line=2,
        end_line=2,
        token_count=3,
        metadata={"poison": True},
    )

    written = await writer.flush_artifact([good, bad])

    assert written == 1
    assert pg.successful_writes == [["good"]]
    assert qdrant.successful_writes == [["good"]]
    assert current_dead_letter_count(config.dead_letter_path) == 1
    dead_letter = config.dead_letter_path.read_text(encoding="utf-8")
    assert "bad" in dead_letter
    assert "poison chunk" in dead_letter
