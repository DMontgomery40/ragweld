# LiteLLM to vLLM Cutover Implementation Plan

> **For Codex:** Execute test-first in the listed order. Commit after each green
> task. Do not add direct-provider fallbacks. Do not fix unrelated layout bugs;
> append rendered frontend defects to
> `docs/exec-plans/active/frontend-browser-findings-2026-08-20.md`.

**Goal:** Make LiteLLM the only Ragweld generation egress, make vLLM the default
local serving backend, and prove the topology with real protocol/runtime tests.

**Architecture:** See
`docs/design-docs/litellm-vllm-generation-boundary.md`. Ragweld sends one
OpenAI-compatible contract to LiteLLM; LiteLLM maps `ragweld-local` to vLLM and
keeps one explicit paid OpenRouter smoke alias outside normal model discovery.

**Tech stack:** FastAPI, Pydantic, HTTPX, Docker Compose, LiteLLM proxy, vLLM
OpenAI server, pytest, Vite/React, Prometheus/Grafana, Codex in-app Browser.

---

## Task 1: Lock the deployment contract

**Files:**

- Create: `infra/litellm-config.yaml`
- Create: `infra/litellm.env.example`
- Modify: `.gitignore`
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `start.sh`
- Modify: `scripts/runtime_lifecycle.sh`
- Modify: `server/api/docker.py`
- Modify: `web/src/api/docker.ts`
- Modify: `web/src/components/Infrastructure/ServicesSubtab.tsx`
- Modify: `tests/unit/test_runtime_launch_contract.py`

**Test first:** extend the existing runtime contract matrix to assert:

1. exact pinned LiteLLM/vLLM images;
2. loopback-only `54000`/`58080` publishes;
3. `vllm -> litellm -> api` dependency order;
4. exact project and managed labels;
5. read-only LiteLLM YAML mount;
6. API environment contains `LITELLM_API_KEY` but not provider keys;
7. config has `num_retries: 0`, no fallbacks, and only the two approved aliases;
8. every lifecycle/API/frontend allowlist equals the Compose service set.

Run the focused test and confirm it fails. Add config/Compose/lifecycle code,
render `docker compose config --format json`, then rerun until green.

**Commit:** `feat(runtime): add LiteLLM and vLLM topology`

## Task 2: Collapse provider routing to LiteLLM

**Files:**

- Create: `server/chat/gateway_runtime.py`
- Modify: `server/chat/provider_router.py`
- Replace: `tests/unit/test_provider_router.py`
- Add: `tests/unit/test_gateway_runtime.py`

**Test first:** matrix cases:

- default and unprefixed aliases resolve `kind=litellm`;
- `litellm:ragweld-local` resolves identically;
- disabled/missing gateway fails closed;
- `openrouter:`, `local:`, `ragweld:`, and direct cloud prefixes are rejected;
- host and container base URL resolution is deterministic;
- no upstream provider key is read by the router.

Use controlled environment setup/restore without monkeypatch. Run the test and
confirm the old router fails. Implement the single-route resolver and rerun.

**Commit:** `refactor(chat): route generation only through LiteLLM`

## Task 3: Collapse generation transport

**Files:**

- Modify: `server/chat/generation.py`
- Modify callers: `server/chat/handler.py`,
  `server/services/answer_service.py`, `server/chat/benchmark_runner.py`,
  `server/api/eval.py`, `server/synthetic/recipes.py`,
  `server/synthetic/providers/sdkit_provider.py`
- Add/replace focused generation tests under `tests/unit/`

**Test first:** start a real controlled OpenAI-compatible loopback HTTP process
and prove non-stream and SSE parsing, usage propagation, response IDs, timeout
mapping, and no second request on failure. Confirm the old multi-transport code
fails the new contract.

Delete OpenRouter header construction, direct cloud Responses handling, local
URL branches, and in-process MLX generation. Keep `GenerationResult` stable.
Drop `openrouter_cfg` from signatures/callers. Rerun Chat, answer, eval,
benchmark, and synthetic focused suites.

**Commit:** `refactor(chat): use one gateway generation transport`

## Task 4: Make model discovery and readiness truthful

**Files:**

- Modify: `server/chat/model_discovery.py`
- Modify: `server/api/chat.py`
- Modify: `server/api/health.py`
- Modify: `server/runtime_capabilities.py`
- Modify: `server/config_control_plane.py`
- Modify: `server/observability/status.py`
- Replace focused model discovery, Chat model, health, runtime capability, and
  readiness tests.

**Test first:** a real loopback HTTP process implements authenticated
`/v1/models`. Assert only LiteLLM aliases are published, the paid smoke alias is
filtered from ordinary Chat, bad auth/unreachable gateway fails honestly, and
readiness distinguishes gateway from serving.

Delete direct OpenRouter/local discovery and credential probes. Use the shared
gateway resolver everywhere. Run the focused API/status suites.

**Commit:** `fix(runtime): derive generation readiness from the gateway`

## Task 5: Remove direct-provider configuration contracts

**Files:**

- Modify: `server/models/runtime_gateway.py`
- Modify: `server/models/tribrid_config_model.py`
- Modify: `server/models/chat_config.py`
- Modify: `tribrid_config.json`
- Modify: `server/services/config_store.py`
- Modify: `server/api/config.py`
- Modify: relevant glossary/catalog/config reality source files
- Regenerate: `web/src/types/generated.ts`
- Regenerate: contract bundles/config reference docs via owned generators
- Update contract/config tests.

**Test first:** assert only LiteLLM route/source literals remain for generation;
defaults enable LiteLLM/vLLM with namespaced URLs and `ragweld-local`; removed
direct fields fail validation rather than being accepted as compatibility data.

Remove `OpenRouterConfig`, local generation-provider config, direct generation
backend/base URL/Ollama fields, and all remaining callers. Preserve unrelated
embedding/reranker providers. Regenerate and validate every derived artifact.

**Commit:** `refactor(config): remove direct generation provider contracts`

## Task 6: Align the necessary frontend contract surface

**Files:** only authored files that fail compilation or still actively submit
removed generation contracts. Do not fix layout, styling, or unrelated UX.

**Test first:** extend real frontend contract/E2E coverage without interception:
normal model selection receives gateway aliases only and never displays the
paid smoke alias. Remove direct-provider submission logic and stale source
orders. Run TypeScript lint and production build.

Append remaining visual/operator issues to the dedicated frontend findings
handoff instead of fixing them here.

**Commit:** `refactor(web): consume gateway-only generation contracts`

## Task 7: Add observability truth

**Files:**

- Modify: `infra/prometheus.yml`
- Modify: `infra/grafana/provisioning/dashboards/gateway-serving.json`
- Modify: observability catalog/tests as required

**Test first:** assert Prometheus has exact LiteLLM/vLLM jobs and the dashboard
queries those jobs rather than Ragweld search metrics. After the real services
run, query their `/metrics` output before choosing any vendor metric names.

**Commit:** `fix(observability): monitor the real gateway and serving path`

## Task 8: Real topology integration

**Files:**

- Add: `tests/integration/test_generation_gateway.py`
- Add: a controlled OpenAI-compatible fixture process using the repo's real
  subprocess/HTTP test style
- Modify: `scripts/test_integration.sh` only if an explicit gateway lane is needed

Run the actual pinned LiteLLM container against the controlled upstream and
prove non-stream plus SSE. Then opt into the pinned vLLM image/model lane and
prove `/v1/models` plus one `temperature=0` generation through LiteLLM.

**Commit:** `test(runtime): prove the generation gateway topology`

## Task 9: Rendered product proof and paid smoke

1. Start the real stack with namespaced ports.
2. Use the Codex in-app Browser to verify gateway-only model discovery and send
   one empty-source Chat message through `ragweld-local`.
3. Confirm trace/debug metadata identifies LiteLLM and the `ragweld-local` alias.
4. Append frontend defects to the handoff Markdown; do not repair layout here.
5. Confirm `OPENROUTER_API_KEY` exists without printing it.
6. Send exactly one LiteLLM request to `ragweld-openrouter-smoke` with prompt
   `Reply with OK only.`, `temperature=0`, `max_tokens=8`, curl retry zero, and
   no gateway retry/fallback.
7. Record response ID/model/usage only; never record secrets or full headers.

**Commit:** `test(runtime): record gateway acceptance evidence`

## Task 10: Final verification

Run:

```bash
uv run python scripts/check_docs_ownership.py
uv run scripts/check_banned.py
uv run scripts/validate_types.py
uv run scripts/validate_contract_bundle.py
uv run pytest -q
npm --prefix web run lint
npm --prefix web run build
git diff --check
```

Re-check Docker resource scope, empty-store truth, readiness, Prometheus targets,
Browser console, and Git topology. Completion requires a clean one-branch
worktree and no direct generation transport reachable from Ragweld code.

