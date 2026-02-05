import { create } from 'zustand';
import { configApi } from '@/api/config';
import type { TriBridConfig } from '@/types/generated';

interface ConfigStore {
  config: TriBridConfig | null;
  loading: boolean;
  error: string | null;
  saving: boolean;
  /**
   * Optional mapping of flat config keys -> UI categories.
   * Used by Eval drill-down to group config snapshots.
   */
  evalKeyCategories: Record<string, string>;

  // Actions
  loadConfig: () => Promise<void>;
  saveConfig: (config: TriBridConfig) => Promise<void>;
  patchSection: (section: keyof TriBridConfig, updates: Record<string, unknown>) => Promise<void>;
  /**
   * Debounced patch for high-frequency UI changes (typing, sliders).
   * Applies an optimistic local update immediately, then persists via PATCH after ~300ms.
   */
  patchSectionDebounced: (section: keyof TriBridConfig, updates: Record<string, unknown>) => void;
  /** Cancel any pending debounced patch timers (e.g. when switching corpora). */
  cancelPendingPatches: (corpusId?: string) => void;
  resetConfig: () => Promise<void>;
  loadEvalKeyCategories: () => void;

  reset: () => void;
}

export const useConfigStore = create<ConfigStore>((set) => {
  // Debounce + aggregation per top-level section AND per corpus.
  // This prevents corpus-switch races from canceling/flush-ing the wrong corpus' pending writes.
  const pendingByCorpus: Record<string, Record<string, Record<string, unknown>>> = {};
  const timersByCorpus: Record<string, Record<string, ReturnType<typeof setTimeout>>> = {};
  const DEBOUNCE_MS = 300;

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
          return { config: nextConfig, saving: false, error: null };
        });
      } else {
        set({ saving: false, error: null });
      }
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to save configuration',
      });
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
    await Promise.all(sections.map((section) => flushSection(corpusKey, section)));
  };

  const patchSectionDebounced = (section: keyof TriBridConfig, updates: Record<string, unknown>) => {
    const sectionKey = String(section);
    const corpusKey = String(getActiveCorpusId() || '');

    // Optimistic local update so controlled inputs stay responsive.
    set((state) => {
      const cur = state.config as any;
      if (!cur) return {};
      const curSection = (cur as any)[sectionKey] || {};
      const nextSection = { ...(curSection as any), ...(updates as any) };
      return { config: { ...cur, [sectionKey]: nextSection } as TriBridConfig, error: null };
    });

    // Merge into pending patch and debounce the network call.
    pendingByCorpus[corpusKey] = pendingByCorpus[corpusKey] || {};
    pendingByCorpus[corpusKey][sectionKey] = {
      ...(pendingByCorpus[corpusKey][sectionKey] || {}),
      ...(updates || {})
    };
    timersByCorpus[corpusKey] = timersByCorpus[corpusKey] || {};
    if (timersByCorpus[corpusKey][sectionKey]) clearTimeout(timersByCorpus[corpusKey][sectionKey]);
    timersByCorpus[corpusKey][sectionKey] = setTimeout(() => {
      void flushSection(corpusKey, sectionKey);
    }, DEBOUNCE_MS);
  };

  return ({
  config: null,
  loading: false,
  error: null,
  saving: false,
  evalKeyCategories: {},

  loadConfig: async () => {
    // Critical: do NOT cancel optimistic patches here. Flush them before loading so
    // debounced saves are not lost and GET does not overwrite local updates.
    
    const corpusKey = String(getActiveCorpusId() || '');

    // Capture optimistic updates BEFORE flushing (flush will clear pendingByCorpus for this corpus)
    const optimisticUpdates = { ...(pendingByCorpus[corpusKey] || {}) } as Record<string, Record<string, unknown>>;
    for (const key in optimisticUpdates) {
      optimisticUpdates[key] = { ...(optimisticUpdates[key] || {}) };
    }

    await flushAllPendingPatches(corpusKey);
    
    set({ loading: true, error: null });
    try {
      const config = await configApi.load();
      
      // Merge server config with optimistic updates that were pending before flush
      // This preserves user changes even if server hasn't processed the flush yet
      const mergedConfig = { ...config } as any;
      for (const [sectionKey, updates] of Object.entries(optimisticUpdates)) {
        if (updates && Object.keys(updates).length > 0) {
          const curSection = mergedConfig[sectionKey] || {};
          mergedConfig[sectionKey] = { ...curSection, ...updates };
        }
      }
      
      set({ config: mergedConfig as TriBridConfig, loading: false, error: null });
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : 'Failed to load configuration',
      });
    }
  },

  saveConfig: async (config: TriBridConfig) => {
    set({ saving: true, error: null });
    try {
      const saved = await configApi.save(config);
      cancelPendingPatches(String(getActiveCorpusId() || ''));
      set({ config: saved, saving: false, error: null });
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to save configuration',
      });
    }
  },

  patchSection: async (section: keyof TriBridConfig, updates: Record<string, unknown>) => {
    const corpusKey = String(getActiveCorpusId() || '');
    set({ saving: true, error: null });
    try {
      const saved = await configApi.patchSection(String(section), updates, corpusKey || undefined);
      if (String(getActiveCorpusId() || '') === String(corpusKey || '')) {
        set((state) => {
          const sectionKey = String(section);
          const cur = state.config as any;
          const nextSection = (saved as any)?.[sectionKey];
          const nextConfig = cur ? ({ ...cur, [sectionKey]: nextSection } as TriBridConfig) : saved;
          return { config: nextConfig, saving: false, error: null };
        });
      } else {
        set({ saving: false, error: null });
      }
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to save configuration',
      });
    }
  },

  patchSectionDebounced,
  cancelPendingPatches,

  resetConfig: async () => {
    set({ saving: true, error: null });
    try {
      const saved = await configApi.reset();
      cancelPendingPatches(String(getActiveCorpusId() || ''));
      set({ config: saved, saving: false, error: null });
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to reset configuration',
      });
    }
  },

  loadEvalKeyCategories: () => {
    // Minimal implementation: keep empty mapping (everything groups as "Other").
    // If/when we want richer grouping, we can populate this deterministically from
    // `TriBridConfig.to_flat_dict()` key prefixes.
    set({ evalKeyCategories: {} });
  },

  reset: () =>
    (() => {
      cancelPendingPatches();
      set({
      config: null,
      loading: false,
      error: null,
      saving: false,
      evalKeyCategories: {},
      })
    })(),
});
});
