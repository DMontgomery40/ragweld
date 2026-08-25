/**
 * MCPServerService — status of the embedded MCP server plus a real tool probe.
 *
 * The Streamable HTTP transport is mounted inside the FastAPI process
 * (cfg.mcp.mount_path); there is no separate daemon. The probe runs the MCP
 * `search` tool through a real client session on that transport (server side),
 * so what the operator sees is exactly what an MCP client gets.
 */
import type { MCPProbeRequest, MCPProbeResponse, MCPStatusResponse } from '@/types/generated';

export class MCPServerService {
  constructor(private api: (path: string) => string) {}

  async getStatus(): Promise<MCPStatusResponse> {
    const res = await fetch(this.api('/mcp/status'));
    if (!res.ok) throw new Error((await res.text().catch(() => '')) || `Failed to fetch MCP status (${res.status})`);
    return (await res.json()) as MCPStatusResponse;
  }

  async probeSearch(request: MCPProbeRequest): Promise<MCPProbeResponse> {
    const res = await fetch(this.api('/mcp/probe'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      let detail = text;
      try {
        const parsed = JSON.parse(text) as { detail?: unknown };
        if (parsed && parsed.detail !== undefined) detail = typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail);
      } catch {
        // plain-text error body
      }
      throw new Error(detail || `MCP probe failed (${res.status})`);
    }
    return (await res.json()) as MCPProbeResponse;
  }
}
