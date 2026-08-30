/**
 * TriBridRAG - Centralized Corpus State Management
 *
 * Provides a single source of truth for:
 * - Available repositories list
 * - Currently active repository
 * - Repo switching with backend propagation
 *
 * All components should use this store instead of local state for repo selection.
 */

import { create } from 'zustand';
import type { Corpus, CorpusCreateRequest, CorpusUpdateRequest } from '@/types/generated';
import { resolveAPIBase } from '@/api/client';
import { describeIndexRunConflict } from '@/utils/indexRunConflict';

// Re-export for backward compatibility with existing components
export type Repository = Corpus;

interface RepoStore {
  // State
  repos: Corpus[];
  activeRepo: string;
  loading: boolean;
  error: string | null;
  switching: boolean;
  /** True after first load attempt (success or failure) - prevents infinite loops */
  initialized: boolean;

  // Actions
  loadRepos: () => Promise<void>;
  setActiveRepo: (repoName: string) => Promise<void>;
  refreshActiveRepo: () => Promise<void>;
  getRepoByName: (name: string) => Corpus | undefined;
  addRepo: (request: CorpusCreateRequest) => Promise<Corpus>;
  updateCorpus: (corpusId: string, updates: CorpusUpdateRequest) => Promise<Corpus>;
  deleteCorpus: (corpusId: string) => Promise<void>;
  /** Deletes all corpora with last_indexed == null (excludes runtime-managed corpora). */
  deleteUnindexedCorpora: () => Promise<string[]>;
}

// Determine API base URL
const getApiBase = (): string => {
  try {
    return resolveAPIBase();
  } catch {
    return '/api';
  }
};

export const useRepoStore = create<RepoStore>((set, get) => ({
  repos: [],
  activeRepo: '',
  loading: false,
  error: null,
  switching: false,
  initialized: false,

  loadRepos: async () => {
    // Prevent concurrent loads - if already loading, skip
    const { loading } = get();
    if (loading) {
      return;
    }

    set({ loading: true, error: null });
    try {
      const apiBase = getApiBase();

      // Fetch corpus list
      const reposRes = await fetch(`${apiBase}/corpora`);
      if (!reposRes.ok) {
        throw new Error('Failed to load corpora');
      }

      const repos: Corpus[] = await reposRes.json();

      // Determine active corpus from URL, localStorage, or first corpus (and validate it exists)
      const url = new URL(window.location.href);
      const urlCorpusRaw = url.searchParams.get('corpus') || url.searchParams.get('repo') || '';
      const storedRaw =
        localStorage.getItem('tribrid_active_corpus') || localStorage.getItem('tribrid_active_repo') || '';

      const resolveToCorpusId = (candidate: string): string => {
        const v = String(candidate || '').trim();
        if (!v) return '';
        const found = repos.find((r) => r.corpus_id === v || r.slug === v || r.name === v);
        return String(found?.corpus_id || '').trim();
      };

      const resolvedFromUrl = resolveToCorpusId(urlCorpusRaw);
      const resolvedFromStored = resolveToCorpusId(storedRaw);
      const activeRepo =
        resolvedFromUrl ||
        resolvedFromStored ||
        String(repos[0]?.corpus_id || repos[0]?.slug || repos[0]?.name || '').trim();

      set({
        repos,
        activeRepo,
        loading: false,
        error: null,
        initialized: true
      });

      // Persist + broadcast
      if (activeRepo) {
        localStorage.setItem('tribrid_active_corpus', activeRepo);
        // Keep URL in sync (canonicalize to ?corpus=<id>)
        try {
          const nextUrl = new URL(window.location.href);
          nextUrl.searchParams.set('corpus', activeRepo);
          nextUrl.searchParams.delete('repo');
          window.history.replaceState({}, '', nextUrl.toString());
        } catch {
          // ignore
        }
      }
      window.dispatchEvent(
        new CustomEvent('tribrid-corpus-loaded', {
          detail: { repos, activeRepo }
        })
      );

    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : 'Failed to load repositories',
        initialized: true  // Mark as initialized even on error to prevent retry loops
      });
    }
  },

  setActiveRepo: async (repoName: string) => {
    const { activeRepo, repos } = get();
    if (repoName === activeRepo) return;
    
    // Verify corpus exists
    const targetRepo = repos.find(r => r.corpus_id === repoName || r.slug === repoName || r.name === repoName);
    if (!targetRepo && repos.length > 0) {
      set({ error: `Repository "${repoName}" not found` });
      return;
    }
    
    set({ switching: true, error: null });
    
    try {
      const previousRepo = activeRepo;
      set({ activeRepo: repoName, switching: false });

      // Persist active corpus locally and in URL
      localStorage.setItem('tribrid_active_corpus', repoName);
      const url = new URL(window.location.href);
      url.searchParams.set('corpus', repoName);
      window.history.replaceState({}, '', url.toString());
      
      // Broadcast repo change for all listeners
      window.dispatchEvent(
        new CustomEvent('tribrid-corpus-changed', {
          detail: { corpus: repoName, repo: repoName, previous: previousRepo },
        })
      );
      
    } catch (error) {
      set({
        switching: false,
        error: error instanceof Error ? error.message : 'Failed to switch repository'
      });
    }
  },

  refreshActiveRepo: async () => {
    try {
      const url = new URL(window.location.href);
      const urlCorpus = url.searchParams.get('corpus') || url.searchParams.get('repo') || '';
      const stored =
        localStorage.getItem('tribrid_active_corpus') || localStorage.getItem('tribrid_active_repo') || '';
      const activeRepo = urlCorpus || stored;
      if (activeRepo) set({ activeRepo });
    } catch {
      // Silent fail - will use cached value
    }
  },

  getRepoByName: (name: string) => {
    return get().repos.find(r => r.corpus_id === name || r.slug === name || r.name === name);
  },

  addRepo: async (request: CorpusCreateRequest) => {
    const apiBase = getApiBase();
    const response = await fetch(`${apiBase}/corpora`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    });
    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new Error(detail || `Failed to create corpus (${response.status})`);
    }
    const created: Corpus = await response.json();
    // Refresh list and set active
    await get().loadRepos();
    await get().setActiveRepo(created.corpus_id);
    return created;
  },

  updateCorpus: async (corpusId: string, updates: CorpusUpdateRequest) => {
    const apiBase = getApiBase();
    const response = await fetch(`${apiBase}/corpora/${encodeURIComponent(corpusId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    });
    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new Error(detail || `Failed to update corpus (${response.status})`);
    }
    const updated: Corpus = await response.json();
    // Refresh list to reflect changes
    await get().loadRepos();
    return updated;
  },

  deleteCorpus: async (corpusId: string) => {
    const apiBase = getApiBase();
    const beforeActive = String(get().activeRepo || '').trim();
    const response = await fetch(`${apiBase}/corpora/${encodeURIComponent(corpusId)}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      // A corpus held by a live index run is refused with the typed fence envelope. Raw
      // `{"detail":{...}}` JSON told the operator nothing about which run held it or what
      // that run was doing, which is the whole question when a delete is refused.
      throw new Error(
        describeIndexRunConflict(detail) || detail || `Failed to delete corpus (${response.status})`
      );
    }

    // Refresh list after deletion
    await get().loadRepos();
    const afterActive = String(get().activeRepo || '').trim();

    // If the active corpus changed under us, notify listeners that depend on
    // `tribrid-corpus-changed` rather than `tribrid-corpus-loaded`.
    if (beforeActive && beforeActive !== afterActive) {
      window.dispatchEvent(
        new CustomEvent('tribrid-corpus-changed', {
          detail: { corpus: afterActive, repo: afterActive, previous: beforeActive },
        })
      );
    }

    if (!afterActive) {
      try {
        localStorage.removeItem('tribrid_active_corpus');
        localStorage.removeItem('tribrid_active_repo');
      } catch {
        // ignore
      }
    }
  },

  deleteUnindexedCorpora: async () => {
    const apiBase = getApiBase();
    const { repos, activeRepo } = get();
    const beforeActive = String(activeRepo || '').trim();

    const toDelete = (repos || []).filter((c) => {
      const id = String(c.corpus_id || '').trim();
      if (!id) return false;
      // Runtime-registered corpora are never the operator's to clean up, and they index
      // through their own path so they look unindexed here. `internal` is the typed answer;
      // the hardcoded `recall_default` this replaces missed the Codex session corpora and
      // was exactly the duplicated contract that field was added to remove.
      if (c.internal) return false;
      return !c.last_indexed;
    });

    if (toDelete.length === 0) {
      return [];
    }

    const deleted: string[] = [];
    const failed: Array<{ id: string; status: number; detail: string }> = [];

    for (const c of toDelete) {
      const id = String(c.corpus_id || '').trim();
      if (!id) continue;
      try {
        const response = await fetch(`${apiBase}/corpora/${encodeURIComponent(id)}`, {
          method: 'DELETE',
        });
        if (!response.ok) {
          const detail = await response.text().catch(() => '');
          failed.push({ id, status: response.status, detail });
          continue;
        }
        deleted.push(id);
      } catch (e) {
        failed.push({ id, status: 0, detail: e instanceof Error ? e.message : String(e) });
      }
    }

    await get().loadRepos();
    const afterActive = String(get().activeRepo || '').trim();
    if (beforeActive && afterActive && beforeActive !== afterActive) {
      window.dispatchEvent(
        new CustomEvent('tribrid-corpus-changed', {
          detail: { corpus: afterActive, repo: afterActive, previous: beforeActive },
        })
      );
    }

    if (failed.length > 0) {
      const first = failed[0];
      throw new Error(
        `Deleted ${deleted.length}/${toDelete.length} corpora. ` +
          `Failed ${failed.length} (first: ${first.id}${first.status ? ` ${first.status}` : ''})`
      );
    }

    return deleted;
  },
}));

// Export selector hooks for convenience
export const useActiveRepo = () => useRepoStore(state => state.activeRepo);
export const useRepos = () => useRepoStore(state => state.repos);
export const useRepoLoading = () => useRepoStore(state => state.loading || state.switching);

/** Returns true after first load attempt (success or failure) - use to prevent infinite load loops */
export const useRepoInitialized = () => useRepoStore(state => state.initialized);
