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

```mermaid
flowchart LR
    Client["MCP Client"] --> HTTP["MCP HTTP\n(mount /mcp)"]
    HTTP --> RAG["Tri-brid Retrieval"]
```

??? info "Legacy stdio"
    `python_stdio_available` indicates whether the stdio transport can be launched by clients (no daemon).
