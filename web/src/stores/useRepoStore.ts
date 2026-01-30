/**
 * AGRO - Centralized Repository State Management
 *
 * Provides a single source of truth for:
 * - Available repositories list
 * - Currently active repository
 * - Repo switching with backend propagation
 *
 * All components should use this store instead of local state for repo selection.
 */

import { create } from 'zustand';
import type { Repository, RepoIndexingConfig } from '@web/types';

// Re-export types for backward compatibility
export type { Repository, RepoIndexingConfig };

interface RepoStore {
  // State
  repos: Repository[];
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
  getRepoByName: (name: string) => Repository | undefined;
  updateRepoIndexing: (repoName: string, indexing: Partial<RepoIndexingConfig>) => Promise<void>;
}

// Determine API base URL
/**
 * ---agentspec
 * what: |
 *   Determines the API base URL for HTTP requests based on the current browser environment.
 *   Takes no parameters. Returns a string representing the API endpoint base URL.
 *   Parses window.location.href to extract origin and port information.
 *   If running on development port 5173 (Vite dev server), returns hardcoded backend URL 'http://127.0.0.1:8012/api'.
 *   Otherwise returns the current origin with '/api' appended. Falls back to '/api' if URL parsing fails.
 *
 * why: |
 *   Centralizes API endpoint configuration to handle different deployment environments (local development vs. production).
 *   Development environment (port 5173) typically runs a separate backend server, requiring explicit URL override.
 *   Production deployments serve API from the same origin, so relative path '/api' works correctly.
 *   Try-catch wrapper prevents crashes if window.location is inaccessible in edge cases (SSR, iframe restrictions).
 *
 * guardrails:
 *   - DO NOT hardcode 'http://127.0.0.1:8012/api' in multiple places; this function is the single source of truth for dev backend routing
 *   - ALWAYS verify that port 5173 matches your actual Vite dev server configuration before deploying; mismatched ports will route to wrong backend
 *   - NOTE: Hardcoded backend URL assumes backend runs on localhost:8012 during development; this breaks if backend runs on different host/port
 *   - ASK USER: Before changing the development backend URL or port detection logic, confirm the actual dev environment setup and whether multiple developers use different backend ports
 * ---/agentspec
 */
const getApiBase = (): string => {
  try {
    const u = new URL(window.location.href);
    if (u.port === '5173') return 'http://127.0.0.1:8012/api';
    return u.origin + '/api';
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

      // Fetch repos list AND current config in parallel
      const [reposRes, configRes] = await Promise.all([
        fetch(`${apiBase}/repos`),
        fetch(`${apiBase}/config`)
      ]);

      if (!reposRes.ok || !configRes.ok) {
        throw new Error('Failed to load repos or config');
      }

      const reposData = await reposRes.json();
      const configData = await configRes.json();

      const repos: Repository[] = reposData.repos || [];
      const activeRepo = configData.env?.REPO || configData.default_repo || (repos[0]?.name || 'agro');

      set({
        repos,
        activeRepo,
        loading: false,
        error: null,
        initialized: true
      });

      // Broadcast repo state for any listeners
      window.dispatchEvent(new CustomEvent('agro-repo-loaded', {
        detail: { repos, activeRepo }
      }));

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
    
    // Verify repo exists
    const targetRepo = repos.find(r => r.name === repoName || r.slug === repoName);
    if (!targetRepo && repos.length > 0) {
      set({ error: `Repository "${repoName}" not found` });
      return;
    }
    
    set({ switching: true, error: null });
    
    try {
      const apiBase = getApiBase();
      
      // Update backend config with new REPO
      const response = await fetch(`${apiBase}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ env: { REPO: repoName } })
      });
      
      if (!response.ok) {
        throw new Error('Failed to update active repository');
      }
      
      // Trigger config reload to propagate changes to all backend modules
      await fetch(`${apiBase}/env/reload`, { method: 'POST' });
      
      const previousRepo = activeRepo;
      set({ activeRepo: repoName, switching: false });
      
      // Broadcast repo change for all listeners
      window.dispatchEvent(new CustomEvent('agro-repo-changed', { 
        detail: { repo: repoName, previous: previousRepo } 
      }));
      
    } catch (error) {
      set({
        switching: false,
        error: error instanceof Error ? error.message : 'Failed to switch repository'
      });
    }
  },

  refreshActiveRepo: async () => {
    const apiBase = getApiBase();
    try {
      const response = await fetch(`${apiBase}/config`);
      if (response.ok) {
        const data = await response.json();
        const activeRepo = data.env?.REPO || data.default_repo || 'agro';
        set({ activeRepo });
      }
    } catch {
      // Silent fail - will use cached value
    }
  },

  getRepoByName: (name: string) => {
    return get().repos.find(r => r.name === name || r.slug === name);
  },

  updateRepoIndexing: async (repoName: string, indexing: Partial<RepoIndexingConfig>) => {
    const { repos } = get();
    const targetRepo = repos.find(r => r.name === repoName || r.slug === repoName);
    if (!targetRepo) {
      set({ error: `Repository "${repoName}" not found` });
      return;
    }

    try {
      const apiBase = getApiBase();
      const response = await fetch(`${apiBase}/repos/${repoName}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ indexing })
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || 'Failed to update repo indexing config');
      }

      // Update local state
      const updatedRepos = repos.map(r => {
        if (r.name === repoName || r.slug === repoName) {
          return {
            ...r,
            indexing: { ...r.indexing, ...indexing } as RepoIndexingConfig
          };
        }
        return r;
      });

      set({ repos: updatedRepos, error: null });

      // Broadcast for listeners
      window.dispatchEvent(new CustomEvent('agro-repo-indexing-updated', {
        detail: { repo: repoName, indexing }
      }));

    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to update indexing config' });
      throw error;
    }
  }
}));

// Export selector hooks for convenience
/**
 * ---agentspec
 * what: |
 *   Exports three custom React hooks that provide selectively-memoized access to repository state from a Zustand store.
 *   useActiveRepo() returns the currently active repository object; useRepos() returns the full array of repositories; useRepoLoading() returns a boolean indicating whether the store is in loading or switching state.
 *   Each hook uses Zustand's selector pattern to subscribe only to its specific state slice, preventing unnecessary re-renders when unrelated state changes.
 *   No parameters are required; hooks automatically connect to the global repoStore context.
 *
 * why: |
 *   Zustand selectors enable fine-grained subscriptions so components only re-render when their specific data changes, not on every store update.
 *   Exporting these as hooks provides a clean, composable API that follows React conventions and hides store implementation details from consumers.
 *   Combining loading and switching flags into a single useRepoLoading hook reduces boilerplate in components that need to show loading UI during either operation.
 *
 * guardrails:
 *   - DO NOT modify the selector logic without understanding Zustand's shallow equality checks; changing state shape may break memoization
 *   - ALWAYS use these hooks instead of direct store access to maintain consistent subscription behavior across the codebase
 *   - NOTE: useRepoLoading combines two separate boolean flags; if loading and switching need independent control, split into separate hooks
 *   - ASK USER: Before adding new repository-related hooks, confirm whether they should be selectors (fine-grained) or if a single useRepo hook returning the entire state object is preferred
 * ---/agentspec
 */
export const useActiveRepo = () => useRepoStore(state => state.activeRepo);
/**
 * ---agentspec
 * what: |
 *   Two custom React hooks that provide selector access to the repository store state.
 *   useRepos() returns the repos array from store state; useRepoLoading() returns a boolean indicating whether repos are currently loading or a repo switch is in progress.
 *   Both hooks use Zustand's selector pattern to subscribe only to their specific state slices, preventing unnecessary re-renders when unrelated store state changes.
 *   No parameters required; hooks automatically connect to the global useRepoStore context.
 *   Edge case: useRepoLoading returns true if either loading OR switching is true, combining two related loading states into a single boolean.
 *
 * why: |
 *   These hooks encapsulate store selectors to provide a clean, reusable API for components that need repo data or loading status.
 *   Zustand selectors enable fine-grained subscriptions, so components only re-render when their specific slice of state changes.
 *   Combining loading and switching into one hook simplifies component logic since both states represent "user should see a loading indicator."
 *
 * guardrails:
 *   - DO NOT add additional state slices to these hooks without updating all consuming components; selector changes are breaking changes
 *   - ALWAYS use these hooks instead of accessing useRepoStore directly in components to maintain selector consistency
 *   - NOTE: useRepoLoading combines two separate boolean flags; if you need to distinguish between loading and switching, create a separate hook
 *   - ASK USER: Before adding new repo-related selectors, confirm whether they should be separate hooks or combined with existing ones
 * ---/agentspec
 */
export const useRepos = () => useRepoStore(state => state.repos);
/**
 * ---agentspec
 * what: |
 *   Custom React hook that selects and returns a boolean indicating whether a repository is currently loading or switching.
 *   Takes no parameters; accesses the global repo store via useRepoStore.
 *   Returns a boolean: true if either state.loading or state.switching is true, false otherwise.
 *   Used to display loading indicators or disable UI interactions during repo operations.
 *   Combines two separate state flags into a single derived boolean for convenience.
 *
 * why: |
 *   Centralizes the logic for determining "is repo busy" so components don't need to know about both loading and switching states.
 *   Reduces boilerplate in components that need to show loading UI during either operation.
 *   Provides a single source of truth for the "repo is not ready" condition across the application.
 *
 * guardrails:
 *   - DO NOT add additional state flags to this selector without updating all dependent components; this hook is a contract
 *   - ALWAYS use this hook instead of accessing state.loading or state.switching directly in components to maintain consistency
 *   - NOTE: This is a synchronous selector; it does not trigger any state updates or side effects
 *   - ASK USER: Before adding conditional logic (e.g., prioritizing one flag over the other), confirm the intended behavior when both flags are true
 * ---/agentspec
 */
export const useRepoLoading = () => useRepoStore(state => state.loading || state.switching);

/** Returns true after first load attempt (success or failure) - use to prevent infinite load loops */
export const useRepoInitialized = () => useRepoStore(state => state.initialized);
