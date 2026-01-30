/**
 * MCPRagService - MCP RAG Search Backend Service
 * Converted from /web/src/modules/mcp_rag.js
 *
 * Handles RAG search via MCP protocol
 */

export interface MCPRagResult {
  file_path: string;
  start_line: number;
  end_line: number;
  rerank_score?: number;
}

export interface MCPRagResponse {
  results?: MCPRagResult[];
  error?: string;
}

export class MCPRagService {
  private apiBase: string;

  constructor(apiBase: string) {
    this.apiBase = apiBase;
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

    const response = await fetch(`${this.apiBase}/api/mcp/rag_search?${params.toString()}`);

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
