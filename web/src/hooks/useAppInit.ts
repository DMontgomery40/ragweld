import { useState, useEffect } from 'react';
import { useRepoStore } from '@/stores/useRepoStore';
import { useConfigStore } from '@/stores/useConfigStore';
import { useHealthStore } from '@/stores/useHealthStore';
import { apiUrl } from '@/api/client';

/**
 * Hook for app initialization
 * Handles loading config, profiles, and repos via Zustand stores
 * NO LONGER depends on window.CoreUtils - uses typed API client
 */
export function useAppInit() {
  const [isInitialized, setIsInitialized] = useState(false);
  const [initError, setInitError] = useState<string | null>(null);
  const { loadRepos } = useRepoStore();
  const { loadConfig } = useConfigStore();
  const { checkHealth } = useHealthStore();

  useEffect(() => {
    const init = async () => {
      try {
        console.log('[useAppInit] Starting app initialization (no CoreUtils dependency)...');

        // Load initial data in parallel using Zustand stores and typed API
        await Promise.all([
          // Load config via Zustand store
          loadConfig()
            .catch((err: unknown) => console.warn('Failed to load config:', err)),

          // Load repos via Zustand store
          loadRepos()
            .catch((err: unknown) => console.warn('Failed to load repos:', err)),

          // Load models.json for cost estimation (still needed for legacy modules during transition)
          fetch(apiUrl('/models'))
            .then(r => r.json())
            .then(models => {
              // Store in window for legacy modules that still need it
              if ((window as any).CoreUtils?.state) {
                (window as any).CoreUtils.state.models = models;
              }
            })
            .catch((err: unknown) => console.warn('Failed to load models:', err)),

          // Load profiles (still needed for legacy modules during transition)
          fetch(apiUrl('/profiles'))
            .then(r => r.json())
            .then(data => {
              // Store in window for legacy modules that still need it
              if ((window as any).CoreUtils?.state) {
                (window as any).CoreUtils.state.profiles = data.profiles || [];
                (window as any).CoreUtils.state.defaultProfile = data.default || null;
              }
            })
            .catch((err: unknown) => console.warn('Failed to load profiles:', err)),

          // Load commit metadata if available (legacy module)
          (window as any).GitCommitMeta?.loadCommitMeta?.()
            .catch((err: Error) => console.warn('Failed to load commit meta:', err))
        ]);

        // Trigger initial health check via Zustand store
        await checkHealth().catch((err: Error) =>
          console.warn('Initial health check failed:', err)
        );

        // Legacy module initializations (temporary, will be removed as modules migrate)
        if ((window as any).Autotune?.refreshAutotune) {
          await (window as any).Autotune.refreshAutotune().catch((err: Error) =>
            console.warn('Failed to refresh autotune:', err)
          );
        }

        if ((window as any).UiHelpers?.wireDayConverters) {
          (window as any).UiHelpers.wireDayConverters();
        }

        if ((window as any).GitHooks?.refreshHooksStatus) {
          await (window as any).GitHooks.refreshHooksStatus().catch((err: Error) =>
            console.warn('Failed to refresh git hooks:', err)
          );
        }

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
  }, [loadConfig, loadRepos, checkHealth]);

  return { isInitialized, initError };
}
