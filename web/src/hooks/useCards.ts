import { useCallback, useEffect } from 'react';
import { useAPI } from './useAPI';
import { useCardsStore } from '@/stores';
import type {
  CardsResponse,
  CardsBuildOptions,
} from '@web/types/cards';

/**
 * ---agentspec
 * what: |
 *   Custom React hook that wraps useCardsStore (Zustand) to manage card data and build state.
 *   Uses centralized Zustand store for state management with Pydantic validation from backend.
 *   Returns an object containing: cards array, lastBuild, loading states, error, and action functions.
 *   All state changes go through the Zustand store to maintain single source of truth.
 *
 * why: |
 *   Follows AGRO architecture pattern: Hooks wrap Zustand stores that sync with Pydantic backend.
 *   Eliminates local useState which causes state duplication and sync issues.
 *   Provides consistent state access across all components using cards functionality.
 *
 * guardrails:
 *   - DO NOT use useState for any state - MUST use Zustand store only
 *   - ALWAYS clear error state when starting new operations
 *   - All config values MUST come from Pydantic backend via useConfigStore
 * ---/agentspec
 */
export function useCards() {
  const { api } = useAPI();
  const {
    cards,
    lastBuild,
    isLoading,
    isBuilding,
    buildInProgress,
    buildStage,
    buildProgress,
    progressRepo,
    error,
    setCards,
    setLastBuild,
    setIsLoading,
    setIsBuilding,
    setBuildInProgress,
    setBuildStage,
    setBuildProgress,
    setProgressRepo,
    setError,
  } = useCardsStore();

  const load = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const response = await fetch(api('/api/cards'));
      if (!response.ok) {
        throw new Error(`Failed to load cards: ${response.status}`);
      }
      const data: CardsResponse = await response.json();
      setCards(Array.isArray(data.cards) ? data.cards : []);
      setLastBuild(data.last_build || null);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error loading cards';
      setError(message);
      console.error('[useCards] Load error:', err);
    } finally {
      setIsLoading(false);
    }
  }, [api]);

  const build = useCallback(async (options: CardsBuildOptions) => {
    try {
      setIsBuilding(true);
      setError(null);

      const params = new URLSearchParams({
        repo: options.repo,
        enrich: options.enrich ? '1' : '0',
        exclude_dirs: options.exclude_dirs || '',
        exclude_patterns: options.exclude_patterns || '',
        exclude_keywords: options.exclude_keywords || ''
      });

      const response = await fetch(api(`/api/cards/build/start?${params}`), {
        method: 'POST'
      });

      if (response.status === 409) {
        const data = await response.json();
        throw new Error(data.detail || 'Job already running');
      }

      if (!response.ok) {
        throw new Error(`Failed to start cards build: ${response.status}`);
      }

      const data = await response.json();
      return data.job_id;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error building cards';
      setError(message);
      console.error('[useCards] Build error:', err);
      throw err;
    } finally {
      setIsBuilding(false);
    }
  }, [api]);

  const deleteCard = useCallback(async (cardId: string) => {
    try {
      const response = await fetch(api(`/api/cards/${cardId}`), {
        method: 'DELETE'
      });

      if (!response.ok) {
        throw new Error(`Failed to delete card: ${response.status}`);
      }

      // Remove from local state
      setCards(prev => prev.filter(c => c.id !== cardId));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error deleting card';
      setError(message);
      console.error('[useCards] Delete error:', err);
      throw err;
    }
  }, [api]);

  const jumpToLine = useCallback((filePath: string, lineNumber: number | string) => {
    // Dispatch custom event for navigation
    const event = new CustomEvent('cardNavigation', {
      detail: { file: filePath, line: lineNumber }
    });
    window.dispatchEvent(event);
  }, []);

  // Load cards on mount
  useEffect(() => {
    load();
  }, [load]);

  return {
    cards,
    lastBuild,
    isLoading,
    isBuilding,
    buildInProgress,
    buildStage,
    buildProgress,
    progressRepo,
    error,
    load,
    build,
    deleteCard,
    jumpToLine,
    setBuildInProgress,
    setBuildStage,
    setBuildProgress,
    setProgressRepo,
  };
}
