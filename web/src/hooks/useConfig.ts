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
  const stageSection = useConfigStore((s) => s.stageSection);
  const stageSectionReplace = useConfigStore((s) => s.stageSectionReplace);
  const flushPendingPatches = useConfigStore((s) => s.flushPendingPatches);
  const resetConfig = useConfigStore((s) => s.resetConfig);

  // Load config on mount (once)
  useEffect(() => {
    // Avoid retry-loops: if a load failed, surface the error and wait for user action/corpus-change.
    if (!config && !loading && !error) {
      loadConfig();
    }
  }, [config, error, loading, loadConfig]);

  // Reload config when active corpus changes. loadConfig replaces both config and persisted with
  // the new corpus's server state, so any unapplied staged edits for the previous corpus are
  // dropped (the staged-form contract: apply before you switch corpus).
  useEffect(() => {
    const handler = () => {
      loadConfig();
    };
    window.addEventListener('tribrid-corpus-changed', handler as EventListener);
    return () => {
      window.removeEventListener('tribrid-corpus-changed', handler as EventListener);
    };
  }, [loadConfig]);

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
    stageSection,
    stageSectionReplace,
    flushPendingPatches,
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
  const { config, loading, error, stageSection } = useConfig();

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
        // Whole-section replacement: stage the object; the deep merge mirrors the server so a
        // partial object keeps its siblings, matching the prior PATCH semantics.
        stageSection(section as keyof TriBridConfig, newValue as any);
        return;
      }
      // Build nested patch object (shallow at top-level section)
      let patch: any = newValue as any;
      for (let i = rest.length - 1; i >= 0; i -= 1) {
        patch = { [rest[i]]: patch };
      }
      // Stage the edit locally. Nothing is written until the operator clicks "Apply"; the field
      // shows as dirty in the meantime (M-08: no more silent immediate PATCH on every keystroke,
      // toggle, or strategy-card click).
      stageSection(section as keyof TriBridConfig, patch);
    },
    [stageSection, path]
  );

  return [value, setValue, { loading, error }];
}

export default useConfig;
