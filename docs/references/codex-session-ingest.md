# Codex Session Ingest

This note tracks the standalone Codex session ingestion worker introduced for
large local CLI/Desktop history corpora.

## What it is

- Source file: `/Users/davidmontgomery/ragweld/server/codex_session_ingest.py`
- CLI entrypoint: `/Users/davidmontgomery/ragweld/scripts/codex_session_ingest.py`
- Purpose:
  - stream `~/.codex/sessions/**/rollout-*.jsonl`
  - normalize high-value user/assistant/tool/error events
  - write a semantic corpus and an artifact corpus into local pgvector/Postgres
  - expose a standalone Prometheus `/metrics` endpoint and JSON `/status`
  - run retrieval verification against the currently indexed corpus, even mid-run
  - expose a post-run status exporter so Prometheus/Grafana can keep showing terminal-state metrics
  - provision a dedicated Prometheus scrape job and Grafana dashboard on a remote box

## Design boundaries

- This worker is intentionally separate from ragweld's built-in observability stack.
- It reuses ragweld-compatible indexing semantics:
  - local embedding model naming
  - HuggingFace tokenization
  - pgvector/Postgres corpora via `PostgresClient`
- It does **not** reuse ragweld's metric names, dashboard json, or app runtime.

## Output shape

- Semantic corpus:
  - user requests
  - assistant replies
  - paired user/assistant chunks
  - session summaries
- Artifact corpus:
  - tool calls
  - tool outputs
  - high-signal failures and execution traces

## Operational notes

- Checkpoints live under `output/codex_session_ingest/`.
- The worker is resumable by file size + mtime.
- Retrieval verification writes `output/codex_session_ingest/verification.json` and can be re-run while a long ingest is still active.
- Retrieval verification records per-leg latency so you can separate embedding time from vector-search time on the semantic path.
- `build-vector-index` creates a per-corpus HNSW pgvector index for semantic corpora after a large ingest finishes.
- `serve-status` reads the persisted status and verification files and re-exposes them on `/metrics` and `/status` after the ingest worker exits.
- Remote telemetry bootstrap updates Prometheus in the Grafana LXC and imports a dedicated dashboard.
- If throughput is poor, reduce embedding batch size before increasing concurrency.
