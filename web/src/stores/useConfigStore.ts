import { create } from 'zustand';
import { configApi } from '@/api/config';
import type { AppConfig, EnvConfig, ConfigUpdate, KeywordCatalog, Repository } from '@web/types';

interface ConfigStore {
  config: AppConfig | null;
  loading: boolean;
  error: string | null;
  saving: boolean;
  keywordsCatalog: KeywordCatalog | null;
  keywordsLoading: boolean;
  evalKeyCategories: Record<string, string> | null;
  evalKeyCategoriesLoading: boolean;

  // Actions
  loadConfig: () => Promise<void>;
  saveEnv: (env: Partial<EnvConfig>) => Promise<void>;
  saveConfig: (update: ConfigUpdate) => Promise<void>;
  reloadEnv: () => Promise<void>;
  updateEnv: (key: string, value: string | number | boolean) => void;
  updateRepo: (repoName: string, updates: Partial<Repository>) => Promise<void>;

  // Keyword actions
  loadKeywords: () => Promise<void>;
  addKeyword: (keyword: string, category?: string) => Promise<void>;
  deleteKeyword: (keyword: string) => Promise<void>;

  // Eval key categories (for eval config display)
  loadEvalKeyCategories: () => Promise<void>;

  reset: () => void;
}

export const useConfigStore = create<ConfigStore>((set, get) => ({
  config: null,
  loading: false,
  error: null,
  saving: false,
  keywordsCatalog: null,
  keywordsLoading: false,
  evalKeyCategories: null,
  evalKeyCategoriesLoading: false,

  loadConfig: async () => {
    console.log('[useConfigStore] loadConfig called');
    set({ loading: true, error: null });
    try {
      // Reload from agro_config.json first
      await configApi.reloadConfig().catch(() => {});
      const config = await configApi.load();
      console.log('[useConfigStore] loadConfig success, env keys:', Object.keys(config?.env || {}));
      set({ config, loading: false, error: null });
    } catch (error) {
      console.error('[useConfigStore] loadConfig error:', error);
      set({
        loading: false,
        error: error instanceof Error ? error.message : 'Failed to load configuration'
      });
    }
  },

  saveEnv: async (env: Partial<EnvConfig>) => {
    set({ saving: true, error: null });
    try {
      await configApi.saveEnv(env);
      set({ saving: false, error: null });
      // Reload config after save
      await get().loadConfig();
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to save configuration'
      });
    }
  },

  saveConfig: async (update: ConfigUpdate) => {
    set({ saving: true, error: null });
    try {
      await configApi.saveConfig(update);
      set({ saving: false, error: null });
      // Reload config after save
      await get().loadConfig();
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to save configuration'
      });
    }
  },

  reloadEnv: async () => {
    // DEPRECATED: Use loadConfig() instead. This exists for backwards compatibility.
    try {
      await configApi.reloadConfig();
      await get().loadConfig();
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to reload configuration'
      });
    }
  },

  updateEnv: (key: string, value: string | number | boolean) => {
    const { config } = get();
    if (!config) {
      console.warn('[useConfigStore] updateEnv called but config is null, key:', key);
      return;
    }

    console.log('[useConfigStore] updateEnv:', key, '=', value);
    set({
      config: {
        ...config,
        env: {
          ...config.env,
          [key]: value,
        },
      },
    });
  },

  updateRepo: async (repoName: string, updates: Partial<Repository>) => {
    const { config } = get();
    if (!config) return;

    // Save to repos.json via API first
    try {
      // Determine API base URL
      let apiBase = '/api';
      try {
        const u = new URL(window.location.href);
        if (u.port === '5173') apiBase = 'http://127.0.0.1:8012/api';
        else if (u.protocol.startsWith('http')) apiBase = u.origin + '/api';
      } catch {}

      const response = await fetch(`${apiBase}/repos/${repoName}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      });
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || 'Failed to save repo updates');
      }

      // Update local state after successful save
      const updatedRepos = config.repos.map(repo =>
        repo.name === repoName ? { ...repo, ...updates } : repo
      );

      set({
        config: {
          ...config,
          repos: updatedRepos,
        },
      });

      // Dispatch event so RepositoryConfig can refresh
      window.dispatchEvent(new CustomEvent('repo-updated', { detail: { repoName } }));
    } catch (error) {
      console.error('Error saving repo updates:', error);
      throw error; // Re-throw so caller can handle
    }
  },

  loadKeywords: async () => {
    set({ keywordsLoading: true, error: null });
    try {
      const keywordsCatalog = await configApi.loadKeywords();
      set({ keywordsCatalog, keywordsLoading: false, error: null });
    } catch (error) {
      set({
        keywordsLoading: false,
        error: error instanceof Error ? error.message : 'Failed to load keywords'
      });
    }
  },

  addKeyword: async (keyword: string, category?: string) => {
    try {
      await configApi.addKeyword(keyword, category);
      // Update local state immediately
      const { keywordsCatalog } = get();
      if (keywordsCatalog) {
        const updated: KeywordCatalog = {
          ...keywordsCatalog,
          keywords: [...(keywordsCatalog.keywords || []), keyword].sort(),
        };

        if (category && category in keywordsCatalog) {
          updated[category as keyof KeywordCatalog] = [
            ...(keywordsCatalog[category as keyof KeywordCatalog] as string[] || []),
            keyword
          ].sort();
        }

        set({ keywordsCatalog: updated });
      }
      // Reload from server to ensure consistency
      await get().loadKeywords();
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to add keyword'
      });
      throw error;
    }
  },

  deleteKeyword: async (keyword: string) => {
    try {
      await configApi.deleteKeyword(keyword);
      // Update local state immediately
      const { keywordsCatalog } = get();
      if (keywordsCatalog) {
        const updated: KeywordCatalog = {
          keywords: keywordsCatalog.keywords?.filter(k => k !== keyword) || [],
          discriminative: keywordsCatalog.discriminative?.filter(k => k !== keyword),
          semantic: keywordsCatalog.semantic?.filter(k => k !== keyword),
          llm: keywordsCatalog.llm?.filter(k => k !== keyword),
          repos: keywordsCatalog.repos?.filter(k => k !== keyword),
        };
        set({ keywordsCatalog: updated });
      }
      // Reload from server to ensure consistency
      await get().loadKeywords();
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to delete keyword'
      });
      throw error;
    }
  },

  loadEvalKeyCategories: async () => {
    // Skip if already loaded
    if (get().evalKeyCategories) return;

    set({ evalKeyCategoriesLoading: true });
    try {
      // Determine API base URL (same pattern as updateRepo)
      let apiBase = '/api';
      try {
        const u = new URL(window.location.href);
        if (u.port === '5173') apiBase = 'http://127.0.0.1:8012/api';
        else if (u.protocol.startsWith('http')) apiBase = u.origin + '/api';
      } catch { /* ignore */ }

      const response = await fetch(`${apiBase}/config/eval-key-categories`);
      if (!response.ok) {
        throw new Error(`Failed to fetch eval key categories: ${response.status}`);
      }
      const data = await response.json();
      set({ evalKeyCategories: data.categories, evalKeyCategoriesLoading: false });
    } catch (error) {
      console.error('[useConfigStore] loadEvalKeyCategories error:', error);
      set({
        evalKeyCategoriesLoading: false,
        error: error instanceof Error ? error.message : 'Failed to load eval key categories'
      });
    }
  },

  reset: () => set({
    config: null,
    loading: false,
    error: null,
    saving: false,
    keywordsCatalog: null,
    keywordsLoading: false,
    evalKeyCategories: null,
    evalKeyCategoriesLoading: false,
  }),
}));
