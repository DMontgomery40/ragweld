# Semantic Caching Initialization Plan

## Objective
Implement semantic caching across all user-facing retrieval and response surfaces:
- `/api/search`
- `/api/answer` and `/api/answer/stream`
- `/api/chat` and `/api/chat/stream`

The cache must support exact matches and semantic nearest-neighbor matches, with scoped invalidation and safe bypass controls.

## Source-of-Truth Changes
1. Add cache config to `server/models/tribrid_config_model.py`.
2. Regenerate frontend types from Pydantic (`scripts/generate_types.py`).
3. Update backend API specs to include per-request cache controls.

## Design

### 1. Config Surface
Add `semantic_cache` top-level config with:
- enable/disable
- read/write mode
- per-endpoint similarity thresholds (`search`, `answer`, `chat`)
- per-endpoint TTLs
- size bound (`max_entries`)
- chat-specific safeguards (`chat_history_window`, `bypass_if_images`, `max_temperature_for_write`)

### 2. Request Control
Add request-level `cache_mode` with values:
- `default`: follow config read/write mode
- `bypass`: no reads/writes
- `refresh`: skip reads, force write on completion

### 3. Storage (Postgres)
Create `semantic_cache_entries` table with:
- `scope_key`, `endpoint`, `exact_key` (PK)
- `query_text`, `query_embedding`
- `request_fingerprint`
- `payload` JSON
- `created_at`, `expires_at`, `last_hit_at`, `hit_count`

Add indexes for scope/endpoint/expiry and operational cleanup.

### 4. Cache Service
Implement in `server/retrieval/cache.py`:
- exact lookup
- semantic lookup (vector distance threshold)
- write/upsert
- touch/hit increment
- prune/cleanup
- stable request and context fingerprints

### 5. Retrieval Integration
Integrate into `TriBridFusion.search(...)`:
- early lookup path
- fast return of cached retrieval results
- write of final fused/reranked/shaped results
- debug metadata for hit/miss/bypass

### 6. Generation Integration
Integrate in:
- `server/services/answer_service.py`
- `server/chat/handler.py`

Behavior:
- lookup before LLM call
- write after successful final answer
- stream endpoints emit cached text as immediate completion payload
- chat generation cache keyed by bounded conversation-history fingerprint + retrieval context fingerprint

### 7. Observability
Add Prometheus metrics for:
- cache lookups by endpoint + outcome
- cache writes by endpoint + outcome
- semantic-hit similarity distribution
- cache service errors

### 8. Invalidation Strategy
Bound cache validity by:
- corpus scope key (corpus IDs)
- request fingerprint (retrieval toggles, fusion/rerank knobs, model/prompt controls)
- TTL expiration

Operational invalidation:
- table cleanup on writes (expiry + max-entry pruning)
- optional explicit clear function in Postgres client

## Acceptance Criteria
1. Repeated equivalent search requests return cache hits.
2. Semantically similar requests can hit when similarity exceeds threshold.
3. `/api/answer` and `/api/chat` can return cached model responses when retrieval and control fingerprints match.
4. Stream variants return immediate cached completion with valid `done` payload.
5. `cache_mode=bypass` never reads/writes cache.
6. `cache_mode=refresh` skips reads and overwrites cache entries.
7. Cache metadata appears in debug payloads and metrics.

## Verification
Run:
```bash
cd /Users/davidmontgomery/ragweld
uv run scripts/check_banned.py
uv run scripts/validate_types.py
uv run pytest -q
npm --prefix web run lint
npm --prefix web run build
```

## Rollout Order
1. Config + DB schema + cache service.
2. Retrieval cache in fusion.
3. Answer generation cache.
4. Chat generation cache.
5. Metrics + tests + docs cleanup.

## Implementation Notes (2026-02-27)
- All `semantic_cache.*` fields are now exposed in the Retrieval UI at:
  - `RAG > Retrieval > Ops & Tracing > Runtime Compatibility > Semantic Cache`
- Config-surface enforcement now includes `semantic_cache` via:
  - `/Users/davidmontgomery/ragweld/scripts/validate_retrieval_config_surface.py`
- This keeps the “config must be in UI” rule mechanically enforced by `uv run scripts/check_banned.py`.
