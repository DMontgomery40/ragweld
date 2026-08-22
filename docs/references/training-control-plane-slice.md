# Training Control Plane: Flyte + MLflow (+ Unsloth)

Learning Agent Studio is the Training Center surface for the Learning Agent
lane. Three typed backend choices compose the control plane:

- `training.ragweld_agent_workflow_backend` (`local` | `flyte`): who owns the
  run lifecycle (launch/status/cancel).
- `training.ragweld_agent_tracking_backend` (`local` | `mlflow`): where run
  params, metrics, and artifacts are recorded.
- `training.ragweld_agent_backend` (`mlx_qwen3` | `unsloth`): which execution
  backend performs the training.

Operator-facing API: `GET /api/agent/train/control-plane/status` reports each
component as `disabled` / `unconfigured` / `ready` / `degraded` from functional
probes (never from config presence alone), plus links and an operator hint.
Run records carry `workflow_backend`, `tracking_backend`, `execution_backend`,
`workflow_run_id`, `workflow_phase`, `tracking_run_id`, `artifacts_uri`,
`external_links`, and `operator_hint`.

## Source of truth files

- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`
- `/Users/davidmontgomery/ragweld/server/training/control_plane.py`
- `/Users/davidmontgomery/ragweld/server/training/flyte_client.py`
- `/Users/davidmontgomery/ragweld/server/training/mlflow_client.py`
- `/Users/davidmontgomery/ragweld/server/api/agent.py`
- `/Users/davidmontgomery/ragweld/infra/flyte/workflows/learning_agent.py`
- `/Users/davidmontgomery/ragweld/infra/flyte/flytectl.yaml`
- `/Users/davidmontgomery/ragweld/scripts/flyte_register_learning_agent.sh`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/TrainingStudio.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/ControlPlaneStatus.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/RunOverview.tsx`

## Flyte orchestration (real since 2026-08-21)

Deployment: the Compose-owned `flyte` service in `docker-compose.yml` runs the
pinned Flyte v1.16.8 sandbox bundle (flyteadmin + propeller + console + minio
+ postgres on an embedded k3s, `privileged`). Start it with
`./start.sh --with-flyte` (or `docker compose --project-name ragweld -f
docker-compose.yml up -d --wait flyte`). It publishes flyteadmin/console on
`127.0.0.1:${FLYTE_PORT:-30080}` and the sandbox minio on `127.0.0.1:30002`
(fast registration uploads go there; keep the default port). Infrastructure ->
Docker can start/stop it like any other managed service.

Registration: `scripts/flyte_register_learning_agent.sh` creates the `ragweld`
project if needed, waits for the `ragweld-development` namespace that
flyteadmin materializes asynchronously, and fast-registers
`infra/flyte/workflows/learning_agent.py` (task `execute_learning_agent_run`,
workflow `learning_agent_train`, launch plan `learning-agent-train`) with a
content-hash version using the `flyte` extra (`flytekit`). The task only needs
the standard library, so the stock `cr.flyte.org/flyteorg/flytekit` image runs
it.

Why the task calls back: the `mlx_qwen3` execution backend only exists on the
Apple Silicon host, so the Flyte task cannot train inside its pod. Instead the
task hands the run to the host API and tracks it:

1. `POST /api/agent/train/start` with `workflow=flyte` preflights the admin
   (`/healthcheck`) and resolves the newest version of the configured launch
   plan; any gap is a typed 503 `workflow_backend_unavailable` with the exact
   reason. It then records the run as `queued`, creates the Flyte execution
   (inputs `run_id`, `corpus_id`, `callback_base_url`, `execution_backend`),
   and stores `workflow_run_id` (execution name) and `workflow_phase`.
   No in-process job starts at launch.
2. The Flyte task calls `POST /api/agent/train/run/{run_id}/execute` with its
   execution name. The API accepts it only for a Flyte-owned run whose
   `workflow_run_id` matches (409 `workflow_backend_mismatch` /
   `workflow_run_mismatch` / `run_terminal` otherwise), flips the run to
   `running`, and starts the host training job. The task then polls
   `GET /api/agent/train/run/{run_id}` until a terminal status and fails the
   execution on anything but `completed`.
3. Every run load mirrors the Flyte phase onto `workflow_phase` (throttled).
   For a non-terminal local run, Flyte `ABORTING/ABORTED` cancels the host job
   and `FAILED/TIMED_OUT` fails it (with Flyte's error message); a `SUCCEEDED`
   execution against a still-running host run is recorded as an inconsistency
   failure, never inferred as success. Terminal local runs keep mirroring the
   phase until Flyte is terminal too.
4. `POST /api/agent/train/run/{run_id}/cancel` terminates the Flyte execution
   (cause recorded in Flyte) and cancels the host job, or finalizes a still
   `queued` run directly; MLflow runs are terminated `KILLED`/`FAILED` in
   lockstep.

`training.ragweld_agent_flyte_callback_base_url` is the host API as reachable
from Flyte task pods. On Colima that is the VM gateway
(`http://192.168.5.2:58012`); pods cannot resolve `host.docker.internal`.
Console deep links use `ragweld_agent_flyte_console_base_url` (or
`<admin>/console`).

## MLflow tracking (real)

When `tracking=mlflow`, `/api/agent/train/start` opens a run on the
Compose-owned `mlflow` service (`127.0.0.1:55500`), logs params and train/eval
metrics, uploads `ragweld_run_manifest.json`, and terminates the MLflow run
FINISHED/KILLED/FAILED in lockstep with the local run. An unreachable server is
a typed 503 `tracking_backend_unavailable`.

## Unsloth execution (blocked by hardware)

`execution=unsloth` needs an NVIDIA CUDA runtime; this host is darwin/arm64.
Launch refuses with a typed 503 `execution_backend_unavailable` naming the
blocker. No cloud GPU spend without explicit authorization.

## Verification

- `tests/unit/test_flyte_client.py` (REST contract against a real local
  server), `tests/unit/test_agent_training_control_plane.py` (readiness
  semantics including callback + launch-plan registration).
- `tests/api/test_agent_train_launch_boundaries.py` (typed 503s for missing
  config / unreachable admin / unreachable MLflow / Unsloth).
- `tests/api/test_agent_train_flyte_orchestration.py` (`requires_flyte`,
  strict lane): real execution created, execute-boundary guards, cancel ->
  Flyte ABORTED with cause -> phase mirrored onto the run.
- Operator acceptance (recorded in the recovery exec plan): full round trip
  Flyte task -> execute boundary -> MLX training -> `completed` -> Flyte
  `SUCCEEDED`, rendered in Training Center with the Flyte execution link.
