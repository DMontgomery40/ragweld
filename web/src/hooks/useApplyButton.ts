import { useState, useEffect, useCallback } from 'react';
import { useConfigStore } from '@/stores';

/**
 * Manages the global "Apply All Changes" button.
 *
 * Dirty truth comes from the config store: `config` is the working copy
 * (including optimistic debounced edits), `persisted` is the last
 * server-acknowledged snapshot. Loads and corpus switches replace both, so
 * navigation never reads as an operator edit.
 */
export function useApplyButton() {
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [storeState, setStoreState] = useState(() => {
    const s = useConfigStore.getState();
    return { config: s.config, persisted: s.persisted, saving: s.saving, error: s.error };
  });

  useEffect(() => {
    const unsubscribe = useConfigStore.subscribe((state) => {
      setStoreState({
        config: state.config,
        persisted: state.persisted,
        saving: state.saving,
        error: state.error,
      });
    });
    return () => {
      unsubscribe();
    };
  }, []);

  const isDirty =
    !!storeState.config &&
    !!storeState.persisted &&
    JSON.stringify(storeState.config) !== JSON.stringify(storeState.persisted);

  // Ensure config is loaded on mount
  useEffect(() => {
    if (!storeState.config && !storeState.saving) {
      useConfigStore.getState().loadConfig().catch(() => {});
    }
  }, [storeState.config, storeState.saving]);

  const handleApply = useCallback(async () => {
    setIsSaving(true);
    setSaveError(null);

    try {
      const w = window as any;

      // Ensure we have the latest Pydantic-backed config
      if (!useConfigStore.getState().config) {
        await useConfigStore.getState().loadConfig();
      }
      const currentConfig = useConfigStore.getState().config;
      if (!currentConfig) {
        throw new Error('Configuration not loaded');
      }

      // Save via Pydantic/Zustand pipeline
      await useConfigStore.getState().saveConfig(currentConfig);
      const postSaveError = useConfigStore.getState().error;
      if (postSaveError) {
        throw new Error(String(postSaveError));
      }

      const savedConfig = useConfigStore.getState().config || currentConfig;
      console.log('[useApplyButton] Configuration saved successfully');

      if (w.showStatus) {
        w.showStatus('Settings saved successfully', 'success');
      }

      return savedConfig;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      console.error('[useApplyButton] Failed to save configuration:', err);
      setSaveError(message);

      const w = window as any;
      if (w.showStatus) {
        w.showStatus(`Failed to save: ${message}`, 'error');
      }

      throw err;
    } finally {
      setIsSaving(false);
    }
  }, []);

  return {
    handleApply,
    isDirty,
    isSaving: isSaving || storeState.saving,
    saveError: saveError || (storeState.error ? String(storeState.error) : null),
  };
}
