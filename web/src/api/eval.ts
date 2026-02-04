import { apiClient, api, withCorpusScope } from './client';
import type {
  EvalAnalyzeComparisonRequest,
  EvalAnalyzeComparisonResponse,
  EvalRequest,
  EvalRun,
  EvalRunsResponse,
} from '@/types/generated';

export const evalApi = {
  async run(request: EvalRequest): Promise<EvalRun> {
    const { data } = await apiClient.post<EvalRun>(api('/eval/run'), request);
    return data;
  },

  async listRuns(corpusId: string): Promise<EvalRunsResponse> {
    const qs = new URLSearchParams({ corpus_id: corpusId });
    const { data } = await apiClient.get<EvalRunsResponse>(api(`/eval/runs?${qs.toString()}`), {
      // Equivalent of fetch({ cache: 'no-store' }) for axios.
      headers: { 'Cache-Control': 'no-store' },
    });
    return data;
  },

  async getResults(runId: string): Promise<EvalRun> {
    const { data } = await apiClient.get<EvalRun>(api(`/eval/results/${encodeURIComponent(runId)}`));
    return data;
  },

  async analyzeComparison(payload: EvalAnalyzeComparisonRequest): Promise<EvalAnalyzeComparisonResponse> {
    const { data } = await apiClient.post<EvalAnalyzeComparisonResponse>(
      withCorpusScope(api('/eval/analyze_comparison')),
      payload
    );
    return data;
  },
};
