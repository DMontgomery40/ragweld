/**
 * Chunk Summaries Store
 *
 * Uses types from generated.ts (Pydantic-first):
 * - ChunkSummary
 * - ChunkSummariesLastBuild
 */

import { create } from 'zustand';
import type { ChunkSummary, ChunkSummariesLastBuild } from '@/types/generated';

interface ChunkSummariesStore {
  // State
  chunkSummaries: ChunkSummary[];
  lastBuild: ChunkSummariesLastBuild | null;
  isLoading: boolean;
  isBuilding: boolean;
  error: string | null;

  // Actions
  setChunkSummaries: (summaries: ChunkSummary[] | ((prev: ChunkSummary[]) => ChunkSummary[])) => void;
  setLastBuild: (build: ChunkSummariesLastBuild | null) => void;
  setIsLoading: (loading: boolean) => void;
  setIsBuilding: (building: boolean) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

export const useChunkSummariesStore = create<ChunkSummariesStore>()((set) => ({
  // Initial state
  chunkSummaries: [],
  lastBuild: null,
  isLoading: false,
  isBuilding: false,
  error: null,

  // Actions
  setChunkSummaries: (summaries) =>
    set((state) => ({
      chunkSummaries:
        typeof summaries === 'function' ? summaries(state.chunkSummaries) : summaries,
    })),
  setLastBuild: (lastBuild) => set({ lastBuild }),
  setIsLoading: (isLoading) => set({ isLoading }),
  setIsBuilding: (isBuilding) => set({ isBuilding }),
  setError: (error) => set({ error }),
  reset: () =>
    set({
      chunkSummaries: [],
      lastBuild: null,
      isLoading: false,
      isBuilding: false,
      error: null,
    }),
}));

// Legacy alias - DO NOT USE in new code
export const useCardsStore = useChunkSummariesStore;
