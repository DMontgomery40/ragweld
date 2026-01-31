import { useState, useEffect, useCallback, useRef } from 'react';
import { useConfigStore } from '@/stores';

/**
 * Hook for managing the sidepanel Apply button
 * ADA CRITICAL: This button saves all settings changes
 * Must be fully functional for accessibility compliance
 */
/**
 * ---agentspec
 * what: |
 *   Custom React hook that manages the "Apply" button state for configuration changes.
 *   Tracks dirty state (whether config differs from baseline), saving state, and save errors using local useState and Zustand store snapshots.
 *   Returns state variables: isDirty (boolean), isSaving (boolean), saveError (string | null), and baselineRef (MutableRefObject).
 *   Initializes baselineRef to null and captures initial Zustand store state (config and saving flag) into local state snapshots.
 *   Edge case: Does not subscribe to Zustand store updates; snapshots are captured only at mount time, so subsequent store changes are not reflected.
 *
 * why: |
 *   Separates UI state management (isDirty, isSaving, saveError) from Zustand global state to avoid adding extra hooks to the App component.
 *   Uses baselineRef to store the original config value for dirty-state comparison without triggering re-renders.
 *   Captures store state at initialization to provide a consistent baseline, avoiding the need for useShallow or manual subscription logic.
 *
 * guardrails:
 *   - DO NOT rely on this hook to reflect real-time Zustand store updates; snapshots are frozen at mount time and will not update if the store changes
 *   - ALWAYS initialize baselineRef.current with the actual config value before comparing isDirty, or dirty detection will fail
 *   - NOTE: This hook does not include useEffect subscriptions to Zustand; if store state must be reactive, consider adding useShallow or a custom subscription
 *   - ASK USER: Confirm whether configSnapshot and storeSaving should auto-update when the Zustand store changes, or if frozen snapshots at mount are intentional
 * ---/agentspec
 */
export function useApplyButton() {
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const baselineRef = useRef<string | null>(null);

  // Local snapshots of Zustand store state (avoids adding an extra hook to App)
  const [configSnapshot, setConfigSnapshot] = useState(useConfigStore.getState().config);
  const [storeSaving, setStoreSaving] = useState(useConfigStore.getState().saving);
  const [storeError, setStoreError] = useState<string | null>(
    useConfigStore.getState().error ? String(useConfigStore.getState().error) : null
  );

  // Track form changes to enable/disable Apply button
  useEffect(() => {
    /**
     * ---agentspec
     * what: |
     *   Handles form state changes by setting a dirty flag and clearing any previous save errors.
     *   Takes no parameters; triggered by 'input' and 'change' events on the document.
     *   Sets isDirty to true (indicating unsaved changes) and clears setSaveError to null.
     *   Attaches global event listeners to document that fire on any input or change event anywhere in the DOM.
     *   Edge case: Listeners are never removed, causing memory leaks if component unmounts; listeners will fire even after component is destroyed.
     *
     * why: |
     *   Tracks whether the form has unsaved changes and clears stale error messages when the user modifies any field.
     *   Global document listeners were chosen for simplicity to catch all form changes without wiring individual field handlers.
     *   This approach avoids prop drilling and per-field onChange handlers, but sacrifices cleanup and specificity.
     *
     * guardrails:
     *   - DO NOT attach event listeners without cleanup; these listeners will persist after component unmount and cause memory leaks
     *   - ALWAYS remove event listeners in a useEffect cleanup function to prevent duplicate listeners and memory accumulation
     *   - NOTE: Global document listeners fire on ANY input/change event, including unrelated form fields or third-party components
     *   - ASK USER: Confirm whether listeners should be scoped to a specific form element (e.g., formRef) instead of the entire document before refactoring
     * ---/agentspec
     */
    const handleFormChange = () => {
      setIsDirty(true);
      setSaveError(null);
    };

    // Listen for input and change events on the document
    document.addEventListener('input', handleFormChange);
    document.addEventListener('change', handleFormChange);

    // Listen for custom dirty events from modules
    window.addEventListener('agro-form-dirty', handleFormChange);

    return () => {
      document.removeEventListener('input', handleFormChange);
      document.removeEventListener('change', handleFormChange);
      window.removeEventListener('agro-form-dirty', handleFormChange);
    };
  }, []);

  // Subscribe to Zustand store for config/saving/error without adding extra hooks
  useEffect(() => {
    const unsubscribe = useConfigStore.subscribe(state => {
      const cfg = state.config;
      setConfigSnapshot(cfg);
      // set baseline if first time
      if (cfg && !baselineRef.current) {
        baselineRef.current = JSON.stringify(cfg);
      }
      setStoreSaving(state.saving);
      setStoreError(state.error ? String(state.error) : null);
    });
    return () => {
      unsubscribe();
    };
  }, []);

  // Keep baseline snapshot for dirty comparison
  useEffect(() => {
    if (configSnapshot && !baselineRef.current) {
      baselineRef.current = JSON.stringify(configSnapshot);
    }
  }, [configSnapshot]);

  // Mark dirty when config diverges from baseline
  useEffect(() => {
    if (!configSnapshot || !baselineRef.current) return;
    const snapshot = JSON.stringify(configSnapshot);
    setIsDirty(snapshot !== baselineRef.current);
  }, [configSnapshot]);

  // Ensure config is loaded on mount
  useEffect(() => {
    if (!configSnapshot && !storeSaving) {
      useConfigStore.getState().loadConfig().catch(() => {});
    }
  }, [configSnapshot, storeSaving]);

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

      // Save via Pydantic/Zustand pipeline (TriBridConfig is the law)
      await useConfigStore.getState().saveConfig(currentConfig);

      // Refresh snapshot after save
      const savedConfig = useConfigStore.getState().config || currentConfig;
      baselineRef.current = JSON.stringify(savedConfig);

      setIsDirty(false);
      console.log('[useApplyButton] Configuration saved successfully');

      // Show success status if available
      if (w.showStatus) {
        w.showStatus('Settings saved successfully', 'success');
      }

      // Emit success event for any listeners
      window.dispatchEvent(new CustomEvent('agro-config-saved', { detail: savedConfig }));

      return savedConfig;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      console.error('[useApplyButton] Failed to save configuration:', err);
      setSaveError(message);

      // Show error status if available
      const w = window as any;
      if (w.showStatus) {
        w.showStatus(`Failed to save: ${message}`, 'error');
      } else {
        alert(`Failed to save settings: ${message}`);
      }

      throw err;
    } finally {
      setIsSaving(false);
    }
  }, []);

  // Provide a way to manually mark as dirty (for programmatic changes)
  const markDirty = useCallback(() => {
    setIsDirty(true);
  }, []);

  // Provide a way to manually mark as clean (after save)
  const markClean = useCallback(() => {
    setIsDirty(false);
    setSaveError(null);
  }, []);

  return {
    handleApply,
    isDirty,
    isSaving: isSaving || storeSaving,
    saveError: saveError || (storeError ? String(storeError) : null),
    markDirty,
    markClean
  };
}
