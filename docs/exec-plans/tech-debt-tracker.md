# Tech Debt Tracker

Keep this list small and actionable. Each item should have a concrete fix and a verification step.

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

