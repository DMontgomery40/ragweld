# OSS Config And Secret Control Plane

This page defines the operator-facing configuration control plane for the
OSS-composition branch.

## Purpose

- Treat `TriBridConfig` as the broad law for config shape.
- Treat `/api/config/registry` as the executable operator catalog for which
  fields exist, how they are classified, and which surface owns them.
- Treat `/api/config/readiness` as the live dependency truth for locked OSS
  integrations and env-only secrets.

## Key Rules

- Every `TriBridConfig` leaf must appear exactly once in the registry.
- Every field is classified with:
  - `path`
  - `section`
  - `type`
  - `default`
  - `scope`
  - `integration`
  - `exposure_level`
  - `impact`
  - `secret_dependency_ids`
  - `ui_surface`
- Secrets stay env-only. They are not persisted through normal `/api/config`
  CRUD.
- Protected surfaces use layered exposure:
  - Basic: curated operator controls
  - Advanced: searchable full registry explorer
  - Raw: full section editor fallback
  - Dependencies: secret and integration readiness

## Source Of Truth Files

- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`
- `/Users/davidmontgomery/ragweld/server/config_control_plane.py`
- `/Users/davidmontgomery/ragweld/server/api/config.py`
- `/Users/davidmontgomery/ragweld/web/src/components/Admin/configControlPlane.tsx`

## Locked Integration Contracts

- `litellm`
- `vllm`
- `flyte`
- `haystack_docling_qdrant`
- `neo4j`
- `unsloth`
- `mlflow`
- `ragas`
- `promptfoo`
- `langfuse`
- `otel_grafana_stack`
- `shell_ui`

## Enforcement

- Unit tests validate:
  - every config leaf is registered once
  - every secret dependency id resolves to a declared env-only secret
  - every locked integration contract exists and has protected surface metadata
- API tests validate:
  - `/api/config/registry`
  - `/api/config/readiness`
  - secret blocker surfacing for Langfuse

## Secret Handling

- Gateway API keys, Neo4j password, and similar credentials are env-only.
- `GET /api/secrets/check` now uses the registry-backed secret list rather than
  a hardcoded allowlist.
- The workbench dependency panel is the operator-facing place to confirm whether
  required app credentials are present.

OpenAI embeddings and generation authenticate to LiteLLM using the app's
`LITELLM_API_KEY`; Compose supplies that credential to the gateway as
`LITELLM_MASTER_KEY`. Upstream keys such as `OPENAI_API_KEY` belong only in the
gateway's private `infra/litellm.env`, outside the app registry and browser secret
controls. See [gateway credentials](generation-gateway-catalog.md#gateway-credentials)
for the Proxmox file mapping and required gateway recreation after an env change.

For an app-side presence check on LXC100:

```bash
curl -sS "http://127.0.0.1:58012/api/secrets/check?keys=LITELLM_API_KEY" | jq .
```

This returns presence only, never a credential value or proof that the gateway
accepts the key. Requesting `OPENAI_API_KEY` here returns an unsupported-secret
error; it cannot check the gateway's upstream key or establish provider readiness.
