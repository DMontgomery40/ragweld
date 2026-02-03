/**
 * MCPServerService
 * Replacement for legacy `web/src/modules/mcp_server.js` (no window globals).
 */
import type { MCPStatusResponse } from '@/types/generated';

export type MCPHttpStatusResponse = {
  running: boolean;
  port?: number;
  mode?: string;
  url?: string;
  host?: string;
  path?: string;
  error?: string;
  [k: string]: unknown;
};

export type MCPActionResponse = {
  success?: boolean;
  ok?: boolean;
  port?: number;
  error?: string;
  output?: string;
  [k: string]: unknown;
};

export type MCPStdioTestResponse = {
  success?: boolean;
  tools?: string[];
  tools_count?: number;
  output?: string;
  error?: string;
  [k: string]: unknown;
};

export class MCPServerService {
  constructor(private api: (path: string) => string) {}

  async getStatus(): Promise<MCPStatusResponse> {
    const res = await fetch(this.api('/mcp/status'));
    if (!res.ok) throw new Error(await res.text().catch(() => '') || `Failed to fetch MCP status (${res.status})`);
    return (await res.json()) as MCPStatusResponse;
  }

  async getHttpStatus(): Promise<MCPHttpStatusResponse> {
    const res = await fetch(this.api('/mcp/http/status'));
    if (!res.ok) throw new Error(await res.text().catch(() => '') || `Failed to fetch MCP HTTP status (${res.status})`);
    return (await res.json()) as MCPHttpStatusResponse;
  }

  async startHttp(): Promise<MCPActionResponse> {
    const res = await fetch(this.api('/mcp/http/start'), { method: 'POST' });
    if (!res.ok) throw new Error(await res.text().catch(() => '') || `Failed to start MCP HTTP (${res.status})`);
    return (await res.json()) as MCPActionResponse;
  }

  async stopHttp(): Promise<MCPActionResponse> {
    const res = await fetch(this.api('/mcp/http/stop'), { method: 'POST' });
    if (!res.ok) throw new Error(await res.text().catch(() => '') || `Failed to stop MCP HTTP (${res.status})`);
    return (await res.json()) as MCPActionResponse;
  }

  async restartHttp(): Promise<MCPActionResponse> {
    const res = await fetch(this.api('/mcp/http/restart'), { method: 'POST' });
    if (!res.ok) throw new Error(await res.text().catch(() => '') || `Failed to restart MCP HTTP (${res.status})`);
    return (await res.json()) as MCPActionResponse;
  }

  async testStdio(): Promise<MCPStdioTestResponse> {
    const res = await fetch(this.api('/mcp/test'));
    if (!res.ok) throw new Error(await res.text().catch(() => '') || `Failed to test stdio MCP (${res.status})`);
    return (await res.json()) as MCPStdioTestResponse;
  }
}

