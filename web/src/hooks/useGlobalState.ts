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
  const { config, keywordsCatalog } = useConfigStore();
  const { repos, currentRepo } = useRepoStore();

  // Derive state from Zustand stores
  const state = {
    config: config?.env || null,
    models: null, // models are loaded via useAppInit into legacy window.CoreUtils.state during transition
    profiles: [], // Profiles managed by legacy modules during transition
    defaultProfile: null,
    hwScan: null,
    keywords: keywordsCatalog,
    commitMeta: null,
    repos,
    currentRepo
  };

  const updateState = useCallback((updates: Record<string, unknown>) => {
    // During transition, also update legacy window.CoreUtils.state if it exists
    const w = window as any;
    if (w.CoreUtils?.state) {
      Object.assign(w.CoreUtils.state, updates);
      window.dispatchEvent(new CustomEvent('agro-state-update', { detail: updates }));
    }

    // Note: Most updates should go through individual Zustand stores
    // This is a fallback for legacy code paths
    console.warn('[useGlobalState] updateState called - use individual Zustand stores instead');
  }, []);

  const getState = useCallback((key: string) => {
    return state[key as keyof typeof state];
  }, [state]);

  return { state, updateState, getState };
}
