/**
 * Chunk Summaries Types (formerly "Cards")
 *
 * Per CLAUDE.md: "cards" is a banned term - use "chunk_summaries" instead.
 */

export interface ChunkSummaryBuildOptions {
  repo: string;
  enrich: boolean;
  exclude_dirs?: string;
  exclude_patterns?: string;
  exclude_keywords?: string;
}

export interface ChunkSummaryBuildStatus {
  status: 'running' | 'done' | 'error' | 'cancelled';
  stage: string;
  total: number;
  done: number;
  pct: number;
  tip?: string;
  repo?: string;
  eta_s?: number;
  throughput?: string;
  result?: {
    chunk_summaries_written?: number;
    chunks_skipped?: number;
    duration_s?: number;
  };
  error?: string;
}

export interface ChunkSummary {
  file_path: string;
  start_line?: number;
  end_line?: number;
  purpose?: string;
  symbols?: string[];
  technical_details?: string;
  domain_concepts?: string[];
}

export interface ChunkSummariesResponse {
  chunk_summaries: ChunkSummary[];
  last_build: LastBuild | null;
}

export interface LastBuild {
  timestamp?: string;
  repo?: string;
  total?: number;
  enriched?: number;
}

// Legacy aliases for backward compatibility
export type CardsBuildOptions = ChunkSummaryBuildOptions;
export type CardsBuildStatus = ChunkSummaryBuildStatus;
export type Card = ChunkSummary;
export type CardsResponse = ChunkSummariesResponse;
