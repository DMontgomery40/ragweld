/**
 * useChunkSummaries - Hook for managing chunk summaries (formerly "cards")
 *
 * Per CLAUDE.md: "cards" is a banned term - use "chunk_summaries" instead.
 *
 * Uses centralized Zustand store for state management with Pydantic validation from backend.
 */
import { useCallback, useEffect } from 'react';
import { useAPI } from './useAPI';
import { useChunkSummariesStore } from '@/stores/useChunkSummariesStore';
import type {
  ChunkSummariesResponse,
  ChunkSummaryBuildOptions,
} from '@/types/chunk_summaries';

export function useChunkSummaries() {
  const { api } = useAPI();
  const {
    chunkSummaries,
    lastBuild,
    isLoading,
    isBuilding,
    buildInProgress,
    buildStage,
    buildProgress,
    progressRepo,
    error,
    setChunkSummaries,
    setLastBuild,
    setIsLoading,
    setIsBuilding,
    setBuildInProgress,
    setBuildStage,
    setBuildProgress,
    setProgressRepo,
    setError,
  } = useChunkSummariesStore();

  const load = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      // API endpoint still uses /api/cards for backward compatibility
      const response = await fetch(api('/api/cards'));
      if (!response.ok) {
        throw new Error(`Failed to load chunk summaries: ${response.status}`);
      }
      const data: ChunkSummariesResponse = await response.json();
      setChunkSummaries(Array.isArray(data.chunk_summaries) ? data.chunk_summaries : []);
      setLastBuild(data.last_build || null);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error loading chunk summaries';
      setError(message);
      console.error('[useChunkSummaries] Load error:', err);
    } finally {
      setIsLoading(false);
    }
  }, [api, setChunkSummaries, setLastBuild, setIsLoading, setError]);

  const build = useCallback(
    async (options: ChunkSummaryBuildOptions) => {
      try {
        setIsBuilding(true);
        setError(null);

        const params = new URLSearchParams({
          repo: options.repo,
          enrich: options.enrich ? '1' : '0',
          exclude_dirs: options.exclude_dirs || '',
          exclude_patterns: options.exclude_patterns || '',
          exclude_keywords: options.exclude_keywords || '',
        });

        // API endpoint still uses /api/cards for backward compatibility
        const response = await fetch(api(`/api/cards/build/start?${params}`), {
          method: 'POST',
        });

        if (response.status === 409) {
          const data = await response.json();
          throw new Error(data.detail || 'Job already running');
        }

        if (!response.ok) {
          throw new Error(`Failed to start chunk summaries build: ${response.status}`);
        }

        const data = await response.json();
        return data.job_id;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Unknown error building chunk summaries';
        setError(message);
        console.error('[useChunkSummaries] Build error:', err);
        throw err;
      } finally {
        setIsBuilding(false);
      }
    },
    [api, setIsBuilding, setError]
  );

  const deleteChunkSummary = useCallback(
    async (summaryId: string) => {
      try {
        // API endpoint still uses /api/cards for backward compatibility
        const response = await fetch(api(`/api/cards/${summaryId}`), {
          method: 'DELETE',
        });

        if (!response.ok) {
          throw new Error(`Failed to delete chunk summary: ${response.status}`);
        }

        // Remove from local state
        setChunkSummaries((prev) => prev.filter((s) => s.file_path !== summaryId));
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Unknown error deleting chunk summary';
        setError(message);
        console.error('[useChunkSummaries] Delete error:', err);
        throw err;
      }
    },
    [api, setChunkSummaries, setError]
  );

  const jumpToLine = useCallback((filePath: string, lineNumber: number | string) => {
    // Dispatch custom event for navigation
    const event = new CustomEvent('chunkSummaryNavigation', {
      detail: { file: filePath, line: lineNumber },
    });
    window.dispatchEvent(event);
  }, []);

  // Load chunk summaries on mount
  useEffect(() => {
    load();
  }, [load]);

  return {
    // State - using new names
    chunkSummaries,
    lastBuild,
    isLoading,
    isBuilding,
    buildInProgress,
    buildStage,
    buildProgress,
    progressRepo,
    error,

    // Actions
    load,
    build,
    deleteChunkSummary,
    jumpToLine,
    setBuildInProgress,
    setBuildStage,
    setBuildProgress,
    setProgressRepo,

    // Legacy aliases for backward compatibility
    cards: chunkSummaries,
    deleteCard: deleteChunkSummary,
  };
}

// Legacy alias for backward compatibility
export const useCards = useChunkSummaries;

export default useChunkSummaries;
