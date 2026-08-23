# Local generation lane: vLLM Metal + Qwen3.8-27B (4-bit MLX) on the host

Date: 2026-08-22 (recovery session 7, supersedes P0-2's model choice)

Status: runtime installed (`~/.venv-vllm-metal`, vllm 0.27.1 + mlx 0.32) and
weights downloaded (`mlx-community/Qwen3.8-27B-4bit`, 15 GiB); cutover NOT
landed and the model has NOT been loaded. Two machine crashes on 2026-08-22/23
(bf16 4B vLLM in the VM; then host MLX reranker training) mean the first load
of the 27B happens only with the operator present, the Colima VM at 16 GiB,
nothing else heavy running, and a conservative `--gpu-memory-utilization`.
The Colima profile was restarted at `--memory 16` on 2026-08-23; `start.sh`
and the launch-contract test still carry the 28 GiB string until this slice
lands.

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
