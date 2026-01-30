import { useState, useCallback, useMemo, useEffect } from 'react';
import { RerankService, RerankerStatus, TrainingOptions, EvaluationMetrics } from '../services/RerankService';
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

  const [status, setStatus] = useState<RerankerStatus>({
    running: false,
    progress: 0,
    task: '',
    message: ''
  });

  const [isPolling, setIsPolling] = useState(false);
  const [pollingInterval, setPollingInterval] = useState<number | null>(null);

  const [stats, setStats] = useState({
    queryCount: 0,
    tripletCount: 0,
    cost24h: 0,
    costAvg: 0
  });

  /**
   * Start status polling
   */
  const startPolling = useCallback(() => {
    if (isPolling) return;

    setIsPolling(true);

    const interval = window.setInterval(async () => {
      const currentStatus = await service.getStatus();
      setStatus(currentStatus);

      // Stop polling when task completes
      if (!currentStatus.running) {
        stopPolling();
      }
    }, 2000); // poll every 2 seconds during reranker training

    setPollingInterval(interval);
  }, [service, isPolling]);

  /**
   * Stop status polling
   */
  const stopPolling = useCallback(() => {
    if (pollingInterval) {
      window.clearInterval(pollingInterval);
      setPollingInterval(null);
    }
    setIsPolling(false);
  }, [pollingInterval]);

  /**
   * Mine triplets
   */
  const mineTriplets = useCallback(async () => {
    const result = await service.mineTriplets();
    startPolling();
    return result;
  }, [service, startPolling]);

  /**
   * Train model
   */
  const trainModel = useCallback(async (options: TrainingOptions = {}) => {
    const result = await service.trainModel(options);
    startPolling();
    return result;
  }, [service, startPolling]);

  /**
   * Evaluate model
   */
  const evaluateModel = useCallback(async () => {
    const result = await service.evaluateModel();
    startPolling();
    return result;
  }, [service, startPolling]);

  /**
   * Submit feedback
   */
  const submitFeedback = useCallback(async (eventId: string, signal: string, note?: string) => {
    await service.submitFeedback({ eventId, signal, note });
  }, [service]);

  /**
   * Track file click
   */
  const trackFileClick = useCallback(async (eventId: string, docId: string) => {
    await service.trackFileClick(eventId, docId);
  }, [service]);

  /**
   * Get reranker info
   */
  const getInfo = useCallback(async () => {
    return await service.getInfo();
  }, [service]);

  /**
   * Get logs
   */
  const getLogs = useCallback(async () => {
    return await service.getLogs();
  }, [service]);

  /**
   * Download logs
   */
  const downloadLogs = useCallback(async () => {
    const blob = await service.downloadLogs();
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
   * Clear logs
   */
  const clearLogs = useCallback(async () => {
    await service.clearLogs();
    await refreshStats();
  }, [service]);

  /**
   * Save baseline
   */
  const saveBaseline = useCallback(async () => {
    return await service.saveBaseline();
  }, [service]);

  /**
   * Compare with baseline
   */
  const compareBaseline = useCallback(async () => {
    return await service.compareBaseline();
  }, [service]);

  /**
   * Rollback to baseline
   */
  const rollbackModel = useCallback(async () => {
    return await service.rollbackModel();
  }, [service]);

  /**
   * Run smoke test
   */
  const runSmokeTest = useCallback(async (query: string) => {
    return await service.runSmokeTest(query);
  }, [service]);

  /**
   * Setup nightly job
   */
  const setupNightlyJob = useCallback(async (time: string) => {
    return await service.setupNightlyJob(time);
  }, [service]);

  /**
   * Remove nightly job
   */
  const removeNightlyJob = useCallback(async () => {
    return await service.removeNightlyJob();
  }, [service]);

  /**
   * Refresh statistics
   */
  const refreshStats = useCallback(async () => {
    try {
      const [logsCount, tripletsCount, costs] = await Promise.all([
        service.getLogsCount(),
        service.getTripletsCount(),
        service.getCosts()
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
   * Get no-hit queries
   */
  const getNoHits = useCallback(async () => {
    return await service.getNoHits();
  }, [service]);

  /**
   * Parse metrics from output
   */
  const parseMetrics = useCallback((output: string): EvaluationMetrics | null => {
    return service.parseMetrics(output);
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

    // Baselines
    saveBaseline,
    compareBaseline,
    rollbackModel,

    // Testing
    runSmokeTest,

    // Automation
    setupNightlyJob,
    removeNightlyJob,

    // Utilities
    refreshStats,
    parseMetrics,
    startPolling,
    stopPolling
  };
}
