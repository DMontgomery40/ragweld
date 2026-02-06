import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { RerankService } from '../services/RerankService';
import type { RerankerLegacyStatus, RerankerTrainLegacyRequest } from '@/types/generated';
import { useAPI } from './useAPI';

/**
 * useReranker Hook
 * React hook for reranker operations and status polling
 * Converted from /web/src/modules/reranker.js
 */
/**
 * ---agentspec
 * what: |
 *   Custom React hook that initializes and manages a RerankService instance for document reranking operations.
 *   Takes no parameters; uses apiBase from the useAPI hook context to instantiate RerankService.
 *   Returns an object containing the service instance and a status state object with fields: running (boolean), progress (number 0-100), task (string), and message (string).
 *   Memoizes the service instance to prevent unnecessary reinstantiation when apiBase remains stable.
 *   Provides reactive status updates for UI components to display reranking progress and state.
 *
 * why: |
 *   Encapsulates RerankService initialization logic in a reusable hook to avoid repeated instantiation across components.
 *   Memoization ensures the service instance persists across re-renders unless apiBase changes, reducing memory churn.
 *   Status state enables real-time UI feedback during long-running reranking operations.
 *
 * guardrails:
 *   - DO NOT remove the useMemo dependency on apiBase; changes to apiBase must trigger service recreation to use the correct API endpoint
 *   - ALWAYS ensure RerankService is properly initialized before calling reranking methods; incomplete initialization will cause runtime errors
 *   - NOTE: Status state is initialized but the hook does not show how status updates are triggered; verify that RerankService or calling code properly invokes setStatus
 *   - ASK USER: Confirm whether status updates should be managed within this hook or delegated to the service; current implementation suggests status is managed externally
 * ---/agentspec
 */
export function useReranker() {
  const { apiBase } = useAPI();
  const service = useMemo(() => new RerankService(apiBase), [apiBase]);

  const [status, setStatus] = useState<RerankerLegacyStatus>({
    running: false,
    progress: 0,
    task: '',
    message: '',
    result: null,
    live_output: [],
    run_id: null,
  });

  const [isPolling, setIsPolling] = useState(false);
  const pollingIntervalRef = useRef<number | null>(null);

  const [stats, setStats] = useState({
    queryCount: 0,
    tripletCount: 0,
    cost24h: 0,
    costAvg: 0
  });

  /**
   * Stop status polling
   */
  const stopPolling = useCallback(() => {
    if (pollingIntervalRef.current != null) {
      window.clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
    setIsPolling(false);
  }, []);

  /**
   * Start status polling
   */
  const startPolling = useCallback((corpusId?: string) => {
    if (pollingIntervalRef.current != null) return;

    setIsPolling(true);

    pollingIntervalRef.current = window.setInterval(async () => {
      const currentStatus = await service.getStatus(corpusId);
      setStatus(currentStatus);

      // Stop polling when task completes
      if (!currentStatus.running) {
        stopPolling();
      }
    }, 2000); // poll every 2 seconds during reranker training
  }, [service, stopPolling]);

  /**
   * Mine triplets
   */
  const mineTriplets = useCallback(async (corpusId?: string) => {
    // Optimistically set status immediately from the response so the UI doesn't depend on
    // process-local backend polling state (which can drift under multi-worker servers).
    setStatus((prev) => ({
      ...prev,
      running: true,
      progress: 0,
      task: 'mining',
      message: 'Mining triplets…',
      result: null,
      live_output: [],
      run_id: null,
    }));

    try {
      const result = await service.mineTriplets(corpusId);

      if (result?.ok) {
        setStatus((prev) => ({
          ...prev,
          running: false,
          progress: 100,
          task: 'mining',
          message: 'Mining complete',
          result: {
            ok: true,
            output: result.output ?? null,
            metrics: null,
            error: null,
            run_id: null,
          },
          live_output: [],
          run_id: null,
        }));
      } else {
        setStatus((prev) => ({
          ...prev,
          running: false,
          progress: 0,
          task: 'mining',
          message: 'Mining failed',
          result: {
            ok: false,
            output: null,
            metrics: null,
            error: result?.error ?? 'Mining failed',
            run_id: null,
          },
          live_output: [],
          run_id: null,
        }));
      }

      return result;
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Mining failed';
      setStatus((prev) => ({
        ...prev,
        running: false,
        progress: 0,
        task: 'mining',
        message: 'Mining failed',
        result: {
          ok: false,
          output: null,
          metrics: null,
          error: msg,
          run_id: null,
        },
        live_output: [],
        run_id: null,
      }));
      throw e;
    }
  }, [service]);

  /**
   * Train model
   */
  const trainModel = useCallback(async (options: RerankerTrainLegacyRequest = {}, corpusId?: string) => {
    const result = await service.trainModel(options, corpusId);
    if (result?.ok && result?.run_id) {
      setStatus((prev) => ({
        ...prev,
        running: true,
        progress: 0,
        task: 'training',
        message: `Training run started: ${result.run_id}`,
        result: null,
        live_output: [],
        run_id: result.run_id,
      }));
    }
    startPolling(corpusId);
    return result;
  }, [service, startPolling]);

  /**
   * Evaluate model
   */
  const evaluateModel = useCallback(async (corpusId?: string) => {
    // Optimistically set status immediately from the response so the UI doesn't depend on
    // process-local backend polling state (which can drift under multi-worker servers).
    setStatus((prev) => ({
      ...prev,
      running: true,
      progress: 0,
      task: 'evaluating',
      message: 'Evaluating model…',
      result: null,
      live_output: [],
      run_id: null,
    }));

    try {
      const result = await service.evaluateModel(corpusId);

      if (result?.ok) {
        setStatus((prev) => ({
          ...prev,
          running: false,
          progress: 100,
          task: 'evaluating',
          message: 'Evaluation complete',
          result: {
            ok: true,
            output: result.output ?? null,
            metrics: result.metrics ?? null,
            error: null,
            run_id: null,
          },
          live_output: [],
          run_id: null,
        }));
      } else {
        setStatus((prev) => ({
          ...prev,
          running: false,
          progress: 0,
          task: 'evaluating',
          message: 'Evaluation failed',
          result: {
            ok: false,
            output: null,
            metrics: null,
            error: result?.error ?? 'Evaluation failed',
            run_id: null,
          },
          live_output: [],
          run_id: null,
        }));
      }

      return result;
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Evaluation failed';
      setStatus((prev) => ({
        ...prev,
        running: false,
        progress: 0,
        task: 'evaluating',
        message: 'Evaluation failed',
        result: {
          ok: false,
          output: null,
          metrics: null,
          error: msg,
          run_id: null,
        },
        live_output: [],
        run_id: null,
      }));
      throw e;
    }
  }, [service]);

  /**
   * Submit feedback
   */
  const submitFeedback = useCallback(async (eventId: string, signal: string, note?: string, corpusId?: string) => {
    await service.submitFeedback({ eventId, signal, note }, corpusId);
  }, [service]);

  /**
   * Track file click
   */
  const trackFileClick = useCallback(async (eventId: string, docId: string, corpusId?: string) => {
    await service.trackFileClick(eventId, docId, corpusId);
  }, [service]);

  /**
   * Get reranker info
   */
  const getInfo = useCallback(async (corpusId?: string) => {
    return await service.getInfo(corpusId);
  }, [service]);

  /**
   * Get logs
   */
  const getLogs = useCallback(async (corpusId?: string) => {
    return await service.getLogs(corpusId);
  }, [service]);

  /**
   * Download logs
   */
  const downloadLogs = useCallback(async (corpusId?: string) => {
    const blob = await service.downloadLogs(corpusId);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `queries-${new Date().toISOString().split('T')[0]}.jsonl`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [service]);

  /**
   * Refresh statistics
   */
  const refreshStats = useCallback(async (corpusId?: string) => {
    try {
      const [logsCount, tripletsCount, costs] = await Promise.all([
        service.getLogsCount(corpusId),
        service.getTripletsCount(corpusId),
        service.getCosts(corpusId)
      ]);

      setStats({
        queryCount: logsCount.count || 0,
        tripletCount: tripletsCount.count || 0,
        cost24h: costs.total_24h || 0,
        costAvg: costs.avg_per_query || 0
      });
    } catch (error) {
      console.error('[useReranker] Failed to refresh stats:', error);
    }
  }, [service]);

  /**
   * Clear logs
   */
  const clearLogs = useCallback(async (corpusId?: string) => {
    await service.clearLogs(corpusId);
    await refreshStats(corpusId);
  }, [service, refreshStats]);

  /**
   * Get no-hit queries
   */
  const getNoHits = useCallback(async (corpusId?: string) => {
    return await service.getNoHits(corpusId);
  }, [service]);

  /**
   * Cleanup on unmount
   */
  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, [stopPolling]);

  return {
    // Status
    status,
    isPolling,
    stats,

    // Operations
    mineTriplets,
    trainModel,
    evaluateModel,
    submitFeedback,
    trackFileClick,

    // Info & logs
    getInfo,
    getLogs,
    downloadLogs,
    clearLogs,
    getNoHits,

    // Utilities
    refreshStats,
    startPolling,
    stopPolling
  };
}
