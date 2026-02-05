/**
 * RerankerTrainingService - Thin API client for /api/reranker/train endpoints
 *
 * ALL TYPES COME FROM generated.ts (Pydantic-first architecture).
 */

import { apiClient, api, apiUrl } from '@/api/client';
import type {
  CorpusEvalProfile,
  OkResponse,
  RerankerTrainDiffRequest,
  RerankerTrainDiffResponse,
  RerankerTrainMetricEvent,
  RerankerTrainMetricsResponse,
  RerankerTrainRun,
  RerankerTrainRunsResponse,
  RerankerTrainStartRequest,
  RerankerTrainStartResponse,
  RerankerScoreRequest,
  RerankerScoreResponse,
} from '@/types/generated';

export type RerankerTrainRunsScope = 'corpus' | 'all';

export class RerankerTrainingService {
  async getProfile(corpusId: string): Promise<CorpusEvalProfile> {
    const { data } = await apiClient.get<CorpusEvalProfile>(
      api(`/reranker/train/profile?corpus_id=${encodeURIComponent(corpusId)}`),
      { headers: { 'Cache-Control': 'no-store' } }
    );
    return data;
  }

  async listRuns(
    corpusId: string,
    scope: RerankerTrainRunsScope = 'corpus',
    limit = 50
  ): Promise<RerankerTrainRunsResponse> {
    const qs = new URLSearchParams();
    qs.set('scope', scope);
    qs.set('limit', String(limit));
    if (scope === 'corpus') qs.set('corpus_id', corpusId);
    else if (corpusId) qs.set('corpus_id', corpusId);

    const { data } = await apiClient.get<RerankerTrainRunsResponse>(
      api(`/reranker/train/runs?${qs.toString()}`),
      { headers: { 'Cache-Control': 'no-store' } }
    );
    return data;
  }

  async startRun(payload: RerankerTrainStartRequest): Promise<RerankerTrainStartResponse> {
    const { data } = await apiClient.post<RerankerTrainStartResponse>(api('/reranker/train/start'), payload);
    return data;
  }

  async getRun(runId: string): Promise<RerankerTrainRun> {
    const { data } = await apiClient.get<RerankerTrainRun>(
      api(`/reranker/train/run/${encodeURIComponent(runId)}`),
      { headers: { 'Cache-Control': 'no-store' } }
    );
    return data;
  }

  async getMetrics(runId: string, limit = 500): Promise<RerankerTrainMetricsResponse> {
    const { data } = await apiClient.get<RerankerTrainMetricsResponse>(
      api(
        `/reranker/train/run/${encodeURIComponent(runId)}/metrics?limit=${encodeURIComponent(String(limit))}`
      ),
      { headers: { 'Cache-Control': 'no-store' } }
    );
    return data;
  }

  async diffRuns(baselineRunId: string, currentRunId: string): Promise<RerankerTrainDiffResponse> {
    const payload: RerankerTrainDiffRequest = {
      baseline_run_id: baselineRunId,
      current_run_id: currentRunId,
    };
    const { data } = await apiClient.post<RerankerTrainDiffResponse>(api('/reranker/train/diff'), payload);
    return data;
  }

  async promoteRun(runId: string): Promise<OkResponse> {
    const { data } = await apiClient.post<OkResponse>(
      api(`/reranker/train/run/${encodeURIComponent(runId)}/promote`),
      {}
    );
    return data;
  }

  async scorePair(payload: RerankerScoreRequest): Promise<RerankerScoreResponse> {
    const { data } = await apiClient.post<RerankerScoreResponse>(api('/reranker/score'), payload);
    return data;
  }

  streamRun(
    runId: string,
    onEvent: (ev: RerankerTrainMetricEvent) => void,
    opts?: { onError?: (message: string) => void; onComplete?: () => void }
  ): () => void {
    const url = apiUrl(`/api/reranker/train/run/stream?run_id=${encodeURIComponent(runId)}`);
    const es = new EventSource(url);

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as RerankerTrainMetricEvent;
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
}

export const rerankerTrainingService = new RerankerTrainingService();
