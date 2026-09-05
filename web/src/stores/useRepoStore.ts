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
import type { Corpus, CorpusAlreadyIndexedResponse, CorpusCreateRequest, CorpusUpdateRequest } from '@/types/generated';
import { resolveAPIBase } from '@/api/client';
import { describeIndexRunConflict } from '@/utils/indexRunConflict';

// Re-export for backward compatibility with existing components
export type Repository = Corpus;

// Registry reads are also called from void mount/event handlers. Carry failures as an explicit
// result so awaited mutation refreshes can stop without introducing unhandled rejections there.
type RepoLoadResult = { ok: true } | { ok: false; error: string };

interface RepoStore {
  // State
  repos: Corpus[];
  activeRepo: string;
  loading: boolean;
  error: string | null;
  switching: boolean;
  /** True after first load attempt (success or failure) - prevents infinite loops */
  initialized: boolean;
  /**
   * True after a registry response has been successfully applied, including a successful empty
   * list. Unlike `initialized`, this stays false through an initial failure and its pending retry,
   * so consumers never mistake cleared retry errors for resolved global scope.
   */
  resolved: boolean;

  // Actions
  /**
   * `force` skips the shared in-flight load. A mutation must never resolve against a
   * registry read that started BEFORE it: `deleteCorpus` awaiting a pre-delete load would
   * come back with the deleted corpus still in the list. `loadConfig` has the same guard
   * for pending patches.
   */
  loadRepos: (options?: { force?: boolean }) => Promise<RepoLoadResult>;
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

// One GET /api/corpora in flight at a time. The old guard returned early when a load
// was already running, so the second caller resolved *before* the corpus list existed
// and carried on with an empty registry; app init awaits `loadRepos()` precisely so the
// corpus scope is settled before config loads (M-129). Sharing the promise makes every
// caller wait for the same answer. It is not a cache: the entry is dropped as soon as
// the load settles, so the next call always goes to the server.
interface RepoLoadRequest {
  generation: number;
  /** Raw request work only. Chaining wrappers must never be stored here or await cycles form. */
  promise: Promise<RepoLoadResult>;
}

let inFlightRepoLoad: RepoLoadRequest | null = null;
// Retain the newest settled result as well: it may settle before a superseded older request.
// This is not a read cache; only inFlightRepoLoad can be shared by a newly started loadRepos call.
let latestRepoLoad: RepoLoadRequest | null = null;
// Only the newest registry request may publish state or canonicalize browser scope. Forced
// mutation refreshes intentionally supersede an older shared read that may still be pending.
let repoLoadGeneration = 0;

/**
 * Wait until the newest request in a supersession chain settles. Mutation callers depend on their
 * awaited forced refresh having published the winning registry before they inspect it. Shared
 * non-forced callers need the same transitive guarantee when their raw request is superseded.
 */
const waitForWinningRepoLoad = async (initial: RepoLoadRequest): Promise<RepoLoadResult> => {
  let current = initial;
  while (true) {
    const result = await current.promise;
    const newer = latestRepoLoad;
    if (!newer || newer.generation <= current.generation) {
      return result;
    }
    current = newer;
  }
};

const requireSuccessfulRepoRefresh = (result: RepoLoadResult, completedOperation: string): void => {
  if (!result.ok) {
    // The server mutation already happened. Report that fact so the operator does not repeat it,
    // and leave the winning registry error/state intact until a successful read reconciles it.
    throw new Error(
      `${completedOperation}, but the corpus list could not be refreshed. ${result.error}. ` +
      'Reload the corpus list before continuing.'
    );
  }
};

export const useRepoStore = create<RepoStore>((set, get) => ({
  repos: [],
  activeRepo: '',
  loading: false,
  error: null,
  switching: false,
  initialized: false,
  resolved: false,

  loadRepos: async (options?: { force?: boolean }) => {
    if (inFlightRepoLoad && !options?.force) return waitForWinningRepoLoad(inFlightRepoLoad);
    const generation = ++repoLoadGeneration;
    // Publish request ownership before notifying synchronous Zustand subscribers below.
    const run = Promise.resolve().then(async (): Promise<RepoLoadResult> => {
    set({ loading: true, error: null });
    try {
      const apiBase = getApiBase();

      // Fetch corpus list
      const reposRes = await fetch(`${apiBase}/corpora`);
      if (!reposRes.ok) {
        throw new Error('Failed to load corpora');
      }

      const repos: Corpus[] = await reposRes.json();
      if (generation !== repoLoadGeneration) return { ok: true };

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

      // Canonicalize every scope, including no corpus, BEFORE publishing state or
      // events: subscribers may immediately issue a scoped config request.
      if (activeRepo) {
        localStorage.setItem('tribrid_active_corpus', activeRepo);
      } else {
        localStorage.removeItem('tribrid_active_corpus');
      }
      localStorage.removeItem('tribrid_active_repo');
      try {
        const nextUrl = new URL(window.location.href);
        if (activeRepo) nextUrl.searchParams.set('corpus', activeRepo);
        else nextUrl.searchParams.delete('corpus');
        nextUrl.searchParams.delete('repo');
        window.history.replaceState({}, '', nextUrl.toString());
      } catch {
        // ignore
      }

      set({ repos, activeRepo, loading: false, error: null, initialized: true, resolved: true });
      window.dispatchEvent(
        new CustomEvent('tribrid-corpus-loaded', {
          detail: { repos, activeRepo }
        })
      );
      return { ok: true };

    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load repositories';
      if (generation !== repoLoadGeneration) return { ok: false, error: message };
      set({
        loading: false,
        error: message,
        initialized: true  // Mark as initialized even on error to prevent retry loops
      });
      return { ok: false, error: message };
    }
    });
    const request = { generation, promise: run };
    inFlightRepoLoad = request;
    latestRepoLoad = request;
    try {
      return await waitForWinningRepoLoad(request);
    } finally {
      if (inFlightRepoLoad === request) inFlightRepoLoad = null;
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
    requireSuccessfulRepoRefresh(
      await get().loadRepos({ force: true }), `Corpus "${created.corpus_id}" was created`
    );
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
    requireSuccessfulRepoRefresh(
      await get().loadRepos({ force: true }), `Corpus "${corpusId}" was updated`
    );
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
    requireSuccessfulRepoRefresh(
      await get().loadRepos({ force: true }), `Corpus "${corpusId}" was deleted`
    );
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
    // A corpus can finish indexing while Sources remains open. Never turn the
    // previously displayed metadata into a destructive cleanup candidate list.
    const refreshed = await get().loadRepos({ force: true });
    if (!refreshed.ok) {
      throw new Error(`No corpora were deleted. The corpus list could not be refreshed. ${refreshed.error}`);
    }
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
        const response = await fetch(`${apiBase}/corpora/${encodeURIComponent(id)}?only_unindexed=true`, {
          method: 'DELETE',
        });
        if (!response.ok) {
          const detail = await response.text().catch(() => '');
          if (response.status === 409) {
            try {
              const refusal = JSON.parse(detail) as CorpusAlreadyIndexedResponse;
              if (refusal?.detail?.code === 'corpus_already_indexed' && refusal.detail.corpus_id === id) {
                // Indexing committed after our snapshot. Leave this corpus in
                // place and reconcile it in the same final registry refresh.
                continue;
              }
            } catch {
              // A different failure retains the existing cleanup error behavior.
            }
          }
          failed.push({ id, status: response.status, detail });
          continue;
        }
        deleted.push(id);
      } catch (e) {
        failed.push({ id, status: 0, detail: e instanceof Error ? e.message : String(e) });
      }
    }

    requireSuccessfulRepoRefresh(
      await get().loadRepos({ force: true }),
      `Deleted ${deleted.length}/${toDelete.length} corpora` +
        (failed.length ? `; ${failed.length} deletions failed` : '')
    );
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
