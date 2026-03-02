// TriBrid RAG - Dashboard API Client
// Centralized API calls for all Dashboard operations

import { apiClient, api, withCorpusScope } from './client';
import type {
  DashboardIndexStatsResponse,
  DashboardIndexStatusResponse,
  DockerContainer,
  DockerContainersResponse,
  DockerStatus,
  HealthStatus,
  LokiStatus,
  MCPStatusResponse,
  RerankerLogsResponse,
  TriBridConfig,
  TracesLatestResponse,
} from '@/types/generated';

// Re-export selected generated types for convenience in consumers that import `* as DashAPI`.
export type { DockerContainer, DockerStatus, HealthStatus, LokiStatus, TracesLatestResponse, TriBridConfig };

// ============================================================================
// System Status APIs
// ============================================================================

export async function getHealth(): Promise<HealthStatus> {
  const { data } = await apiClient.get<HealthStatus>(api('/health'));
  return data;
}

export async function getConfig(): Promise<TriBridConfig> {
  const { data } = await apiClient.get<TriBridConfig>(withCorpusScope(api('/config')));
  return data;
}

export async function getMCPStatus(): Promise<MCPStatusResponse> {
  const { data } = await apiClient.get<MCPStatusResponse>(api('/mcp/status'));
  return data;
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
  const { data } = await apiClient.get<AlertStatus>(api('/webhooks/alertmanager/status'));
  return data;
}

export interface Trace {
  timestamp: string;
  query: string;
  repo?: string;
  duration_ms?: number;
  [key: string]: any;
}

export async function getTraces(limit: number = 50): Promise<Trace[]> {
  const limitNum = Number(limit);
  const safeLimit = Number.isFinite(limitNum) ? Math.max(1, Math.min(500, Math.trunc(limitNum))) : 50;
  const fetchLimit = Math.max(200, Math.min(2000, safeLimit * 5));
  try {
    const path = withCorpusScope(api(`/reranker/logs?limit=${encodeURIComponent(String(fetchLimit))}`));
    const { data } = await apiClient.get<RerankerLogsResponse>(path);
    const logs = Array.isArray((data as any)?.logs) ? ((data as any).logs as Array<Record<string, any>>) : [];
    return logs
      .filter((row) => {
        const kind = String(row?.kind || row?.type || '').trim().toLowerCase();
        return kind === 'chat' || kind === 'search' || kind === 'query';
      })
      .map((row) => {
        const startedAtMs = typeof row?.started_at_ms === 'number' ? row.started_at_ms : undefined;
        const endedAtMs = typeof row?.ended_at_ms === 'number' ? row.ended_at_ms : undefined;
        const durationMs =
          typeof startedAtMs === 'number' && typeof endedAtMs === 'number'
            ? Math.max(0, endedAtMs - startedAtMs)
            : undefined;
        const timestamp =
          (typeof row?.ts === 'string' && row.ts) ||
          (typeof row?.timestamp === 'string' && row.timestamp) ||
          (typeof startedAtMs === 'number' ? new Date(startedAtMs).toISOString() : new Date().toISOString());
        const query =
          (typeof row?.query === 'string' && row.query) ||
          (typeof row?.query_raw === 'string' && row.query_raw) ||
          '';
        const repo =
          (typeof row?.corpus_id === 'string' && row.corpus_id) ||
          (Array.isArray(row?.corpus_ids) && typeof row.corpus_ids[0] === 'string' ? row.corpus_ids[0] : undefined);
        return {
          timestamp,
          query,
          repo,
          duration_ms: durationMs,
          ...row,
        } as Trace;
      })
      .slice(-safeLimit);
  } catch {
    return [];
  }
}

export async function getLatestTrace(): Promise<TracesLatestResponse | null> {
  try {
    const { data } = await apiClient.get<TracesLatestResponse>(withCorpusScope(api('/traces/latest')));
    return data;
  } catch {
    return null;
  }
}

export async function getLokiStatus(): Promise<LokiStatus> {
  try {
    const { data } = await apiClient.get<LokiStatus>(api('/loki/status'));
    return data;
  } catch {
    return { reachable: false, status: 'unreachable' };
  }
}

// ============================================================================
// Storage & Index APIs
// ============================================================================

export async function getIndexStats(): Promise<DashboardIndexStatsResponse> {
  const { data } = await apiClient.get<DashboardIndexStatsResponse>(withCorpusScope(api('/index/stats')));
  return data;
}

export async function getIndexStatus(): Promise<DashboardIndexStatusResponse> {
  const { data } = await apiClient.get<DashboardIndexStatusResponse>(withCorpusScope(api('/index/status')));
  return data;
}

// ============================================================================
// Quick Actions APIs
// ============================================================================

export interface RerankerOption {
  id: string;
  backend: string;
  label: string;
  description: string;
}

export async function getRerankerOptions(): Promise<RerankerOption[]> {
  try {
    const { data } = await apiClient.get(api('/reranker/available'));
    const options = (data as any)?.options;
    return Array.isArray(options) ? (options as RerankerOption[]) : [];
  } catch {
    return [];
  }
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
    const [statusRes, containersRes] = await Promise.allSettled([
      apiClient.get<DockerStatus>(api('/docker/status')),
      apiClient.get<DockerContainersResponse>(api('/docker/containers')),
    ]);

    const status: DockerStatus =
      statusRes.status === 'fulfilled'
        ? statusRes.value.data
        : { running: false, runtime: '', containers_count: 0 };

    const containers: DockerContainer[] =
      containersRes.status === 'fulfilled'
        ? containersRes.value.data.containers ?? []
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
    const { data } = await apiClient.get<DockerContainersResponse>(api('/docker/containers'));
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
  try {
    const { data } = await apiClient.get<RepoInfo[]>(api('/repos'));
    return data;
  } catch {
    return [];
  }
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
    const { data } = await apiClient.get<TopQueriesResponse>(api('/monitoring/top-queries?limit=100'));
    
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
    const safeLimit = Number.isFinite(Number(limit)) ? Number(limit) : 20;
    const { data } = await apiClient.get<TopQueriesResponse>(
      api(`/monitoring/top-queries?limit=${encodeURIComponent(String(safeLimit))}`)
    );
    return data;
  } catch (err) {
    console.error('[getTopQueries] Error:', err);
    return { total_queries: 0, top: [] };
  }
}
