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
  cancelPendingPatches: () => void;
  resetConfig: () => Promise<void>;
  loadEvalKeyCategories: () => void;

  reset: () => void;
}

export const useConfigStore = create<ConfigStore>((set) => {
  // Debounce + aggregation per top-level section
  const pendingBySection: Record<string, Record<string, unknown>> = {};
  const timersBySection: Record<string, ReturnType<typeof setTimeout>> = {};
  const DEBOUNCE_MS = 300;

  const cancelPendingPatches = () => {
    for (const key of Object.keys(timersBySection)) {
      clearTimeout(timersBySection[key]);
      delete timersBySection[key];
    }
    for (const key of Object.keys(pendingBySection)) {
      delete pendingBySection[key];
    }
  };

  const flushSection = async (sectionKey: string) => {
    const updates = pendingBySection[sectionKey];
    if (!updates || Object.keys(updates).length === 0) return;
    delete pendingBySection[sectionKey];
    delete timersBySection[sectionKey];

    set({ saving: true, error: null });
    try {
      const saved = await configApi.patchSection(sectionKey, updates);
      set((state) => {
        const cur = state.config as any;
        const nextSection = (saved as any)?.[sectionKey];
        // Merge only the patched section to avoid clobbering other optimistic changes.
        const nextConfig = cur
          ? ({ ...cur, [sectionKey]: nextSection } as TriBridConfig)
          : saved;
        return { config: nextConfig, saving: false, error: null };
      });
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to save configuration',
      });
    }
  };

  const patchSectionDebounced = (section: keyof TriBridConfig, updates: Record<string, unknown>) => {
    const sectionKey = String(section);

    // Optimistic local update so controlled inputs stay responsive.
    set((state) => {
      const cur = state.config as any;
      if (!cur) return {};
      const curSection = (cur as any)[sectionKey] || {};
      const nextSection = { ...(curSection as any), ...(updates as any) };
      return { config: { ...cur, [sectionKey]: nextSection } as TriBridConfig, error: null };
    });

    // Merge into pending patch and debounce the network call.
    pendingBySection[sectionKey] = { ...(pendingBySection[sectionKey] || {}), ...(updates || {}) };
    if (timersBySection[sectionKey]) clearTimeout(timersBySection[sectionKey]);
    timersBySection[sectionKey] = setTimeout(() => {
      void flushSection(sectionKey);
    }, DEBOUNCE_MS);
  };

  return ({
  config: null,
  loading: false,
  error: null,
  saving: false,
  evalKeyCategories: {},

  loadConfig: async () => {
    cancelPendingPatches();
    set({ loading: true, error: null });
    try {
      const config = await configApi.load();
      set({ config, loading: false, error: null });
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
      cancelPendingPatches();
      set({ config: saved, saving: false, error: null });
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to save configuration',
      });
    }
  },

  patchSection: async (section: keyof TriBridConfig, updates: Record<string, unknown>) => {
    set({ saving: true, error: null });
    try {
      const saved = await configApi.patchSection(String(section), updates);
      set((state) => {
        const sectionKey = String(section);
        const cur = state.config as any;
        const nextSection = (saved as any)?.[sectionKey];
        const nextConfig = cur ? ({ ...cur, [sectionKey]: nextSection } as TriBridConfig) : saved;
        return { config: nextConfig, saving: false, error: null };
      });
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
      cancelPendingPatches();
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
