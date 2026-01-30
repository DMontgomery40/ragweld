/**
 * IndexingService - Repository Indexing Backend Service
 * Converted from /web/src/modules/indexing.js
 *
 * Handles:
 * - Index operations (start, stop, status)
 * - Repository dropdown population
 * - Index statistics and overview
 * - Progress polling
 */

export interface IndexStats {
  repos: Array<{
    name: string;
    chunk_count: number;
    last_indexed?: string;
  }>;
  total_storage: number;
  current_repo?: string;
}

export interface IndexStatus {
  running: boolean;
  current_repo?: string;
  progress?: number;
  lines?: string[];
  metadata?: {
    current_repo: string;
    current_branch: string;
    timestamp: string;
    embedding_model: string;
    keywords_count: number;
    repos: Array<{
      name: string;
      profile: string;
      chunk_count: number;
      has_cards: boolean;
      sizes: {
        chunks: number;
        bm25: number;
        cards: number;
      };
    }>;
    total_storage: number;
    embedding_config?: {
      model: string;
      dimensions: number;
      precision: string;
    };
    storage_breakdown?: {
      chunks_json: number;
      embeddings_raw: number;
      qdrant_overhead: number;
      bm25_index: number;
      cards: number;
      reranker_cache: number;
      redis: number;
    };
    costs?: {
      total_tokens: number;
      embedding_cost: number;
    };
  };
}

export interface IndexOptions {
  repo: string;
  skip_dense?: boolean;
  enrich?: boolean;
}

export class IndexingService {
  private apiBase: string;

  constructor(apiBase: string) {
    this.apiBase = apiBase;
  }

  /**
   * Get index statistics
   */
  async getStats(): Promise<IndexStats> {
    const response = await fetch(`${this.apiBase}/api/index/stats`);
    if (!response.ok) {
      throw new Error('Failed to load index stats');
    }
    return await response.json();
  }

  /**
   * Start indexing
   */
  async startIndexing(options: IndexOptions): Promise<{ success: boolean; pid?: number; error?: string }> {
    const response = await fetch(`${this.apiBase}/api/index/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        repo: options.repo,
        skip_dense: options.skip_dense || false,
        enrich: options.enrich || false
      })
    });

    if (!response.ok) {
      throw new Error('Failed to start indexing');
    }

    return await response.json();
  }

  /**
   * Stop indexing
   */
  async stopIndexing(): Promise<{ success: boolean; error?: string }> {
    const response = await fetch(`${this.apiBase}/api/index/stop`, {
      method: 'POST'
    });

    if (!response.ok) {
      throw new Error('Failed to stop indexing');
    }

    return await response.json();
  }

  /**
   * Get index status
   */
  async getStatus(): Promise<IndexStatus> {
    const response = await fetch(`${this.apiBase}/api/index/status`);
    if (!response.ok) {
      throw new Error('Failed to get index status');
    }
    return await response.json();
  }

  /**
   * Calculate totals from stats
   */
  calculateTotals(stats: IndexStats): {
    totalChunks: number;
    reposCount: number;
    lastIndexed: string;
    totalSizeGB: string;
  } {
    let totalChunks = 0;
    let reposCount = 0;
    let lastIndexed = 'Never';

    if (stats.repos && Array.isArray(stats.repos)) {
      stats.repos.forEach(repo => {
        if (repo.chunk_count > 0) {
          totalChunks += repo.chunk_count;
          reposCount++;
        }
      });
    }

    // Get total storage
    const totalStorage = stats.total_storage || 0;
    const sizeGB = (totalStorage / (1024 * 1024 * 1024)).toFixed(2);

    // Get last indexed timestamp from current repo
    if (stats.repos && stats.repos.length > 0) {
      const currentRepo = stats.repos.find(r => r.name === stats.current_repo) || stats.repos[0];
      if (currentRepo && currentRepo.last_indexed) {
        lastIndexed = new Date(currentRepo.last_indexed).toLocaleString();
      }
    }

    return {
      totalChunks,
      reposCount,
      lastIndexed,
      totalSizeGB: sizeGB
    };
  }

  /**
   * Format bytes to human readable
   */
  formatBytes(bytes: number): string {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
  }
}
