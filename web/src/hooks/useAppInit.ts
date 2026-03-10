import { useState, useEffect } from 'react';
import { useRepoStore } from '@/stores/useRepoStore';
import { useConfigStore } from '@/stores/useConfigStore';
import { modelsApi } from '@/api';
import { UiHelpers } from '@/utils/uiHelpers';

/**
 * Hook for app initialization
 * Handles loading config and repos via Zustand stores
 * NO LONGER depends on window.CoreUtils - uses typed API client
 */
export function useAppInit() {
  const [isInitialized, setIsInitialized] = useState(false);
  const [initError, setInitError] = useState<string | null>(null);
  const { loadRepos } = useRepoStore();
  const loadConfig = useConfigStore((s) => s.loadConfig);

  useEffect(() => {
    const init = async () => {
      try {
        console.log('[useAppInit] Starting app initialization (no CoreUtils dependency)...');

        // Load repos first so corpus scope is canonicalized before config loads.
        // (Prevents config load from using stale/invalid localStorage corpus_id.)
        await loadRepos().catch((err: unknown) => console.warn('Failed to load repos:', err));

        // Load config + models in parallel after corpora are available
        await Promise.all([
          loadConfig().catch((err: unknown) => console.warn('Failed to load config:', err)),

          // Best-effort: warm the models list (cost estimation, model pickers, etc.)
          modelsApi.listAll()
            .then(() => {})
            .catch((err: unknown) => console.warn('Failed to load models:', err)),
        ]);

        UiHelpers.wireDayConverters();

        console.log('[useAppInit] Initialization complete');
        setIsInitialized(true);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Unknown error';
        console.error('[useAppInit] Initialization failed:', err);
        setInitError(message);
        // Still set initialized to true to prevent blocking the UI
        setIsInitialized(true);
      }
    };

    // Wait for React to be ready
    if (document.readyState === 'loading') {
      window.addEventListener('DOMContentLoaded', init);
      return () => window.removeEventListener('DOMContentLoaded', init);
    } else {
      // Give a moment for initial render
      setTimeout(init, 50);
    }
  }, [loadConfig, loadRepos]);

  return { isInitialized, initError };
}
