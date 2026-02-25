import { useCallback, useState } from 'react';
import { useAPI } from './useAPI';
import type { IndexRequest, IndexStats, IndexStatus } from '@/types/generated';
import { TerminalService } from '@/services/TerminalService';

type UseIndexingState = {
  status: IndexStatus | null;
  stats: IndexStats | null;
  loading: boolean;
  error: string | null;
};

type FetchOptions = {
  signal?: AbortSignal;
  quiet?: boolean;
};

type IndexStreamCallbacks = {
  terminalId: string;
  onLine?: (line: string) => void;
  onProgress?: (percent: number, message: string) => void;
  onError?: (error: string) => void;
  onComplete?: (status: IndexStatus | null, stats: IndexStats | null) => void;
  onCancelled?: (status: IndexStatus | null, stats: IndexStats | null) => void;
};

type StopOptions = {
  terminalId?: string;
};

/**
 * Shared indexing orchestration used by Dashboard + RAG tabs.
 */
export function useIndexing() {
  const { api } = useAPI();

  const [state, setState] = useState<UseIndexingState>({
    status: null,
    stats: null,
    loading: false,
    error: null,
  });

  const clearError = useCallback(() => setState((s) => ({ ...s, error: null })), []);

  const fetchStatus = useCallback(
    async (corpusId: string, options: FetchOptions = {}) => {
      if (!options.quiet) {
        setState((s) => ({ ...s, loading: true, error: null }));
      }
      try {
        const r = await fetch(api(`index/${encodeURIComponent(corpusId)}/status`), { signal: options.signal });
        if (!r.ok) throw new Error((await r.text().catch(() => '')) || `Status request failed (${r.status})`);
        const data: IndexStatus = await r.json();
        setState((s) => ({ ...s, status: data, loading: false }));
        return data;
      } catch (e) {
        if ((e as Error)?.name === 'AbortError') {
          throw e;
        }
        const msg = e instanceof Error ? e.message : 'Failed to fetch status';
        setState((s) => ({ ...s, loading: false, error: msg }));
        throw e;
      }
    },
    [api]
  );

  const fetchStats = useCallback(
    async (corpusId: string, options: FetchOptions = {}) => {
      if (!options.quiet) {
        setState((s) => ({ ...s, loading: true, error: null }));
      }
      try {
        const r = await fetch(api(`index/${encodeURIComponent(corpusId)}/stats`), { signal: options.signal });
        if (!r.ok) {
          setState((s) => ({ ...s, stats: null, loading: false }));
          return null;
        }
        const data: IndexStats = await r.json();
        setState((s) => ({ ...s, stats: data, loading: false }));
        return data;
      } catch (e) {
        if ((e as Error)?.name === 'AbortError') {
          throw e;
        }
        const msg = e instanceof Error ? e.message : 'Failed to fetch stats';
        setState((s) => ({ ...s, stats: null, loading: false, error: msg }));
        throw e;
      }
    },
    [api]
  );

  const startIndex = useCallback(
    async (req: IndexRequest) => {
      setState((s) => ({ ...s, loading: true, error: null }));
      try {
        const r = await fetch(api('index'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(req),
        });
        if (!r.ok) throw new Error((await r.text().catch(() => '')) || `Index request failed (${r.status})`);
        const data: IndexStatus = await r.json();
        setState((s) => ({ ...s, status: data, loading: false }));
        return data;
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Failed to start indexing';
        setState((s) => ({ ...s, loading: false, error: msg }));
        throw e;
      }
    },
    [api]
  );

  const connectStream = useCallback(
    (corpusId: string, callbacks: IndexStreamCallbacks) => {
      TerminalService.streamIndexRun(callbacks.terminalId, {
        repo: corpusId,
        onLine: callbacks.onLine,
        onProgress: callbacks.onProgress,
        onError: (error) => {
          setState((s) => ({ ...s, loading: false, error }));
          callbacks.onError?.(error);
        },
        onComplete: () => {
          void (async () => {
            const [nextStatus, nextStats] = await Promise.all([
              fetchStatus(corpusId, { quiet: true }).catch(() => null),
              fetchStats(corpusId, { quiet: true }).catch(() => null),
            ]);
            callbacks.onComplete?.(nextStatus, nextStats);
          })();
        },
        onCancelled: () => {
          void (async () => {
            const [nextStatus, nextStats] = await Promise.all([
              fetchStatus(corpusId, { quiet: true }).catch(() => null),
              fetchStats(corpusId, { quiet: true }).catch(() => null),
            ]);
            callbacks.onCancelled?.(nextStatus, nextStats);
          })();
        },
      });
    },
    [fetchStats, fetchStatus]
  );

  const disconnectStream = useCallback((terminalId: string) => {
    TerminalService.disconnect(terminalId);
  }, []);

  const startAndStream = useCallback(
    async (req: IndexRequest, callbacks: IndexStreamCallbacks) => {
      const corpusId = String(req.corpus_id || '').trim();
      if (!corpusId) throw new Error('corpus_id is required');
      const status = await startIndex(req);
      connectStream(corpusId, callbacks);
      return status;
    },
    [connectStream, startIndex]
  );

  const stopIndex = useCallback(
    async (corpusId: string, options: StopOptions = {}) => {
      if (options.terminalId) {
        TerminalService.disconnect(options.terminalId);
      }
      setState((s) => ({ ...s, loading: true, error: null }));
      try {
        const r = await fetch(api(`index/${encodeURIComponent(corpusId)}/stop`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });
        if (!r.ok) throw new Error((await r.text().catch(() => '')) || `Stop request failed (${r.status})`);
        const data: IndexStatus = await r.json();
        setState((s) => ({ ...s, status: data, loading: false }));
        return data;
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Failed to stop indexing';
        setState((s) => ({ ...s, loading: false, error: msg }));
        throw e;
      }
    },
    [api]
  );

  const deleteIndex = useCallback(
    async (corpusId: string) => {
      setState((s) => ({ ...s, loading: true, error: null }));
      try {
        const r = await fetch(api(`index/${encodeURIComponent(corpusId)}`), { method: 'DELETE' });
        if (!r.ok) throw new Error((await r.text().catch(() => '')) || `Delete failed (${r.status})`);
        setState((s) => ({ ...s, status: null, stats: null, loading: false }));
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Failed to delete index';
        setState((s) => ({ ...s, loading: false, error: msg }));
        throw e;
      }
    },
    [api]
  );

  return {
    status: state.status,
    stats: state.stats,
    loading: state.loading,
    error: state.error,
    clearError,
    fetchStatus,
    fetchStats,
    startIndex,
    stopIndex,
    startAndStream,
    connectStream,
    disconnectStream,
    deleteIndex,
  };
}
