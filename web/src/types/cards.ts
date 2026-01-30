export interface CardsBuildOptions {
  repo: string;
  enrich: boolean;
  exclude_dirs?: string;
  exclude_patterns?: string;
  exclude_keywords?: string;
}

export interface CardsBuildStatus {
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
    cards_written?: number;
    chunks_skipped?: number;
    duration_s?: number;
  };
  error?: string;
}

