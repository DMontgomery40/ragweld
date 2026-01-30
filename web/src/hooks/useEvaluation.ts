/**
 * useEvaluation - Hook for running and managing RAG evaluations
 *
 * Uses types from generated.ts (Pydantic-first architecture):
 * - EvalRequest, EvalMetrics, EvalResult, EvalRun, EvalComparisonResult
 *
 * USAGE:
 *   const {
 *     runEvaluation,
 *     currentRun,
 *     isRunning,
 *     progress,
 *     error,
 *     compareRuns,
 *     comparison
 *   } = useEvaluation();
 */

import { useState, useCallback } from 'react';
import type {
  EvalRequest,
  EvalMetrics,
  EvalResult,
  EvalRun,
  EvalComparisonResult,
} from '@/types/generated';
import { useRepoStore } from '@/stores';

// API endpoint for evaluation
const EVAL_API_BASE = '/api/eval';

interface EvaluationState {
  currentRun: EvalRun | null;
  isRunning: boolean;
  progress: number;
  error: string | null;
  comparison: EvalComparisonResult | null;
}

export function useEvaluation() {
  const { activeRepo } = useRepoStore();
  const [state, setState] = useState<EvaluationState>({
    currentRun: null,
    isRunning: false,
    progress: 0,
    error: null,
    comparison: null,
  });

  /**
   * Run a new evaluation
   */
  const runEvaluation = useCallback(
    async (options?: { datasetId?: string; sampleSize?: number }) => {
      if (!activeRepo) {
        setState((prev) => ({ ...prev, error: 'No repository selected' }));
        return null;
      }

      setState((prev) => ({
        ...prev,
        isRunning: true,
        progress: 0,
        error: null,
        currentRun: null,
      }));

      const request: EvalRequest = {
        repo_id: activeRepo.id,
        dataset_id: options?.datasetId ?? null,
        sample_size: options?.sampleSize ?? null,
      };

      try {
        const response = await fetch(`${EVAL_API_BASE}/run`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(request),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `Evaluation failed: ${response.status}`);
        }

        const run: EvalRun = await response.json();

        setState((prev) => ({
          ...prev,
          currentRun: run,
          isRunning: false,
          progress: 100,
        }));

        return run;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Evaluation failed';
        setState((prev) => ({
          ...prev,
          isRunning: false,
          error: message,
        }));
        return null;
      }
    },
    [activeRepo]
  );

  /**
   * Compare two evaluation runs
   */
  const compareRuns = useCallback(
    async (baselineRunId: string, currentRunId: string) => {
      setState((prev) => ({ ...prev, error: null, comparison: null }));

      try {
        const response = await fetch(`${EVAL_API_BASE}/compare`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            baseline_run_id: baselineRunId,
            current_run_id: currentRunId,
          }),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `Comparison failed: ${response.status}`);
        }

        const comparison: EvalComparisonResult = await response.json();

        setState((prev) => ({
          ...prev,
          comparison,
        }));

        return comparison;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Comparison failed';
        setState((prev) => ({
          ...prev,
          error: message,
        }));
        return null;
      }
    },
    []
  );

  /**
   * Fetch a specific evaluation run by ID
   */
  const fetchRun = useCallback(async (runId: string): Promise<EvalRun | null> => {
    try {
      const response = await fetch(`${EVAL_API_BASE}/runs/${runId}`);
      if (!response.ok) {
        return null;
      }
      return await response.json();
    } catch {
      return null;
    }
  }, []);

  /**
   * List all evaluation runs for the active repository
   */
  const listRuns = useCallback(async (): Promise<EvalRun[]> => {
    if (!activeRepo) return [];

    try {
      const response = await fetch(`${EVAL_API_BASE}/runs?repo_id=${activeRepo.id}`);
      if (!response.ok) {
        return [];
      }
      return await response.json();
    } catch {
      return [];
    }
  }, [activeRepo]);

  /**
   * Clear the current state
   */
  const clearState = useCallback(() => {
    setState({
      currentRun: null,
      isRunning: false,
      progress: 0,
      error: null,
      comparison: null,
    });
  }, []);

  return {
    // State
    currentRun: state.currentRun,
    isRunning: state.isRunning,
    progress: state.progress,
    error: state.error,
    comparison: state.comparison,

    // Actions
    runEvaluation,
    compareRuns,
    fetchRun,
    listRuns,
    clearState,
  };
}

export default useEvaluation;
