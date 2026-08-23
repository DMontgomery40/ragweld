# LiteLLM to vLLM Generation Boundary

Date: 2026-08-20

Status: approved for implementation

## Decision

Ragweld has one generation egress:

```text
Browser -> Ragweld API -> LiteLLM -> vLLM            (alias ragweld-local, default)
                               \-> OpenRouter       (one alias per catalog GEN row)
```

The application knows LiteLLM's OpenAI-compatible endpoint, client key, and
model aliases. It does not select direct OpenAI, OpenRouter, Ollama, llama.cpp,
or in-process MLX transports for generation. LiteLLM owns upstream translation.
vLLM owns the default local model-serving path.

Update 2026-08-22: the alias set is generated from `data/models.json`. Every
GEN catalog row carries `gateway_alias` + `gateway_upstream`, and
`infra/litellm-config.yaml` is rendered from those rows
(`scripts/generate_litellm_config.py`; lockstep enforced by
`tests/unit/test_gateway_catalog.py`). The former hand-written
`ragweld-openrouter-smoke` alias is gone; paid OpenRouter routes are ordinary,
catalog-backed aliases (for example `openai.gpt-5.4-mini`) and never the
default, never a retry target, never a fallback. See
`docs/references/generation-gateway-catalog.md`.

## Deployment topology

- LiteLLM image: `ghcr.io/berriai/litellm:v1.94.0`
- Local serving: the HOST `local-model` process (vllm-metal / MLX on Apple
  Silicon, started by `./start.sh`, venv `~/.venv-vllm-metal`) — there is no
  in-VM vLLM container.
- Host LiteLLM URL: `http://127.0.0.1:54000/v1`
- Compose LiteLLM URL: `http://litellm:4000/v1`
- Host local-model URL: `http://127.0.0.1:58080/v1`
- Container view of the local model: `http://host.docker.internal:58080/v1`
  (`extra_hosts: host-gateway` on `litellm` and `api`)
- Local alias and served name: `ragweld-local`
- Served model: `mlx-community/Qwen3.8-27B-4bit` (Qwen3.8 hybrid
  SDPA + Gated DeltaNet; 4-bit MLX weights, `--max-model-len 32768`,
  `--max-num-seqs 1`, `--gpu-memory-utilization 0.50`, thinking disabled with
  `--default-chat-template-kwargs '{"enable_thinking": false}'`). The catalog's
  `ragweld` row (`data/models.json`) must name the same model and context;
  `tests/unit/test_runtime_launch_contract.py` pins the pairing against
  `start.sh`.

The 15 GiB 4-bit weights plus KV cache live in host unified memory (M4 Pro,
48 GiB): `--gpu-memory-utilization 0.50` budgets 24 GiB, which fits the 32k
window with headroom. The Colima VM no longer serves models and is sized down
(`colima start --profile ragweld --vm-type vz --cpu 6 --memory 16`). The
retired path — `Qwen/Qwen3-4B-Instruct-2507` bf16 on
`vllm/vllm-openai-cpu:v0.26.0-arm64` in the VM — ran at ~2 tok/s and needed a
28 GiB VM; the host Metal path serves the 27B at ~12 tok/s measured on the
Barry Cohen probe (200 tokens in 16.2 s wall, prefill included). Serving stays
single-stream; it is the honest local path, not a throughput tier.

## Configuration and secrets

`infra/litellm-config.yaml` is what LiteLLM loads, and it is generated output
of the catalog (never hand-edited). LiteLLM database-backed config is disabled.
The file declares:

- `ragweld-local` -> the internal vLLM OpenAI-compatible endpoint (always first)
- one `<provider>.<model>` alias per OpenRouter route in the catalog ->
  `openrouter/<provider>/<model>` with `os.environ/OPENROUTER_API_KEY`

Retries are zero and all fallback lists are empty. Secrets use LiteLLM's
`os.environ/NAME` indirection. `OPENROUTER_API_KEY` is loaded only into the
LiteLLM container from an ignored mode-0600 environment file. Ragweld API
processes receive only `LITELLM_API_KEY`.

## Application contract

- `ProviderRoute.kind` is only `litellm`.
- A model override is either `ragweld-local` or `litellm:<alias>`, where
  `<alias>` is a catalog `gateway_alias` (slash-free; `/` and `:` become `.`).
- Direct prefixes are rejected; they do not silently normalize.
- Non-stream and stream generation use one OpenAI Chat Completions wire path.
- `/api/chat/models` is authenticated LiteLLM discovery, filtered to ordinary
  user-selectable aliases.
- Readiness and observability distinguish LiteLLM gateway health from vLLM
  serving health.
- A gateway outage fails closed with a typed operator-facing error. No direct
  transport is attempted.

Existing direct-provider configuration may remain only until its callers are
removed in the same implementation series. It is not allowed to remain as a
no-op operator promise at completion.

## Testing contract

No Python mocks or Playwright interception.

1. Static Compose/config tests prove exact images, loopback ports, ownership
   labels, service dependencies, secret isolation, and zero retry/fallback.
2. Router tests prove only LiteLLM routes exist and direct prefixes fail.
3. A real controlled OpenAI-compatible HTTP process proves non-stream and SSE
   forwarding through a real pinned LiteLLM container.
4. An opt-in vLLM integration lane proves `/v1/models` and one deterministic
   generation through LiteLLM.
5. The in-app Browser proves real Chat discovery and one send against the
   running application.
6. One explicit paid OpenRouter request through a catalog alias proves a
   grounded answer on a real corpus with a real domain question, no retries,
   no gateway fallback.
7. The catalog, its web mirror and the generated gateway YAML are proven in
   lockstep by a unit test and `scripts/generate_litellm_config.py --check`.

## Source basis

- LiteLLM's official config documentation defines `model_list`, aliases,
  OpenAI-compatible upstreams, environment indirection, master-key auth, and
  file-authoritative mode when database config is off.
- vLLM's official documentation defines its OpenAI-compatible server and CPU
  deployment constraints.
- OpenRouter's official documentation defines Bearer authentication, the
  OpenAI-compatible Chat Completions endpoint, streaming, and the
  `openai/gpt-5.4-mini` slug.

