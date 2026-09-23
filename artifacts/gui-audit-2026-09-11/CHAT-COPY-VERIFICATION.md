# Chat dev-copy removal — 2026-09-12

Scope: the user explicitly directed removal of development/migration commentary from Chat during the otherwise audit-only task. This is not a layout, Dock, or Jump-to-latest fix.

## Changed surface

- `web/src/components/Chat/ChatInterface.tsx`: removed the assistant-ui rebuild banner and migration paragraph from the empty state; removed the runtime subtitle; reduced composer help to the useful keyboard shortcut. Starter prompts, sources, citations, traces, model controls, and assistant-ui behavior remain.
- `web/tests/e2e/exhaustive/chat_reliability.spec.ts`: changed the existing reset-conversation expectation from the removed internal heading to the first real starter prompt.
- Patch size: 2 insertions and 18 deletions across these two files. Existing unrelated instruction-file modifications were preserved.

## Runtime and publication

- Source checkout: Mac; validation and frontend build: LXC100, `/opt/ragweld`, as the ragweld account.
- Remote HEAD when applying the patch: `46e84aa810a1a33894989b667d2596441507251a`. Only the two-file patch was transferred, after `git apply --check`; unrelated local/remote differences were not synchronized.
- Built into `/opt/ragweld/web/.dist-dev-copy-20260912` and published versioned assets additively, then atomically replaced the served index. No container or server restart.
- Main JS: `index-CzhhN_vU.js`. CSS: `index-CuQYpYHT.css`.
- Served index SHA-256: `e0d49311bf224cce00bc01d0dced53ba823dc52e34b604749a6e7254c3e296ca`.
- Previous index retained as `/opt/ragweld/web/.dist-dev-copy-20260912/index.before.html`; existing versioned assets retained. No user data or configuration deleted.

## Verification results

| Check | Result |
|---|---|
| Patch application check and `git diff --check` | Passed |
| `npm --prefix web run lint` | Passed |
| `npm --prefix web run build -- --outDir .dist-dev-copy-20260912` | Passed; 3,873 modules |
| `uv run python scripts/check_docs_ownership.py` | Passed |
| `uv run scripts/check_banned.py` | Passed |
| `uv run scripts/validate_types.py` | Passed |
| `uv run python scripts/check_runtime_capabilities_catalog.py` | Passed; 435 rows |
| `uv run pytest -q` | 24 failed, 2,937 passed, 394 skipped, 136 warnings; 403.22 seconds |
| Python Chat web-contract tests inside full pytest run | Passed |
| Live in-app Browser, populated conversation | Passed: new JS loaded, 10 existing messages, composer present, removed copy absent |
| Live in-app Browser, existing empty conversation | Passed: all three starter prompts present, composer enabled, removed copy absent |

Accepted browser evidence: [populated Chat](screenshots/159-chat-copy-removed-live.png) and [empty Chat](screenshots/160-chat-empty-dev-copy-removed.png). No message was sent and no conversation was created or deleted for verification.

The modified Playwright reset test was not executed end-to-end: its fixture provisions/indexes a corpus and its scenario issues a real model request. Existing empty/populated conversation states were checked in the user's chosen browser instead. This does not establish the entire reset-request workflow as passing.

## Full-suite failure boundary

The full repository gate is **not green**. Failures are in the following Python suites, not files touched by this copy patch. This run did not independently establish whether they were already failing before the patch, and they were not repaired as part of this task.

- Graph schema endpoints: 4 failures, covering textless PDF and graph-policy refusals, schema approval, and extraction-prompt validation.
- Index-run replay endpoints: 5 failures, covering latest/events, promotion telemetry, persisted status, and stale indexing-run handling.
- MCP endpoints: 2 failures, covering advertised host/tool defaults and typed answer-tool refusal without generation.
- Models endpoint: 12 parametrized failures in the executable OpenAI embedding-route write contract.
- Reranker status endpoint: 1 failure in corpus-scoped versus global info.

## Still open

Chat viewport allocation, Dock clipping/reflow, keyboard access, and Jump-to-latest remain audit findings. The desktop Dock splitter was subsequently proven to work by dragging 348px → 546px and reloading; content still overflowed at the wider allocation. Width was restored to 348px.

No commit, push, pull request, or merge was created for this patch.
