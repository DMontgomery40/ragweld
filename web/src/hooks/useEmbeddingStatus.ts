/**
 * useEmbeddingStatus Hook
 * 
 * Detects embedding configuration mismatches between the current config
 * and what was used to create the index. This is CRITICAL because mismatched
 * embeddings will cause search to return completely irrelevant results.
 * 
 * The hook fetches from /api/index/stats which now includes:
 * - embedding_config: current configuration from env/config
 * - index_embedding_config: what the index was built with (from last_index.json)
 * - embedding_mismatch: boolean flag for quick checks
 * - embedding_mismatch_details: type/dimension comparison details
 */

import { useState, useEffect, useCallback } from 'react';

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
  const [status, setStatus] = useState<EmbeddingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const checkStatus = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch('/api/index/stats');
      if (!response.ok) {
        throw new Error(`Failed to fetch index stats: ${response.status}`);
      }

      const data = await response.json();

      // Extract current config
      const embeddingConfig = data.embedding_config || {};
      const configType = (embeddingConfig.provider || 'openai').toLowerCase();
      const configDim = embeddingConfig.dimensions || 3072;
      const configModel = embeddingConfig.model || 'text-embedding-3-large';

      // Extract index config (may be null if no index)
      const indexConfig = data.index_embedding_config;
      
      // Use explicit has_index flag from backend, fallback to checking index_embedding_config
      // This ensures we don't show "embeddings match" when there's no actual index
      const hasIndex = data.has_index === true || (indexConfig !== null && data.total_chunks > 0);

      // Get mismatch details
      const mismatchDetails = data.embedding_mismatch_details || {};

      const embeddingStatus: EmbeddingStatus = {
        configType,
        configDim,
        configModel,
        indexType: indexConfig?.provider || null,
        indexDim: indexConfig?.dimensions || null,
        indexedAt: indexConfig?.indexed_at || null,
        indexPath: indexConfig?.index_path || null,
        isMismatched: data.embedding_mismatch === true,
        hasIndex,
        typeMatch: mismatchDetails.type_match !== false,
        dimMatch: mismatchDetails.dim_match !== false,
        totalChunks: data.total_chunks || 0,
      };

      setStatus(embeddingStatus);
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

    return () => {
      window.removeEventListener('config-updated', handleConfigChange);
      window.removeEventListener('index-completed', handleConfigChange);
      window.removeEventListener('dashboard-refresh', handleConfigChange);
    };
  }, [checkStatus]);

  return {
    status,
    loading,
    error,
    refresh: checkStatus,
  };
}

