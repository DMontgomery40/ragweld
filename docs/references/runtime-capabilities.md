# Runtime Capabilities vs Catalog

This page defines the truth boundary between the broad model catalog and the runtime product surface.

## Source-of-truth split

- `data/models.json` is the broad catalog for pricing, context windows, and known model candidates.
- `server/runtime_capabilities.py` is the executable capability registry for what ragweld can actually run/select today.
- `/api/models` exposes both truths together by attaching `selection_roles`, `selection_status`, and `selection_reason` to catalog rows.
- `/api/runtime-capabilities` exposes the non-model runtime matrix: embedding providers/backends, reranker providers/backends, chunking strategies, and indexing/search backends.

## Selection metadata contract

- `selection_roles`
  - `generation`: this row belongs in generation model selection surfaces.
  - `embedding_provider`: this row belongs in embedding model selection surfaces.
  - `reranker_cloud`: this row belongs in the cloud reranker model selection surface.
- `selection_status`
  - `runtime_selectable`: selectable in the current product/runtime surface.
  - `catalog_only`: present for pricing/reference, but not a current runtime picker option.
- `selection_reason`
  - Human-readable explanation for why a row is catalog-only.

## Guardrail

Do not treat `components` alone as runtime truth. `components` is intentionally broader than the current executable surface.
