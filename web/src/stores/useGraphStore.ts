/**
 * Graph Store - Zustand store for knowledge graph state
 *
 * Uses types from generated.ts (Pydantic-first architecture):
 * - Entity, Relationship, Community, GraphStats
 */
import { create } from 'zustand';
import type { Entity, Relationship, Community, GraphStats } from '@/types/generated';

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
  setVisibleEntityTypes: (types: string[]) => void;
  setVisibleRelationTypes: (types: string[]) => void;
  setMaxHops: (hops: number) => void;
  reset: () => void;
}

const defaultEntityTypes = ['function', 'class', 'module', 'variable', 'concept'];
const defaultRelationTypes = ['calls', 'imports', 'inherits', 'contains', 'references', 'related_to'];

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
  setVisibleEntityTypes: (visibleEntityTypes) => set({ visibleEntityTypes }),
  setVisibleRelationTypes: (visibleRelationTypes) => set({ visibleRelationTypes }),
  setMaxHops: (maxHops) => set({ maxHops }),
  reset: () =>
    set({
      entities: [],
      relationships: [],
      communities: [],
      stats: null,
      selectedEntity: null,
      selectedCommunity: null,
      isLoading: false,
      error: null,
      visibleEntityTypes: defaultEntityTypes,
      visibleRelationTypes: defaultRelationTypes,
      maxHops: 2,
    }),
}));

export default useGraphStore;
