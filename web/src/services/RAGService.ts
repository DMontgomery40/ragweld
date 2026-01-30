/**
 * RAGService - Main RAG Operations Orchestrator
 * Coordinates all RAG backend services
 *
 * This service acts as a facade for:
 * - RerankService (reranking, feedback, training)
 * - IndexingService (indexing operations)
 * - IndexProfilesService (profile management)
 * - KeywordsService (keyword management)
 * - MCPRagService (MCP search)
 */

import { RerankService } from './RerankService';
import { IndexingService } from './IndexingService';
import { IndexProfilesService } from './IndexProfilesService';
import { KeywordsService } from './KeywordsService';
import { MCPRagService } from './MCPRagService';

export interface SearchOptions {
  repo?: string;
  top_k?: number;
  force_local?: boolean;
  rerank?: boolean;
}

export interface SearchResult {
  file_path: string;
  start_line: number;
  end_line: number;
  score?: number;
  rerank_score?: number;
  content?: string;
}

export class RAGService {
  public rerank: RerankService;
  public indexing: IndexingService;
  public profiles: IndexProfilesService;
  public keywords: KeywordsService;
  public mcp: MCPRagService;

  constructor(apiBase: string) {
    this.rerank = new RerankService(apiBase);
    this.indexing = new IndexingService(apiBase);
    this.profiles = new IndexProfilesService(apiBase);
    this.keywords = new KeywordsService(apiBase);
    this.mcp = new MCPRagService(apiBase);
  }

  /**
   * High-level search operation
   * Orchestrates MCP search with optional reranking
   */
  async search(query: string, options: SearchOptions = {}): Promise<SearchResult[]> {
    // Execute MCP search
    const mcpResponse = await this.mcp.search(query, {
      repo: options.repo,
      top_k: options.top_k,
      force_local: options.force_local
    });

    if (mcpResponse.error) {
      throw new Error(mcpResponse.error);
    }

    if (!mcpResponse.results) {
      return [];
    }

    // Convert to SearchResult format
    const results: SearchResult[] = mcpResponse.results.map(r => ({
      file_path: r.file_path,
      start_line: r.start_line,
      end_line: r.end_line,
      rerank_score: r.rerank_score
    }));

    return results;
  }

  /**
   * Get comprehensive system status
   * Returns status from all subsystems
   */
  async getSystemStatus(): Promise<{
    indexing: any;
    reranker: any;
  }> {
    const [indexingStatus, rerankerStatus] = await Promise.all([
      this.indexing.getStatus(),
      this.rerank.getStatus()
    ]);

    return {
      indexing: indexingStatus,
      reranker: rerankerStatus
    };
  }

  /**
   * Get comprehensive statistics
   * Returns stats from all subsystems
   */
  async getSystemStats(): Promise<{
    indexing: any;
    reranker: any;
    keywords: any;
  }> {
    const [indexStats, logsCount, tripletsCount, costs, keywordsCatalog] = await Promise.all([
      this.indexing.getStats(),
      this.rerank.getLogsCount(),
      this.rerank.getTripletsCount(),
      this.rerank.getCosts(),
      this.keywords.loadKeywords()
    ]);

    return {
      indexing: indexStats,
      reranker: {
        queryCount: logsCount.count,
        tripletCount: tripletsCount.count,
        cost24h: costs.total_24h,
        costAvg: costs.avg_per_query
      },
      keywords: {
        count: keywordsCatalog.keywords?.length || 0,
        catalog: keywordsCatalog
      }
    };
  }
}
