/**
 * AgentTrainingService - Thin API client for /api/agent/train endpoints
 *
 * Public API wire types come from generated.ts.
 */

import { apiClient, api, apiUrl } from '@/api/client';
import type {
  AgentTrainControlPlaneStatusResponse,
  AgentTrainDiffRequest,
  AgentTrainDiffResponse,
  AgentTrainMetricEvent,
  AgentTrainMetricsResponse,
  AgentTrainRun,
  AgentTrainRunsResponse,
  AgentTrainStartRequest,
  AgentTrainStartResponse,
  OkResponse,
} from '@/types/generated';

export type AgentTrainRunsScope = 'corpus' | 'all';

export class AgentTrainingService {
  async getControlPlaneStatus(corpusId?: string): Promise<AgentTrainControlPlaneStatusResponse> {
    const qs = new URLSearchParams();
    if (corpusId) qs.set('corpus_id', corpusId);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    const { data } = await apiClient.get<AgentTrainControlPlaneStatusResponse>(
      api(`/agent/train/control-plane/status${suffix}`),
      { headers: { 'Cache-Control': 'no-store' } }
    );
    return data;
  }

  async listRuns(
    corpusId: string,
    scope: AgentTrainRunsScope = 'corpus',
    limit = 50
  ): Promise<AgentTrainRunsResponse> {
    const qs = new URLSearchParams();
    qs.set('scope', scope);
    qs.set('limit', String(limit));
    if (scope === 'corpus') qs.set('corpus_id', corpusId);
    else if (corpusId) qs.set('corpus_id', corpusId);

    const { data } = await apiClient.get<AgentTrainRunsResponse>(api(`/agent/train/runs?${qs.toString()}`), {
      headers: { 'Cache-Control': 'no-store' },
    });
    return data;
  }

  async startRun(payload: AgentTrainStartRequest): Promise<AgentTrainStartResponse> {
    const { data } = await apiClient.post<AgentTrainStartResponse>(api('/agent/train/start'), payload);
    return data;
  }

  async getRun(runId: string): Promise<AgentTrainRun> {
    const { data } = await apiClient.get<AgentTrainRun>(api(`/agent/train/run/${encodeURIComponent(runId)}`), {
      headers: { 'Cache-Control': 'no-store' },
    });
    return data;
  }

  async getMetrics(runId: string, limit = 500): Promise<AgentTrainMetricsResponse> {
    const { data } = await apiClient.get<AgentTrainMetricsResponse>(
      api(`/agent/train/run/${encodeURIComponent(runId)}/metrics?limit=${encodeURIComponent(String(limit))}`),
      { headers: { 'Cache-Control': 'no-store' } }
    );
    return data;
  }

  streamRun(
    runId: string,
    onEvent: (ev: AgentTrainMetricEvent) => void,
    opts?: { onError?: (message: string) => void; onComplete?: () => void }
  ): () => void {
    const url = apiUrl(`/api/agent/train/run/${encodeURIComponent(runId)}/stream`);
    const es = new EventSource(url);

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as AgentTrainMetricEvent;
        onEvent(data);
        if (data.type === 'complete') {
          opts?.onComplete?.();
          es.close();
        }
      } catch {
        // Ignore malformed lines
      }
    };

    es.onerror = () => {
      opts?.onError?.('Connection lost');
      es.close();
    };

    return () => es.close();
  }

  async cancelRun(runId: string): Promise<OkResponse> {
    const { data } = await apiClient.post<OkResponse>(api(`/agent/train/run/${encodeURIComponent(runId)}/cancel`), {});
    return data;
  }

  async promoteRun(runId: string): Promise<OkResponse> {
    const { data } = await apiClient.post<OkResponse>(api(`/agent/train/run/${encodeURIComponent(runId)}/promote`), {});
    return data;
  }

  async getDiff(payload: AgentTrainDiffRequest): Promise<AgentTrainDiffResponse> {
    const current = encodeURIComponent(String(payload.current_run_id || ''));
    const { data } = await apiClient.post<AgentTrainDiffResponse>(api(`/agent/train/run/${current}/diff`), payload);
    return data;
  }
}

export const agentTrainingService = new AgentTrainingService();
