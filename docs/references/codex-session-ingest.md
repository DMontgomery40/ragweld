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
- Remote telemetry bootstrap updates Prometheus in the Grafana LXC and imports a dedicated dashboard.
- If throughput is poor, reduce embedding batch size before increasing concurrency.
