/**
 * Graph Store - Zustand store for knowledge graph state
 *
 * Uses public wire types from generated.ts:
 * - Entity, Relationship, Community, GraphStats
 */
import { create } from 'zustand';
import type { Entity, Relationship, Community, GraphStats } from '@/types/generated';

/**
 * Outcome of the last entity expansion. Local UI state, not a wire contract.
 * `null` means nothing has been expanded; a `failed` entry keeps the operator's
 * results on screen and lets the details pane say what actually went wrong
 * instead of looping "select an entity to load its neighborhood" (M-01, M-65).
 */
export interface EntityExpansion {
  entityId: string;
  status: 'ok' | 'failed';
  /** Server `detail` when the expansion failed; empty on success. */
  detail: string;
}

interface GraphStore {
  // State
  entities: Entity[];
  relationships: Relationship[];
  communities: Community[];
  stats: GraphStats | null;
  selectedEntity: Entity | null;
  selectedCommunity: Community | null;
  isLoading: boolean;
  error: string | null;
  expansion: EntityExpansion | null;
  viewMode: 'viz' | 'table';
  /** Entities matching the last load before the display limit was applied (the denominator). */
  totalMatched: number;
  /** Search term the currently displayed entities were loaded with; '' means the whole corpus. */
  activeQuery: string;

  // Filter state
  visibleEntityTypes: string[];
  visibleRelationTypes: string[];
  maxHops: number;

  // Actions
  setEntities: (entities: Entity[]) => void;
  setRelationships: (relationships: Relationship[]) => void;
  setCommunities: (communities: Community[]) => void;
  setStats: (stats: GraphStats | null) => void;
  setSelectedEntity: (entity: Entity | null) => void;
  setSelectedCommunity: (community: Community | null) => void;
  setIsLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setExpansion: (expansion: EntityExpansion | null) => void;
  setTotalMatched: (total: number) => void;
  setActiveQuery: (query: string) => void;
  setViewMode: (mode: 'viz' | 'table') => void;
  setVisibleEntityTypes: (types: string[]) => void;
  setVisibleRelationTypes: (types: string[]) => void;
  setMaxHops: (hops: number) => void;
  reset: () => void;
}

/** Server cap on `/graph/{corpus}/subgraph?limit=`; the picker must not offer more. */
export const MAX_ENTITY_LIMIT = 2000;
export const DEFAULT_ENTITY_LIMIT = 200;
export const ENTITY_LIMIT_CHOICES = [100, 200, 500, 1000, MAX_ENTITY_LIMIT] as const;

const defaultEntityTypes: string[] = [];
const defaultRelationTypes: string[] = [];

export const useGraphStore = create<GraphStore>()((set) => ({
  // Initial state
  entities: [],
  relationships: [],
  communities: [],
  stats: null,
  selectedEntity: null,
  selectedCommunity: null,
  isLoading: false,
  error: null,
  expansion: null,
  viewMode: 'viz',
  totalMatched: 0,
  activeQuery: '',
  visibleEntityTypes: defaultEntityTypes,
  visibleRelationTypes: defaultRelationTypes,
  maxHops: 2,

  // Actions
  setEntities: (entities) => set({ entities }),
  setRelationships: (relationships) => set({ relationships }),
  setCommunities: (communities) => set({ communities }),
  setStats: (stats) => set({ stats }),
  setSelectedEntity: (selectedEntity) => set({ selectedEntity }),
  setSelectedCommunity: (selectedCommunity) => set({ selectedCommunity }),
  setIsLoading: (isLoading) => set({ isLoading }),
  setError: (error) => set({ error }),
  setExpansion: (expansion) => set({ expansion }),
  setTotalMatched: (totalMatched) => set({ totalMatched: Math.max(0, totalMatched) }),
  setActiveQuery: (activeQuery) => set({ activeQuery }),
  setViewMode: (viewMode) => set({ viewMode }),
  setVisibleEntityTypes: (visibleEntityTypes) => set({ visibleEntityTypes }),
  setVisibleRelationTypes: (visibleRelationTypes) => set({ visibleRelationTypes }),
  setMaxHops: (maxHops) => set({ maxHops }),
  reset: () =>
    set((state) => ({
      entities: [],
      relationships: [],
      communities: [],
      stats: null,
      selectedEntity: null,
      selectedCommunity: null,
      isLoading: false,
      error: null,
      expansion: null,
      totalMatched: 0,
      activeQuery: '',
      viewMode: state.viewMode,
      visibleEntityTypes: defaultEntityTypes,
      visibleRelationTypes: defaultRelationTypes,
      maxHops: 2,
    })),
}));

export default useGraphStore;
