# Local generation lane: vLLM Metal + Qwen3.8-27B (4-bit MLX) on the host

Date: 2026-08-22 (recovery session 7, supersedes P0-2's model choice)

Status: **LANDED 2026-08-23 (session 8)** — cutover executed with the operator
present. Execution record:

- First supervised load: fraction 0.45 failed clean (vLLM refused: 1.53 GiB KV
  available < 2.15 GiB needed for one 32k sequence; est. max len 21952). The
  landed serving parameters, measured on this host (M4 Pro 48 GiB, VM at 16):
  `--gpu-memory-utilization 0.50` (24 GiB budget, ~3.9 GiB KV), `--max-num-seqs 1`,
  `--max-model-len 32768`. Host memory bottomed at 31% free under load; no
  pressure events, no crash. MLX weight load: 8 s; full serve-ready ~100 s.
- Qwen3.8 is a thinking-mode hybrid: with no switch the content stream opens
  with raw chain-of-thought. Disabled at the SERVING layer with
  `--default-chat-template-kwargs '{"enable_thinking": false}'` (vllm 0.27.1
  flag) so no per-caller kwargs return; the Ragas/Promptfoo runners stay clean.
- Throughput on the Barry Cohen probe: ~12 tok/s wall (200 tokens in 16.2 s,
  prefill included) vs ~2 tok/s on the retired CPU 4B path.
- `start.sh` owns the `local-model` host process (launched before Compose so
  the weight load overlaps the container wait; readiness enforced before the
  backend starts; `--no-local-model` opt-out; missing venv fails closed with
  the install commands; output in `.ragweld-runtime/local-model.log`);
  `stop.sh` and the lifecycle helpers own stop/supervise; the Compose `vllm`
  service, its `hf_cache` mount, `VLLM_CPU_KVCACHE_SPACE`, and the litellm
  `depends_on` are deleted; `litellm`/`api` reach the host via
  `host.docker.internal` (`extra_hosts: host-gateway`); Prometheus scrapes the
  host process; the stale `ragweld-vllm-1` container was removed
  (`ragweld_hf_cache` volume left for the operator to purge; reset keeps it
  deletable).
- Contracts moved together: catalog row (model/context 32768/base_url/notes),
  `VLLMConfig.default_model`, `tribrid_config.json`, the three stored corpus
  configs (PUT /api/config), regenerated LiteLLM YAML + generated.ts +
  contract bundle, readiness expectations, ProviderSetup copy, docker-service
  allowlists (server + web), launch-contract/clean-start/readiness/gateway/
  refresh/prompt-budget tests, design + reference docs, Colima 16 GiB strings.
  `Qwen/Qwen3-4B-Instruct-2507` joined the retired-serving-id sweep (the
  mlx-community 4-bit agent TRAINING base remains, per §5 below).
- Proof: host `/v1/models` reports `ragweld-local`, root
  `mlx-community/Qwen3.8-27B-4bit`, `max_model_len 32768`; `/api/ready` green
  on all four dependencies through the new `./start.sh --with-observability`;
  LiteLLM→host chat completion (`chatcmpl-…`); grounded API chat on
  `epstein-files-1` (Barry Cohen question, 10 sources, `llm_used: true`, 78 s);
  Chrome real-mouse drive (Epstein-only sources, "Ragweld local (vLLM Metal)"
  picker, streamed grounded cited answer, `provider_response_id: chatcmpl-…`,
  73 s, zero console errors); `./start.sh --check` prints the local-model
  serve command; gateway Playwright 7/7.
- Adversarial review (`codex exec`, high effort, prompted to refute): REFUTED
  the first cut with 2 P1 / 5 P2 / 1 P3. Outcomes:
  - P1 "EngineCore death invisible to supervision/readiness": empirically
    refuted — `kill -9` of the live EngineCore made the APIServer exit within
    ~3 s (`EngineDeadError` → clean shutdown) and the supervised stack tore
    down through the owned lifecycle, observed live. Readiness additionally
    hardened (below).
  - P1 "force-KILL orphans EngineCore": fixed — both lifecycle stop paths
    collect validated descendants before signaling and sweep survivors
    (`stop_process_descendants`), re-checking each pid's cwd ownership.
  - P2 identity-blind readiness: fixed — `wait_for_local_model` verifies
    `root` and `max_model_len`, and `/api/ready` runs `vllm_serving_mismatch`
    against `chat.vllm.default_model` + the catalog row (real wrong-model
    HTTP-server regression test in `tests/api/test_health_endpoints.py`).
  - P2 docker-backend healthcheck race: fixed — the model wait is serialized
    before Compose in `--docker-backend` mode and the api healthcheck carries
    `start_period: 150s`.
  - P2 `LOCAL_MODEL_PORT` split-brain: fixed — the port is pinned to 58080
    (no env override) with backend/frontend collision checks.
  - P2 stale docs: the session-8 handoff checkpoint supersedes the retired
    topology notes; `autopilot-status/ui-proof.md` updated.
  - P3 HTTP budget coverage off the local alias: the vision-refusal test now
    asserts the refusal carries the ragweld-local 32768 window (live catalog
    resolution on the HTTP path).
- Residuals: the lifecycle lock still serializes `stop.sh` against a
  `start.sh` that is mid-startup (pre-existing semantics; the recourse during
  a model load is Ctrl-C on the launcher or signaling the pid in
  `.ragweld-runtime/local-model.pid`). Pre-existing, not this slice: OTel
  "Failed to detach context" ERROR log lines during streaming responses.

Original context: runtime installed (`~/.venv-vllm-metal`, vllm 0.27.1 + mlx
0.32), weights downloaded (15 GiB). Two machine crashes on 2026-08-22/23
(bf16 4B vLLM in the VM; then host MLX reranker training) meant the first load
of the 27B happened only with the operator present, the Colima VM at 16 GiB,
nothing else heavy running, and a conservative `--gpu-memory-utilization`.

## Operator mandate

The local model must be a current, quantized Qwen 3.8 (3.7/3.6 at minimum).
`Qwen/Qwen3-4B-Instruct-2507` bf16 on the CPU vLLM image is rejected: a
generation behind, ~17 GiB of the 28 GiB Colima VM at ~2 tok/s, and part of
the memory pressure that crashed the machine on 2026-08-22.

## Facts established

- Qwen3.8 ships only as 27B (dense, vision-capable, 262k ctx, Apache 2.0) and
  a 2.4T-A95B MoE. Qwen3.6 ships 27B and 35B-A3B; no Qwen 3.5+ model under
  10B exists except Qwen3.5-4B. `mlx-community/Qwen3.8-27B-4bit` (≈15 GiB) is
  downloaded to the host HF cache.
- Qwen3.5/3.6/3.8 use the hybrid SDPA + Gated DeltaNet architecture
  (`Qwen3_5ForConditionalGeneration`). vLLM's GDN kernels are Triton/GPU; the
  arm64 CPU image cannot serve them, so the containerised vLLM service is a
  dead end on this host.
- `vllm-project/vllm-metal` (community plugin, v0.2.x, 2026) runs vLLM on
  Apple Silicon with MLX as the compute backend and lists Qwen3.5/3.6/3.8 as
  fully supported, including MLX 4-bit/8-bit checkpoints
  (`mlx-community/Qwen3.8-27B-8bit` is their reference example). Requirements:
  macOS 15+, native arm64 Python 3.12; installs into `~/.venv-vllm-metal`.
  Memory budget: `VLLM_METAL_MEMORY_FRACTION=auto` with paged attention uses
  `--gpu-memory-utilization` as the unified-memory fraction.
- Host: Apple M4 Pro, 48 GiB unified memory, macOS 27. The Colima VM currently
  reserves 28 GiB (sized for the bf16 4B model); without the in-VM vLLM the
  data plane uses ~5 GiB.

## Replacement design (one path, no CPU fallback)

1. **Serving runs on the host, not in the VM.** `start.sh` owns a third host
   process, `local-model`, next to backend/frontend:
   `~/.venv-vllm-metal/bin/vllm serve mlx-community/Qwen3.8-27B-4bit
   --served-model-name ragweld-local --host 127.0.0.1 --port 58080
   --max-model-len 32768 --gpu-memory-utilization <fraction>` (exact fraction
   and max-num-seqs measured on this host). `--no-local-model` opts out; a
   missing venv fails closed with the install command. `stop.sh` stops it.
2. **Compose:** the `vllm` service and the `litellm` `depends_on: vllm` are
   deleted. The gateway reaches the host process at
   `http://host.docker.internal:58080/v1` (verified resolvable from the
   LiteLLM container on Colima).
3. **Contracts moved together:** catalog `ragweld` row (model id, context ==
   `--max-model-len`, base_url, display name, notes), `VLLMConfig.default_model`,
   `tribrid_config.json`, stored per-corpus configs (`PUT /api/config`),
   generated LiteLLM YAML (`generate_litellm_config.py`), readiness probe
   expectations (`root` == model id, `max_model_len` == catalog context),
   ProviderSetup placeholder, design docs, launch-contract tests, retired-id
   sweep (`Qwen/Qwen3-4B-Instruct-2507` joins the retired serving ids).
4. **Colima sizing:** VM back to `--cpu 6 --memory 16` so the host keeps
   ≥ 28 GiB for the 27B weights + KV cache; `start.sh` hint and
   `tests/unit/test_runtime_launch_contract.py` updated with that string.
5. **Learning Agent base model:** decision pending with the operator. A 27B
   LoRA on this host is feasible but slow; the only current small Qwen is
   `Qwen3.5-4B`, and `server/training/mlx_qwen3_agent_trainer.py` targets Qwen3
   module names, so a 3.5+ base needs trainer work. Until decided the agent
   base stays `mlx-community/Qwen3-4B-Instruct-2507-4bit` (training-only
   artifact, never served).

## Proof required

- `/v1/models` on the host process reports `ragweld-local` with the 27B root
  and `max_model_len 32768`; readiness green; measured tok/s on the Barry
  Cohen question through `litellm:ragweld-local` (API + Chrome).
- `./start.sh --check` shows the local-model process; `docker compose config`
  has no `vllm` service.
- Standard gates + adversarial `codex exec` review.
