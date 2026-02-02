// TriBrid RAG - Dashboard API Client
// Centralized API calls for all Dashboard operations

import { apiUrl, withCorpusScope } from './client';
import type {
  DashboardIndexStatsResponse,
  DashboardIndexStatusResponse,
  DockerContainer,
  DockerContainersResponse,
  DockerStatus,
  HealthStatus,
  LokiStatus,
  MCPStatusResponse,
  TriBridConfig,
  TracesLatestResponse,
} from '@/types/generated';

// Re-export selected generated types for convenience in consumers that import `* as DashAPI`.
export type { DockerContainer, DockerStatus, HealthStatus, LokiStatus, TracesLatestResponse, TriBridConfig };

// ============================================================================
// System Status APIs
// ============================================================================

export async function getHealth(): Promise<HealthStatus> {
  const response = await fetch(apiUrl('/health'));
  if (!response.ok) throw new Error('Failed to fetch health');
  return response.json();
}

export async function getConfig(): Promise<TriBridConfig> {
  const response = await fetch(apiUrl('/config'));
  if (!response.ok) throw new Error('Failed to fetch config');
  return response.json();
}

export async function getMCPStatus(): Promise<MCPStatusResponse> {
  const response = await fetch(apiUrl('/mcp/status'));
  if (!response.ok) throw new Error('Failed to fetch MCP status');
  return response.json();
}

// ============================================================================
// Monitoring & Alerts APIs
// ============================================================================

export interface Alert {
  labels?: {
    alertname?: string;
    [key: string]: any;
  };
  startsAt: string;
  endsAt?: string;
  annotations?: Record<string, any>;
}

export type AlertStatus = {
  recent_alerts?: Alert[];
  total_count?: number;
};

export async function getAlertStatus(): Promise<AlertStatus> {
  const response = await fetch(apiUrl('/webhooks/alertmanager/status'));
  if (!response.ok) throw new Error('Failed to fetch alert status');
  return response.json();
}

export interface Trace {
  timestamp: string;
  query: string;
  repo?: string;
  duration_ms?: number;
  [key: string]: any;
}

export async function getTraces(limit: number = 50): Promise<Trace[]> {
  const response = await fetch(apiUrl(`/traces?limit=${limit}`));
  if (!response.ok) throw new Error('Failed to fetch traces');
  return response.json();
}

export async function getLatestTrace(): Promise<TracesLatestResponse | null> {
  const response = await fetch(apiUrl('/traces/latest'));
  if (!response.ok) return null;
  return response.json();
}

export async function getLokiStatus(): Promise<LokiStatus> {
  const response = await fetch(apiUrl('/loki/status'));
  if (!response.ok) return { reachable: false, status: 'unreachable' };
  return response.json();
}

// ============================================================================
// Storage & Index APIs
// ============================================================================

export async function getIndexStats(): Promise<DashboardIndexStatsResponse> {
  const response = await fetch(apiUrl(withCorpusScope('/index/stats')));
  if (!response.ok) throw new Error('Failed to fetch index stats');
  return response.json();
}

export async function getIndexStatus(): Promise<DashboardIndexStatusResponse> {
  const response = await fetch(apiUrl(withCorpusScope('/index/status')));
  if (!response.ok) throw new Error('Failed to fetch index status');
  return response.json();
}

// ============================================================================
// Quick Actions APIs
// ============================================================================

export async function startIndexer(repo?: string): Promise<Response> {
  return fetch(apiUrl('/index/start'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: repo ? JSON.stringify({ repo }) : undefined
  });
}

export async function generateKeywords(repo?: string): Promise<Response> {
  return fetch(apiUrl('/keywords/generate'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: repo ? JSON.stringify({ repo }) : undefined
  });
}

export async function reloadConfig(): Promise<{ status: string }> {
  const response = await fetch(apiUrl('/config/reload'), {
    method: 'POST'
  });
  if (!response.ok) throw new Error('Failed to reload config');
  return response.json();
}

export async function reloadEnv(): Promise<{ status: string }> {
  const response = await fetch(apiUrl('/env/reload'), {
    method: 'POST'
  });
  if (!response.ok) throw new Error('Failed to reload env');
  return response.json();
}

export interface RerankerOption {
  id: string;
  backend: string;
  label: string;
  description: string;
}

export async function getRerankerOptions(): Promise<RerankerOption[]> {
  const response = await fetch(apiUrl('/reranker/available'));
  if (!response.ok) return [];
  const data = await response.json();
  return data.options || [];
}

export async function runEval(backend: string, repo?: string): Promise<Response> {
  return fetch(apiUrl('/eval/run'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ backend, repo })
  });
}

export type EvalStatus = {
  running: boolean;
  progress?: number;
  current_step?: string;
};

export async function getEvalStatus(): Promise<EvalStatus> {
  const response = await fetch(apiUrl('/eval/status'));
  if (!response.ok) return { running: false };
  return response.json();
}

// ============================================================================
// Docker & Infrastructure APIs
// ============================================================================

export type DockerOverview = {
  status: DockerStatus;
  containers: DockerContainer[];
};

/**
 * Get Docker daemon status + container list.
 * Calls both /api/docker/status and /api/docker/containers.
 */
export async function getDockerStatus(): Promise<DockerOverview> {
  try {
    // Fetch status and containers in parallel
    const [statusRes, containersRes] = await Promise.all([
      fetch(apiUrl('/docker/status')),
      fetch(apiUrl('/docker/containers'))
    ]);

    const status: DockerStatus = statusRes.ok
      ? await statusRes.json()
      : { running: false, runtime: '', containers_count: 0 };

    // Get container list if available
    const containers: DockerContainer[] = containersRes.ok
      ? ((await containersRes.json()) as DockerContainersResponse).containers ?? []
      : [];

    return { status, containers };
  } catch (err) {
    console.error('[getDockerStatus] Error:', err);
    return { status: { running: false, runtime: '', containers_count: 0 }, containers: [] };
  }
}

/**
 * Get raw container list from Docker.
 * Returns the containers array directly (unwrapped from response object).
 */
export async function getDockerContainers(): Promise<DockerContainer[]> {
  try {
    const response = await fetch(apiUrl('/docker/containers'));
    if (!response.ok) return [];
    const data: DockerContainersResponse = await response.json();
    return data.containers || [];
  } catch (err) {
    console.error('[getDockerContainers] Error:', err);
    return [];
  }
}

export interface RepoInfo {
  name: string;
  profile?: string;
  path?: string;
  branch?: string;
  [key: string]: any;
}

export async function getRepos(): Promise<RepoInfo[]> {
  const response = await fetch(apiUrl('/repos'));
  if (!response.ok) return [];
  return response.json();
}

// ============================================================================
// Analytics APIs
// ============================================================================

export interface FolderMetrics {
  folder: string;
  access_count: number;
  last_access?: string;
}

export interface TopQueryData {
  query: string;
  count: number;
  routes: Array<[string, number]>;
  ips: Array<[string, number]>;
}

export type TopQueriesResponse = {
  total_queries: number;
  top: TopQueryData[];
};

/**
 * Get top folder access metrics by extracting folder paths from query analytics.
 * Wired to /api/monitoring/top-queries endpoint.
 * @param _days - Number of days to analyze (reserved for future backend filtering)
 */
export async function getTopFolders(_days: number = 5): Promise<FolderMetrics[]> {
  try {
    // Note: _days parameter reserved for future backend filtering implementation
    const response = await fetch(apiUrl('/monitoring/top-queries?limit=100'));
    if (!response.ok) return [];
    
    const data: TopQueriesResponse = await response.json();
    
    // Extract folder references from queries and aggregate by folder
    const folderCounts: Record<string, number> = {};
    
    for (const item of data.top || []) {
      // Extract file paths from queries that mention folders/files
      const pathMatches = item.query.match(/(?:\/[\w.-]+)+/g) || [];
      for (const path of pathMatches) {
        // Get the folder part (parent directory)
        const parts = path.split('/').filter(Boolean);
        if (parts.length >= 2) {
          const folder = parts.slice(0, -1).join('/');
          folderCounts[folder] = (folderCounts[folder] || 0) + item.count;
        }
      }
    }
    
    // Convert to array and sort by access count
    const folders: FolderMetrics[] = Object.entries(folderCounts)
      .map(([folder, count]) => ({ folder, access_count: count }))
      .sort((a, b) => b.access_count - a.access_count)
      .slice(0, 10);
    
    return folders;
  } catch (err) {
    console.error('[getTopFolders] Error:', err);
    return [];
  }
}

/**
 * Get raw top queries data from monitoring endpoint.
 */
export async function getTopQueries(limit: number = 20): Promise<TopQueriesResponse> {
  try {
    const response = await fetch(apiUrl(`/monitoring/top-queries?limit=${limit}`));
    if (!response.ok) return { total_queries: 0, top: [] };
    return response.json();
  } catch (err) {
    console.error('[getTopQueries] Error:', err);
    return { total_queries: 0, top: [] };
  }
}

