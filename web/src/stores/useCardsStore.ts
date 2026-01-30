import { create } from 'zustand';

export interface Card {
  file_path: string;
  start_line?: number;
  end_line?: number;
  purpose?: string;
  symbols?: string[];
  technical_details?: string;
  domain_concepts?: string[];
}

export interface LastBuild {
  timestamp?: string;
  repo?: string;
  total?: number;
  enriched?: number;
}

interface CardsStore {
  // State
  cards: Card[];
  lastBuild: LastBuild | null;
  isLoading: boolean;
  isBuilding: boolean;
  buildInProgress: boolean;
  buildStage: string;
  buildProgress: number;
  progressRepo: string;
  error: string | null;

  // Actions
  setCards: (cards: Card[]) => void;
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

export const useCardsStore = create<CardsStore>()((set) => ({
  // Initial state
  cards: [],
  lastBuild: null,
  isLoading: false,
  isBuilding: false,
  buildInProgress: false,
  buildStage: '',
  buildProgress: 0,
  progressRepo: '',
  error: null,

  // Actions
  setCards: (cards) => set({ cards }),
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
      cards: [],
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
