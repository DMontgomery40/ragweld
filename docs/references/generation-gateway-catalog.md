# Generation Gateway Catalog (LiteLLM aliases from `data/models.json`)

Date: 2026-08-22

Status: landed (recovery session 5, P0)

## What exists

Ragweld has exactly one generation egress: the application talks to LiteLLM by
**alias**, and LiteLLM maps each alias to its real upstream. Since this slice,
the alias set is not hand-maintained: it is rendered from the model catalog.

```text
OpenRouter models feed  --refresh_models_catalog.py-->  data/models.json (+ web/public mirror)
                                                             |  GEN rows carry gateway_alias + gateway_upstream
                                                             v
                                           generate_litellm_config.py --> infra/litellm-config.yaml (GENERATED)
                                                             |
Browser picker <-- /api/chat/models <-- LiteLLM /v1/models (live) JOIN catalog rows by alias
```

- `data/models.json` is the source of truth. Every GEN row the gateway serves
  has `gateway_alias` (application-visible LiteLLM alias) and `gateway_upstream`
  (LiteLLM `litellm_params.model`). Rows also carry `display_name`, `context`,
  per-1k pricing and `supports_vision` from the feed.
- `infra/litellm-config.yaml` is **generated output** (header says so). Never
  hand-edit it; regenerate with `uv run python scripts/generate_litellm_config.py`
  (`--check` fails when stale). `tests/unit/test_gateway_catalog.py` enforces
  lockstep between the checked-in YAML, the catalog and its web mirror.
- The local vLLM serving row is the `ragweld` provider row
  (`gateway_alias: ragweld-local`, `gateway_upstream: openai/ragweld-local`,
  `base_url: http://vllm:8000/v1`). It is always rendered first.
- `/api/chat/models` discovers aliases from LiteLLM (authenticated, fails 503
  when the gateway is down) and joins them to catalog rows so every surface
  (Chat picker, Sidepanel quick model, Benchmark, Synthetic Lab, Indexing
  semantic-KG model, Retrieval) can show `provider · name`, context, pricing
  and vision support. An alias LiteLLM serves that the catalog does not know
  is drift (stale container config or a hand edit): it is NOT published and
  is logged as a warning. Only catalog-backed aliases are selectable.
- `server/gateway_catalog.gateway_rows` fails closed: every GEN-only row must
  carry both gateway fields, rows validate as `ModelCatalogEntry`,
  `gateway_alias` must equal the alias derived from the OpenRouter id and
  `gateway_upstream` must equal `openrouter/<id>`, aliases are lowercase and
  unique, and exactly one `ragweld-local` row exists. `/api/models/upsert`
  derives the gateway fields for GEN rows (the id must be `<provider>/<model>`)
  and regenerates the YAML in the same write.
- `select_provider_route` (every chat/answer/enrich/judge generation) accepts
  only aliases present in the in-memory catalog snapshot; an unknown alias or
  an unloaded catalog fails closed with a typed `RuntimeError`, so the catalog
  cannot be bypassed by a direct API caller. Aliases are lowercase-only;
  `openrouter/*` meta-router ids are rejected at alias derivation (refresh and
  upsert alike).
- Writes go through one `write_catalog_trio` (API upsert and the refresh CLI
  alike): validate and render every output before the first byte hits disk,
  take an interprocess `flock` on `data/models.json.lock`, write through
  pid-unique temp files. The three files are still written in sequence (not
  one transaction), so an IO failure mid-sequence is caught by
  `generate_litellm_config.py --check` and the lockstep unit test rather than
  silently tolerated.
- A running API picks up a CLI refresh on its own: the lifespan re-warms the
  in-memory catalog views every 15 s off the event loop (one `stat` unless the
  file changed). `/api/config/validate` warns when any generation alias field
  (`chat.litellm.default_model`, `generation.*_model`, vision override,
  semantic-KG model) names an alias the catalog does not serve.
- Trace cost falls back to catalog pricing by alias from an in-memory snapshot
  (warmed at startup, refreshed by `/api/chat/models` off the event loop).
  Catalog rates are the base tier; rows whose feed pricing has volume
  overrides carry `[auto-refresh] pricing_tiered=true`, and the estimate is
  labeled non-authoritative.

## Alias grammar

`gateway_alias` = OpenRouter id with `/` and `:` replaced by `.`:

| OpenRouter id | alias | config/override form |
|---|---|---|
| `openai/gpt-5.4-mini` | `openai.gpt-5.4-mini` | `litellm:openai.gpt-5.4-mini` |
| `qwen/qwen3-coder:free` | `qwen.qwen3-coder.free` | `litellm:qwen.qwen3-coder.free` |
| (vLLM) | `ragweld-local` | `litellm:ragweld-local` |

Aliases never contain `/` or `:`; `validate_litellm_alias` keeps rejecting
direct provider identifiers in config, so `gen_model: openai/gpt-5.4-mini` is
still a validation error and `gen_model: openai.gpt-5.4-mini` is a gateway route.

## Refresh procedure

```bash
cd /Users/davidmontgomery/ragweld
uv run python scripts/refresh_models_catalog.py            # dry run, prints stats
uv run python scripts/refresh_models_catalog.py --apply    # writes catalog, mirror, litellm-config.yaml
docker compose --project-name ragweld -f docker-compose.yml -f infra/docker-compose.observability.yml \
  up -d --force-recreate --no-deps litellm                  # config is a read-only bind mount
uv run pytest -q tests/unit/test_gateway_catalog.py tests/unit/test_refresh_models_catalog.py
```

Refresh semantics (replacement-only):

- Every text-output OpenRouter route (including `:free`/`:thinking` variants)
  becomes one GEN row; routes that leave the feed are removed. Skipped and
  counted in the printed stats (`skipped_*`, `duplicate_feed_ids`): `~provider/…-latest`
  rolling pointers (unstable, invalid alias grammar), `openrouter/*`
  meta-routers (`auto`, `free`, `fusion`, … pick a different model per request,
  so lineage would not name the model that answered), malformed ids, non-text
  routes, routes without a context length, duplicate ids.
- Embedding/reranker rows and the `ragweld` vLLM row are never touched by the
  feed. (The one-time cutover in this slice also deleted the dead
  `ollama/nomic-embed-text` EMB row by hand: Ollama is not part of the stack and
  the row was `catalog_only`.)
- Missing feed pricing is recorded as `[auto-refresh] pricing_unknown=true`,
  never invented. Missing context is a skip.
- `OPENROUTER_API_KEY` lives only in `infra/litellm.env` (LiteLLM container);
  the API process still sees only `LITELLM_API_KEY`.

## Verified 2026-08-22

- Feed: 421 rows → 403 routed (12 rolling pointers + 6 meta-routers skipped)
  + `ragweld-local` = 404 aliases; LiteLLM `/v1/models` serves 404 after recreate.
- `/api/chat/models?corpus_id=epstein-files-1` returns 404 joined rows
  (93 openai, 51 qwen, 41 google, 28 anthropic, …).
- Paid end-to-end proof: see the session-5 handoff / memory note for the
  grounded `epstein-files-1` answer through `litellm:openai.gpt-5.4-mini`.

## Related

- `docs/design-docs/litellm-vllm-generation-boundary.md` (boundary decision)
- `server/gateway_catalog.py`, `scripts/generate_litellm_config.py`,
  `scripts/refresh_models_catalog.py`, `server/api/chat.py` (`/chat/models`)
- `web/src/components/Chat/ModelPicker.tsx`, `web/src/components/Chat/modelLabel.ts`
