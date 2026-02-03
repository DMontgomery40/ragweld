import { useCallback } from 'react';
import { useConfigStore } from '@/stores/useConfigStore';
import { useRepoStore } from '@/stores/useRepoStore';

/**
 * Hook for accessing global application state via Zustand stores
 * NO LONGER bridges to window.CoreUtils.state - uses Zustand directly
 *
 * @deprecated Use individual Zustand stores directly (useConfigStore, useRepoStore, etc.)
 * This hook exists only for backwards compatibility during migration
 */
export function useGlobalState() {
  const config = useConfigStore((s) => s.config);
  const repos = useRepoStore((s) => s.repos);
  const activeRepo = useRepoStore((s) => s.activeRepo);

  // Derive state from Zustand stores
  const state = {
    config: config || null,
    models: null,
    profiles: [],
    defaultProfile: null,
    hwScan: null,
    keywords: null,
    commitMeta: null,
    repos,
    currentRepo: activeRepo
  };

  const updateState = useCallback((updates: Record<string, unknown>) => {
    // Note: Most updates should go through individual Zustand stores
    // This is a fallback for legacy code paths
    console.warn('[useGlobalState] updateState called - use individual Zustand stores instead');
    try {
      window.dispatchEvent(new CustomEvent('tribrid-state-update', { detail: updates }));
    } catch {}
  }, []);

  const getState = useCallback((key: string) => {
    return state[key as keyof typeof state];
  }, [state]);

  return { state, updateState, getState };
}
