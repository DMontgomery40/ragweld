/**
 * EvaluationService - Thin API client for /api/eval endpoints
 *
 * ALL TYPES COME FROM generated.ts (Pydantic-first)
 * This file only provides API call wrappers.
 */

// Re-export types from generated.ts - DO NOT define interfaces here
export type {
  EvalResult,
  EvalRun,
  EvalRunMeta,
  EvalMetrics,
  EvalRequest,
  EvalRunsResponse,
  EvalComparisonResult,
  EvalDatasetItem,
  EvaluationConfig,
} from '@/types/generated';

import type {
  EvalResult,
  EvalRun,
  EvalRunsResponse,
  EvalComparisonResult,
} from '@/types/generated';

const EVAL_API_BASE = '/api/eval';

/**
 * Run evaluation for a corpus
 */
export async function runEvaluation(
  corpusId: string,
  options?: { datasetId?: string; sampleSize?: number }
): Promise<EvalRun> {
  const response = await fetch(`${EVAL_API_BASE}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo_id: corpusId,
      dataset_id: options?.datasetId ?? null,
      sample_size: options?.sampleSize ?? null,
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Evaluation failed: ${response.status}`);
  }

  return response.json();
}

/**
 * List evaluation runs for a corpus
 */
export async function listRuns(corpusId: string, limit = 20): Promise<EvalRunsResponse> {
  const response = await fetch(
    `${EVAL_API_BASE}/runs?corpus_id=${encodeURIComponent(corpusId)}&limit=${limit}`
  );

  if (!response.ok) {
    throw new Error(`Failed to list runs: ${response.status}`);
  }

  return response.json();
}

/**
 * Get a specific evaluation run
 */
export async function getRun(runId: string): Promise<EvalRun> {
  const response = await fetch(`${EVAL_API_BASE}/runs/${runId}`);

  if (!response.ok) {
    throw new Error(`Failed to get run: ${response.status}`);
  }

  return response.json();
}

/**
 * Delete an evaluation run
 */
export async function deleteRun(runId: string): Promise<void> {
  const response = await fetch(`${EVAL_API_BASE}/runs/${runId}`, {
    method: 'DELETE',
  });

  if (!response.ok) {
    throw new Error(`Failed to delete run: ${response.status}`);
  }
}

/**
 * Compare two evaluation runs
 */
export async function compareRuns(
  baselineRunId: string,
  currentRunId: string
): Promise<EvalComparisonResult> {
  // Load both runs and compute comparison
  const [baseline, current] = await Promise.all([getRun(baselineRunId), getRun(currentRunId)]);

  const response = await fetch(`${EVAL_API_BASE}/analyze_comparison`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      baseline_run: baseline,
      current_run: current,
    }),
  });

  if (!response.ok) {
    throw new Error(`Comparison failed: ${response.status}`);
  }

  return response.json();
}

/**
 * Test a single query (ad-hoc evaluation)
 */
export async function testQuery(
  corpusId: string,
  question: string,
  expectedPaths: string[],
  finalK?: number
): Promise<EvalResult> {
  const response = await fetch(`${EVAL_API_BASE}/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo_id: corpusId,
      question,
      expected_paths: expectedPaths,
      final_k: finalK,
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Test failed: ${response.status}`);
  }

  return response.json();
}

/**
 * Export results to JSON string
 */
export function exportResultsToJson(results: EvalResult[]): string {
  return JSON.stringify(results, null, 2);
}

/**
 * Export results to CSV string
 */
export function exportResultsToCsv(results: EvalResult[]): string {
  const headers = ['entry_id', 'question', 'top1_hit', 'topk_hit', 'reciprocal_rank', 'recall', 'latency_ms'];
  const rows = results.map((r) => [
    r.entry_id,
    `"${r.question.replace(/"/g, '""')}"`,
    r.top1_hit ? '1' : '0',
    r.topk_hit ? '1' : '0',
    r.reciprocal_rank.toFixed(4),
    r.recall.toFixed(4),
    r.latency_ms?.toFixed(2) ?? '',
  ]);
  return [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
}
