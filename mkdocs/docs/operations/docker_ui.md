# Docker services UI

<div class="grid chunk_summaries" markdown>

-   :material-docker:{ .lg .middle } **Project-scoped**

    ---

    Only containers carrying the exact `ragweld` Compose project label and the `io.ragweld.managed=true` ownership label are listed or controlled.

-   :material-shield-lock:{ .lg .middle } **Localhost only**

    ---

    Docker endpoints answer only to requests from 127.0.0.1 and require a local Docker context (no remote `DOCKER_HOST`).

-   :material-text-box-outline:{ .lg .middle } **Logs on demand**

    ---

    Pull recent logs for any managed service without leaving the workbench.

</div>

[Operations & metrics](../operations.md){ .md-button .md-button--primary }
[Config reference: docker](../reference/config/docker.md){ .md-button }
[Troubleshooting](../troubleshooting.md){ .md-button }

!!! tip "Where to find it"
    Open **Infrastructure → Docker** in the workbench. The same controls are available over the API under `/api/docker/services` (default dev base `http://127.0.0.1:58012/api`).

## What the surface shows

The Docker subtab lists the **allowlisted ragweld Compose services** and their live state. A service that has not been created yet shows as **Missing**; the Proxmox ingress overlay services (`caddy`, `authelia`, `authelia-redis`, `cloudflared`) are labeled deployment-only — Authelia keeps its sessions in its own Redis, so an operator signed out unexpectedly should look there first.

Two services are deliberately **optional**: `api` and `postgres-exporter`. A missing optional container reads as "— Optional, not deployed" on both the Docker and Services subtabs, and it is the same wording on both pages: the ragweld API normally runs as a host process, so its absence is expected in the default local topology, not a fault. "Missing" is reserved for a service the topology genuinely needs.

### Host processes: backend and frontend serving mode

`GET /api/dev/status` reports the two host processes (backend and frontend). The backend card is a plain process probe; the frontend card answers a different question — *how is the frontend served?* — via `frontend_mode`:

| `frontend_mode` | Meaning | Services subtab wording |
|-----------------|---------|-------------------------|
| `dev_server` | A Vite dev server is reachable (the dev topology) | "● Dev server running" |
| `built_bundle` | No dev server, but `web/dist/index.html` exists — the deployed topology, where a reverse proxy serves the built bundle; `frontend_bundle_built_at` records when it was written | "● Served from build" |
| `absent` | Neither | "○ Not built and no dev server" |

!!! tip "A missing dev server is not an outage"
    On a deployed host, the "Frontend" row used to sit permanently red because the probe looked for a dev server that legitimately does not exist there — while that very frontend was serving the page you were reading. `frontend_mode=built_bundle` is that deployment's healthy answer: the detail line names the bundle path (`web/dist`) and its build time. Only `absent` is actionable, and the card says what to run.

## What it deliberately does not do

!!! warning "No host-wide container control"
    The UI never lists, starts, stops, or removes arbitrary containers on your machine. Before acting, each endpoint resolves a service to **one full container id** and re-verifies both ownership labels on that exact id. Anything that is not an allowlisted ragweld service in the `ragweld` Compose project is invisible here — use `docker` directly for everything else.

## API surface

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/docker/status` | GET | Docker daemon status + managed service count |
| `/api/docker/services` | GET | Allowlisted ragweld services and their state |
| `/api/docker/services/{service}/{action}` | POST | `start`, `stop`, or `restart` one service |
| `/api/docker/services/{service}/logs` | GET | Recent logs (`?tail=` up to 1000 lines) |

Timeouts and log defaults come from the `docker.*` config section — see the [config reference](../reference/config/docker.md).

*Concept diagram (this surface only): resolve, authorize, then act — one service at a time.*

```mermaid
flowchart LR
  A["UI / API client"] --> B["GET /api/docker/services"]
  B --> C{"Local request?\n(127.0.0.1 only)"}
  C -->|"no"| D["403 forbidden"]
  C -->|"yes"| E["docker ps\nproject=ragweld + io.ragweld.managed=true"]
  E --> F["Allowlisted service list"]
  F --> G["POST /api/docker/services/{service}/{action}"]
  G --> H["docker inspect\nre-verify ownership labels"]
  H --> I["docker start / stop / restart"]
  F --> J["GET /api/docker/services/{service}/logs"]
  J --> K["docker logs --tail N"]
```

## Safe defaults and failure modes

- **403 from a remote host** — controls are localhost-only by design. SSH-tunnel or run the workbench locally.
- **"Ragweld Docker service not found"** — the service is not part of the `ragweld` Compose project, or the stack is not up yet. Run `./start.sh` first.
- **Ambiguous ownership (409)** — more than one container matched the service; resolve duplicates with `docker ps --filter "label=com.docker.compose.project=ragweld"`.
- **Docker daemon unavailable** — start your host-owned Docker runtime first (for a dedicated Colima profile: `colima start --profile ragweld ... && docker context use colima-ragweld`), then refresh.

??? tip "If you're not sure"
    Prefer `restart` over `stop`. Stopping `postgres`, `qdrant`, or `neo4j` takes the corresponding retrieval legs down with it; `/api/ready` reports which dependency is missing.
