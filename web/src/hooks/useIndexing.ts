import { useCallback, useState } from 'react';
import { useAPI } from './useAPI';
import type { IndexRequest, IndexStats, IndexStatus } from '@/types/generated';

type UseIndexingState = {
  status: IndexStatus | null;
  stats: IndexStats | null;
  loading: boolean;
  error: string | null;
};

/**
 * useIndexing
 * Replacement for legacy `window.IndexStatus` coordination.
 *
 * This hook provides typed, corpus-first helpers around the indexing endpoints:
 * - POST   /api/index
 * - GET    /api/index/{corpus_id}/status
 * - GET    /api/index/{corpus_id}/stats
 * - DELETE /api/index/{corpus_id}
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
    async (corpusId: string) => {
      setState((s) => ({ ...s, loading: true, error: null }));
      try {
        const r = await fetch(api(`index/${encodeURIComponent(corpusId)}/status`));
        if (!r.ok) throw new Error(await r.text().catch(() => '') || `Status request failed (${r.status})`);
        const data: IndexStatus = await r.json();
        setState((s) => ({ ...s, status: data, loading: false }));
        return data;
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Failed to fetch status';
        setState((s) => ({ ...s, loading: false, error: msg }));
        throw e;
      }
    },
    [api]
  );

  const fetchStats = useCallback(
    async (corpusId: string) => {
      setState((s) => ({ ...s, loading: true, error: null }));
      try {
        const r = await fetch(api(`index/${encodeURIComponent(corpusId)}/stats`));
        if (!r.ok) throw new Error(await r.text().catch(() => '') || `Stats request failed (${r.status})`);
        const data: IndexStats = await r.json();
        setState((s) => ({ ...s, stats: data, loading: false }));
        return data;
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Failed to fetch stats';
        setState((s) => ({ ...s, loading: false, error: msg }));
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
        if (!r.ok) throw new Error(await r.text().catch(() => '') || `Index request failed (${r.status})`);
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

  const deleteIndex = useCallback(
    async (corpusId: string) => {
      setState((s) => ({ ...s, loading: true, error: null }));
      try {
        const r = await fetch(api(`index/${encodeURIComponent(corpusId)}`), { method: 'DELETE' });
        if (!r.ok) throw new Error(await r.text().catch(() => '') || `Delete failed (${r.status})`);
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
    deleteIndex,
  };
}
