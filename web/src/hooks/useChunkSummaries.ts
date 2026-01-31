/**
 * useChunkSummaries - Hook for managing chunk summaries
 *
 * Uses types from generated.ts (Pydantic-first):
 * - ChunkSummary
 * - ChunkSummariesResponse
 * - ChunkSummariesBuildRequest
 * - ChunkSummariesLastBuild
 */

import { useCallback, useEffect } from 'react';
import { useAPI } from './useAPI';
import { useChunkSummariesStore } from '@/stores/useChunkSummariesStore';
import type {
  ChunkSummariesResponse,
  ChunkSummariesBuildRequest,
} from '@/types/generated';

const CHUNK_SUMMARIES_API = '/api/chunk_summaries';

export function useChunkSummaries() {
  const { api } = useAPI();
  const {
    chunkSummaries,
    lastBuild,
    isLoading,
    isBuilding,
    error,
    setChunkSummaries,
    setLastBuild,
    setIsLoading,
    setIsBuilding,
    setError,
  } = useChunkSummariesStore();

  const load = useCallback(async (corpusId?: string) => {
    try {
      setIsLoading(true);
      setError(null);
      const url = corpusId
        ? api(`${CHUNK_SUMMARIES_API}?corpus_id=${encodeURIComponent(corpusId)}`)
        : api(CHUNK_SUMMARIES_API);
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Failed to load chunk summaries: ${response.status}`);
      }
      const data: ChunkSummariesResponse = await response.json();
      setChunkSummaries(Array.isArray(data.chunk_summaries) ? data.chunk_summaries : []);
      setLastBuild(data.last_build ?? null);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error loading chunk summaries';
      setError(message);
      console.error('[useChunkSummaries] Load error:', err);
    } finally {
      setIsLoading(false);
    }
  }, [api, setChunkSummaries, setLastBuild, setIsLoading, setError]);

  const build = useCallback(
    async (request: ChunkSummariesBuildRequest): Promise<ChunkSummariesResponse> => {
      try {
        setIsBuilding(true);
        setError(null);

        const response = await fetch(api(`${CHUNK_SUMMARIES_API}/build`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(request),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `Failed to build chunk summaries: ${response.status}`);
        }

        const data: ChunkSummariesResponse = await response.json();
        setChunkSummaries(data.chunk_summaries);
        setLastBuild(data.last_build ?? null);
        return data;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Unknown error building chunk summaries';
        setError(message);
        console.error('[useChunkSummaries] Build error:', err);
        throw err;
      } finally {
        setIsBuilding(false);
      }
    },
    [api, setChunkSummaries, setLastBuild, setIsBuilding, setError]
  );

  const jumpToLine = useCallback((filePath: string, lineNumber: number | string) => {
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
    // State
    chunkSummaries,
    lastBuild,
    isLoading,
    isBuilding,
    error,

    // Actions
    load,
    build,
    jumpToLine,

    // Legacy aliases - DO NOT USE in new code
    cards: chunkSummaries,
  };
}

// Legacy alias - DO NOT USE in new code
export const useCards = useChunkSummaries;

export default useChunkSummaries;
