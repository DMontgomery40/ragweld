import { create } from 'zustand';
import { configApi } from '@/api/config';
import type { TriBridConfig } from '@/types/generated';
import { extractPatchErrorDetail, parseConfigPatchErrors } from '@/utils/configPatchErrors';
import { formatSaveError, type IndexContractConflict } from '@/utils/saveErrorMessage';

interface ConfigStore {
  config: TriBridConfig | null;
  /** Last server-acknowledged config. `config !== persisted` means unsaved local edits. */
  persisted: TriBridConfig | null;
  loading: boolean;
  error: string | null;
  /**
   * Field-level detail from the last rejected config PATCH, keyed by full dotted TriBridConfig
   * path (e.g. "enrichment.max_chunk_summaries") -- `NumberField`'s `configPath` prop reads
   * this directly. Cleared for a section's paths as soon as that section's next PATCH lands,
   * successful or not (a fresh attempt replaces stale errors rather than accumulating them).
   */
  fieldErrors: Record<string, string>;
  /**
   * Set when a save was refused (HTTP 409) because the change would invalidate the stored
   * index contract (`_enforce_index_contract_lock`, server/api/config.py). The footer reads
   * this to offer a reload-and-re-index affordance instead of a bare error string (M-20).
   * Cleared on any successful load or save.
   */
  saveConflict: IndexContractConflict | null;
  saving: boolean;
  // Actions
  loadConfig: () => Promise<void>;
  saveConfig: (config: TriBridConfig) => Promise<void>;
  patchSection: (section: keyof TriBridConfig, updates: Record<string, unknown>) => Promise<void>;
  /**
   * Stage a field edit LOCALLY, with no network write. The working `config` diverges from
   * `persisted` (the footer shows the dirty count) and nothing reaches the server until "Apply"
   * PUTs the whole document. This is the single commit model for `useConfigField`: selecting a
   * chunking strategy, toggling a boolean, dragging a slider all stage, so an edit is never a
   * silent immediate PATCH the operator cannot see, undo, or gate (M-08). The merge mirrors the
   * server's `_deep_merge_dicts` so a nested edit keeps its siblings.
   */
  stageSection: (section: keyof TriBridConfig, updates: Record<string, unknown>) => void;
  /**
   * Debounced patch for high-frequency UI changes (typing, sliders).
   * Applies an optimistic local update immediately, then persists via PATCH after ~300ms.
   */
  patchSectionDebounced: (section: keyof TriBridConfig, updates: Record<string, unknown>) => void;
  /** Cancel any pending debounced patch timers (e.g. when switching corpora). */
  cancelPendingPatches: (corpusId?: string) => void;
  /** Immediately flush all pending debounced patches for the active corpus. */
  flushPendingPatches: () => Promise<void>;
  resetConfig: () => Promise<void>;

  reset: () => void;
}

type PatchObject = Record<string, unknown>;

const isPatchObject = (value: unknown): value is PatchObject =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * Merge a PATCH payload into a config section exactly the way the server does
 * (`_deep_merge_dicts`, server/api/config.py): recurse into nested objects, replace
 * arrays and scalars wholesale.
 *
 * A shallow spread is wrong for any nested config group (`indexing.figures`,
 * `chat.recall`, `chat.multimodal`): `useConfigField('indexing.figures.enabled')`
 * emits `{ figures: { enabled: true } }`, and spreading that over the section drops
 * every sibling key of `figures` from the optimistic copy and from the aggregated
 * pending patch — so a second nested edit inside the debounce window would never
 * send the first one, and "Apply All Changes" would PUT a collapsed group.
 */
const deepMergePatch = (base: PatchObject, updates: PatchObject): PatchObject => {
  const merged: PatchObject = { ...base };
  for (const key of Object.keys(updates)) {
    if (key === '__proto__') continue;
    const current = merged[key];
    const next = updates[key];
    merged[key] = isPatchObject(current) && isPatchObject(next) ? deepMergePatch(current, next) : next;
  }
  return merged;
};

/**
 * Undo the optimistic edits a rejected PATCH applied, restoring only the leaf paths it
 * actually set -- never the whole section.
 *
 * The server validates a section's merged body atomically (`TriBridConfig.model_validate`),
 * so a 422 means nothing in this PATCH was saved (C-01/X-11: the field must not keep a value
 * the server refused, or "Apply" re-sends it forever). But `flushSection` clears the pending
 * entry before the `await`: a fresh `patchSectionDebounced` call for the same path during that
 * in-flight window applies its own optimistic update AND queues its own pending patch. Blindly
 * restoring the whole section here would erase that newer edit's on-screen value while its
 * patch still lands later, and the field would snap back only for the wrong value to arrive
 * moments after. A leaf is reverted only if the live config still holds exactly what this
 * rejected patch wrote to it -- evidence nothing newer has touched it since.
 */
const revertPaths = (curNode: PatchObject, persistedNode: PatchObject, updateNode: PatchObject): PatchObject => {
  let changed = false;
  const next: PatchObject = { ...curNode };
  for (const key of Object.keys(updateNode)) {
    const updateValue = updateNode[key];
    const curValue = curNode[key];
    if (isPatchObject(updateValue) && isPatchObject(curValue)) {
      const persistedChild = isPatchObject(persistedNode[key]) ? (persistedNode[key] as PatchObject) : {};
      const revertedChild = revertPaths(curValue, persistedChild, updateValue);
      if (revertedChild !== curValue) {
        next[key] = revertedChild;
        changed = true;
      }
      continue;
    }
    if (Object.is(curValue, updateValue)) {
      next[key] = persistedNode[key];
      changed = true;
    }
  }
  return changed ? next : curNode;
};

/** Field errors under `sectionKey` (top-level equal, or dotted-prefixed) removed. */
const withoutSectionFieldErrors = (
  fieldErrors: Record<string, string>,
  sectionKey: string
): Record<string, string> => {
  const next = { ...fieldErrors };
  let changed = false;
  for (const key of Object.keys(next)) {
    if (key === sectionKey || key.startsWith(`${sectionKey}.`)) {
      delete next[key];
      changed = true;
    }
  }
  return changed ? next : fieldErrors;
};

/** Field errors under `sectionKey`, replaced with what this PATCH failure parsed out of `detail`. */
const withParsedFieldErrors = (
  fieldErrors: Record<string, string>,
  sectionKey: string,
  detail: unknown
): Record<string, string> => {
  const cleared = withoutSectionFieldErrors(fieldErrors, sectionKey);
  const parsed = parseConfigPatchErrors(detail);
  if (parsed.length === 0) return cleared;
  const next = { ...cleared };
  for (const { path, message } of parsed) next[path] = message;
  return next;
};

export const useConfigStore = create<ConfigStore>((set) => {
  // Debounce + aggregation per top-level section AND per corpus.
  // This prevents corpus-switch races from canceling/flush-ing the wrong corpus' pending writes.
  const pendingByCorpus: Record<string, Record<string, Record<string, unknown>>> = {};
  const timersByCorpus: Record<string, Record<string, ReturnType<typeof setTimeout>>> = {};
  const DEBOUNCE_MS = 300;

  // One GET /api/config per corpus in flight at a time. Several hooks call `loadConfig`
  // on the same mount (app init, `useConfig`'s mount effect, the corpus-changed
  // listener) and each one used to issue its own request: a single dashboard load spent
  // four round trips fetching the identical document (M-129).
  //
  // This shares the request, it does not cache the answer: the entry is dropped the
  // moment the load settles, so the next caller always goes to the server. A caller
  // that arrives while patches are still queued for this corpus never joins -- the
  // shared load already ran its flush, and joining it would drop the newer edits.
  const inFlightLoadByCorpus: Record<string, Promise<void>> = {};

  const getActiveCorpusId = (): string => {
    try {
      const u = new URL(window.location.href);
      return (
        u.searchParams.get('corpus') ||
        u.searchParams.get('repo') ||
        localStorage.getItem('tribrid_active_corpus') ||
        localStorage.getItem('tribrid_active_repo') ||
        ''
      );
    } catch {
      return (
        localStorage.getItem('tribrid_active_corpus') ||
        localStorage.getItem('tribrid_active_repo') ||
        ''
      );
    }
  };

  const cancelPendingPatches = (corpusId?: string) => {
    const corpusKeys = corpusId === undefined ? Object.keys(timersByCorpus) : [String(corpusId || '')];
    for (const corpusKey of corpusKeys) {
      const timers = timersByCorpus[corpusKey] || {};
      for (const sectionKey of Object.keys(timers)) {
        clearTimeout(timers[sectionKey]);
        delete timers[sectionKey];
      }
      delete timersByCorpus[corpusKey];
      delete pendingByCorpus[corpusKey];
    }
  };

  const flushSection = async (corpusKey: string, sectionKey: string) => {
    const updates = pendingByCorpus[corpusKey]?.[sectionKey];
    if (!updates || Object.keys(updates).length === 0) return;
    delete pendingByCorpus[corpusKey][sectionKey];
    if (Object.keys(pendingByCorpus[corpusKey] || {}).length === 0) delete pendingByCorpus[corpusKey];
    delete (timersByCorpus[corpusKey] || {})[sectionKey];
    if (Object.keys(timersByCorpus[corpusKey] || {}).length === 0) delete timersByCorpus[corpusKey];

    set({ saving: true, error: null });
    try {
      const saved = await configApi.patchSection(sectionKey, updates, corpusKey || undefined);
      // Only merge the saved config if we're still on the same corpus.
      if (String(getActiveCorpusId() || '') === String(corpusKey || '')) {
        set((state) => {
          const cur = state.config as any;
          const nextSection = (saved as any)?.[sectionKey];
          // Merge only the patched section to avoid clobbering other optimistic changes.
          const nextConfig = cur ? ({ ...cur, [sectionKey]: nextSection } as TriBridConfig) : saved;
          const curPersisted = state.persisted as any;
          const nextPersisted = curPersisted
            ? ({ ...curPersisted, [sectionKey]: nextSection } as TriBridConfig)
            : saved;
          return {
            config: nextConfig,
            persisted: nextPersisted,
            saving: false,
            error: null,
            fieldErrors: withoutSectionFieldErrors(state.fieldErrors, sectionKey),
            saveConflict: null,
          };
        });
      } else {
        set((state) => ({
          saving: false,
          error: null,
          fieldErrors: withoutSectionFieldErrors(state.fieldErrors, sectionKey),
          saveConflict: null,
        }));
      }
    } catch (error) {
      const presentation = formatSaveError(error);
      const message = presentation.message;
      const detail = extractPatchErrorDetail(error);
      set((state) => {
        const cur = state.config as any;
        const persisted = state.persisted as any;
        // The server validated the whole merged section atomically, so nothing in this PATCH
        // was saved: the optimistic local copy must not keep the value it refused (see
        // `revertPaths`), or the next "Apply" silently re-sends the same rejected value.
        const nextConfig =
          cur && persisted && String(getActiveCorpusId() || '') === String(corpusKey || '')
            ? (() => {
                const curSection = (cur[sectionKey] as PatchObject) || {};
                const persistedSection = (persisted[sectionKey] as PatchObject) || {};
                const revertedSection = revertPaths(curSection, persistedSection, updates);
                return revertedSection === curSection ? cur : { ...cur, [sectionKey]: revertedSection };
              })()
            : cur;
        return {
          config: nextConfig as TriBridConfig,
          saving: false,
          error: message,
          fieldErrors: withParsedFieldErrors(state.fieldErrors, sectionKey, detail),
          saveConflict: presentation.conflict ? presentation.contractConflict ?? null : null,
        };
      });
      throw new Error(message);
    }
  };

  const flushAllPendingPatches = async (corpusKey: string) => {
    const timers = timersByCorpus[corpusKey] || {};
    for (const sectionKey of Object.keys(timers)) {
      clearTimeout(timers[sectionKey]);
      delete timers[sectionKey];
    }
    if (Object.keys(timers).length === 0) delete timersByCorpus[corpusKey];

    const pending = pendingByCorpus[corpusKey] || {};
    const sections = Object.keys(pending);
    if (sections.length === 0) return;
    const results = await Promise.allSettled(sections.map((section) => flushSection(corpusKey, section)));
    const failures = results
      .filter((res): res is PromiseRejectedResult => res.status === 'rejected')
      .map((res) => String(res.reason instanceof Error ? res.reason.message : res.reason || '').trim())
      .filter(Boolean);
    if (failures.length > 0) {
      throw new Error(Array.from(new Set(failures)).join(' | '));
    }
  };

  const stageSection = (section: keyof TriBridConfig, updates: Record<string, unknown>) => {
    const sectionKey = String(section);
    // Local stage only: mutate the working `config` and leave `persisted` alone, so the edit
    // shows as dirty and nothing is written until Apply. No pending patch, no timer, no request.
    set((state) => {
      const cur = state.config as any;
      if (!cur) return {};
      const curSection = (cur as any)[sectionKey] || {};
      const nextSection = deepMergePatch(curSection as PatchObject, updates);
      return {
        config: { ...cur, [sectionKey]: nextSection } as TriBridConfig,
        // Editing again clears a stale save error / conflict banner.
        error: null,
        saveConflict: null,
      };
    });
  };

  const patchSectionDebounced = (section: keyof TriBridConfig, updates: Record<string, unknown>) => {
    const sectionKey = String(section);
    const corpusKey = String(getActiveCorpusId() || '');

    // Optimistic local update so controlled inputs stay responsive.
    set((state) => {
      const cur = state.config as any;
      if (!cur) return {};
      const curSection = (cur as any)[sectionKey] || {};
      const nextSection = deepMergePatch(curSection as PatchObject, updates);
      return { config: { ...cur, [sectionKey]: nextSection } as TriBridConfig, error: null };
    });

    // Merge into pending patch and debounce the network call.
    pendingByCorpus[corpusKey] = pendingByCorpus[corpusKey] || {};
    pendingByCorpus[corpusKey][sectionKey] = deepMergePatch(
      pendingByCorpus[corpusKey][sectionKey] || {},
      updates || {}
    );
    timersByCorpus[corpusKey] = timersByCorpus[corpusKey] || {};
    if (timersByCorpus[corpusKey][sectionKey]) clearTimeout(timersByCorpus[corpusKey][sectionKey]);
    timersByCorpus[corpusKey][sectionKey] = setTimeout(() => {
      void flushSection(corpusKey, sectionKey).catch(() => {
        // State is already updated with error in flushSection; avoid unhandled promise noise.
      });
    }, DEBOUNCE_MS);
  };

  /** The real load. `loadConfig` wraps it so concurrent callers share one request. */
  const loadConfigOnce = async (corpusKey: string): Promise<void> => {
    // Critical: do NOT cancel optimistic patches here. Flush them before loading so
    // debounced saves are not lost and GET does not overwrite local updates.


    // Capture optimistic updates BEFORE flushing (flush will clear pendingByCorpus for this corpus)
    const optimisticUpdates = { ...(pendingByCorpus[corpusKey] || {}) } as Record<string, Record<string, unknown>>;
    for (const key in optimisticUpdates) {
      optimisticUpdates[key] = { ...(optimisticUpdates[key] || {}) };
    }

    let flushError: string | null = null;
    try {
      await flushAllPendingPatches(corpusKey);
    } catch (error) {
      flushError = formatSaveError(error).message;
    }

    set({ loading: true, error: flushError });
    try {
      const config = await configApi.load();

      // Merge server config with optimistic updates that were pending before flush,
      // but only when flush succeeded. If flush failed, show persisted server state.
      const mergedConfig = { ...config } as any;
      if (!flushError) {
        for (const [sectionKey, updates] of Object.entries(optimisticUpdates)) {
          if (updates && Object.keys(updates).length > 0) {
            const curSection = mergedConfig[sectionKey] || {};
            mergedConfig[sectionKey] = deepMergePatch(curSection as PatchObject, updates);
          }
        }
      }

      set({ config: mergedConfig as TriBridConfig, persisted: config, loading: false, error: flushError });
    } catch (error) {
      const loadError = formatSaveError(error).message;
      set({
        loading: false,
        error: flushError ? `${flushError} | ${loadError}` : loadError,
      });
    }
  };

  return ({
  config: null,
  persisted: null,
  loading: false,
  error: null,
  fieldErrors: {},
  saveConflict: null,
  saving: false,

  loadConfig: async () => {
    const sharedCorpusKey = String(getActiveCorpusId() || '');
    const hasQueuedPatches = Object.keys(pendingByCorpus[sharedCorpusKey] || {}).length > 0;
    const shared = inFlightLoadByCorpus[sharedCorpusKey];
    if (shared && !hasQueuedPatches) return shared;

    const run = loadConfigOnce(sharedCorpusKey);
    inFlightLoadByCorpus[sharedCorpusKey] = run;
    try {
      await run;
    } finally {
      if (inFlightLoadByCorpus[sharedCorpusKey] === run) delete inFlightLoadByCorpus[sharedCorpusKey];
    }
  },

  saveConfig: async (config: TriBridConfig) => {
    set({ saving: true, error: null });
    try {
      const saved = await configApi.save(config);
      cancelPendingPatches(String(getActiveCorpusId() || ''));
      set({ config: saved, persisted: saved, saving: false, error: null, fieldErrors: {}, saveConflict: null });
    } catch (error) {
      // A whole-config PUT validates every section atomically, so a 422 attributes to fields
      // anywhere: replace the field-error map with what this failure named (M-20). A 409/network
      // failure carries no per-field detail, so the map clears.
      const presentation = formatSaveError(error);
      const message = presentation.message;
      set({
        saving: false,
        error: message,
        fieldErrors: Object.fromEntries(presentation.fieldErrors.map((fe) => [fe.path, fe.message])),
        saveConflict: presentation.conflict ? presentation.contractConflict ?? null : null,
      });
      throw new Error(message);
    }
  },

  patchSection: async (section: keyof TriBridConfig, updates: Record<string, unknown>) => {
    const corpusKey = String(getActiveCorpusId() || '');
    const sectionKey = String(section);
    set({ saving: true, error: null });
    try {
      const saved = await configApi.patchSection(sectionKey, updates, corpusKey || undefined);
      if (String(getActiveCorpusId() || '') === String(corpusKey || '')) {
        set((state) => {
          const cur = state.config as any;
          const nextSection = (saved as any)?.[sectionKey];
          const nextConfig = cur ? ({ ...cur, [sectionKey]: nextSection } as TriBridConfig) : saved;
          const curPersisted = state.persisted as any;
          const nextPersisted = curPersisted
            ? ({ ...curPersisted, [sectionKey]: nextSection } as TriBridConfig)
            : saved;
          return {
            config: nextConfig,
            persisted: nextPersisted,
            saving: false,
            error: null,
            fieldErrors: withoutSectionFieldErrors(state.fieldErrors, sectionKey),
            saveConflict: null,
          };
        });
      } else {
        set((state) => ({
          saving: false,
          error: null,
          fieldErrors: withoutSectionFieldErrors(state.fieldErrors, sectionKey),
          saveConflict: null,
        }));
      }
    } catch (error) {
      // No optimistic update precedes this call (unlike `patchSectionDebounced`), so there is
      // nothing in `config` to revert -- only the field-attributed detail is worth recording.
      const detail = extractPatchErrorDetail(error);
      const presentation = formatSaveError(error);
      set((state) => ({
        saving: false,
        error: presentation.message,
        fieldErrors: withParsedFieldErrors(state.fieldErrors, sectionKey, detail),
        saveConflict: presentation.conflict ? presentation.contractConflict ?? null : null,
      }));
    }
  },

  stageSection,
  patchSectionDebounced,
  cancelPendingPatches,
  flushPendingPatches: async () => {
    // A server-side action about to read scoped config (starting an index run, saving paths)
    // must see the operator's edits. Two edit shapes can be outstanding: the legacy debounced
    // patches still used by a couple of direct callers, and — since the commit model became
    // staged — local staged edits that only live in `config`. Flush the debounced ones, then
    // persist any remaining staged divergence through the safe PUT path (contract lock + secret
    // restore). Without this second step, an index run would read stale server config.
    const corpusKey = String(getActiveCorpusId() || '');
    await flushAllPendingPatches(corpusKey);
    const { config, persisted } = useConfigStore.getState();
    if (config && JSON.stringify(config) !== JSON.stringify(persisted)) {
      await useConfigStore.getState().saveConfig(config);
    }
  },

  resetConfig: async () => {
    set({ saving: true, error: null });
    try {
      const saved = await configApi.reset();
      cancelPendingPatches(String(getActiveCorpusId() || ''));
      set({ config: saved, persisted: saved, saving: false, error: null, fieldErrors: {}, saveConflict: null });
    } catch (error) {
      set({
        saving: false,
        error: formatSaveError(error).message,
      });
    }
  },

  reset: () =>
    (() => {
      cancelPendingPatches();
      set({
      config: null,
      persisted: null,
      loading: false,
      error: null,
      fieldErrors: {},
      saveConflict: null,
      saving: false,
      })
    })(),
});
});
