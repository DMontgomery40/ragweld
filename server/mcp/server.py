"""FastMCP server construction for TriBridRAG."""

from __future__ import annotations

from functools import lru_cache

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from server.config import load_config
from server.mcp.tools import register_mcp_tools
from server.models.tribrid_config_model import MCPConfig

_MOUNTED: dict[str, object] = {"enabled": False, "mount_path": ""}
# The exact MCPConfig the mounted tools close over. Captured, not copied: `register_mcp_tools`
# closes over this object, so reporting it can never drift from what a tool call actually uses.
_MOUNTED_TOOL_CONFIG: dict[str, MCPConfig | None] = {"cfg": None}


def record_mounted_state(*, enabled: bool, mount_path: str) -> None:
    """Record what the running process actually mounted (set once by server.main at startup)."""
    _MOUNTED["enabled"] = bool(enabled)
    _MOUNTED["mount_path"] = str(mount_path or "")


def mounted_state() -> tuple[bool, str]:
    """The MCP transport this process serves right now, independent of persisted config edits."""
    return bool(_MOUNTED["enabled"]), str(_MOUNTED["mount_path"])


def mounted_tool_config() -> MCPConfig | None:
    """The MCP config the mounted tools actually run on, or None when no server was built.

    The FastMCP singleton is built once per process and its tools close over the config as it
    was then, so an operator's later `mcp.default_mode` / `mcp.default_top_k` edit does not
    reach them until a restart. Every surface that describes what the tools do must report
    THIS, not `load_global_config()`, or it describes a deployment that does not exist yet.
    """
    return _MOUNTED_TOOL_CONFIG["cfg"]


@lru_cache(maxsize=1)
def get_mcp_server() -> FastMCP:
    """Return the process-wide FastMCP server singleton."""
    cfg = load_config()
    mcp_cfg = cfg.mcp

    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(mcp_cfg.enable_dns_rebinding_protection),
        allowed_hosts=list(mcp_cfg.allowed_hosts),
        allowed_origins=list(mcp_cfg.allowed_origins),
    )

    mcp = FastMCP(
        "TriBridRAG",
        instructions="Tri-brid RAG system with vector, sparse, and graph retrieval.",
        stateless_http=bool(mcp_cfg.stateless_http),
        json_response=bool(mcp_cfg.json_response),
        # We mount this ASGI app under cfg.mcp.mount_path, so the internal MCP endpoint path
        # must be "/" (otherwise we'd end up with /mcp/mcp).
        streamable_http_path="/",
        transport_security=transport_security,
    )

    register_mcp_tools(mcp, mcp_cfg)
    _MOUNTED_TOOL_CONFIG["cfg"] = mcp_cfg
    return mcp

