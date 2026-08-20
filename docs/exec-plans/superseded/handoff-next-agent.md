# Handoff Prompt: Ragweld Provider + Learning Agent Studio (Qwen3-1.7B MLX LoRA)

Date: 2026-02-16
Repo: `/Users/davidmontgomery/ragweld`
Branch: `main` (already pushed)

## 0) Read This First (What You Are Walking Into)

The previous agent shipped a large end-to-end feature set:

- A first-class built-in chat provider kind: `ragweld` (in-process MLX model with hot-swappable LoRA adapter).
- A full “Learning Agent Studio” UI and backend run system mirroring the existing Learning Reranker Studio (runs list, inspector, metrics streaming, run HUD, NeuralVisualizer, telemetry).
- A real MLX LoRA training loop for a chat-style model (Qwen3-1.7B 4-bit base) that trains on chat datasets and can promote a LoRA adapter to the active runtime model path.

The user is unhappy because there is a “LAW mismatch” in the repo about how models are selected for dropdowns:

- `server/api/models.py` explicitly claims `data/models.json` is “THE source of truth” and forbids hardcoded model lists anywhere else.
- But `ragweld` is a runtime provider model and not present in `data/models.json`.
- The current solution injects `ragweld:mlx-community/Qwen3-1.7B-4bit` into the Generation dropdown in the UI as a special-case, which violates that stated law.

Your job as the next agent is likely to:

- Fix that “LAW mismatch” correctly (backend catalog augmentation and removing the UI injection).
- Produce a screen recording of Qwen3 training with live telemetry and the gradient descent visualization visible and updating.
- Double-check any remaining “not following the law” inconsistencies and close them.

This document is intentionally extremely specific and includes exact paths, commit hashes, and concrete verification steps.

## 1) What Is Already On `main` (Do Not Re-Implement)

Recent commits on `main` (newest first):

- `b084ce9` `docs: add agent kb + mkdocs repo nav @codex`
- `8560d1f` `fix: allow ragweld for graphrag semantic KG llm @codex`
- `f8d70be` `fix: expose ragweld qwen3 in chat + GEN pickers @codex`
- `3c93823` `fix: agent studio gradient descent + mlx lora stability @codex`
- `1f01ede` `feat: ragweld provider + Learning Agent Studio @codex`

There are also a couple of general stability fixes in between (`8fab532`, `83d8249`, `d66e59e`) that reduce import-time OpenAI init and fix docker build behavior.

Untracked local artifacts currently exist (NOT committed):

- `models/learning-agent-epstein-files-1/` (promoted adapter artifacts)
- `output/` (training + playwright artifacts, including videos if recorded)

These are intentionally untracked because they can be large and machine-specific.

## 2) Core Feature Inventory (What Exists Where)

### 2.1 Ragweld Provider Routing

Key files:

- `/Users/davidmontgomery/ragweld/server/chat/provider_router.py`
- `/Users/davidmontgomery/ragweld/server/services/answer_service.py`
- `/Users/davidmontgomery/ragweld/server/chat/handler.py`
- `/Users/davidmontgomery/ragweld/server/api/eval.py`
- `/Users/davidmontgomery/ragweld/server/chat/benchmark_runner.py`

Important behavior:

- `ProviderRoute.kind` includes `"ragweld"`.
- `select_provider_route(...)` now accepts the full `TriBridConfig` (not only `chat_config`) so it can read `training.ragweld_agent_*`.
- `ragweld` is selected when `model_override` is prefixed like: `ragweld:<model-id>`.
  - Example: `ragweld:mlx-community/Qwen3-1.7B-4bit`
- Route fields used by generation:
  - `route.model` is the ragweld model id (suffix after `ragweld:`)
  - `route.provider_name` is `"Ragweld"`
  - `route.base_url` is empty/None (in-process)
  - Optional ragweld-specific fields exist on the route:
    - `ragweld_backend`
    - `ragweld_base_model`
    - `ragweld_adapter_dir`
- Fallback semantics:
  - If ragweld is selected but MLX is unavailable, the router logs a warning and falls back to the existing provider selection order.
  - If the user explicitly requested ragweld via prefix and fallback also can’t resolve, it should surface an error as appropriate.

### 2.2 Ragweld Inference (In-Process Generation)

Key files:

- `/Users/davidmontgomery/ragweld/server/chat/generation.py` (integration point)
- `/Users/davidmontgomery/ragweld/server/chat/ragweld_mlx.py` (new dedicated module)
- `/Users/davidmontgomery/ragweld/server/retrieval/mlx_qwen3.py` (LoRA injection utilities + MLX availability checks)

Important behavior:

- `generate_chat_text(...)` routes to `ragweld_mlx.generate(...)` when `route.kind == "ragweld"`.
- `stream_chat_text(...)` routes to `ragweld_mlx.stream(...)` for token/chunk deltas compatible with existing SSE behavior.
- `ragweld_mlx.py`:
  - Caches base model + tokenizer in-process and applies LoRA layers using the same approach as retrieval/reranker MLX utilities.
  - Loads adapter weights from `training.ragweld_agent_model_path` (expects `adapter.npz` and `adapter_config.json`).
  - Hot-reload support:
    - Reloads adapter when `training.ragweld_agent_reload_period_sec` elapses OR adapter mtime changes.
  - Unload-after-idle:
    - If idle longer than `training.ragweld_agent_unload_after_sec`, unloads model to reclaim memory.
  - Vision unsupported:
    - If `images[]` is non-empty, it raises a clear error that ragweld doesn’t support vision yet.
  - Exposes a cache reset hook:
    - `ragweld_mlx.clear_cache()` is used after promotion so inference swaps immediately.

### 2.3 /api/chat Models + Health

Key file:

- `/Users/davidmontgomery/ragweld/server/api/chat.py`

Behavior:

- `GET /api/chat/models` includes a ragweld entry:
  - `provider = "Ragweld"`
  - `source = "ragweld"`
  - `id = training.ragweld_agent_base_model` (default `"mlx-community/Qwen3-1.7B-4bit"`)
  - `supports_vision = false`
- `GET /api/chat/health` includes a ragweld health row:
  - reachable is true only if MLX is available and basic imports/model checks succeed (kept fast).
  - detail includes actionable error messages when unreachable.

### 2.4 Training Config (New “ragweld agent” knobs)

Key file:

- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`

New config fields live under `training.*`:

- `training.ragweld_agent_backend` (default `"mlx_qwen3"`)
- `training.ragweld_agent_base_model` (default `"mlx-community/Qwen3-1.7B-4bit"`)
- `training.ragweld_agent_model_path` (default `"models/learning-agent-epstein-files-1"`)
- `training.ragweld_agent_unload_after_sec`
- `training.ragweld_agent_reload_period_sec`
- `training.ragweld_agent_train_dataset_path` (default `""`, empty means use `evaluation.eval_dataset_path`)
- `training.ragweld_agent_lora_rank`
- `training.ragweld_agent_lora_alpha`
- `training.ragweld_agent_lora_dropout`
- `training.ragweld_agent_lora_target_modules` (list[str])
- `training.ragweld_agent_grad_accum_steps`
- `training.ragweld_agent_telemetry_interval_steps`
- `training.ragweld_agent_promote_if_improves` (0/1)
- `training.ragweld_agent_promote_epsilon`

Env mapping exists:

- `TriBridConfig.to_env_dict()` includes `RAGWELD_AGENT_*` keys.
- `TriBridConfig.from_env()` parses those keys back into `training.*`.
- `ENV_VARS` includes those keys so docs stay complete.

### 2.5 Agent Training Run System (Backend)

Key files:

- `/Users/davidmontgomery/ragweld/server/api/agent.py` (new)
- `/Users/davidmontgomery/ragweld/server/api/__init__.py` (router export)
- `/Users/davidmontgomery/ragweld/server/main.py` (router include)
- `/Users/davidmontgomery/ragweld/server/training/mlx_qwen3_agent_trainer.py` (new trainer)
- `/Users/davidmontgomery/ragweld/server/chat/ragweld_mlx.py` (cache clear called by promote endpoint)

Runs directory:

- `data/agent_train_runs/<run_id>/`
- Contains:
  - `run.json`
  - `metrics.jsonl` (JSON per line Studio events)
  - `model/` (adapter artifact output: `adapter.npz`, `adapter_config.json`, `manifest.json`, etc.)

Endpoints (mirror reranker training patterns):

- `GET  /api/agent/train/runs?scope=...`
- `POST /api/agent/train/start`
- `GET  /api/agent/train/run/{run_id}`
- `GET  /api/agent/train/run/{run_id}/metrics`
- `GET  /api/agent/train/run/{run_id}/stream` (SSE tailing `metrics.jsonl`)
- `POST /api/agent/train/run/{run_id}/cancel`
- `POST /api/agent/train/run/{run_id}/promote` (copies run artifacts to `training.ragweld_agent_model_path` and calls `ragweld_mlx.clear_cache()`)
- `POST /api/agent/train/run/{run_id}/diff`

Cancellation:

- In-memory map of running tasks + cancellation flags (pattern-matched from reranker).
- Training loop checks cancel flag and raises `TrainingCancelledError`.

### 2.6 Agent Training Models + TS Types

Key files:

- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py` (new Pydantic models)
- `/Users/davidmontgomery/ragweld/scripts/generate_types.py`
- `/Users/davidmontgomery/ragweld/web/src/types/generated.ts` (generated; do not hand-edit)

New models (mirroring reranker but agent-specific):

- `AgentTrainStartRequest`, `AgentTrainStartResponse`
- `AgentTrainRunStatus`, `AgentTrainRunSummary`, `AgentTrainRun`, `AgentTrainRunsResponse`
- `AgentTrainEventType`, `AgentTrainMetricEvent`, `AgentTrainMetricsResponse`
- `AgentTrainDiffRequest`, `AgentTrainDiffResponse`

Primary metric semantics:

- Primary metric defaults to `"eval_loss"` and goal is `"minimize"`.
- Diff response “improved” respects minimize-vs-maximize.

### 2.7 Learning Agent Studio (Frontend)

Key files:

- `/Users/davidmontgomery/ragweld/web/src/components/RAG/RAGSubtabs.tsx` (new subtab entry)
- `/Users/davidmontgomery/ragweld/web/src/components/tabs/RAGTab.tsx` (renders new subtab)
- `/Users/davidmontgomery/ragweld/web/src/components/RAG/LearningAgentSubtab.tsx` (new)

Studio components (agent-specific, adapted from reranker):

- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/TrainingStudio.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/RunOverview.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/RunDiff.tsx`
- `/Users/davidmontgomery/ragweld/web/src/services/AgentTrainingService.ts`

Visualization components are reused (not reimplemented):

- `/Users/davidmontgomery/ragweld/web/src/components/RerankerTraining/NeuralVisualizer.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/RerankerTraining/NeuralVisualizerCore.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/RerankerTraining/NeuralVisualizerControls.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/RerankerTraining/StudioLogTerminal.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/RerankerTraining/DotMatrix.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/RerankerTraining/GradientDescentViz.tsx`

Important UI requirements implemented:

- Same concepts as Reranker Studio: runs list, inspector panel, metrics streaming, run HUD, neural/telemetry visualization.
- “Debug Score Pair” was removed for Agent Studio and replaced with “Debug Prompt”:
  - Textarea + Run button that calls the existing chat/answer endpoint using `model_override = ragweld:<base_model>`.
  - Displays raw completion for quick validation of the currently-active adapter.
- CSS:
  - `/Users/davidmontgomery/ragweld/web/src/styles/learning-studio.css` includes `.learning-agent-subtab` layout styling parallel to `.learning-reranker-subtab`.

### 2.8 Model Picker Integration (Frontend)

Key files:

- `/Users/davidmontgomery/ragweld/web/src/components/Chat/ModelPicker.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Benchmark/BenchmarkTab.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Chat/ProviderSetup.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Chat/ChatInterface.tsx`

Behavior:

- `ChatModelInfo.source` union includes `"ragweld"`.
- ModelPicker generates option values like `ragweld:<id>` for ragweld models.
- ProviderSetup displays ragweld health row from `/api/chat/health`.
- `ChatInterface.tsx` was fixed so persisted model overrides keep the correct `ragweld:` prefix when re-selected.

Additionally:

- `/Users/davidmontgomery/ragweld/web/src/components/RAG/RetrievalSubtab.tsx` injects the ragweld base model into the “Generation Model” dropdown by merging `ragweld:<base>` into the list loaded from `/api/models/by-type/GEN`.
  - This is the key “LAW mismatch” (see section 4).

### 2.9 GraphRAG Semantic KG LLM (Backend)

Key file:

- `/Users/davidmontgomery/ragweld/server/api/index.py`

Behavior change:

- Semantic KG extraction previously hardwired to OpenAI `responses.create`.
- It now routes via `select_provider_route(...)` and `generate_chat_text(...)` so ragweld/local/openrouter can be used.
- It preserves OpenAI JSON-mode Responses when `route.kind == cloud_direct` and provider is OpenAI.
- On failure/parse issues it returns empty extraction so indexing falls back to heuristics.

## 3) How To Verify Everything Quickly (Local Checklist)

### 3.1 Backend Start Sanity

- Confirm working tree is clean (except untracked artifacts):
  - `git status --porcelain=v1`
- Start backend using whatever normal dev workflow exists in this repo.
  - If you don’t know, check `/Users/davidmontgomery/ragweld/start.sh` and `/Users/davidmontgomery/ragweld/README.md`.

### 3.2 Ragweld Provider Shows Up

Hit:

- `GET /api/chat/models`
  - Expect an entry with `provider="Ragweld"`, `source="ragweld"`, `id="mlx-community/Qwen3-1.7B-4bit"`.
- `GET /api/chat/health`
  - Expect a row with `kind="ragweld"`.
  - If MLX isn’t available (common on non-Apple hardware), it should be `reachable=false` with a clear detail message.

### 3.3 Ragweld Inference Works

Call any existing chat/answer endpoint with:

- `model_override = "ragweld:mlx-community/Qwen3-1.7B-4bit"`

Expected:

- If MLX is available and model can load, response comes from in-process model.
- If MLX is unavailable, you should see a clear warning and fallback behavior consistent with router semantics.

### 3.4 Agent Training Run End-to-End

From UI:

- Open “RAG” tab.
- Select “Learning Agent Studio”.
- Start a run.

Expected on disk:

- `data/agent_train_runs/<run_id>/run.json`
- `data/agent_train_runs/<run_id>/metrics.jsonl` grows over time with:
  - `type="metrics"` events containing at least `train_loss` and `eval_loss`
  - `type="telemetry"` events containing `proj_x` and `proj_y` (top-level fields)
- `data/agent_train_runs/<run_id>/model/` contains:
  - `adapter.npz`
  - `adapter_config.json`
  - `manifest.json`

Promote:

- Click “Promote” in the Studio.
- Verify artifacts were copied into:
  - `training.ragweld_agent_model_path` (default `models/learning-agent-epstein-files-1`)
- Confirm inference hot-swap:
  - `ragweld_mlx.clear_cache()` runs and the next ragweld request loads the newly promoted adapter.

### 3.5 Gradient Descent Viz (User Explicitly Wants To See This)

In Studio:

- Ensure the NeuralVisualizer panel has the “Gradient Descent” view.
- Confirm the visualization updates as telemetry events stream.

Implementation detail:

- The viz expects `proj_x/proj_y` at the top level of the telemetry event, not nested under `metrics.proj_x`.

## 4) The “LAW Mismatch” (Root Cause, Current State, Required Fix)

The repo contains an explicit “law” statement:

- `/Users/davidmontgomery/ragweld/server/api/models.py` says:
  - `data/models.json` is THE source of truth for all model selection in the UI.
  - No hardcoded model lists anywhere else.

But ragweld is introduced as:

- A provider/model override mechanism for chat generation, not a fixed “catalog model” in `data/models.json`.
- A runtime-only entry that is currently exposed via `/api/chat/models`, not `/api/models`.

What currently violates that law:

- `/Users/davidmontgomery/ragweld/web/src/components/RAG/RetrievalSubtab.tsx`
  - It calls `/api/models/by-type/GEN` but then prepends an extra option:
    - `ragweld:<training.ragweld_agent_base_model>`

This violates the explicit “no hardcoded lists anywhere else” promise.

What the user likely expects:

- If “models.json is the law”, then `ragweld:mlx-community/Qwen3-1.7B-4bit` should come from the backend catalog.
- The UI should not special-case ragweld at all.

Required fix direction (preferred):

- Update the backend models catalog endpoint so it can augment `data/models.json` with a dynamic ragweld entry derived from scoped config.
- Then remove the UI injection from `/Users/davidmontgomery/ragweld/web/src/components/RAG/RetrievalSubtab.tsx`.

Two concrete approaches:

Approach A (simplest, static):

- Add a GEN model row in `/Users/davidmontgomery/ragweld/data/models.json`:
  - provider = Ragweld
  - model = `ragweld:mlx-community/Qwen3-1.7B-4bit`
  - components = ["GEN"]
  - family / metadata consistent with the file’s conventions
- Downside:
  - It becomes stale if `training.ragweld_agent_base_model` changes in config.

Approach B (correct and future-proof, dynamic):

- Modify `/Users/davidmontgomery/ragweld/server/api/models.py` so `GET /api/models` and `/api/models/by-type/*` can:
  - Load scoped config (corpus_id/repo_id) similarly to other endpoints.
  - Append a generated ragweld model entry into the returned catalog:
    - `model = f"ragweld:{training.ragweld_agent_base_model}"`
    - Mark it as GEN capable.
  - Do not write to disk; only augment the response.
- Then delete the special-case injection code in `/Users/davidmontgomery/ragweld/web/src/components/RAG/RetrievalSubtab.tsx`.
- Benefit:
  - UI becomes “lawful” again and config-driven.

If you choose Approach B, be careful about:

- Avoiding heavy work per request:
  - Config load should be cheap, cached, or optional (only when a `scope`/`corpus_id` is provided).
- Not breaking existing clients:
  - Keep existing endpoint shapes identical, only adding models.

## 5) Screen Recording Deliverable (User Asked For This Explicitly)

The user asked to “see” Qwen3 training with:

- Live run metrics streaming.
- Gradient descent viz visibly updating (confirm operating state).

Suggested way to deliver:

- Use Playwright (repo already has `playwright.config.ts`) to:
  - Launch the web UI.
  - Navigate to RAG tab → Learning Agent Studio.
  - Start a training run.
  - Keep the NeuralVisualizer visible on the Gradient Descent view while telemetry streams.
  - Record video and save under `output/` (untracked is fine).

Important:

- Make the recording long enough to show multiple telemetry updates.
- Ensure the Gradient Descent panel is in-frame with moving points/updates, not just a static screen.

If MLX isn’t available on the machine running this, you will need:

- A machine that can run MLX (typically Apple Silicon).
- Or a pre-recorded run plus replay UI (not currently implemented).

## 6) Additional “Law” Checks (What Else Might Be Off)

The user’s “law” language in this repo commonly refers to:

- Pydantic models are the law for API + config shapes.
- TypeScript types are generated from Pydantic and must match.
- Models catalog (data/models.json + /api/models) is the law for dropdown model selection (EMB/GEN/RERANK).

Potential trouble spots to audit:

- Any exhaustive switches over `ChatModelInfo.source` / `ChatProviderInfo.kind` / `ProviderHealth.kind` that might still be missing `ragweld`:
  - Search in `/Users/davidmontgomery/ragweld/web/src` for `switch (` on those unions.
- Any backend references to the old `select_provider_route(chat_config, ...)` signature that weren’t updated (should already be updated, but re-grep to be safe).
- Any other UI dropdowns still using `/api/models` that should include ragweld, now that ragweld is a “real” provider.

## 7) Quick File Index (You Will Use This)

Backend:

- `/Users/davidmontgomery/ragweld/server/chat/provider_router.py`
- `/Users/davidmontgomery/ragweld/server/chat/generation.py`
- `/Users/davidmontgomery/ragweld/server/chat/ragweld_mlx.py`
- `/Users/davidmontgomery/ragweld/server/api/chat.py`
- `/Users/davidmontgomery/ragweld/server/api/agent.py`
- `/Users/davidmontgomery/ragweld/server/training/mlx_qwen3_agent_trainer.py`
- `/Users/davidmontgomery/ragweld/server/api/models.py` (models.json law)
- `/Users/davidmontgomery/ragweld/server/api/index.py` (GraphRAG semantic KG LLM routing)
- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py` (config + pydantic API models)

Frontend:

- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/TrainingStudio.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/RAG/LearningAgentSubtab.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/RAG/RetrievalSubtab.tsx` (CURRENT ragweld GEN injection)
- `/Users/davidmontgomery/ragweld/web/src/components/Chat/ModelPicker.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Chat/ChatInterface.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Chat/ProviderSetup.tsx`
- `/Users/davidmontgomery/ragweld/web/src/styles/learning-studio.css`
- `/Users/davidmontgomery/ragweld/web/src/types/generated.ts` (generated)

## 8) What You Should Do Next (Concrete Task List)

1. Fix the models-catalog law mismatch:
   - Make ragweld appear in `/api/models` without UI injection.
   - Delete the special-case merge in `/Users/davidmontgomery/ragweld/web/src/components/RAG/RetrievalSubtab.tsx`.
2. Produce the requested screen recording:
   - Show a Qwen3 agent training run streaming metrics and telemetry.
   - Ensure the Gradient Descent visualization is visible and updating.
   - Save video under `output/` and provide the path.
3. Re-run type generation if you touch Pydantic models:
   - Use `/Users/davidmontgomery/ragweld/scripts/generate_types.py`.
4. Keep commit messages tagged with `@codex` (user preference).

