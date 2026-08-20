# Chat assistant-ui Slice

## Scope

This page records the first real chat rebuild slice on
On canonical `main`, replace the visible Chat tab with
`assistant-ui` while preserving ragweld recall, source-grounding, and
conversation continuity semantics.

## What Landed

- `web/src/components/Chat/ChatInterface.tsx` now renders the live Chat tab on
  `assistant-ui` primitives with a ragweld-specific external-store runtime.
- `web/src/components/Chat/chatTransport.ts` is the only place that parses the
  chat SSE contract from `POST /api/chat/stream`.
- `web/src/components/Chat/chatSessions.ts` now persists assistant-ui-native
  thread messages plus structured ragweld metadata and migrates the prior local
  chat session shape.
- `server/chat/handler.py` no longer returns retrieval-only fallback answers
  for chat when provider generation fails.
- `server/api/chat.py` now returns `503` for non-stream generation failures and
  preserves SSE `error` events on the stream path.

## Preserved Product Semantics

- `recall_default` still controls both recall retrieval and post-response
  recall auto-indexing.
- recall intensity overrides remain `auto`, `skip`, `light`, `standard`, and
  `deep`.
- citations/source-grounding remain operator-visible and preserve file path and
  line range.
- `conversation_id` and `provider_response_id` continuity are still surfaced in
  the rebuilt chat flow.
- observability headers (`X-Correlation-ID`, `X-Trace-ID`,
  `X-Root-Span-ID`) remain attached to the chat transport and message metadata.

## Still Legacy

- backend conversation continuity still depends on the in-memory
  `ConversationStore`
- browser-local thread persistence is still a stopgap
- there is still no canonical backend thread list/history truth for the
  rebuilt assistant-ui shell

## Verification

- `uv run pytest -q tests/api/test_chat_endpoints.py tests/api/test_chat_requires_provider.py tests/unit/test_recall_gate.py tests/unit/test_recall_indexer.py`
- `uv run python scripts/check_docs_ownership.py`
- `uv run scripts/check_banned.py`
- `uv run scripts/validate_types.py`
- `uv run scripts/generate_types.py`
- `npm --prefix web run lint`
- `npm --prefix web run build`

Attempted but environment-blocked:

- `tests/api/test_stream_feedback_triplet_linkage.py` requires Postgres on
  `localhost:5432`
- `web/tests/e2e/exhaustive/chat_reliability.spec.ts` currently fails before
  reaching the Chat tab because `/api/corpora` returns `500` in the local test
  environment
