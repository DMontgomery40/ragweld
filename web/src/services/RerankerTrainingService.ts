/**
 * RerankerTrainingService - Thin API client for /api/reranker/train endpoints
 *
 * ALL TYPES COME FROM generated.ts (Pydantic-first architecture).
 */

import { apiUrl } from '@/api/client';
import type {
  CorpusEvalProfile,
  RerankerTrainDiffRequest,
  RerankerTrainDiffResponse,
  RerankerTrainMetricEvent,
  RerankerTrainMetricsResponse,
  RerankerTrainRun,
  RerankerTrainRunsResponse,
  RerankerTrainStartRequest,
  RerankerTrainStartResponse,
} from '@/types/generated';

export type RerankerTrainRunsScope = 'corpus' | 'all';

function assertOk(res: Response, context: string): Promise<void> {
  if (res.ok) return Promise.resolve();
  return res
    .json()
    .catch(() => ({}))
    .then((data: any) => {
      const detail = data?.detail ? String(data.detail) : '';
      throw new Error(detail || `${context} failed: ${res.status}`);
    });
}

export class RerankerTrainingService {
  async getProfile(corpusId: string): Promise<CorpusEvalProfile> {
    const res = await fetch(
      apiUrl(`/api/reranker/train/profile?corpus_id=${encodeURIComponent(corpusId)}`),
      { cache: 'no-store' }
    );
    await assertOk(res, 'getProfile');
    return res.json();
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

    const res = await fetch(apiUrl(`/api/reranker/train/runs?${qs.toString()}`), { cache: 'no-store' });
    await assertOk(res, 'listRuns');
    return res.json();
  }

  async startRun(payload: RerankerTrainStartRequest): Promise<RerankerTrainStartResponse> {
    const res = await fetch(apiUrl('/api/reranker/train/start'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await assertOk(res, 'startRun');
    return res.json();
  }

  async getRun(runId: string): Promise<RerankerTrainRun> {
    const res = await fetch(apiUrl(`/api/reranker/train/run/${encodeURIComponent(runId)}`), { cache: 'no-store' });
    await assertOk(res, 'getRun');
    return res.json();
  }

  async getMetrics(runId: string, limit = 500): Promise<RerankerTrainMetricsResponse> {
    const res = await fetch(
      apiUrl(`/api/reranker/train/run/${encodeURIComponent(runId)}/metrics?limit=${encodeURIComponent(String(limit))}`),
      { cache: 'no-store' }
    );
    await assertOk(res, 'getMetrics');
    return res.json();
  }

  async diffRuns(baselineRunId: string, currentRunId: string): Promise<RerankerTrainDiffResponse> {
    const payload: RerankerTrainDiffRequest = {
      baseline_run_id: baselineRunId,
      current_run_id: currentRunId,
    };
    const res = await fetch(apiUrl('/api/reranker/train/diff'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await assertOk(res, 'diffRuns');
    return res.json();
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

