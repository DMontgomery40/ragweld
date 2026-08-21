# Training Control Plane Slice

This reference describes the first bounded Training Center workflow slice for the
Learning Agent lane.

## Scope

- Protected surface: Learning Agent Studio remains the in-product Training Center surface.
- New source-of-truth vocabulary:
  - `training.ragweld_agent_workflow_backend`
  - `training.ragweld_agent_tracking_backend`
  - `training.ragweld_agent_flyte_*`
  - `training.ragweld_agent_mlflow_*`
  - `training.ragweld_agent_unsloth_image`
- New operator-facing API:
  - `GET /api/agent/train/control-plane/status`
- New run metadata:
  - `workflow_backend`
  - `tracking_backend`
  - `execution_backend`
  - `workflow_run_id`
  - `tracking_run_id`
  - `artifacts_uri`
  - `external_links`
  - `operator_hint`

## Source Of Truth Files

- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`
- `/Users/davidmontgomery/ragweld/server/training/control_plane.py`
- `/Users/davidmontgomery/ragweld/server/api/agent.py`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/TrainingStudio.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/ControlPlaneStatus.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/RunOverview.tsx`

## What This Slice Does

- Makes the `Flyte + MLflow + Unsloth` target lane explicit in the Training Center UI.
- Reports per-component readiness, links, and operator hints in-product.
- Extends Learning Agent run models so future cutover work has typed fields for
  workflow/tracking truth instead of local-only filesystem assumptions.

## Current Execution Truth (2026-08-21)

- MLflow tracking is real: when `training.ragweld_agent_tracking_backend=mlflow`,
  `/api/agent/train/start` opens a run on the Compose-owned `mlflow` service
  (`127.0.0.1:55500`), logs params and train/eval metrics, uploads
  `ragweld_run_manifest.json`, and terminates the MLflow run
  FINISHED/KILLED/FAILED in lockstep with the local run. The run record carries
  `tracking_run_id`, `artifacts_uri`, and a deep link to the MLflow run.
- Launch fails closed on configured-but-unavailable backends with typed 503
  details: `workflow=flyte` (no wired Flyte execution path in this build),
  `execution=unsloth` (requires an NVIDIA CUDA runtime; this host is
  darwin/arm64), and `tracking=mlflow` with an unreachable server. The local
  lane is never substituted silently.

## What Is Still Not Wired

- Flyte orchestration: no Flyte deployment is provisioned or wired; the
  workflow boundary refuses to fake orchestration.
- Unsloth execution: blocked by hardware (CUDA) on Apple Silicon; the
  execution boundary reports the exact blocker.
- The active launch path still executes on the local MLX trainer.
