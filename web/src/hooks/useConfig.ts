import { useCallback, useEffect, useMemo } from 'react';
import { useConfigStore } from '@/stores';
import type { TriBridConfig } from '@/types/generated';


export function useConfig() {
  const config = useConfigStore((s) => s.config);
  const loading = useConfigStore((s) => s.loading);
  const error = useConfigStore((s) => s.error);
  const saving = useConfigStore((s) => s.saving);
  const loadConfig = useConfigStore((s) => s.loadConfig);
  const saveConfig = useConfigStore((s) => s.saveConfig);
  const patchSection = useConfigStore((s) => s.patchSection);
  const patchSectionDebounced = useConfigStore((s) => s.patchSectionDebounced);
  const cancelPendingPatches = useConfigStore((s) => s.cancelPendingPatches);
  const resetConfig = useConfigStore((s) => s.resetConfig);

  // Load config on mount (once)
  useEffect(() => {
    // Avoid retry-loops: if a load failed, surface the error and wait for user action/corpus-change.
    if (!config && !loading && !error) {
      loadConfig();
    }
  }, [config, error, loading, loadConfig]);

  // Reload config when active corpus changes
  useEffect(() => {
    const handler = () => {
      // When corpus changes, cancel patches (they're for the old corpus) and load new config.
      // Note: loadConfig() will flush patches, but we cancel here because patches are corpus-scoped.
      cancelPendingPatches();
      loadConfig();
    };
    // New event name (preferred).
    window.addEventListener('tribrid-corpus-changed', handler as EventListener);
    return () => {
      window.removeEventListener('tribrid-corpus-changed', handler as EventListener);
    };
  }, [cancelPendingPatches, loadConfig]);

  const reload = useCallback(async () => {
    await loadConfig();
  }, [loadConfig]);

  const clearError = useCallback(() => {
    // Store error is derived from last action; clearing is just resetting it locally.
    // (We keep it minimal: reload will also clear it.)
  }, []);

  return {
    // State
    config,
    loading,
    error,
    saving,

    // Actions
    loadConfig,
    saveConfig,
    patchSection,
    patchSectionDebounced,
    resetConfig,
    reload,
    clearError,
  };
}

/**
 * Hook for a single config field addressed by dot-path.
 *
 * USAGE:
 *   const [finalK, setFinalK] = useConfigField('retrieval.final_k', 10);
 */
export function useConfigField<T>(
  path: string,
  defaultValue: T
): [T, (value: T) => void, { loading: boolean; error: string | null }] {
  const { config, loading, error, patchSectionDebounced, patchSection } = useConfig();

  const value = useMemo(() => {
    if (!config) return defaultValue;
    const parts = path.split('.').filter(Boolean);
    let cur: any = config as any;
    for (const p of parts) {
      if (cur == null) return defaultValue;
      cur = cur[p];
    }
    return (cur === undefined ? defaultValue : (cur as T));
  }, [config, defaultValue, path]);

  const setValue = useCallback(
    (newValue: T) => {
      const [section, ...rest] = path.split('.').filter(Boolean);
      if (!section) return;
      if (rest.length === 0) {
        // Replace entire section
        // This is rare; keep it immediate.
        void patchSection(section as keyof TriBridConfig, newValue as any);
        return;
      }
      // Build nested patch object (shallow at top-level section)
      let patch: any = newValue as any;
      for (let i = rest.length - 1; i >= 0; i -= 1) {
        patch = { [rest[i]]: patch };
      }
      // Debounced persistence for high-frequency inputs.
      patchSectionDebounced(section as keyof TriBridConfig, patch);
    },
    [patchSection, patchSectionDebounced, path]
  );

  return [value, setValue, { loading, error }];
}

export default useConfig;
