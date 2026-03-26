# Chat Rebuild Agent Handoff (2026-03-25)

## Purpose

This file is the dedicated handoff package for the agent replacing ragweld chat
on `feat/oss-composition-kickoff`.

The mission is **total chat overhaul on `assistant-ui`** while **preserving
ragweld memory, recall, source-grounding, and conversation continuity
semantics**.

This handoff is meant to be **cold-start safe**. Assume the implementing agent
has no useful thread context beyond the files explicitly referenced here.

## Branch Canon

This branch is **replacement-only**.

- No fallbacks.
- No side-by-side old/new chat surfaces.
- No legacy compatibility shims.
- No transition-period dual paths.
- No backend-only migration slice without the matching operator-facing UI, docs,
  tests, and instructions.

If the touched chat slice is not ready on the new path, do not route back into
the legacy implementation.

## Read First

- `/Users/davidmontgomery/ragweld/AGENTS.md`
- `/Users/davidmontgomery/ragweld/CLAUDE.md`
- `/Users/davidmontgomery/ragweld/docs/exec-plans/active/oss-composition-kickoff-handoff-2026-03-25.md`
- `/Users/davidmontgomery/ragweld/docs/references/observability-online-slice.md`
- `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`
- `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/fork-v3-charter-formalization-2026-03-25.md`
- `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/fork-baseline-assessment-2026-03-25.md`

## Locked Direction

- Rebuild chat inside the ragweld shell on `assistant-ui`.
- Preserve ragweld-specific recall and source-grounding semantics as custom
  adapters around the new chat framework.
- Keep the operator-facing shell feel and dock/workbench continuity.
- Do not preserve the hand-rolled chat implementation out of continuity
  concerns.

## Execution Queue Position

As of 2026-03-25, the user explicitly reordered the branch queue so chat is the
current active replacement slice. The locked execution queue in the main
handoff is now:

1. **Rebuild chat on `assistant-ui`** (this handoff)
2. Finish observability as a full-stack replacement layer
3. Replace one bounded Training Center lane with `Flyte + Unsloth + MLflow`
4. Replace eval drilldown substrate with `Langfuse + MLflow + Ragas + Promptfoo`
5. Promote retrieval/indexing from pilot to replacement truth

If the queue changes again, update the main handoff in the same turn.

## Cold-Start Branch Context

These branch slices are already real and should be treated as existing
foundation, not re-debated goals:

- runtime/gateway formalization over `LiteLLM + vLLM`
- retrieval/indexing pilot over `Docling + Haystack + Qdrant`
- observability online slice over `OTel + Alloy + Tempo + Langfuse`
- Training Center control-plane truth exposing `Flyte + MLflow + Unsloth`
  readiness and links

What is still legacy here is the **chat implementation**, not the broader shell
or the branch canon. Chat is allowed to change heavily, but memory/recall,
source-grounding, and conversation continuity are still product-defining
behaviors that must survive the rebuild.

## 2026-03-25 Slice Status

The first assistant-ui cutover slice has now landed:

- the visible Chat tab is powered by `assistant-ui`
- the current FastAPI SSE contract is still the live transport for the first
  slice
- ragweld citations, recall plan, provider response id, and trace headers are
  carried as structured assistant message metadata
- chat no longer returns retrieval-only fallback answers when provider
  generation fails

What remains for the follow-on chat slice is backend/storage truth:

- remove the in-memory `ConversationStore` from the rebuilt path
- replace the browser-local thread persistence stopgap with canonical backend
  truth
- keep the assistant-ui shell and ragweld recall/source-grounding semantics
  intact while deleting those seams

## Current Reality

Primary backend surfaces:

- `/Users/davidmontgomery/ragweld/server/api/chat.py`
- `/Users/davidmontgomery/ragweld/server/chat/handler.py`
- `/Users/davidmontgomery/ragweld/server/chat/retrieval_gate.py`
- `/Users/davidmontgomery/ragweld/server/chat/recall_indexer.py`
- `/Users/davidmontgomery/ragweld/server/chat/context_formatter.py`
- `/Users/davidmontgomery/ragweld/server/chat/prompt_builder.py`
- `/Users/davidmontgomery/ragweld/server/services/conversation_store.py`
- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`

Primary frontend surfaces:

- `/Users/davidmontgomery/ragweld/web/src/components/Chat/ChatInterface.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Chat/chatTransport.ts`
- `/Users/davidmontgomery/ragweld/web/src/components/Chat/chatSessions.ts`
- `/Users/davidmontgomery/ragweld/web/src/components/Chat/SourceDropdown.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/tabs/ChatTab.tsx`

Current state:

- the visible Chat tab now runs on `assistant-ui`
- the transport adapter preserves the current SSE contract
- recall and memory behaviors already exist and are product-critical
- source-grounding and citations are part of the protected behavior of the
  rebuilt chat flow

## assistant-ui Integration Shape

The rebuilt chat should use assistant-ui's `useExternalStoreRuntime` (or a
custom `ChatModelAdapter` if the runtime abstraction is too restrictive) to
bridge ragweld's existing SSE streaming contract into assistant-ui's message
lifecycle. Key mapping decisions:

- **Thread identity**: ragweld's `conversation_id` maps to assistant-ui's
  thread ID. The adapter must propagate `conversation_id` from the `done` SSE
  event back into the thread state so multi-turn continuity works.
- **Message identity**: ragweld's `run_id` per assistant turn maps to
  assistant-ui's message ID. `provider_response_id` should be stored as
  message metadata, not as the primary ID.
- **Recall and source metadata**: recall plan, citations, cost summary, trace
  links, and debug info should ride as assistant-ui `MessageMetadata` (or
  custom `MessageAttachment` parts if richer rendering is needed). Do not try
  to flatten ragweld citations into assistant-ui's generic annotation model
  if it loses file path, line range, or corpus identity.
- **Corpus and recall controls**: these are ragweld-specific and live outside
  assistant-ui's message flow. Render them as companion controls in the Chat
  tab shell, not as assistant-ui thread configuration.
- **Streaming**: use assistant-ui's `AssistantStreamChunkType` with `text-delta`
  for `type: "text"` SSE events. The `type: "done"` event finalizes the
  message with metadata. The adapter must handle the `done` event to update
  sources, citations, recall plan, cost, and trace links on the completed
  message.

The transport adapter wraps `POST /api/chat/stream` and is the only place
where ragweld SSE event shapes are parsed. assistant-ui components consume
typed message state, not raw SSE.

## Streaming Contract Summary

The current FastAPI streaming contract that the first slice must keep stable:

- **Endpoint**: `POST /api/chat/stream`
- **Request body**: `ChatRequest` (Pydantic) -- includes `message`, `sources`
  (corpus IDs including `recall_default`), `conversation_id`, `stream: true`,
  `images`, `model_override`, `include_vector/sparse/graph`,
  `recall_intensity`.
- **Response**: `text/event-stream` with SSE events, each `data: {json}\n\n`:
  - `{"type": "text", "content": "..."}` -- streaming content deltas
  - `{"type": "done", "conversation_id": "...", "sources": [...],
    "run_id": "...", "started_at_ms": N, "ended_at_ms": N,
    "provider_response_id": "...", "debug": {...}}` -- terminal event with
    full metadata including `ChatDebugInfo` (provider info, recall plan,
    rerank debug, confidence, vector/sparse/graph result counts)
  - `{"type": "error", "message": "..."}` -- error event
- **Response headers** (set by observability middleware):
  `X-Correlation-ID`, `X-Trace-ID`, `X-Root-Span-ID`
- **Side effects on `done`**: assistant message persisted to conversation
  store, post-response recall auto-indexing triggered if `recall_default` is
  in sources and `recall.auto_index` is enabled.

The non-streaming `POST /api/chat` returns a `ChatResponse` JSON with the same
metadata fields. The transport adapter should prefer streaming.

## Read In This Order

If you are starting cold, read these in sequence before editing:

1. `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`
2. `/Users/davidmontgomery/ragweld/server/api/chat.py`
3. `/Users/davidmontgomery/ragweld/server/chat/handler.py`
4. `/Users/davidmontgomery/ragweld/server/chat/retrieval_gate.py`
5. `/Users/davidmontgomery/ragweld/server/chat/recall_indexer.py`
6. `/Users/davidmontgomery/ragweld/server/services/conversation_store.py`
7. `/Users/davidmontgomery/ragweld/web/src/components/Chat/ChatInterface.tsx`
8. `/Users/davidmontgomery/ragweld/web/src/components/Chat/chatTransport.ts`
9. `/Users/davidmontgomery/ragweld/web/src/components/Chat/chatSessions.ts`
10. `/Users/davidmontgomery/ragweld/web/src/components/Chat/SourceDropdown.tsx`
11. `/Users/davidmontgomery/ragweld/tests/api/test_chat_endpoints.py`
12. `/Users/davidmontgomery/ragweld/tests/unit/test_recall_gate.py`
13. `/Users/davidmontgomery/ragweld/tests/unit/test_recall_indexer.py`

## Product Semantics That Must Survive The Rebuild

These are not optional polish items. Treat them as product law unless the same
turn updates backend truth, UI, docs, tests, and instructions together.

- `recall_default` means recall retrieval and post-response auto-indexing are
  both on; absence means both are off.
- Recall gating applies to chat memory/recall behavior and must not break
  normal non-recall corpus retrieval.
- Recall intensity override must survive with the current vocabulary:
  `auto`, `skip`, `light`, `standard`, `deep`.
- The current retrieval + recall gate semantics in
  `/Users/davidmontgomery/ragweld/server/chat/retrieval_gate.py` are the
  behavioral baseline.
- The prompt contract still needs to distinguish direct, RAG-only,
  Recall-only, and RAG-plus-Recall behavior.
- Streaming, source citations, conversation continuity, and
  `provider_response_id` continuity must survive.
- Post-response recall auto-indexing must survive.

## Do Not Regress

- Do not let `assistant-ui` push chat into generic framework memory semantics
  that bypass `recall_default` and the existing recall gate.
- Do not drop corpus/source selection, recall visibility, or citations from the
  operator-facing Chat tab.
- Do not keep or expand the retrieval-only "answer anyway without an LLM"
  legacy behavior once the touched slice moves.
- Do not introduce a second chat UI or a hidden route back into the old chat
  stack.
- Do not deepen the current in-memory conversation store if the slice is
  replacing chat truth; replace it cleanly instead.
- Do not take `tests/api/test_chat_always_responds_without_llm.py` as branch
  truth for the rebuilt contract.
- Do not remove or bypass observability instrumentation on the chat and
  chat/stream paths. Both endpoints use `start_request_observation` from
  `server/observability/runtime.py` to emit OTel spans, trace IDs, cost
  summaries, and external links. The rebuilt chat path must preserve this
  instrumentation and continue emitting `X-Correlation-ID`, `X-Trace-ID`,
  and `X-Root-Span-ID` response headers.

## Legacy Targets To Replace

These are replacement targets, not protected implementations.

- the hand-rolled chat UI stack
- localStorage-heavy bespoke chat session plumbing
- retrieval-only "answer anyway without an LLM" behavior in
  `/Users/davidmontgomery/ragweld/server/chat/handler.py`
- in-process/provider assumptions that block the locked `LiteLLM -> vLLM`
  direction
- the current in-memory conversation singleton in
  `/Users/davidmontgomery/ragweld/server/services/conversation_store.py`
- tests that encode old fallback behavior as branch truth

## Recommended First Execution Slice

Make the first real cutover be a **full Chat tab UI replacement on
`assistant-ui`** while keeping the current FastAPI streaming contract stable for
the first slice.

That means:

- rebuild the live Chat tab on `assistant-ui`
- add a thin ragweld transport adapter around `POST /api/chat/stream`
- rebuild source, memory, recall, and corpus controls in the new shell
- keep citations and recall visibility first-class in the workbench
- do not keep the old Chat tab alive next to the new one
- do not add new dependencies on `ConversationStore` in the rebuilt path --
  the follow-on backend slice will replace it, and new coupling makes that
  harder

The follow-on backend slice should then remove the legacy chat-specific storage
and fallback machinery that no longer matches the locked stack.

## First-Slice Definition Of Done

For the first real cutover, "done" means all of the following are true:

- the visible Chat tab is powered by `assistant-ui`
- the old hand-rolled Chat tab is no longer the live surface for the touched
  slice
- corpus selection, recall on/off, recall intensity, and source-grounding are
  still controllable in-product
- the UI still consumes the existing streaming route and final metadata cleanly
- citations, `conversation_id`, `provider_response_id`, and final run/trace
  metadata remain visible and correct
- no touched request path silently routes back into the old fallback behavior

## Acceptance Criteria

- the live Chat tab is powered by `assistant-ui`
- memory and recall controls remain visible and useful in-product
- recall behavior still follows the existing gate and prompt semantics
- streaming, retries, citations, and session continuity still work
- the rebuilt chat path does not silently route into legacy fallback behavior
- touched backend, UI, docs, tests, and instructions move together

## Tests To Extend

- `/Users/davidmontgomery/ragweld/tests/api/test_chat_endpoints.py`
- `/Users/davidmontgomery/ragweld/tests/api/test_stream_feedback_triplet_linkage.py`
- `/Users/davidmontgomery/ragweld/tests/unit/test_recall_gate.py`
- `/Users/davidmontgomery/ragweld/tests/unit/test_recall_indexer.py`
- `/Users/davidmontgomery/ragweld/web/tests/e2e/exhaustive/chat_reliability.spec.ts`

Do not add fake-green fallback tests. Expand coverage across the recall and
memory family, not only the exact literal case you touched.

## Docs And Memory Obligations

Update in the same turn when the slice moves:

- `/Users/davidmontgomery/ragweld/docs/exec-plans/active/oss-composition-kickoff-handoff-2026-03-25.md`
- repo-local reference docs for the chat rebuild slice
- generated types if the Pydantic contract changes
- `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`
- a same-day memory note under
  `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/`

## Exact Prompt For The Chat Agent

> Continue work on `feat/oss-composition-kickoff` by replacing ragweld chat with
> a real `assistant-ui` implementation while preserving ragweld memory, recall,
> source-grounding, and conversation continuity semantics.
>
> Branch canon:
> - replacement-only
> - no fallbacks
> - no legacy chat kept alive beside the new one
> - no backend-only migration slice without matching UI/docs/tests/instructions
>
> Read first:
> - `/Users/davidmontgomery/ragweld/AGENTS.md`
> - `/Users/davidmontgomery/ragweld/CLAUDE.md`
> - `/Users/davidmontgomery/ragweld/docs/exec-plans/active/oss-composition-kickoff-handoff-2026-03-25.md`
> - `/Users/davidmontgomery/ragweld/docs/exec-plans/active/chat-rebuild-memory-recall-agent-handoff-2026-03-25.md`
>   (contains full implementation reading order, assistant-ui integration shape,
>   streaming contract summary, and behavioral law)
> - `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`
>
> Locked stack for this slice:
> - `assistant-ui`
> - `LiteLLM`
> - `vLLM`
> - ragweld-specific recall/source-grounding adapters
>
> Preserve as product law unless you replace them coherently in the same turn:
> - recall gating (`recall_default` on/off controls both retrieval and auto-indexing)
> - recall intensity controls (`auto`, `skip`, `light`, `standard`, `deep`)
> - post-response recall indexing
> - citations and source-grounding (file path, line range, corpus identity)
> - session and `provider_response_id` continuity
> - observability instrumentation on chat/stream paths (`start_request_observation`,
>   `X-Correlation-ID`, `X-Trace-ID`, `X-Root-Span-ID` headers)
>
> Forbidden regressions:
> - no generic framework memory replacing `recall_default`
> - no removal of corpus/source controls or citations
> - no second chat UI left alive
> - no retrieval-only fallback answer path preserved as branch truth
> - no new dependencies on `ConversationStore` in the rebuilt path
> - no removal or bypass of observability instrumentation on chat paths
>
> Preferred first slice:
> - replace the live Chat tab with `assistant-ui`
> - keep the current streaming FastAPI contract stable initially
> - remove old UI/fallback behavior in the touched slice instead of preserving it
>
> Verification expectation:
> - run changed-surface backend and frontend tests
> - run docs/types validators
> - run frontend lint/build
> - attempt full `pytest -q` and report remaining failures honestly
