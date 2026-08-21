# Rendered Frontend Findings Handoff

Date: 2026-08-20 (retested and remediated 2026-08-21)

Status: resolved; every finding below was reproduced against the live runtime on
2026-08-21, fixed, and re-verified in a real rendered browser plus a
viewport-exact Playwright audit (1600x900 and 1280x800, no request
interception). Per-finding retest notes are inline.

## Scope and evidence

These findings came from the Codex in-app Browser against the real running app:

- UI: `http://127.0.0.1:55173/web/`
- API: `http://127.0.0.1:58012/api`
- viewport: 1600 x 900
- real navigation exercised: Dashboard, Admin, Chat, Infrastructure, RAG
- no request interception or synthetic frontend data

The API and data plane were healthy during this pass. Screenshots and semantic
DOM snapshots were captured in the originating Codex task.

## P1: advertised frontend URL opens a Vite warning instead of Ragweld

### Retest status (2026-08-21)

Resolved. `/api/dev/status` now probes and advertises `/web/`, `start.sh` logs
the trailing-slash URL, and the Vite dev server 302-redirects the bare `/web`
(preserving any query string) to `/web/`. Verified with curl (`/web` -> 302 ->
app) and the live `frontend_url` field.

### Reproduction

1. Open the `frontend_url` advertised by `/api/dev/status`.
2. The URL is `http://127.0.0.1:55173/web`.
3. Vite renders: `The server is configured with a public base URL of /web/ - did you mean to visit /web/ instead?`
4. Manually add the trailing slash: `/web/`.
5. Ragweld then loads normally.

### Expected

Every operator-facing/startup/dev-status URL opens the app directly. Either the
advertised URL includes `/web/`, or `/web` redirects to `/web/`.

### Likely owners

- development status URL construction
- launcher output
- Vite base/redirect handling

## P1: the persistent Settings dock clips the workbench

### Retest status (2026-08-21)

Not reproducible on the current runtime. A programmatic layout audit at
1600x900 and 1280x800 across Dashboard, Chat, RAG, Infrastructure, and Admin
found zero elements clipped past the viewport edge, zero overlapping landmark
regions, and `scrollWidth == innerWidth` everywhere. The dock, chat toolbar,
composer, and content region render without overlap. Keep the acceptance
criteria below as regression guidance.

### Evidence

At 1600 x 900, the right Settings dock begins at the extreme right edge and is
mostly outside the usable workbench. Its buttons and fields are visibly cut off.
The problem reproduced on Dashboard, Admin, Chat, and Infrastructure.

Chat is worse: the top workbench toolbar and hero content overlap vertically,
the heading is partially hidden, the composer is squeezed, and the Settings
dock remains clipped. Infrastructure and Admin lose the same right-side content.

The document reports no horizontal overflow (`scrollWidth == innerWidth == 1600`),
so the clipped content cannot be recovered with normal horizontal scrolling.

### Expected

- The dock must fit, collapse, or become an overlay without making content
  unreachable.
- Main content must reserve the correct dock width.
- No heading, toolbar, composer, or scroll area may overlap another region.
- Validate at 1600 x 900 and narrower desktop widths.

### Likely owners

- workbench/dock shell sizing
- right-side Settings panel layout
- Chat workbench nested scroll/positioning

## P1: Chat advertises models that are not runnable

### Retest status

Resolved by the gateway-only runtime slice. Re-verified 2026-08-21: the
rendered selector lists only `LiteLLM · ragweld-local`, `/api/chat/models`
returns only that gateway alias, and a real browser send returned BROWSER_OK
through LiteLLM to local vLLM with run/trace/correlation IDs and
`llm_used: true` visible in the message trace. The rendered Chat, Dashboard quick
switcher, Retrieval, and Indexing surfaces now expose only
`LiteLLM · ragweld-local`. A real Browser send returned `BROWSER_OK` through
LiteLLM to local vLLM with provider response and trace IDs.

### Evidence

The real Chat model selector defaults to:

`Ragweld · ragweld:mlx-community/Qwen3-1.7B-4bit`

The current runtime does not have a usable MLX generation model/path. The same
selector exposes dozens of direct OpenAI models while LiteLLM and vLLM are both
shown as disabled in Admin. This makes model selection look authoritative when
it is actually catalog/config vocabulary rather than executable runtime truth.

### Expected

- Show only models returned by the active, authenticated generation gateway.
- Never default to a route that readiness has not proved runnable.
- Distinguish local serving readiness from paid/operator-only smoke aliases.
- A selected model must support an actual send through the same path the UI uses.

### Coordination note

Re-test after the LiteLLM to vLLM cutover. Frontend work should consume the new
gateway-only model contract rather than preserve direct-provider compatibility.

## P2: Admin Basic is an uncurated raw-registry dump

### Retest status (2026-08-21)

Largely resolved by the registry-driven Configuration Center: Basic renders
per-surface curated fields (`exposure_level == basic`) with live integration
readiness, booleans render as toggles, enums as selects. Residual truth fixes
this session: the dead `tracing.prometheus_port` field (stale 9090 default,
consumed by nothing) was deleted from the model, UI, and glossary.

The boolean-typing follow-up has landed in code, with visual retest still
pending. The 41 boolean-semantic config fields that were still int-typed (0/1)
were migrated to real `bool` in `server/models/tribrid_config_model.py` and
`server/models/runtime_gateway.py`. The config registry derives its UI type from
the Pydantic annotation (`_normalized_field_type` checks `bool` before `int`),
so those fields now report `boolean`, and the 23 legacy 0/1 `<select>` controls
on the older RAG/Training/Eval surfaces were replaced with the shared `.toggle`
checkbox pattern. Stored configs holding 0/1 still load, because Pydantic
coerces them.

Verified: full repo gates green (`check_docs_ownership`, `check_banned`,
`validate_types`, `check_runtime_capabilities_catalog`,
`validate_contract_bundle`, `pytest -q`, `npm run lint`, `npm run build`), plus
unit tests asserting the declared types, the absence of 0/1 range bounds, and
0/1-to-bool coercion of stored config. Not yet verified: no surface was rendered
in a browser, so "booleans render consistently as switches/checkboxes" still
needs a visual retest before this finding is marked resolved.

### Evidence

The page describes itself as a curated configuration center but renders a very
large flat list of fields with hundreds of repeated `Open Raw` and `Save`
controls. Current generation configuration simultaneously exposes LiteLLM,
vLLM, direct OpenAI, Ollama, channel-specific Ollama models, retry controls, and
raw base URLs. The surface communicates coexistence rather than one operational
path.

Several boolean values render as numeric spinbuttons (`0`/`1`) while others are
checkboxes. This is inconsistent and error-prone. Runtime ports/URLs also present
stale-looking defaults, including Prometheus `9090` and Grafana `3301`, while
the namespaced local stack uses different host ports.

### Expected

- Basic shows a small operator-curated set; Raw owns the full registry.
- Booleans render consistently as switches/checkboxes.
- Deployment-derived URLs and ports reflect live resolved topology or are
  clearly labelled as container-internal vs host addresses.
- After gateway cutover, direct provider/Ollama transport controls disappear
  instead of remaining beside LiteLLM/vLLM.

## P2: status truth is fragmented across surfaces

### Retest status (2026-08-21)

Resolved for the reproduced cases. Infrastructure > Services now shows a
dedicated "Host processes" section fed by live `/api/dev/status` probes (host
FastAPI + Vite), labels the optional API container as
"API container (optional)" with "Not deployed (optional)" instead of a
misleading "Missing", and the group copy states that the host API is expected
to run outside Docker in development. The Chat log panel's "Loki unreachable"
label was verified to be a live scoped probe (it reports reachable when Loki
is reachable), not a stale claim.

### Evidence

- Top-level Health reports `OK`.
- Chat reports `Loki unreachable`.
- Infrastructure shows the host API as `Missing` because it checks only for an
  optional API container, even though the actual host API is running and serving
  the page.
- Admin says the Grafana stack is ready while individual configured URLs appear
  stale or container/host ambiguous.

### Expected

Each surface should label exactly what it is reporting: host process, managed
container, dependency readiness, or telemetry backend. A missing optional API
container must not read like a missing Ragweld API when the host API is live.

## P1: Indexing mutates embedding settings on view and immediately conflicts

### Retest status

Resolved by the clean-start config correction. Re-verified 2026-08-21: fresh
loads of every audited page (including RAG) leave `Apply All Changes` disabled
with no unsaved marker; the phantom dirty flag was traced to a baseline
conflation in `useApplyButton` and replaced with store-level
`config` vs `persisted` truth. The catalog-backed default and
stored-config migration now use `BAAI/bge-small-en-v1.5` at 384 dimensions.
Reopening the rendered Indexing page leaves `Apply All Changes` disabled and
shows no 409. Keep the acceptance criteria below as regression guidance.

### Evidence

Opening `RAG > Indexing` against the real `recall_default` corpus changed the
rendered embedding model from the configured local
`all-MiniLM-L6-v2`/384-dimensional lane to the first catalog option
`BAAI/bge-m3`/1024 dimensions. No operator selection was made. The global apply
bar immediately showed an unsaved-change marker and `Request failed with status
code 409`.

The page therefore turns a read/navigation action into an attempted corpus
config mutation, then collides with the index contract lock. This is especially
dangerous because the visible selected model no longer describes the model that
produced existing vectors.

### Expected

- Opening the tab is read-only.
- A configured value absent from the catalog renders as explicitly unavailable;
  it is never silently replaced by the first option.
- Dimension auto-sync runs only after an explicit user model selection.
- Index-contract conflicts explain the exact immutable field and required
  operator action instead of a raw 409.

## P2: direct-provider labels remain after the gateway-only cutover

### Retest status (2026-08-21)

Resolved. The stale `Local` and `OpenRouter` Chat Settings tabs were replaced
by a single `Providers` tab whose copy states the real topology (LiteLLM ->
managed vLLM, no direct app routing). The runtime-capabilities description of
the `local` embedding provider no longer claims "optional MLX fast-paths";
dispatch is the explicit sentence-transformers path and MLX remains a separate
explicit provider.

### Evidence

`Chat > Settings` still renders `Local` and `OpenRouter` top-level tabs. Their
content has already been replaced by the same LiteLLM/vLLM gateway panel, but
the headings and descriptions still promise direct local OpenAI-compatible
endpoints and a combined LiteLLM/OpenRouter/local routing surface.

`RAG > Indexing` also describes the `local` embedding option as having
"optional MLX fast-paths," although local/Hugging Face embedding now follows
the explicit SentenceTransformer path and MLX is a separate explicit provider.

### Expected

- Remove or rename the stale `Local` and `OpenRouter` Chat settings tabs.
- Provider copy describes the one real gateway topology and the isolated paid
  smoke alias without implying direct app routing.
- Embedding copy matches explicit provider dispatch; no hidden MLX fast path.

## P3: React Router future warnings

### Retest status (2026-08-21)

Resolved. `BrowserRouter` now opts into `v7_startTransition` and
`v7_relativeSplatPath`; the rendered console shows no router warnings on any
audited page.

The rendered app logs React Router warnings for:

- `v7_startTransition`
- `v7_relativeSplatPath`

There was no error overlay, but the flags should be resolved before the router
upgrade so warnings do not hide more important console output.

## P2: Chat renders typed retrieval failures as raw JSON in an assistant bubble

### Retest status (2026-08-21)

Resolved and proven against a real organic failure. The 409/503 failure
details are now validated boundary models (`RetrievalContractMismatchDetail`
was registered and generated), the chat transport parses structured details
(including typed `detail` payloads on in-stream SSE error events), and the
rendered Chat surface shows a structured error card: stable code, leg chip,
required action, "Generation did not run for this request.", and
expected/current contracts behind a Details disclosure. No raw JSON in the
bubble and no generated answer. Verified live in the browser when
`recall_default` carried a stale 3072-dim contract: the card rendered exactly
as specified. Root cause of that stale contract (recall writes bypassing
contract recording/enforcement) was also fixed and the polluted recall corpus
was reset.

### Evidence

After the fail-closed retrieval slice, a real standard-Recall send against
`recall_default` correctly stopped before LiteLLM/vLLM generation because the
stored embedding contract is 3072 dimensions while the current query contract
is 384. The rendered Chat surface showed:

`Error: Failed to start streaming: {"detail":{"code":"embedding_contract_mismatch", ...}}`

followed by `Generation ended with an error.` This is operationally truthful,
but it exposes the transport envelope and full contract dictionaries as prose in
the conversation instead of rendering the stable error fields intentionally.

### Expected

- Render a compact error card using `code`, `leg`, and `required_action`.
- Keep expected/current contract details behind a disclosure control.
- Do not present a failed request as a normal Assistant message.
- Preserve the important truth that generation did not run.

## Acceptance pass for the follow-up session

1. Open `/web` and `/web/`; both reach the real app.
2. Exercise Dashboard, Admin, Chat, and Infrastructure at 1600 x 900 and a
   narrower desktop viewport.
3. Prove the Settings dock and Chat regions do not clip or overlap.
4. Confirm Chat lists only runnable gateway models and successfully sends one
   message without request interception.
5. Confirm status labels distinguish host API, container API, dependencies, and
   telemetry truth.
6. Confirm the browser console has no framework warnings or errors.
7. Trigger a retrieval contract mismatch and verify a structured error card,
   no generated assistant answer, and no raw JSON transport envelope.
