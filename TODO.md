# MLX Qwen3 “Learning Reranker” (real training + real inference) — drift guard TODOs

**Note:** This TODO is being executed **incrementally in Cursor** (not Codex CLI) so we can iterate file-by-file, run the repo’s verification loop locally, and keep this checklist updated as we go.

## Phase 1 — Pydantic & types (lock the spec)
- [x] Add TrainingConfig fields + `/api/reranker/score` models in `server/models/tribrid_config_model.py`.
  - Verify: `uv run scripts/validate_types.py` (will fail until generated if types changed)
- [x] Regenerate TS types.
  - Verify: `uv run scripts/generate_types.py` then `uv run scripts/validate_types.py`
- [x] Add tooltips for new keys in `data/glossary.json` and sync `web/public/glossary.json` if required by repo workflow.
  - Verify: `uv run scripts/check_banned.py` (and `uv run scripts/validate_glossary.py` if present)

## Phase 2 — MLX backend module (inference first, no training yet)
- [x] Create `server/reranker/mlx_qwen3.py`:
  - Canonical prompt constants
  - Truncation preserving suffix
  - Yes/no id resolution + validations
  - Batched scoring (right-pad + gather logits at `lengths-1`)
  - Hot-reload fingerprinting (`adapter.npz`) with monotonic throttle
  - Idle unload guard (no unload mid-flight; lock/refcount)
  - Cold loads in `asyncio.to_thread`
  - Verify: `uv run pytest -q tests/unit/test_learning_backend_resolution.py` (once added)

## Phase 3 — Wire MLX inference into reranking pipeline
- [x] Update `server/retrieval/rerank.py`:
  - Accept `training_config`
  - Resolve backend: `auto|mlx_qwen3|transformers`
  - If MLX: call `MLXQwen3Reranker.score_pairs_batched`
  - Include backend fields in chunk metadata
  - Verify: `uv run pytest -q` (targeted reranker tests)
- [x] Update `server/retrieval/fusion.py` to pass `cfg.training` into `Reranker`.
  - Verify: `uv run pytest -q` (targeted reranker tests)

## Phase 4 — Training + eval + promotion (MLX)
- [x] Create `server/training/mlx_qwen3_trainer.py`:
  - Triplet→pair conversion with `negative_ratio=5` and deterministic sampling
  - Deterministic dev split (seed=0) reused for baseline/new eval
  - LoRA training with correct gradient accumulation (tree-add → avg → single update/eval)
  - Emit existing `RerankerTrainMetricEvent` shape
  - Write run artifact dir with `adapter.npz`, `adapter_config.json`, `tribrid_reranker_manifest.json`
  - Verify: `uv run pytest -q tests/unit/test_mlx_grad_accum_contract.py`
- [x] Update `server/api/reranker.py`:
  - Backend selection for training/eval
  - Baseline gating via manifest (Bug Trap #2)
  - Promotion gating by primary metric + epsilon
  - Atomic promotion via existing helper
  - Add `POST /api/reranker/train/run/{run_id}/promote`
  - Verify: `uv run pytest -q` (targeted API + unit tests)

## Phase 5 — Debug proof endpoint
- [x] Add `POST /api/reranker/score` in `server/api/reranker.py`.
  - Verify: `uv run pytest -q tests/api/test_reranker_score_endpoint.py`

## Phase 6 — Dependencies & ignore rules
- [x] Update `pyproject.toml` with optional `mlx` extras.
- [x] Update `.gitignore` to ignore `*.npz`, `adapters/`, and MLX adapter artifacts.
  - Verify: `uv run scripts/check_banned.py`

## Phase 7 — Web/Playwright obligations (only if web changes)
- [x] If `web/` changed: `npm --prefix web run lint` and `npm --prefix web run build`
- [x] If GUI-affecting changes occurred: `./start.sh --with-observability` and Playwright E2E.
- [x] Final: `uv run scripts/check_banned.py` + `uv run scripts/validate_types.py` + `uv run pytest -q`

## Phase 8 — Frontend surfacing (learning backend + score proof + studio promote)
- [x] Export `RerankerScoreRequest/Response` in `web/src/types/generated.ts` (via `scripts/generate_types.py` model list).
- [x] Surface MLX learning backend knobs in UI (backend/base model/LoRA/promotion/unload).
- [x] Add “debug proof” UI using `POST /api/reranker/score`.
- [x] Add Training Studio “Promote” button wired to `POST /api/reranker/train/run/{run_id}/promote`.
- [x] Add Welch-labs-style projection panel (`proj_x/proj_y`) + pass-through progress metrics for live telemetry.
