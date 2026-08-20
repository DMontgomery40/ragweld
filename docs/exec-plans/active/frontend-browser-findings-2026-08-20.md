# Rendered Frontend Findings Handoff

Date: 2026-08-20

Status: open; intentionally not fixed in the backend/runtime cleanup session

## Scope and evidence

These findings came from the Codex in-app Browser against the real running app:

- UI: `http://127.0.0.1:55173/web/`
- API: `http://127.0.0.1:58012/api`
- viewport: 1600 x 900
- real navigation exercised: Dashboard, Admin, Chat, Infrastructure
- no request interception or synthetic frontend data

The API and data plane were healthy during this pass. Screenshots and semantic
DOM snapshots were captured in the originating Codex task.

## P1: advertised frontend URL opens a Vite warning instead of Ragweld

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

## P3: React Router future warnings

The rendered app logs React Router warnings for:

- `v7_startTransition`
- `v7_relativeSplatPath`

There was no error overlay, but the flags should be resolved before the router
upgrade so warnings do not hide more important console output.

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

