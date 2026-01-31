import { useCallback, useEffect, useMemo } from 'react';
import { useConfigStore } from '@/stores';
import type { TriBridConfig } from '@/types/generated';

/**
 * ---agentspec
 * what: |
 *   React hook that provides centralized access to application configuration state and management functions.
 *   Takes no parameters; returns an object containing: config (TriBridConfig), loading, error, saving, and functions to load/save/patch/reset config.
 *   Manages async operations for loading and saving configuration, maintaining loading/saving state flags and error state throughout the lifecycle.
 *   Handles edge cases: returns stale config if load fails, prevents concurrent saves, clears errors on successful operations.
 *
 * why: |
 *   Centralizes configuration state management in a custom hook to avoid prop drilling and provide consistent access across components.
 *   Separates concerns: hook manages async state (loading, saving, error) while components handle UI rendering, making testing and reuse easier.
 *   Exposes both read operations (loadConfig) and write operations (saveConfig, patchSection, resetConfig) through a single interface.
 *
 * guardrails:
 *   - DO NOT mutate config objects directly; always use patchSection/saveConfig
 * ---/agentspec
 */
export function useConfig() {
  const { config, loading, error, saving, loadConfig, saveConfig, patchSection, resetConfig } =
    useConfigStore();

  // Load config on mount (once)
  useEffect(() => {
    if (!config && !loading) {
      loadConfig();
    }
  }, [config, loading, loadConfig]);

  // Reload config when active corpus changes
  useEffect(() => {
    const handler = () => {
      loadConfig();
    };
    // New event name (preferred) + legacy event name for migration.
    window.addEventListener('tribrid-corpus-changed', handler as EventListener);
    window.addEventListener('agro-repo-changed', handler as EventListener);
    return () => {
      window.removeEventListener('tribrid-corpus-changed', handler as EventListener);
      window.removeEventListener('agro-repo-changed', handler as EventListener);
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
    patchSection,
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
  const { config, loading, error, patchSection } = useConfig();

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
        void patchSection(section as keyof TriBridConfig, newValue as any);
        return;
      }
      // Build nested patch object (shallow at top-level section)
      let patch: any = newValue as any;
      for (let i = rest.length - 1; i >= 0; i -= 1) {
        patch = { [rest[i]]: patch };
      }
      void patchSection(section as keyof TriBridConfig, patch);
    },
    [patchSection, path]
  );

  return [value, setValue, { loading, error }];
}

export default useConfig;
