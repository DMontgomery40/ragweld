// TriBrid RAG - Dashboard API Client
// Centralized API calls for all Dashboard operations

import { apiClient, api, withCorpusScope } from './client';
import type {
  AgentTrainControlPlaneStatusResponse,
  BenchmarkObservabilitySummaryResponse,
  DashboardIndexStatsResponse,
  DashboardIndexStatusResponse,
  DockerContainer,
  DockerContainersResponse,
  DockerStatus,
  EvalObservabilitySummaryResponse,
  HealthStatus,
  LokiStatus,
  MCPStatusResponse,
  ObservabilityCatalogResponse,
  ObservabilityIncidentsResponse,
  ObservabilityStatusResponse,
  PromptObservabilitySummaryResponse,
  RerankerLogsResponse,
  TracesLatestResponse,
} from '@/types/generated';

// Re-export selected generated types for convenience in consumers that import `* as DashAPI`.
export type {
  AgentTrainControlPlaneStatusResponse,
  BenchmarkObservabilitySummaryResponse,
  DockerContainer,
  DockerStatus,
  EvalObservabilitySummaryResponse,
  HealthStatus,
  LokiStatus,
  ObservabilityCatalogResponse,
  ObservabilityIncidentsResponse,
  ObservabilityStatusResponse,
  PromptObservabilitySummaryResponse,
  TracesLatestResponse,
};

// ============================================================================
// System Status APIs
// ============================================================================

export async function getHealth(): Promise<HealthStatus> {
  const { data } = await apiClient.get<HealthStatus>(api('/health'));
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

export async function getObservabilityStatus(): Promise<ObservabilityStatusResponse | null> {
  try {
    const { data } = await apiClient.get<ObservabilityStatusResponse>(withCorpusScope(api('/observability/status')));
    return data;
  } catch {
    return null;
  }
}

export async function getObservabilityCatalog(
  corpusId?: string
): Promise<ObservabilityCatalogResponse | null> {
  try {
    const qs = new URLSearchParams();
    if (corpusId) qs.set('corpus_id', corpusId);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    const { data } = await apiClient.get<ObservabilityCatalogResponse>(api(`/observability/catalog${suffix}`));
    return data;
  } catch {
    return null;
  }
}

export async function getObservabilityIncidents(
  corpusId?: string
): Promise<ObservabilityIncidentsResponse | null> {
  try {
    const qs = new URLSearchParams();
    if (corpusId) qs.set('corpus_id', corpusId);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    const { data } = await apiClient.get<ObservabilityIncidentsResponse>(api(`/observability/incidents${suffix}`));
    return data;
  } catch {
    return null;
  }
}

export async function getEvalObservabilitySummary(
  corpusId?: string
): Promise<EvalObservabilitySummaryResponse | null> {
  try {
    const qs = new URLSearchParams();
    if (corpusId) qs.set('corpus_id', corpusId);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    const { data } = await apiClient.get<EvalObservabilitySummaryResponse>(api(`/eval/observability/summary${suffix}`));
    return data;
  } catch {
    return null;
  }
}

export async function getBenchmarkObservabilitySummary(
  corpusId?: string
): Promise<BenchmarkObservabilitySummaryResponse | null> {
  try {
    const qs = new URLSearchParams();
    if (corpusId) qs.set('corpus_id', corpusId);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    const { data } = await apiClient.get<BenchmarkObservabilitySummaryResponse>(
      api(`/benchmark/observability/summary${suffix}`)
    );
    return data;
  } catch {
    return null;
  }
}

export async function getPromptObservabilitySummary(
  corpusId?: string
): Promise<PromptObservabilitySummaryResponse | null> {
  try {
    const qs = new URLSearchParams();
    if (corpusId) qs.set('corpus_id', corpusId);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    const { data } = await apiClient.get<PromptObservabilitySummaryResponse>(
      api(`/prompts/observability/summary${suffix}`)
    );
    return data;
  } catch {
    return null;
  }
}

export async function getAgentControlPlaneStatus(
  corpusId?: string
): Promise<AgentTrainControlPlaneStatusResponse | null> {
  try {
    const qs = new URLSearchParams();
    if (corpusId) qs.set('corpus_id', corpusId);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    const { data } = await apiClient.get<AgentTrainControlPlaneStatusResponse>(
      api(`/agent/train/control-plane/status${suffix}`)
    );
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

export async function getIndexStatus(corpusId: string): Promise<DashboardIndexStatusResponse> {
  const { data } = await apiClient.get<DashboardIndexStatusResponse>(
    withCorpusScope(api('/index/status'), corpusId),
  );
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
  inventoryAvailable: boolean;
};

/**
 * Get Docker daemon status plus the project-scoped Ragweld service list.
 */
export async function getDockerStatus(): Promise<DockerOverview> {
  try {
    const [statusRes, containersRes] = await Promise.allSettled([
      apiClient.get<DockerStatus>(api('/docker/status')),
      apiClient.get<DockerContainersResponse>(api('/docker/services')),
    ]);

    const status: DockerStatus =
      statusRes.status === 'fulfilled'
        ? statusRes.value.data
        : { running: false, runtime: '', containers_count: 0 };

    const containers: DockerContainer[] =
      containersRes.status === 'fulfilled'
        ? containersRes.value.data.containers ?? []
        : [];

    return {
      status,
      containers,
      inventoryAvailable: containersRes.status === 'fulfilled',
    };
  } catch (err) {
    console.error('[getDockerStatus] Error:', err);
    return {
      status: { running: false, runtime: '', containers_count: 0 },
      containers: [],
      inventoryAvailable: false,
    };
  }
}

