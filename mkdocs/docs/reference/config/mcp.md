# Config reference: `mcp`

<div class="grid chunk_summaries" markdown>

-   :material-tune:{ .lg .middle } **Enterprise tuning surface**

    ---

    Defaults + constraints are rendered directly from Pydantic.

-   :material-key-outline:{ .lg .middle } **Env keys when available**

    ---

    Many fields have an env-style alias (from `TriBridConfig.to_flat_dict()`).

-   :material-tooltip-text:{ .lg .middle } **Tooltip-level guidance**

    ---

    If a matching glossary entry exists, you’ll see deeper tuning notes.

</div>

[Config reference](index.md){ .md-button .md-button--primary }
[Config API & workflow](../../configuration.md){ .md-button }
[Glossary](../../glossary.md){ .md-button }

**Total parameters**: 11

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `mcp.allowed_hosts` | — | `list[str]` | `["localhost:*", "127.0.0.1:*"]` | — | Allowed Host header values for MCP HTTP (supports wildcard ':*'). |
| `mcp.allowed_origins` | — | `list[str]` | `["http://localhost:*", "http://127.0.0.1:*"]` | — | Allowed Origin header values for MCP HTTP (supports wildcard ':*'). |
| `mcp.default_mode` | `MCP_DEFAULT_MODE` | `Literal["tribrid", "dense_only", "sparse_only", "graph_only"]` | `"tribrid"` | allowed="tribrid", "dense_only", "sparse_only", "graph_only" | Default retrieval mode for MCP search/answer tools when not provided. |
| `mcp.default_top_k` | `MCP_DEFAULT_TOP_K` | `int` | `20` | ≥ 1, ≤ 200 | Default top_k for MCP search/answer tools when not provided. |
| `mcp.enable_dns_rebinding_protection` | `MCP_HTTP_DNS_REBIND_PROTECTION` | `bool` | `true` | — | Enable DNS rebinding protection for MCP HTTP (recommended). |
| `mcp.enabled` | `MCP_HTTP_ENABLED` | `bool` | `true` | — | Enable the embedded MCP Streamable HTTP server. |
| `mcp.json_response` | `MCP_HTTP_JSON_RESPONSE` | `bool` | `true` | — | Prefer JSON responses for MCP Streamable HTTP (recommended). |
| `mcp.mount_path` | `MCP_HTTP_PATH` | `str` | `"/mcp"` | min_length=2, pattern=^/[^/\s]+(?:/[^/\s]+)*/?$ | Mount path for the MCP Streamable HTTP endpoint (e.g. /mcp). Must name a path segment: a bare "/" would mount the transport at the site root, shadowing every other route, and leaves nothing for the advertised URL to point at. |
| `mcp.public_base_url` | `MCP_PUBLIC_BASE_URL` | `str` | `"http://127.0.0.1:58012"` | — | Externally reachable base URL (scheme://host[:port]) that MCP clients should connect to; the mount path is appended to it. Set this to the deployment's public origin when the API sits behind a proxy -- the workbench advertises exactly this value, and deriving it from the request would advertise the proxy's internal hop instead of the address a client can actually reach. Its host must also appear in `allowed_hosts`: with DNS rebinding protection on, the transport answers 421 to any Host header it does not recognise, so advertising a host that is not allowed trades one broken instruction for another. Writing the mount path here too (`https://host/mcp`) is accepted and not doubled -- both spellings advertise the same URL. |
| `mcp.require_api_key` | `MCP_REQUIRE_API_KEY` | `bool` | `false` | — | Require `Authorization: Bearer $MCP_API_KEY` for MCP HTTP access. |
| `mcp.stateless_http` | `MCP_HTTP_STATELESS` | `bool` | `true` | — | Run MCP Streamable HTTP in stateless mode (recommended). |

### Details (glossary)

??? info "`mcp.mount_path` (`MCP_HTTP_PATH`) — MCP HTTP Path"
    **Category**: `general`

    Path segment for the MCP HTTP endpoint (for example `/mcp`). Clients, gateways, and reverse proxies must agree on this route exactly; mismatches are a common cause of silent connection failures where the server is up but tools are never discovered. Use a stable, version-aware path when multiple environments or gateway rules coexist (for example `/v1/mcp`). If you rewrite paths at the proxy layer, test both health checks and tool invocation end-to-end to ensure the canonical route still maps correctly.

    **Links**:
    - [HumanMCP: Evaluating MCP Tool Retrieval Performance (arXiv 2026)](https://arxiv.org/abs/2602.23367)
    - [Model Context Protocol Docs](https://modelcontextprotocol.io/docs)
    - [Model Context Protocol: Transports](https://modelcontextprotocol.io/docs/concepts/transports)
    - [MDN What is a URL?](https://developer.mozilla.org/en-US/docs/Learn/Common_questions/Web_mechanics/What_is_a_URL)
