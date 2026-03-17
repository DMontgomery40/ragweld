# Post-Index Dense Retrieval Prep

Source of truth:

- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`
- `/Users/davidmontgomery/ragweld/server/api/index.py`
- `/Users/davidmontgomery/ragweld/web/src/components/RAG/IndexingSubtab.tsx`

What it does:

- `indexing.auto_prepare_dense_retrieval=true` keeps dense-retrieval prep inside the normal indexing job.
- After a dense indexing run finishes promoting staged data, ragweld:
  - builds the per-corpus pgvector HNSW index
  - warms representative query embeddings through the shared embedding cache path
  - runs a small dense smoke lookup against the active corpus

Why it exists:

- Dense retrieval latency now has two separable parts:
  - query embedding
  - vector search
- After the pgvector/HNSW fix, vector search is fast; the remaining first-query pain is usually embedder/model cold start.
- Folding index build + query warmup into the main run removes the need for a manual “one more step” after indexing.

UI contract:

- The Indexing tab exposes this as `Auto-prepare dense retrieval`.
- If `indexing.skip_dense=1`, the toggle is effectively ignored and the UI says so.
