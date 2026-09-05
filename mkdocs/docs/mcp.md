# MCP (Model Context Protocol)

<div class="grid chunk_summaries" markdown>

-   :material-transit-connection-variant:{ .lg .middle } **Inbound HTTP**

    ---

    Optional embedded MCP HTTP transport, stateless by default.

-   :material-lock:{ .lg .middle } **Safety**

    ---

    DNS rebinding protection, host/origin allowlists, optional API key.

-   :material-tune:{ .lg .middle } **Defaults**

    ---

    `default_top_k`, `default_mode` for tri-brid retrieval.

</div>

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

!!! tip "Keep Stateless"
    `mcp.stateless_http=true` is recommended; clients provide full context each call.

!!! note "Allowlists"
    Use `mcp.allowed_hosts` and `mcp.allowed_origins` with wildcards like `*:*` only in development.

!!! warning "Auth"
    Set `mcp.require_api_key=true` and pass `Authorization: Bearer $MCP_API_KEY` in production.

## Configuration (Selected)

| Field | Default | Meaning |
|-------|---------|---------|
| `mcp.enabled` | true | Enable embedded MCP HTTP server |
| `mcp.mount_path` | `/mcp` | Path prefix |
| `mcp.public_base_url` | `http://127.0.0.1:58012` | Externally reachable origin MCP clients connect to; the server appends the mount path |
| `mcp.stateless_http` | true | Stateless handling per request |
| `mcp.json_response` | true | Prefer JSON over text |
| `mcp.enable_dns_rebinding_protection` | true | Prevent DNS rebinding |
| `mcp.allowed_hosts` | `localhost:*` | Allowed Host header values |
| `mcp.allowed_origins` | `http://localhost:*` | Allowed Origin values |
| `mcp.require_api_key` | false | Enforce API key on requests |
| `mcp.default_top_k` | 20 | Default top_k for search/answer tools |
| `mcp.default_mode` | `tribrid` | Retrieval mode when not provided |

!!! note "The workbench probe runs on the mounted tools' defaults"
    The **Infrastructure → MCP** probe card calls the mounted `search` tool through a real client session with **no overrides**, so what it reports is exactly what an MCP client gets: the `mcp.default_mode` and `mcp.default_top_k` the **mounted** server captured when this process built it (defaults `tribrid` and `20`). The card reads those values from `GET /api/mcp/status` rather than from live config, because the FastMCP singleton keeps the defaults it captured until the API restarts — when config has moved on, the card shows a **restart pending** notice naming both pairs of values (`default_mode`/`default_top_k` versus `config_default_mode`/`config_default_top_k`). The probe result line labels the transport URL it echoes as the **in-process** address — the address an external MCP client actually dials is the advertised URL from the status card (`mcp.public_base_url` plus the mount path).

## Status Endpoint

=== "Python"
```python
import httpx
print(httpx.get("http://localhost:8000/mcp/status").json())
```

=== "curl"
```bash
curl -sS http://localhost:8000/mcp/status | jq .
```

=== "TypeScript"
```typescript
const status = await (await fetch('/mcp/status')).json();
```

## Structured, fail-closed search errors

The MCP `search` tool never returns a partial result. When retrieval cannot complete, it answers with `isError=true` and a structured payload (`MCPSearchToolResult` in `server/models/tribrid_config_model.py`) that carries exactly one of:

result
:   The successful `ChunkMatch[]` rows. An empty list is a valid successful result — a corpus with no hits is not an error.

error
:   One of the typed failure details the HTTP API already returns, so agent clients branch on stable codes instead of parsing prose:

| Error detail | `code` | Meaning |
|---|---|---|
| `DependencyUnavailableDetail` | `dependency_unavailable` | A required runtime dependency (Postgres, Qdrant, Neo4j, embedding provider) is unavailable. |
| `RequiredRetrievalLegFailureDetail` | `required_retrieval_leg_failed` | A requested retrieval leg failed at execution time (for example, the configured embedding model is missing). |
| `RerankerFailureDetail` | `reranker_failed` | The configured cloud/learning reranker could not rerank the candidates. |
| `AnswerRetrievalFailureDetail` | `answer_retrieval_failed` | Retrieval for an answer failed for a reason no typed retrieval error names. |
| `GenerationUnavailableDetail` | `generation_unavailable` | The generation gateway could not complete the answer. |
| `RetrievalContractMismatchDetail` | `embedding_contract_mismatch` / `sparse_contract_mismatch` | The corpus's stored index contract conflicts with the current configuration; re-index. |

The same errors surface as typed HTTP failures on the probe route: `POST /api/mcp/probe` answers `503` for the first two and `409` for a contract mismatch, with the detail under `detail` — so HTTP clients and MCP clients share one error vocabulary. The integration tests prove the fail-closed contract end to end over the real mounted transport (`tests/integration/test_dependency_outage_asymmetric.py`, `tests/integration/test_required_retrieval_leg_contract.py`): a Neo4j outage or a contract mismatch returns the same typed detail as `/api/search`, never partial rows.

The `answer` tool follows the same contract through `MCPAnswerToolResult`: on success a structured `AnswerResponse`; on any failure `isError=true` with exactly one of the typed details above — never an answer assembled from the retrieved sources without generation. `GET /api/mcp/status` additionally reports the tool defaults the mounted server captured (`default_mode`, `default_top_k`) beside what config says now (`config_default_mode`, `config_default_top_k`), with `defaults_restart_pending=true` when they disagree: the mounted tools keep the values captured at process start until the API is restarted.

!!! tip "If you're not sure"
    Treat `isError=true` as "retry after remediation or re-index", never as "the search came back empty". A genuine empty result arrives with `isError=false` and `result: []`.

```mermaid
flowchart LR
    Client["MCP Client"] --> HTTP["MCP HTTP\n(mount /mcp)"]
    HTTP --> RAG["Tri-brid Retrieval"]
```

??? info "Legacy stdio"
    `python_stdio_available` indicates whether the stdio transport can be launched by clients (no daemon).
