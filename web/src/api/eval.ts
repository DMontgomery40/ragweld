import axios from 'axios';
import { apiClient, api, withCorpusScope } from './client';
import type {
  EvalAnalysisArtifact,
  EvalAnalyzeComparisonRequest,
  EvalAnalyzeComparisonResponse,
  EvalRequest,
  EvalRun,
  EvalRunsResponse,
  PromptfooRun,
  PromptfooRunsResponse,
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

  async runPromptfoo(request: EvalRequest): Promise<PromptfooRun> {
    // The route blocks until the real promptfoo CLI finishes (minutes for a
    // sampled run, ~30 min for the full dataset) — the client's default 30s
    // timeout would abort a healthy run mid-flight. Bounded (not infinite) so
    // a dead connection still surfaces instead of spinning forever.
    const { data } = await apiClient.post<PromptfooRun>(api('/eval/promptfoo/run'), request, {
      timeout: 60 * 60_000,
    });
    return data;
  },

  async listPromptfooRuns(corpusId: string): Promise<PromptfooRunsResponse> {
    const qs = new URLSearchParams({ corpus_id: corpusId });
    const { data } = await apiClient.get<PromptfooRunsResponse>(api(`/eval/promptfoo/runs?${qs.toString()}`), {
      headers: { 'Cache-Control': 'no-store' },
    });
    return data;
  },

  async getResults(runId: string): Promise<EvalRun> {
    const { data } = await apiClient.get<EvalRun>(api(`/eval/results/${encodeURIComponent(runId)}`));
    return data;
  },

  async getCachedAnalysis(runId: string, compareRunId: string): Promise<EvalAnalysisArtifact | null> {
    // The persisted AI analysis for this run/baseline pair, so re-opening a run
    // shows the costed result without re-charging. 404 => nothing cached (or a
    // different baseline was analyzed) => generate fresh.
    try {
      const qs = new URLSearchParams({ compare_run_id: compareRunId });
      const { data } = await apiClient.get<EvalAnalysisArtifact>(
        api(`/eval/analysis/${encodeURIComponent(runId)}?${qs.toString()}`),
        { headers: { 'Cache-Control': 'no-store' } },
      );
      return data;
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 404) return null;
      throw err;
    }
  },

  async analyzeComparison(payload: EvalAnalyzeComparisonRequest): Promise<EvalAnalyzeComparisonResponse> {
    // The analysis is one long LLM generation, server-bounded by
    // generation.gen_timeout (600s default) — on the local lane it routinely
    // outlives the client's 30s default timeout. Bounded at the server budget
    // plus margin so a dead connection still fails instead of spinning.
    const { data } = await apiClient.post<EvalAnalyzeComparisonResponse>(
      withCorpusScope(api('/eval/analyze_comparison')),
      payload,
      { timeout: 660_000 }
    );
    return data;
  },
};
