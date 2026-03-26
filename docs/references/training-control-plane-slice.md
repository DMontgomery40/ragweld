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

## What This Slice Does Not Yet Do

- It does not cut Learning Agent launch execution over to Flyte yet.
- It does not make MLflow the live source of truth for started runs yet.
- It does not replace the local MLX trainer for the active launch path yet.

That cutover is the next bounded slice. This slice exists so the Training Center
is no longer blind to the replacement target stack while that cutover is wired.
