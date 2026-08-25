/**
 * MCPServerService — status of the embedded MCP server plus a real tool probe.
 *
 * The Streamable HTTP transport is mounted inside the FastAPI process
 * (cfg.mcp.mount_path); there is no separate daemon to start/stop/restart and
 * no stdio "test" endpoint. The former lifecycle methods targeted routes that
 * never existed (2026-08-25 drive finding M12) and are gone.
 */
import type { MCPRagSearchResponse, MCPStatusResponse } from '@/types/generated';

export class MCPServerService {
  constructor(private api: (path: string) => string) {}

  async getStatus(): Promise<MCPStatusResponse> {
    const res = await fetch(this.api('/mcp/status'));
    if (!res.ok) throw new Error((await res.text().catch(() => '')) || `Failed to fetch MCP status (${res.status})`);
    return (await res.json()) as MCPStatusResponse;
  }

  /** Run the MCP `search` tool's backing query against a corpus (real retrieval, real question). */
  async probeSearch(question: string, corpusId: string, topK = 5): Promise<MCPRagSearchResponse> {
    const params = new URLSearchParams({ q: question, corpus_id: corpusId, top_k: String(topK) });
    const res = await fetch(this.api(`/mcp/rag_search?${params.toString()}`));
    if (!res.ok) throw new Error((await res.text().catch(() => '')) || `MCP search probe failed (${res.status})`);
    return (await res.json()) as MCPRagSearchResponse;
  }
}
