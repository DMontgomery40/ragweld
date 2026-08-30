import { useState, useEffect } from 'react';
import { useRepoStore } from '@/stores/useRepoStore';
import { useConfigStore } from '@/stores/useConfigStore';
import { initFaroFromConfig } from '@/observability/faro';
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

        // Load config once the corpora are available. There is deliberately no models
        // warm-up here: `useModels` keeps its own per-corpus cache and shares its
        // in-flight request, and a bare `modelsApi.listAll()` populates neither -- it was
        // one more `/api/models` round trip per load that no picker could ever read
        // (M-129).
        await loadConfig().catch((err: unknown) => console.warn('Failed to load config:', err));

        // Frontend RUM: ships errors/web-vitals to the Alloy Faro collector
        // when the loaded config carries a collector endpoint. If the config
        // load failed transiently, retry when the store recovers instead of
        // silently losing RUM for the whole session.
        if (!initFaroFromConfig(useConfigStore.getState().config?.tracing?.faro_base_url)) {
          const unsubscribe = useConfigStore.subscribe((state) => {
            if (!state.config) return;
            initFaroFromConfig(state.config.tracing?.faro_base_url);
            // A loaded config settles the decision either way (an empty
            // collector URL means RUM is intentionally off).
            unsubscribe();
          });
        }

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
