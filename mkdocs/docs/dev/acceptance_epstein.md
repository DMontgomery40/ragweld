# Synthetic acceptance: epstein-files smoke test

<div class="grid chunk_summaries" markdown>

-   :material-clipboard-check-multiple:{ .lg .middle } **End-to-end smoke**

    ---

    One command to exercise the UI + API stack against a known corpus id.

-   :material-rocket-launch:{ .lg .middle } **API-first routing**

    ---

    Defaults target `http://127.0.0.1:8012/api` — the only supported dev prefix.

-   :material-cog:{ .lg .middle } **Safe, overridable defaults**

    ---

    Override `CORPUS_ID`, `UI_BASE`, and `API_BASE` via env without editing the script.

</div>

[Quickstart](../manual/quickstart.md){ .md-button .md-button--primary }
[Configuration](../configuration.md){ .md-button }
[API](../api.md){ .md-button }
[Tracing](../operations/tracing.md){ .md-button }

!!! note "What this is"
    The repository includes a thin acceptance harness that drives a synthetic workflow over a fixed corpus id. It is designed for local bring-up validation and CI smoke checks. It uses a Node runner under `web/` to make API/UI-coupled calls and exits non‑zero on failure.

## What runs under the hood

```mermaid
flowchart LR
  S["acceptance_epstein.sh"] --> N["Node runner\n(\"web/tmp_synthetic_acceptance.mjs\")"]
  N --> UI["UI dev server\n(\"http://127.0.0.1:5173/web\")"]
  N --> API["Backend API\n(\"/api\" prefix)"]
  API --> PG["Postgres"]
  API --> N4J["Neo4j (optional)"]
```

!!! tip "API-first, MCP second"
    The acceptance path talks to the ragweld API directly. MCP integrations sit on top and are not part of this smoke test.

## Script location

- Bash wrapper: `scripts/acceptance_epstein.sh`
- Node driver: `web/tmp_synthetic_acceptance.mjs`

The bash wrapper sets safe defaults and invokes the Node driver using the frontend toolchain so you don’t have to manage Node paths yourself.

## Pre‑flight checklist

- [ ] Postgres reachable and initialized for ragweld
- [ ] Backend running at `http://127.0.0.1:8012/api`
- [ ] UI dev server running at `http://127.0.0.1:5173/web`
- [ ] Node and npm available (used via `npm --prefix web exec -- node ...`)

??? info "Pointers if you need to (re)start things"
    - UI dev URL: `http://127.0.0.1:5173/web` (see [Quickstart](../manual/quickstart.md))
    - Backend API: `http://127.0.0.1:8012/api` (all FastAPI routers mount under `/api`)
    - Native Postgres on macOS: see [Native Postgres (macOS)](../manual/native_postgres.md)

## Run the smoke test

=== "macOS/Linux"

    ```bash
    # From repo root
    bash scripts/acceptance_epstein.sh
    ```

=== "Windows (WSL)"

    ```bash
    # From repo root, inside WSL
    bash scripts/acceptance_epstein.sh
    ```

You should see log lines like:

```
[acceptance_epstein] corpus=epstein-files-1
[acceptance_epstein] ui=http://127.0.0.1:5173/web
[acceptance_epstein] api=http://127.0.0.1:8012/api
```

The script uses `set -euo pipefail` to fail fast on any error. A zero exit status indicates the synthetic checks passed.

## Configuration knobs (env overrides)

CORPUS_ID
:   Corpus identifier to operate on. Defaults to `epstein-files-1`.  
    - Why it matters: corpus separation is foundational; acceptance targets a fixed id for repeatability.  
    - Safe default: keep the default unless you have a conflicting local corpus id.

UI_BASE
:   UI base URL (dev server). Defaults to `http://127.0.0.1:5173/web`.  
    - Why it matters: some checks expect the UI to be reachable for end-to-end flows.  
    - Tradeoffs: pointing at a different host/port is fine if your UI dev server runs elsewhere.

API_BASE
:   API base URL. Defaults to `http://127.0.0.1:8012/api`.  
    - Why it matters: ragweld mounts all dev endpoints under `/api`.  
    - Failure mode: using a URL without `/api` (for example `http://localhost:8012`) will break routes.  
    - If you’re not sure: use the default.

Override examples:

```bash
CORPUS_ID=my-corpus UI_BASE=http://127.0.0.1:5173/web API_BASE=http://127.0.0.1:8012/api \
  bash scripts/acceptance_epstein.sh
```

!!! warning "Always include the `/api` prefix"
    The FastAPI app is mounted with `prefix="/api"`. Requests to bare `/search` or `/config` will 404 in dev. Correct examples:  
    - `http://127.0.0.1:8012/api/search`  
    - `fetch("/api/config")`

## Interpreting results

- Exit code 0: all synthetic assertions passed.
- Non‑zero exit: the Node runner or an API check failed. Inspect terminal output; the first non‑zero step stops the script.

For deeper analysis:

- Check [Tracing](../operations/tracing.md) to confirm requests flow through the retrieval stack.
- Use the UI’s RAG surfaces to manually validate retrieval for the target corpus id.

## Troubleshooting

!!! tip "Fast health checks"
    - API: `curl -sS http://127.0.0.1:8012/api/health | jq .`
    - UI: open `http://127.0.0.1:5173/web` in your browser

??? question "Common failure modes"
    - "Connection refused": a service isn’t running (UI or API). Start it and re‑run the script.
    - "404 Not Found" on API calls: you likely omitted the `/api` prefix.
    - "Database error": Postgres isn’t reachable or schema isn’t initialized.
