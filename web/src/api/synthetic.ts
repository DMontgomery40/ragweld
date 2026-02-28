import { apiClient, api, apiUrl } from './client';
import type {
  OkResponse,
  SyntheticArtifactPreviewResponse,
  SyntheticConfigPatchResponse,
  SyntheticPublishResponse,
  SyntheticRun,
  SyntheticRunEvent,
  SyntheticRunStartRequest,
  SyntheticRunsResponse,
} from '@/types/generated';

export const syntheticApi = {
  async startRun(payload: SyntheticRunStartRequest): Promise<SyntheticRun> {
    const { data } = await apiClient.post<SyntheticRun>(api('/synthetic/run/start'), payload);
    return data;
  },

  async listRuns(corpusId: string, limit = 50): Promise<SyntheticRunsResponse> {
    const qs = new URLSearchParams({ corpus_id: corpusId, limit: String(limit) });
    const { data } = await apiClient.get<SyntheticRunsResponse>(api(`/synthetic/runs?${qs.toString()}`), {
      headers: { 'Cache-Control': 'no-store' },
    });
    return data;
  },

  async getRun(runId: string): Promise<SyntheticRun> {
    const { data } = await apiClient.get<SyntheticRun>(api(`/synthetic/run/${encodeURIComponent(runId)}`), {
      headers: { 'Cache-Control': 'no-store' },
    });
    return data;
  },

  async cancelRun(runId: string): Promise<OkResponse> {
    const { data } = await apiClient.post<OkResponse>(api(`/synthetic/run/${encodeURIComponent(runId)}/cancel`), {});
    return data;
  },

  async publishEvalDataset(runId: string): Promise<SyntheticPublishResponse> {
    const { data } = await apiClient.post<SyntheticPublishResponse>(
      api(`/synthetic/run/${encodeURIComponent(runId)}/publish/eval_dataset`),
      {}
    );
    return data;
  },

  async publishSemanticCards(runId: string): Promise<SyntheticPublishResponse> {
    const { data } = await apiClient.post<SyntheticPublishResponse>(
      api(`/synthetic/run/${encodeURIComponent(runId)}/publish/semantic_cards`),
      {}
    );
    return data;
  },

  async publishKeywords(runId: string): Promise<SyntheticPublishResponse> {
    const { data } = await apiClient.post<SyntheticPublishResponse>(
      api(`/synthetic/run/${encodeURIComponent(runId)}/publish/keywords`),
      {}
    );
    return data;
  },

  async publishTriplets(runId: string): Promise<SyntheticPublishResponse> {
    const { data } = await apiClient.post<SyntheticPublishResponse>(
      api(`/synthetic/run/${encodeURIComponent(runId)}/publish/triplets`),
      {}
    );
    return data;
  },

  async publishConfigPatch(runId: string): Promise<SyntheticConfigPatchResponse> {
    const { data } = await apiClient.post<SyntheticConfigPatchResponse>(
      api(`/synthetic/run/${encodeURIComponent(runId)}/publish/config_patch`),
      {}
    );
    return data;
  },

  async previewArtifact(runId: string, kind: string, limit = 5): Promise<SyntheticArtifactPreviewResponse> {
    const qs = new URLSearchParams({ kind, limit: String(limit) });
    const { data } = await apiClient.get<SyntheticArtifactPreviewResponse>(
      api(`/synthetic/run/${encodeURIComponent(runId)}/artifact/preview?${qs.toString()}`)
    );
    return data;
  },

  streamRun(
    runId: string,
    onEvent: (ev: SyntheticRunEvent) => void,
    opts?: { onError?: (message: string) => void; onComplete?: () => void }
  ): () => void {
    const url = apiUrl(`/api/synthetic/run/stream?run_id=${encodeURIComponent(runId)}`);
    const es = new EventSource(url);

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as SyntheticRunEvent;
        onEvent(data);
        if (data.type === 'complete') {
          opts?.onComplete?.();
          es.close();
        }
      } catch {
        // Ignore malformed lines.
      }
    };

    es.onerror = () => {
      opts?.onError?.('Connection lost');
      es.close();
    };

    return () => es.close();
  },
};
