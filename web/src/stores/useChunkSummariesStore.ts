/**
 * Chunk Summaries Store (formerly "Cards Store")
 *
 * Per CLAUDE.md: "cards" is a banned term - use "chunk_summaries" instead.
 */
import { create } from 'zustand';
import type { ChunkSummary, LastBuild } from '@/types/chunk_summaries';

interface ChunkSummariesStore {
  // State
  chunkSummaries: ChunkSummary[];
  lastBuild: LastBuild | null;
  isLoading: boolean;
  isBuilding: boolean;
  buildInProgress: boolean;
  buildStage: string;
  buildProgress: number;
  progressRepo: string;
  error: string | null;

  // Actions
  setChunkSummaries: (summaries: ChunkSummary[] | ((prev: ChunkSummary[]) => ChunkSummary[])) => void;
  setLastBuild: (build: LastBuild | null) => void;
  setIsLoading: (loading: boolean) => void;
  setIsBuilding: (building: boolean) => void;
  setBuildInProgress: (inProgress: boolean) => void;
  setBuildStage: (stage: string) => void;
  setBuildProgress: (progress: number) => void;
  setProgressRepo: (repo: string) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

export const useChunkSummariesStore = create<ChunkSummariesStore>()((set) => ({
  // Initial state
  chunkSummaries: [],
  lastBuild: null,
  isLoading: false,
  isBuilding: false,
  buildInProgress: false,
  buildStage: '',
  buildProgress: 0,
  progressRepo: '',
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
  setBuildInProgress: (buildInProgress) => set({ buildInProgress }),
  setBuildStage: (buildStage) => set({ buildStage }),
  setBuildProgress: (buildProgress) => set({ buildProgress }),
  setProgressRepo: (progressRepo) => set({ progressRepo }),
  setError: (error) => set({ error }),
  reset: () =>
    set({
      chunkSummaries: [],
      lastBuild: null,
      isLoading: false,
      isBuilding: false,
      buildInProgress: false,
      buildStage: '',
      buildProgress: 0,
      progressRepo: '',
      error: null,
    }),
}));

// Legacy alias for backward compatibility
export const useCardsStore = useChunkSummariesStore;
