// TriBrid RAG - Dashboard API Client
// Centralized API calls for all Dashboard operations

import axios from 'axios';

import { apiClient, api, withCorpusScope } from './client';
import type {
  AgentTrainControlPlaneStatusResponse,
  AlertmanagerAlert,
  AlertmanagerAlertsResponse,
  AlertsUnavailableDetail,
  BenchmarkObservabilitySummaryResponse,
  DashboardIndexStatsResponse,
  DashboardIndexStatusResponse,
  DockerContainer,
  DockerContainersResponse,
  DockerStatus,
  EvalObservabilitySummaryResponse,
  HealthStatus,
  IndexRunSummary,
  LangfuseTraceAccess,
  LokiStatus,
  MCPStatusResponse,
  ObservabilityCatalogResponse,
  ObservabilityIncidentsResponse,
  ObservabilityStatusResponse,
  PromptObservabilitySummaryResponse,
  ReadinessStatus,
  RerankerLogsResponse,
  TracesLatestResponse,
} from '@/types/generated';

// Re-export selected generated types for convenience in consumers that import `* as DashAPI`.
export type {
  AgentTrainControlPlaneStatusResponse,
  AlertmanagerAlert,
  AlertmanagerAlertsResponse,
  AlertsUnavailableDetail,
  BenchmarkObservabilitySummaryResponse,
  DockerContainer,
  DockerStatus,
  EvalObservabilitySummaryResponse,
  HealthStatus,
  IndexRunSummary,
  LangfuseTraceAccess,
  LokiStatus,
  ObservabilityCatalogResponse,
  ObservabilityIncidentsResponse,
  ObservabilityStatusResponse,
  PromptObservabilitySummaryResponse,
  ReadinessStatus,
  TracesLatestResponse,
};

// ============================================================================
// System Status APIs
// ============================================================================

export async function getHealth(): Promise<HealthStatus> {
  const { data } = await apiClient.get<HealthStatus>(api('/health'));
  return data;
}

/**
 * The per-dependency readiness breakdown behind the top-bar health pill.
 *
 * `/api/ready` answers 200 when every required dependency is ready and **503** when one is
 * not (the payload is the same shape either way -- the breakdown is exactly what an operator
 * opens the pill to see in the not-ready case), so 503 is accepted as a status rather than
 * thrown. Any other status still rejects. This is a global infrastructure probe, so it is
 * intentionally unscoped by corpus.
 */
export async function getReadiness(): Promise<ReadinessStatus> {
  const { data } = await apiClient.get<ReadinessStatus>(api('/ready'), {
    validateStatus: (s) => s === 200 || s === 503,
  });
  return data;
}

export async function getMCPStatus(): Promise<MCPStatusResponse> {
  const { data } = await apiClient.get<MCPStatusResponse>(api('/mcp/status'));
  return data;
}

// ============================================================================
// Monitoring & Alerts APIs
// ============================================================================

export async function getAlertmanagerAlerts(): Promise<AlertmanagerAlertsResponse> {
  const { data } = await apiClient.get<AlertmanagerAlertsResponse>(api('/observability/alerts'));
  return data;
}

/** Local view model for a failed alerts read: the server's own reason, never a bare "Failed to load". */
export type AlertsViewError = {
  status: number;
  message: string;
  operatorHint: string | null;
  monitoringPath: string;
};

const MONITORING_FALLBACK_PATH = '/infrastructure?subtab=monitoring';

export function toAlertsViewError(err: unknown): AlertsViewError {
  if (axios.isAxiosError(err)) {
    const status = Number(err.response?.status ?? 0);
    const detail = (err.response?.data as { detail?: AlertsUnavailableDetail | string } | undefined)?.detail;
    if (detail && typeof detail === 'object') {
      return {
        status,
        message: String(detail.message || err.message),
        operatorHint: detail.operator_hint ? String(detail.operator_hint) : null,
        monitoringPath: String(detail.monitoring_path || MONITORING_FALLBACK_PATH),
      };
    }
    return {
      status,
      message: typeof detail === 'string' && detail ? detail : err.message,
      operatorHint: null,
      monitoringPath: MONITORING_FALLBACK_PATH,
    };
  }
  return {
    status: 0,
    message: err instanceof Error ? err.message : 'The alerts request failed before it reached the API.',
    operatorHint: null,
    monitoringPath: MONITORING_FALLBACK_PATH,
  };
}

export interface Trace {
  timestamp: string;
  query: string;
  repo?: string;
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
        // The query log records no per-request timing (no started/ended/latency field is
        // written by the search or chat log writers), so there is nothing here to compute a
        // duration from. The Monitoring table dropped its Duration column accordingly (M-139);
        // this mapper must not resurrect a field nothing populates.
        const timestamp =
          (typeof row?.ts === 'string' && row.ts) ||
          (typeof row?.timestamp === 'string' && row.timestamp) ||
          new Date().toISOString();
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
          ...row,
        } as Trace;
      })
      .slice(-safeLimit);
  } catch {
    return [];
  }
}

/** Ask the API whether Langfuse actually holds a trace before offering its deep link. */
export async function getLangfuseTraceAccess(traceId: string): Promise<LangfuseTraceAccess | null> {
  const id = String(traceId || '').trim();
  if (!id) return null;
  const { data } = await apiClient.get<LangfuseTraceAccess>(
    api(`/observability/langfuse/trace/${encodeURIComponent(id)}`)
  );
  return data;
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

/**
 * The latest persisted run for one corpus, or null when it has never been indexed.
 *
 * `finalize=false`: a pure read of the stored summary. The default path reconciles a run
 * stuck in `indexing` against the manifest and fence and REWRITES its summary, on top of a
 * fence read, a scoped-config load and an event-queue flush per call. A listing that asks
 * every corpus on every dashboard load must not do any of that, least of all mutate a run as
 * a side effect of displaying it. Callers that need the reconciled answer (the Indexing tab
 * watching its own run) keep the default.
 *
 * A never-indexed corpus is an expected answer here, not a failure, so the 404 is accepted
 * as a status rather than thrown: the shared response interceptor console.errors every
 * rejection, and a dashboard listing every corpus would log one per unindexed corpus on
 * every load. Real failures (503 while a corpus is being de-indexed, 409 on a malformed
 * fence) still reject, so the caller can tell "never indexed" from "could not be read".
 */
export async function getLatestIndexRun(corpusId: string): Promise<IndexRunSummary | null> {
  const { status, data } = await apiClient.get<IndexRunSummary>(
    api(`/index/${encodeURIComponent(corpusId)}/runs/latest`),
    { params: { finalize: false }, validateStatus: (s) => s === 200 || s === 404 },
  );
  return status === 404 ? null : data;
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

