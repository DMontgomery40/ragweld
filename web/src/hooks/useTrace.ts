import { useCallback, useEffect, useState } from 'react';
import { useAPI } from '@/hooks/useAPI';
import { useErrorHandler } from '@/hooks/useErrorHandler';
import type { TracesLatestResponse } from '@/types/generated';

/**
 * useTrace - loads the latest trace from the backend.
 *
 * Replaces legacy `window.Trace.loadLatestTrace`.
 */
export function useTrace() {
  const { api } = useAPI();
  const { handleApiError } = useErrorHandler();

  const [traceData, setTraceData] = useState<TracesLatestResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRepo, setSelectedRepo] = useState('');

  const loadLatestTrace = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const repoParam = selectedRepo ? `?repo=${encodeURIComponent(selectedRepo)}` : '';
      const response = await fetch(api(`/traces/latest${repoParam}`));
      const data = (await response.json()) as TracesLatestResponse;
      setTraceData(data);
    } catch (err) {
      console.error('[useTrace] Failed to load trace:', err);
      const errorMsg = handleApiError(err, 'Load trace');
      setError(errorMsg);
    } finally {
      setIsLoading(false);
    }
  }, [api, handleApiError, selectedRepo]);

  useEffect(() => {
    loadLatestTrace();
  }, [loadLatestTrace]);

  return {
    traceData,
    isLoading,
    error,
    selectedRepo,
    setSelectedRepo,
    loadLatestTrace,
  };
}

