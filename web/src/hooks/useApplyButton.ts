import { useState, useEffect, useCallback, useMemo } from 'react';
import { useConfigStore } from '@/stores';
import { confirmDialog } from '@/components/ui/confirmDialog';
import { changedConfigPaths, indexInvalidatingChanges } from '@/utils/configDiff';
import type { IndexContractConflict } from '@/utils/saveErrorMessage';

/**
 * Manages the global "Apply N changes" button.
 *
 * Dirty truth comes from the config store: `config` is the working copy (staged edits),
 * `persisted` is the last server-acknowledged snapshot. Loads and corpus switches replace
 * both, so navigation never reads as an operator edit. Nothing is written to the server until
 * Apply, which PUTs the whole config through the one path that enforces the index-contract
 * lock and restores redacted secrets (server/api/config.py `update_config`).
 */
export function useApplyButton() {
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState(false);

  const [storeState, setStoreState] = useState(() => {
    const s = useConfigStore.getState();
    return {
      config: s.config,
      persisted: s.persisted,
      saving: s.saving,
      error: s.error,
      saveConflict: s.saveConflict,
    };
  });

  useEffect(() => {
    const unsubscribe = useConfigStore.subscribe((state) => {
      setStoreState({
        config: state.config,
        persisted: state.persisted,
        saving: state.saving,
        error: state.error,
        saveConflict: state.saveConflict,
      });
    });
    return () => {
      unsubscribe();
    };
  }, []);

  const changedPaths = useMemo(
    () => changedConfigPaths(storeState.persisted, storeState.config),
    [storeState.persisted, storeState.config]
  );
  const dirtyCount = changedPaths.length;
  const isDirty = dirtyCount > 0;

  const invalidatingSections = useMemo(
    () => indexInvalidatingChanges(storeState.persisted, storeState.config),
    [storeState.persisted, storeState.config]
  );

  // A staged edit clears the "Saved" acknowledgement: it is only true immediately after a
  // successful Apply, so the footer confirms the write happened (C-12) and then goes quiet.
  useEffect(() => {
    if (isDirty && justSaved) setJustSaved(false);
  }, [isDirty, justSaved]);

  const handleApply = useCallback(async () => {
    // When staged edits touch chunking/embedding/tokenization, applying them makes the stored
    // index no longer match the config. Warn with the exact sections and count before the write
    // (M-08); the server still enforces its own 409 contract lock over a populated index.
    const sectionsNow = indexInvalidatingChanges(
      useConfigStore.getState().persisted,
      useConfigStore.getState().config
    );
    const countNow = changedConfigPaths(
      useConfigStore.getState().persisted,
      useConfigStore.getState().config
    ).length;
    if (sectionsNow.length > 0) {
      const list = sectionsNow.join(', ');
      const proceed = await confirmDialog({
        title: 'Apply changes that affect the index',
        message:
          `${countNow} change${countNow === 1 ? '' : 's'} staged. ` +
          `${sectionsNow.length === 1 ? 'One section' : 'Some sections'} you changed (${list}) ` +
          `determine how the current index was built, so applying will make the stored index no ` +
          `longer match the config — you may need to re-index this corpus. Apply anyway?`,
        confirmLabel: `Apply ${countNow} change${countNow === 1 ? '' : 's'}`,
        cancelLabel: 'Keep editing',
      });
      if (!proceed) return undefined;
    }

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
      // A transient acknowledgement: show "Saved", then go quiet. The timeout also stops the
      // ack from surviving a corpus switch (which replaces config/persisted, leaving isDirty
      // false) and reading "Saved" on a corpus that was never saved here.
      setJustSaved(true);
      window.setTimeout(() => setJustSaved(false), 2500);

      if (w.showStatus) {
        w.showStatus('Settings saved successfully', 'success');
      }

      return savedConfig;
    } catch (err) {
      // The store already shaped a server-authored message (never the raw axios string); prefer
      // it over the thrown Error so the footer and the toast read identically (M-20).
      const storeError = useConfigStore.getState().error;
      const message = storeError || (err instanceof Error ? err.message : 'Unknown error');
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

  // 409 index-contract conflict: discard the local edits and pull the server's current config so
  // the operator can re-decide against the truth, rather than staring at a write the server keeps
  // refusing (M-20).
  const reloadLatest = useCallback(async () => {
    setSaveError(null);
    await useConfigStore.getState().loadConfig();
  }, []);

  const saveConflict: IndexContractConflict | null = storeState.saveConflict;

  return {
    handleApply,
    reloadLatest,
    isDirty,
    dirtyCount,
    invalidatingSections,
    justSaved,
    saveConflict,
    isSaving: isSaving || storeState.saving,
    saveError: saveError || (storeState.error ? String(storeState.error) : null),
  };
}
