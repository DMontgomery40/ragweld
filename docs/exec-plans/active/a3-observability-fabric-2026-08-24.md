# A3 — Observability Fabric Completion (Mimir, Pyroscope, Faro, Alertmanager, Langfuse)

Date: 2026-08-24

Status: in progress

## Goal

Deploy the five missing observability-fabric services as real Compose services
with functional readiness, wire their data paths, and turn on the operator
surfaces that already exist for them. No component may report healthy from
config presence; every one must pass its functional readiness probe
(`server/observability/status.py` `_READINESS_PATHS`).

Memory decision (operator, 2026-08-24): the two crashes were local-model RAM,
not the VM; the Colima `ragweld` profile stays at `--cpu 6 --memory 16`. The
VM had ~9.4 GiB free before this slice; the A3 services budget ~3 GiB.

## Topology decisions

- **Mimir** (`mimir`): monolithic mode, filesystem storage, config
  `infra/mimir.yaml`. Prometheus gains `remote_write` to
  `http://mimir:9009/api/v1/push`; Prometheus stays the scraper and rule
  evaluator, Mimir is long-range retention. Grafana gets a `Mimir` datasource
  (`prometheus` type at `/prometheus`). Host port `127.0.0.1:59009`.
  Because Prometheus forwards every WAL sample, Tempo's span-metrics
  (remote-written into Prometheus) reach Mimir too.
- **Pyroscope** (`pyroscope`): host port `127.0.0.1:54040`, volume-backed
  `/data`, Grafana `grafana-pyroscope-datasource`. Host API attaches the
  `pyroscope-io` SDK in the lifespan when `tracing.pyroscope_base_url` is set;
  `RAGWELD_DISABLE_PROFILING=1` (set by `tests/conftest.py` and the strict
  launcher) keeps the agent out of test processes.
- **Faro**: not a new container — Alloy gains a `faro.receiver` on
  `:12347` (host `127.0.0.1:52347`), logs -> Loki, traces -> Tempo, CORS for
  the Vite/API origins. `tracing.faro_base_url` points at the collector
  endpoint (`/collect`); the GET probe treats 405/415 as listener-present.
  Frontend: `@grafana/faro-web-sdk` initialized from the loaded config, gated
  on a non-empty `faro_base_url`.
- **Alertmanager** (`alertmanager`): `infra/alertmanager.yml` (already
  present), host port `127.0.0.1:59093`. Prometheus gains `alerting` +
  `rule_files` (`infra/prometheus-rules.yml`) with real rules: target-down
  alerts for the API/LiteLLM/vllm-metal/Postgres jobs and an always-firing
  `RagweldWatchdog` (severity `none`) that proves the Prometheus->Alertmanager
  pipe end to end without destabilizing anything.
- **Langfuse v3** (`langfuse`, `langfuse-worker`, `langfuse-postgres`,
  `langfuse-clickhouse`, `langfuse-redis`, `langfuse-minio`): web UI on
  `127.0.0.1:53000`, everything else VM-internal only. Secrets follow the
  LiteLLM pattern: committed `infra/langfuse.env.example`, gitignored
  `infra/langfuse.env` (compose `required: false`), `LANGFUSE_INIT_*`
  provisions the org/project/keys headlessly so the host API's
  `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` (root `.env`) work on first
  boot. Host-side ingestion is the existing `langfuse` SDK integration in
  `server/observability/runtime.py` (`record_langfuse_generation`), enabled by
  `tracing_mode=otel_langfuse` + `langfuse_enabled=true` + base URL. No
  LiteLLM callback lane (one canonical ingestion path, replacement-only).
- **OpenCost**: NOT deployed. OpenCost requires a Kubernetes API server;
  the Colima profile runs the plain Docker runtime. It stays `disabled` in
  the status surface (empty base URL). Revisit only if the operator moves the
  VM to a k8s runtime.

## Contract surfaces that must move together

- `infra/docker-compose.observability.yml` (new services, project-scoped
  volumes, `io.ragweld.managed` labels, loopback ports)
- `infra/prometheus.yml`, `infra/prometheus-rules.yml`, `infra/mimir.yaml`,
  `infra/alloy/config.alloy`, `infra/grafana/provisioning/datasources/`
- `start.sh` `--with-observability` service list + help text
- `server/api/docker.py` `_DOCKER_SERVICES` == `web/src/api/docker.ts`
  `RAGWELD_DOCKER_SERVICES` == managed compose services (enforced by
  `test_docker_service_allowlists_match_frontend_and_managed_compose_services`)
- `tribrid_config.json` tracing values +
  `test_active_observability_urls_match_namespaced_loopback_ports`
- `pyproject.toml` (`pyroscope-io`), `web/package.json`
  (`@grafana/faro-web-sdk`)
- `tests/unit/test_runtime_launch_contract.py` extensions (test-first)

## Acceptance

1. `GET /api/observability/status`: mimir, pyroscope, faro, alertmanager,
   langfuse all `enabled=true, reachable=true` via their functional readiness
   paths; opencost stays disabled.
2. Mimir answers a real query for an API metric through Grafana's datasource
   path (samples arrived via Prometheus remote_write).
3. Pyroscope shows `ragweld-api` profiles pushed by the host process.
4. Faro: the rendered app (real browser) emits beacons the Alloy receiver
   accepts (2xx), and the events land in Loki.
5. Alertmanager `/-/ready` green and the Watchdog alert visible in
   `/api/v2/alerts` (Prometheus rule -> Alertmanager delivery proven).
6. Langfuse `/api/public/health` green and a real grounded chat request on
   `epstein-files-1` (real domain query, paid API alias per standing rule)
   produces a Langfuse trace with the generation recorded and an external
   link on the ragweld trace payload.
7. Full verification gates + adversarial codex review (rule 0.2).

## Execution log (final record)

### What landed

- Compose overlay (`infra/docker-compose.observability.yml`): `mimir`
  (grafana/mimir:2.13.0, `infra/mimir.yaml`, monolithic filesystem),
  `pyroscope` (grafana/pyroscope:1.7.1), `alertmanager`
  (prom/alertmanager:v0.27.0, existing `infra/alertmanager.yml`), and the
  Langfuse v4 stack: `langfuse` + `langfuse-worker` (langfuse/langfuse:4 =
  4.17.0), `langfuse-postgres` (postgres:16-alpine), `langfuse-clickhouse`
  (clickhouse/clickhouse-server:25.12 — v4's migrations need its text-index
  syntax; 25.3/25.8 fail with "Only literals can be skip index arguments" /
  "Expected literal"), `langfuse-redis`, `langfuse-minio`. All labelled
  `io.ragweld.managed`, loopback-only ports (59009/54040/59093/53000 + Alloy
  faro 52347), named volumes, healthchecks pinned to IPv4 loopback (in-container
  `localhost` resolves `::1` while ClickHouse listens IPv4-only; the Langfuse
  Next.js standalone binds the container hostname, so its healthcheck targets
  `$(hostname)`).
- Prometheus: `remote_write` -> `mimir:9009`, `alerting` -> `alertmanager:9093`,
  `rule_files` (`infra/prometheus-rules.yml`: `RagweldWatchdog` +
  RagweldApiDown/GatewayDown/LocalModelDown/PostgresDown).
- Alloy: `faro.receiver "web"` on :12347 with CORS for the Vite/API origins and
  pinned labels (`service_name=ragweld-web`, `ragweld_service=web`,
  `deployment_runtime=browser`); logs -> Loki, traces -> Tempo.
- Grafana: `mimir` + `pyroscope` datasources provisioned; the Frontend/RUM
  dashboard now reads the real Faro stream from Loki (events/min by kind +
  live log panel).
- Host API: `server/observability/profiling.py` attaches `pyroscope-io` in the
  lifespan when `tracing.pyroscope_base_url` is set; truthful agent state is
  appended to the Pyroscope component detail. `RAGWELD_DISABLE_PROFILING=1` in
  `tests/conftest.py` and the strict launcher.
- Langfuse ingestion fixed for real: `record_langfuse_generation` had called
  `update_current_generation` outside any Langfuse observation context — a
  silent no-op (this integration had never run against a live server). It now
  creates a real generation observation on the shared TracerProvider; the SDK
  was bumped to `langfuse>=4.7.0` (4.14.5) because older SDKs are delayed up
  to 15 minutes on the v4 read APIs. Cost details are Langfuse-shaped via
  `langfuse_cost_details`; the observation name is a `generate_chat_text`
  parameter (`chat.generation`, `chat.generation.stream`,
  `reranker.generation`, `benchmark.generation`, `eval.answer.generation`,
  `eval.analysis.generation`, `synthetic.grounded_qa.generation`/`.judge`).
- Frontend: `@grafana/faro-web-sdk` (2.10.0) initialized once from the loaded
  config (`web/src/observability/faro.ts`, `useAppInit`), gated on
  `tracing.faro_base_url`. Infrastructure Services/Docker subtabs carry the
  new services (type-enforced by `RagweldDockerService`).
- Config: global + all three per-corpus stored configs updated
  (`tracing_mode=otel_langfuse`, langfuse enabled, all five base URLs);
  OpenCost stays empty. Glossary entries added for
  MIMIR/PYROSCOPE/FARO/ALERTMANAGER_BASE_URL (mirrored to web/public).
- Tests: launch-contract extensions (A3 services managed/loopback/volume-backed,
  Prometheus->Mimir/Alertmanager wiring, Alloy faro receiver, active URLs incl.
  `otel_langfuse`), profiling gates + cost mapping units, Faro RUM Playwright
  lane (`playwright.observability.config.ts`,
  `web/tests/e2e/observability/faro_rum.spec.ts`, no interception).

### Live proof (2026-08-24, VM at 16 GiB — ~9.4 GiB free before, fits)

1. `/api/observability/status`: mimir, pyroscope, faro, alertmanager, langfuse
   all `enabled=true reachable=true` on functional readiness paths; pyroscope
   detail shows `host agent: running`; opencost `enabled=false`; mode
   `otel_langfuse`, severity `info`.
2. Mimir answers `count(up)` = 5 scrape targets via `/prometheus` (samples via
   Prometheus remote_write, includes Tempo span metrics).
3. Pyroscope `service_name` label values include `ragweld-api` (host agent
   pushing; verified via the querier API — the legacy label-values GET returns
   null for this label).
4. Alertmanager `/-/ready` OK and `/api/v2/alerts` carries `RagweldWatchdog`
   (Prometheus -> Alertmanager delivery proven).
5. Faro: Playwright (real browser, no interception) proves the boot beacon is
   ACCEPTED (2xx) by the live collector with a rendered shell and clean
   console; events appear in Loki labelled
   `service_name=ragweld-web, ragweld_service=web, deployment_runtime=browser`.
6. Langfuse: real grounded chat on `epstein-files-1` (real domain questions,
   paid alias `openai.gpt-5.6-luna` per standing rule) produced GENERATION
   observations on the SAME trace id as the API's `X-Trace-ID`
   (`a659c9939466c50f4a1158c586673388`): answer generation $0.000844 with full
   input/output/usage, reranker generation (`openai.gpt-4.1-nano`) $0.000382.
   Read via `GET /api/public/v2/observations?fields=core,basic,io,model,usage`.

### Incidental findings fixed along the way

- Twelve pytest-leftover corpora (pytest_lineage_*, test-mine-*) had leaked
  into the live corpus registry and caused boot-time 404 noise
  (`/api/index/<id>/stats`); deleted via `DELETE /api/repos/{corpus_id}`.
  Root cause (pytest writing the shared registry) not addressed in this slice.
- The operator repositioned README.md mid-session; the positioning guardrail
  test pinned the old tagline literals. The test now pins the surviving safe
  claims ("Versioned source-of-truth config", "Manifest-backed training
  artifacts", "provenance-minded workflows", "without claiming full end-to-end
  DSV governance") and still bans "full DSV compliance".

### Adversarial review (codex exec, high effort — REFUTED, 2 P1 / 8 P2, all acted on)

1. **P1 — blocking HTTP on the async generation path** (`get_trace_url` does a
   synchronous, uncached project lookup): FIXED — the Langfuse deep link is now
   built deterministically from config (`langfuse_trace_url`); the recording
   path only enqueues spans to the SDK's batch exporter thread.
2. **P1 — fresh clone silently records nothing while status shows healthy**
   (no LANGFUSE keys in `.env.example`): FIXED — `start.sh` generates
   per-machine `infra/langfuse.env` secrets and appends the matching ingestion
   keys to `.env` before first boot; the Langfuse component's `configured` now
   requires a buildable ingestion client (`langfuse_client_blockers`) and the
   detail carries the live ingestion state.
3. **P2 — ingestion path invisible to readiness**: FIXED — client-construction
   and record failures set `langfuse_ingestion_state()` (surfaced in the
   component detail); the worker gained a real healthcheck
   (`$(hostname):3030/api/health` — it binds the container hostname).
4. **P2 — Pyroscope "healthy" with a failed/idle host agent**: FIXED — a
   failed agent degrades the component (configured=false -> warning), and the
   agent state is only "verified" after a background one-shot check confirms
   the server reports `ragweld-api` profiles ("attached" until then; "failed"
   if nothing lands in 60s).
5. **P2 — transient config-load failure permanently disables Faro**: FIXED —
   `useAppInit` subscribes to the config store and re-attempts init when the
   first successful config load arrives (an empty collector URL then settles
   RUM as intentionally off).
6. **P2 — Faro E2E green while the Loki pipeline is broken**: FIXED — the spec
   now polls Loki for the labelled stream
   (`service_name="ragweld-web", ragweld_service="web", deployment_runtime="browser"`)
   after the accepted beacon, and fails if nothing lands in 60s.
7. **P2 — port overrides break CORS/NEXTAUTH silently**: FIXED — the Faro CORS
   origins follow `FRONTEND_PORT` through Compose env into
   `sys.env(...)` in config.alloy (start.sh forwards the variable), and
   `NEXTAUTH_URL` is tied to `${LANGFUSE_PORT:-53000}` in the service
   environment.
8. **P2 — committed dev credentials guard real prompt data**: MITIGATED —
   start.sh provisions per-machine secrets before first boot so a normal
   launch never runs on repo-known values; the example file now says exactly
   when its values would apply and why not to boot bare-compose anywhere it
   matters. (The example must stay parseable for `docker compose config`.)
9. **P2 — "wake-up paging" claim with empty receivers**: FIXED — the status
   detail and glossary now describe Alertmanager as aggregation/routing with
   operator-configured delivery, and `infra/alertmanager.yml` documents the
   intentionally-empty receivers.
10. **P2 — `--wait` returns before distroless services are functional**:
    FIXED — Mimir/Pyroscope images have no shell, so `start.sh` probes their
    `/ready` endpoints from the host (90s deadline) after `up --wait`; the
    Langfuse worker got a container healthcheck.

Post-fix verification: Faro E2E green including the Loki-landing assertion;
status shows `pyroscope … host agent: verified (server reports ragweld-api
profiles)` and `langfuse … ingestion: recording (last generation:
chat.generation)` after a real paid chat; the final trace
(`61b0ef1f787034c02339de3d3230b0d1`) carries `chat.generation` ($0.000896,
gpt-5.6-luna) and `reranker.generation` ($0.00033, gpt-4.1-nano).

### Residuals (documented, not hidden)

- OpenCost stays undeployed/disabled: needs a Kubernetes API server; the
  Colima profile runs the plain Docker runtime.
- Langfuse v4 does not surface the OTel model attribute as
  `providedModelName`; the model rides in observation metadata (upstream gap).
- Browser trace instrumentation (`@grafana/faro-web-tracing`) not installed —
  RUM is events/logs (+ Tempo path ready at the receiver).
- Generation latency in Langfuse is the post-hoc recording instant, not the
  upstream call duration (recording happens after the call returns).

