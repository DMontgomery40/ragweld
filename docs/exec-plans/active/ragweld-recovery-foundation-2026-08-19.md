# Ragweld Recovery Foundation

Date: 2026-08-19

Status: active

## Goal

Produce one clean, reproducible Ragweld development platform from current `main` plus the preserved OSS-composition work. Local databases and generated indexes start empty. Git history, stashes, and source work remain recoverable. Colima is host-owned; repository code never starts, stops, resets, or deletes a VM.

## Locked operating model

- Branch: `feat/ragweld-recovery-foundation`
- Colima: dedicated host-managed `ragweld` profile
- Docker context: selected explicitly by the operator before repository launch
- Data and observability: one Compose project named `ragweld`
- Application processes: FastAPI and Vite run on the host in normal development
- Persistent development stores: Compose named volumes scoped to the `ragweld` project
- Integration tests: isolated Compose project and empty disposable volumes
- Test behavior:
  - ordinary local tests skip explicitly marked live-service tests when a service is unreachable
  - strict integration mode fails immediately when a required service is unreachable
  - tests never infer readiness from environment-variable presence
- No legacy fallback launchers, hidden process spawning, fixed global container names, or automatic Colima recovery/deletion

## Completed recovery evidence

- Current remote `main`: `d39c84605f8063b292270341ba0258e8ea512aee`
- Recovered OSS replay tree before local graph work: `281f510014f706680fd2503e494391a08ecc5fb3`
- Preserved graph patch ID: `7ca5c5fb1d5d90cfe818855ccb82349177b1eb61`
- Primary checkout is the only worktree.
- Local `main` equals `origin/main`.
- Local branches are reduced to `main` and the active recovery branch. The six
  agent-created archive/rescue refs were removed after a complete temporary
  recovery bundle was verified outside the repository.
- Old Postgres, Neo4j, and Qdrant state was deleted after explicit clean-start authorization.
- 6,543 committed `tmp/` and `web/tmp/` artifacts were removed and ignored.
- Replacement-only synthetic contracts and model-catalog selection metadata are repaired.

## Task 1: Lock runtime ownership with executable tests

Status: complete

Files:

- Add `tests/unit/test_runtime_launch_contract.py`
- Modify `start.sh`
- Modify `web/vite.config.ts`

Test first:

1. Assert `start.sh --check` never emits a `colima start`, `colima stop`, or `colima delete` action.
2. Assert a real launch fails with an operator-facing message when the selected Docker daemon is unavailable.
3. Assert Vite exposes no endpoint that spawns a backend process.

Implementation:

- Delete Colima lifecycle functions and stale-container reuse logic from `start.sh`.
- Require an already-reachable Docker daemon when Docker services are requested.
- Report the selected Docker context and tell the operator how to select/start the dedicated profile.
- Remove the Vite `child_process` backend launcher and its POST route; retain status-only development reporting only if it has a live UI consumer.

Acceptance:

```bash
uv run pytest -q tests/unit/test_runtime_launch_contract.py tests/api/test_dev_stack_endpoints.py
./start.sh --check --no-backend --no-frontend
npm --prefix web run lint
npm --prefix web run build
```

## Task 2: Make Compose project-scoped and path-correct

Status: complete

Files:

- Modify `docker-compose.yml`
- Modify `infra/docker-compose.observability.yml`
- Delete or replace `infra/docker-compose.dev.yml`
- Add `infra/.env.ragweld.example` only if Compose needs documented non-secret port defaults
- Extend `tests/unit/test_runtime_launch_contract.py`

Test first:

1. Render merged Compose configuration and assert no `container_name` or fixed global network name exists.
2. Assert Postgres and Neo4j use project-scoped named volumes, not sibling bind directories.
3. Assert observability mounts resolve to `infra/tempo.yaml` and `infra/alloy/config.alloy`.
4. Assert host ports are configurable and default away from known foreign observability listeners.

Implementation:

- Remove every fixed `tribrid-*` container name.
- Remove the fixed `tribrid-network` name.
- Replace external database bind mounts with named volumes.
- Fix secondary Compose-file paths using paths that resolve correctly from the project directory.
- Make Grafana, Loki, Tempo, Alloy, Prometheus, and OTLP host ports configurable.
- Use namespaced application ports `58012` and `55173`; keep Postgres `5432` and Neo4j `7474`/`7687` while they are free.

Acceptance:

```bash
docker compose --project-name ragweld config
docker compose --project-name ragweld -f docker-compose.yml -f infra/docker-compose.observability.yml config
uv run pytest -q tests/unit/test_runtime_launch_contract.py
```

## Task 3: Make test service requirements explicit

Status: complete; live disposable-service execution is part of Task 4

Files:

- Modify `server/main.py`
- Modify `tests/conftest.py`
- Modify `pyproject.toml`
- Modify the 34 service-bound tests only to add truthful service markers/fixtures
- Add `scripts/test_integration.sh`
- Add tests for the capability probe itself

Test first:

1. Prove importing `server.main` in test mode does not load repository `.env`.
2. Prove Postgres readiness requires a successful real connection, not an environment key.
3. Prove local mode skips marked tests with an exact reason when Postgres is unreachable.
4. Prove strict mode fails the session when a required service is unreachable.

Implementation:

- Add an explicit environment switch that disables dotenv loading before app import.
- Register `requires_postgres` and `requires_neo4j` markers.
- Add one session-scoped real capability probe.
- Mark live-service tests; do not mock the services.
- Add a strict integration launcher that assumes Docker/Colima is already running, starts isolated empty services, runs marked tests, and tears down its volumes.

Acceptance:

```bash
uv run pytest -q
RAGWELD_STRICT_INTEGRATION=1 ./scripts/test_integration.sh
```

## Task 4: Bring up and prove a clean data plane

Host action, outside repository automation:

```bash
colima start --profile ragweld --vm-type vz --cpu 4 --memory 8
docker context use colima-ragweld
```

Repository action:

```bash
docker compose --project-name ragweld up -d --wait postgres neo4j
```

Acceptance:

- Fresh named volumes are created.
- Postgres initializes required extensions and schema from empty state.
- Neo4j initializes from empty state.
- `/api/health` remains dependency-free liveness.
- `/api/ready` reports dependency truth.
- Strict Postgres and Neo4j integration tests pass.
- No foreign listener is mistaken for a Ragweld service.

## Task 5: Repair service-outage semantics

Files:

- Modify stateful API boundaries in `server/api/search.py`, `server/api/feedback.py`, `server/api/graph.py`, and scoped config/corpus loading
- Add regression tests using real unreachable endpoints, not mocks

Behavior:

- Unavailable required stores return structured `503` responses with an operator hint.
- `404` is reserved for a reachable store that proves a corpus does not exist.
- Search does not swallow a Postgres outage and return an empty `200`.

## Task 6: Continue dead-code removal after the runtime baseline is green

Method for every slice:

1. GitNexus upstream impact/context.
2. Repository-wide literal and dynamic-reference search.
3. Delete backend, UI, tests, docs, and generated contracts together when the replacement rule applies.
4. Run the affected suite plus standard repository gates.

Next candidates:

- Dead internal synthetic recipe-generation functions left behind after `synthetic_data_kit` replacement
- Orphaned frontend components and service facades identified in the architecture audit
- Stale Docker UI contracts with no backend owner
- Tracked model artifacts with no runtime references
- Agent-spec prose blocks that no tool consumes

## Standard closeout gate

```bash
uv run python scripts/check_docs_ownership.py
uv run scripts/check_banned.py
uv run scripts/validate_types.py
uv run python scripts/check_runtime_capabilities_catalog.py
uv run pytest -q
npm --prefix web run lint
npm --prefix web run build
```

CI is not authoritative until the GitHub billing lock is cleared; local verification remains mandatory.
