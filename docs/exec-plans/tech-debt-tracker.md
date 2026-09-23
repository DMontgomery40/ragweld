# Tech Debt Tracker

Keep this list small and actionable. Each item should have a concrete fix and a verification step.

## PINNED — operator-mandated, do not bury

### Reranker training moves to Hugging Face cloud GPUs (2026-09-23)

**Status:** deferred until there is a large, domain-specific labelled dataset. Today's
corpora are too small to show a trained reranker beating zero-shot Qwen3-Reranker plus
multi-query, fusion and a SOTA gateway reranker, so there is nothing to test it on yet.

**Why it can't run where it is:** the learning reranker (Qwen3-Reranker-0.6B, LoRA,
pointwise BCE on p(yes)) is MLX-only. The Mac may not run anything, and even when it
did, MLX training repeatedly crashed it. LXC100 is CPU-only with 24 GiB and would OOM.
Training and batch labelling must run on **Hugging Face cloud GPUs**; the `hf` CLI is
already logged in on the operator's machine.

**When picked up:** replace the MLX trainer (replacement-only) with an HF GPU job
(HF Jobs or a Space or Endpoint) that consumes chunk-level label rows
(`query, chunk_id, chunk text snapshot, label 0..1, source, corpus_id`) instead of
file-path triplets. Evaluate on held-out queries with real ranking metrics over the full
candidate list, and promote only if the result beats both the zero-shot base and plain
fusion order. Background map: the 2026-09-23 reranker pipeline research. Triplets are
file-granular, text is the first 700 chars of a file (raw bytes for PDFs),
single-document corpora yield zero rows, and a thumbs-up is credited to the top file.

**Not deferred:** chunk-level feedback *capture* (both polarities, citation clicks,
linkable search events, per-corpus labels) is being fixed now without training.

| Item | Impact | Owner | Suggested fix | Verification |
|---|---|---|---|---|
| (example) Reduce config drift | Agents build on stale docs |  | Add validation + update docs | `uv run scripts/validate_types.py` is green |

## Corpus deletion is a non-transactional saga (2026-08-25)

`DELETE /api/corpora/{id}` removes Qdrant generations, then the Neo4j graph, then
corpus-scoped lineage (aliases/bundles), then the Postgres row. A failure at any
step answers a typed 503 with the registry row still present but the earlier stores
already gone; the retry finishes the job, and a lineage writer racing the last step
can recreate alias/bundle directories that then orphan. The honest fix is a durable
`deleting` tombstone on the corpus row that every store writer checks, with idempotent
cleanup and a recovery sweep. Found by the session-13 codex review; not built in that
slice. Owner: retrieval/registry.

