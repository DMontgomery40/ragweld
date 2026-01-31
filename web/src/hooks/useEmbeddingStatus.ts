/**
 * useEmbeddingStatus Hook
 * 
 * Detects embedding configuration mismatches between the current config
 * and what was used to create the index. This is CRITICAL because mismatched
 * embeddings will cause search to return completely irrelevant results.
 */

import { useState, useEffect, useCallback } from 'react';
import { useAPI } from '@/hooks/useAPI';
import { useConfig } from '@/hooks/useConfig';
import { useRepoStore } from '@/stores/useRepoStore';
import type { IndexStats } from '@/types/generated';

export interface EmbeddingStatus {
  // Current configuration (from agro_config.json / env)
  configType: string;
  configDim: number;
  configModel: string;
  
  // Index configuration (from last_index.json)
  indexType: string | null;
  indexDim: number | null;
  indexedAt: string | null;
  indexPath: string | null;
  
  // Mismatch status
  isMismatched: boolean;
  hasIndex: boolean;
  
  // Detailed comparison
  typeMatch: boolean;
  dimMatch: boolean;
  
  // Index stats
  totalChunks: number;
}

interface UseEmbeddingStatusResult {
  status: EmbeddingStatus | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * ---agentspec
 * what: |
 *   Custom React hook that manages embedding service status polling and state management.
 *   Takes no parameters; returns UseEmbeddingStatusResult object containing status (EmbeddingStatus | null), loading (boolean), and error (string | null).
 *   Initializes with loading=true, status=null, error=null. The checkStatus callback function fetches current embedding service status asynchronously.
 *   Handles async errors by catching exceptions and storing error messages in state. Does not automatically poll; checkStatus must be called explicitly by consuming components.
 *
 * why: |
 *   Centralizes embedding status logic into a reusable hook to avoid duplicating state management across multiple components.
 *   Separates concerns: hook manages state/loading/error lifecycle while consumers decide when to call checkStatus.
 *   Callback pattern allows flexible polling strategies (manual calls, useEffect intervals, or event-driven triggers) without coupling the hook to a specific polling mechanism.
 *
 * guardrails:
 *   - DO NOT add automatic polling inside this hook; polling strategy should be controlled by consuming components via useEffect to prevent unnecessary requests
 *   - ALWAYS reset error state to null before calling checkStatus to avoid stale error messages persisting after successful retries
 *   - NOTE: checkStatus implementation is incomplete in provided code; full async logic needed to determine actual error handling behavior
 *   - ASK USER: Confirm whether checkStatus should auto-retry on failure, what timeout duration is acceptable, and if status should be cached between calls
 * ---/agentspec
 */
export function useEmbeddingStatus(): UseEmbeddingStatusResult {
  const { api } = useAPI();
  const { config } = useConfig();
  const { activeRepo } = useRepoStore();

  const [status, setStatus] = useState<EmbeddingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const checkStatus = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const corpusId = String(activeRepo || '').trim();
      if (!corpusId || !config) {
        setStatus(null);
        return;
      }

      // Current config (TriBridConfig is the law)
      const emb = config.embedding;
      const provider = String(emb?.embedding_type || '').toLowerCase();
      const configType = provider || 'openai';
      const configDim = Number(emb?.embedding_dim || 0);
      let configModel = String(emb?.embedding_model || '');
      if (provider === 'voyage') configModel = String(emb?.voyage_model || '');
      if (provider === 'local' || provider === 'huggingface') configModel = String(emb?.embedding_model_local || '');

      // Index config (from Postgres corpus metadata via /api/index/{corpus_id}/stats)
      const response = await fetch(api(`index/${encodeURIComponent(corpusId)}/stats`));
      if (response.status === 404) {
        setStatus({
          configType,
          configDim,
          configModel,
          indexType: null,
          indexDim: null,
          indexedAt: null,
          indexPath: null,
          hasIndex: false,
          isMismatched: false,
          typeMatch: true,
          dimMatch: true,
          totalChunks: 0,
        });
        return;
      }
      if (!response.ok) {
        throw new Error(`Failed to fetch index stats: ${response.status}`);
      }

      const data: IndexStats = await response.json();
      const totalChunks = Number(data.total_chunks || 0);
      const indexModelRaw = String(data.embedding_model || '').trim();
      const indexDimRaw = Number(data.embedding_dimensions || 0);

      // Treat empty/0 as “no dense embedding index” (e.g., skip_dense=1 runs).
      const indexType = indexModelRaw ? indexModelRaw : null;
      const indexDim = indexDimRaw > 0 ? indexDimRaw : null;
      const hasIndex = Boolean(indexType && indexDim && totalChunks > 0);

      const dimMatch = hasIndex ? configDim === indexDim : true;
      const modelMatch = hasIndex ? configModel === indexType : true;

      setStatus({
        configType,
        configDim,
        configModel,
        indexType,
        indexDim,
        indexedAt: data.last_indexed ? String(data.last_indexed) : null,
        indexPath: null,
        hasIndex,
        isMismatched: hasIndex ? !(dimMatch && modelMatch) : false,
        typeMatch: true, // provider is not persisted in index stats currently
        dimMatch,
        totalChunks,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error checking embedding status');
      console.error('[useEmbeddingStatus] Error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial check on mount
  useEffect(() => {
    checkStatus();

    // Re-check on config changes and index completion
    /**
     * ---agentspec
     * what: |
     *   Sets up event listeners that trigger a status check whenever configuration or dashboard state changes.
     *   Registers three custom window event listeners ('config-updated', 'index-completed', 'dashboard-refresh') that all invoke the same checkStatus() callback.
     *   Returns a cleanup function that removes all three listeners to prevent memory leaks when the component unmounts.
     *   Handles no edge cases for malformed events; assumes events are dispatched correctly elsewhere in the application.
     *
     * why: |
     *   Centralizes reactive status updates by coupling them to application-wide events rather than polling or prop changes.
     *   Using a single handleConfigChange function for all three events reduces code duplication and ensures consistent behavior.
     *   The cleanup function is essential in React to prevent duplicate listeners accumulating on re-renders and to free memory on unmount.
     *
     * guardrails:
     *   - DO NOT add conditional logic inside handleConfigChange; keep it a simple pass-through to checkStatus() to maintain predictability
     *   - ALWAYS call the cleanup function (return statement) to remove listeners; failure to do so causes memory leaks and duplicate event handlers
     *   - NOTE: This pattern assumes checkStatus() is idempotent; if checkStatus() has side effects or state mutations, rapid event firing may cause race conditions
     *   - ASK USER: Confirm whether checkStatus() should be debounced or throttled if 'index-completed' and 'dashboard-refresh' fire in quick succession
     * ---/agentspec
     */
    const handleConfigChange = () => checkStatus();
    window.addEventListener('config-updated', handleConfigChange);
    window.addEventListener('index-completed', handleConfigChange);
    window.addEventListener('dashboard-refresh', handleConfigChange);
    window.addEventListener('tribrid-corpus-changed', handleConfigChange as EventListener);
    window.addEventListener('agro-repo-changed', handleConfigChange as EventListener);

    return () => {
      window.removeEventListener('config-updated', handleConfigChange);
      window.removeEventListener('index-completed', handleConfigChange);
      window.removeEventListener('dashboard-refresh', handleConfigChange);
      window.removeEventListener('tribrid-corpus-changed', handleConfigChange as EventListener);
      window.removeEventListener('agro-repo-changed', handleConfigChange as EventListener);
    };
  }, [checkStatus]);

  return {
    status,
    loading,
    error,
    refresh: checkStatus,
  };
}

