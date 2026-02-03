/**
 * MCPRagService - MCP RAG Search Backend Service
 * Converted from /web/src/modules/mcp_rag.js
 *
 * Handles RAG search via MCP protocol
 */

import type { MCPRagSearchResponse, MCPRagSearchResult } from '@/types/generated';

export type MCPRagResult = MCPRagSearchResult;
export type MCPRagResponse = MCPRagSearchResponse;

export class MCPRagService {
  private api: (path: string) => string;

  constructor(api: (path: string) => string) {
    this.api = api;
  }

  /**
   * Execute MCP RAG search
   */
  async search(
    query: string,
    options: {
      repo?: string;
      top_k?: number;
      force_local?: boolean;
    } = {}
  ): Promise<MCPRagResponse> {
    const params = new URLSearchParams({
      q: query,
      top_k: String(options.top_k || 10),
      force_local: String(options.force_local || false)
    });

    if (options.repo) {
      params.set('repo', options.repo);
    }

    const response = await fetch(this.api(`/mcp/rag_search?${params.toString()}`));

    if (!response.ok) {
      throw new Error('MCP RAG search failed');
    }

    return await response.json();
  }

  /**
   * Format search results for display
   */
  formatResults(results: MCPRagResult[]): string[] {
    return results.map(x =>
      `${x.file_path}:${x.start_line}-${x.end_line}  score=${Number(x.rerank_score || 0).toFixed(3)}`
    );
  }
}
