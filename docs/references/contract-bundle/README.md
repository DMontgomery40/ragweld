# Contract Bundle

This folder contains the repo-local contract bundle exported directly from code truth.

Files:

- `openapi.json` - FastAPI OpenAPI exported from `server.main`
- `json_schema_bundle.json` - JSON Schema bundle exported from Pydantic models in `server.models.tribrid_config_model`
- `surface_target_manifest.json` - machine-readable mapping from current ragweld surfaces to locked OSS-composition targets

Generate or refresh:

```bash
uv run scripts/export_contract_bundle.py
```

Validate in CI:

```bash
uv run scripts/validate_contract_bundle.py
```
