# OSS Retrieval Pilot

This reference tracks the first real retrieval/indexing pilot seam for the
OSS-composition fork.

## Goal

Create a bounded sidecar export and preview-search path that prepares ragweld
corpora for the locked `Docling + Haystack + Qdrant` direction without
pretending the full external stack is already cut over.

## What Exists

- API endpoints:
  - `GET /api/index/{corpus_id}/pilot/status`
  - `POST /api/index/{corpus_id}/pilot/export`
  - `POST /api/index/{corpus_id}/pilot/ingest`
  - `POST /api/index/{corpus_id}/pilot/search`
  - `POST /api/index/{corpus_id}/pilot/search-preview`
- Backend implementation:
  - `/Users/davidmontgomery/ragweld/server/indexing/oss_retrieval_pilot.py`
- Operator-facing UI:
  - `/Users/davidmontgomery/ragweld/web/src/components/RAG/IndexingPilotPanel.tsx`
  - rendered inside `/Users/davidmontgomery/ragweld/web/src/components/RAG/IndexingSubtab.tsx`
  - `/Users/davidmontgomery/ragweld/web/src/components/RAG/RetrievalPilotPanel.tsx`
  - rendered inside `/Users/davidmontgomery/ragweld/web/src/components/RAG/RetrievalSubtab.tsx`

## Sidecar Export Contract

The pilot export writes:

- `data/retrieval_pilot/<corpus_id>/documents.jsonl`
- `data/retrieval_pilot/<corpus_id>/manifest.json`

Each JSONL row is chunk-oriented and preserves provenance-critical metadata:

- `corpus_id`
- `repo_path`
- `file_path`
- `source_path`
- `start_line`
- `end_line`
- `language`
- `token_count`
- `chunk_ordinal`
- `parent_doc_id`
- `char_start`
- `char_end`
- `graph_parity_mode`

## Why This Matters

- It gives the fork a real migration seam that can run beside current indexing.
- It keeps the UI in the slice instead of deferring operator visibility.
- It preserves source-grounded provenance so later Haystack/Qdrant execution does
  not lose file/line fidelity.
- It keeps Neo4j parity explicit with `graph_parity_mode="neo4j_v1"` while graph
  cutover work is still pending.
- It now proves a real local Haystack/Qdrant execution lane on top of the same
  sidecar contract, instead of stopping at export-only plumbing.

## Current Limits

- The real pilot lane currently uses deterministic embeddings to prove the
  Haystack/Qdrant mechanics and provenance contract without coupling hydration to
  provider-backed embedding availability.
- Preview search still exists as a sidecar-debug tool, but the Retrieval tab now
  prefers the real Haystack/Qdrant lane.
- Dependency status for `docling`, `haystack`, and `qdrant_client` is surfaced
  in-product, and the repo now carries those dependencies in `pyproject.toml`.
- Docling is not the active extractor inside the sidecar export yet; existing
  text extraction still prepares the contract while the execution lane advances.
