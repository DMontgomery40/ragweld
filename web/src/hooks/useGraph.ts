/**
 * useGraph - Hook for knowledge graph operations
 *
 * Uses types from generated.ts (Pydantic-first architecture):
 * - Entity, Relationship, Community, GraphStats
 *
 * USAGE:
 *   const {
 *     entities,
 *     relationships,
 *     communities,
 *     stats,
 *     loadGraph,
 *     searchEntities,
 *     getNeighbors,
 *     selectEntity,
 *     selectCommunity,
 *   } = useGraph();
 */
import { useCallback, useEffect } from 'react';
import { useGraphStore } from '@/stores/useGraphStore';
import { useRepoStore } from '@/stores';
import type { Entity, Relationship, Community, GraphStats } from '@/types/generated';

const GRAPH_API_BASE = '/api/graph';

export function useGraph() {
  const { activeRepo } = useRepoStore();
  const {
    entities,
    relationships,
    communities,
    stats,
    selectedEntity,
    selectedCommunity,
    isLoading,
    error,
    visibleEntityTypes,
    visibleRelationTypes,
    maxHops,
    setEntities,
    setRelationships,
    setCommunities,
    setStats,
    setSelectedEntity,
    setSelectedCommunity,
    setIsLoading,
    setError,
    setVisibleEntityTypes,
    setVisibleRelationTypes,
    setMaxHops,
    reset,
  } = useGraphStore();

  /**
   * Load graph statistics for the current repository
   */
  const loadStats = useCallback(async (): Promise<GraphStats | null> => {
    if (!activeRepo) {
      setError('No repository selected');
      return null;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`${GRAPH_API_BASE}/${encodeURIComponent(activeRepo)}/stats`);
      if (!response.ok) {
        throw new Error(`Failed to load graph stats: ${response.status}`);
      }
      const data: GraphStats = await response.json();
      setStats(data);
      return data;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load graph stats';
      setError(message);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, [activeRepo, setStats, setIsLoading, setError]);

  /**
   * Load all communities for the current repository
   */
  const loadCommunities = useCallback(async (): Promise<Community[]> => {
    if (!activeRepo) {
      setError('No repository selected');
      return [];
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`${GRAPH_API_BASE}/${encodeURIComponent(activeRepo)}/communities`);
      if (!response.ok) {
        throw new Error(`Failed to load communities: ${response.status}`);
      }
      const data: Community[] = await response.json();
      setCommunities(data);
      return data;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load communities';
      setError(message);
      return [];
    } finally {
      setIsLoading(false);
    }
  }, [activeRepo, setCommunities, setIsLoading, setError]);

  /**
   * Search for entities matching a query
   */
  const searchEntities = useCallback(
    async (query: string, limit: number = 50): Promise<Entity[]> => {
      if (!activeRepo) {
        setError('No repository selected');
        return [];
      }

      setIsLoading(true);
      setError(null);

      try {
        const response = await fetch(
          `${GRAPH_API_BASE}/${encodeURIComponent(activeRepo)}/entities?limit=${encodeURIComponent(String(limit))}`
        );
        if (!response.ok) {
          throw new Error(`Failed to search entities: ${response.status}`);
        }
        const data: Entity[] = await response.json();
        const q = query.trim().toLowerCase();
        const filtered = q ? data.filter((e) => (e.name || '').toLowerCase().includes(q)) : data;
        setEntities(filtered);
        return filtered;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to search entities';
        setError(message);
        return [];
      } finally {
        setIsLoading(false);
      }
    },
    [activeRepo, setEntities, setIsLoading, setError]
  );

  /**
   * Get neighbors of an entity within N hops
   */
  const getNeighbors = useCallback(
    async (_entityId: string, _hops: number = maxHops): Promise<{ entities: Entity[]; relationships: Relationship[] }> => {
      if (!activeRepo) {
        setError('No repository selected');
        return { entities: [], relationships: [] };
      }

      setIsLoading(true);
      setError(null);

      try {
        setError('Neighbor lookup is not implemented for graph API yet');
        return { entities: [], relationships: [] };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to get neighbors';
        setError(message);
        return { entities: [], relationships: [] };
      } finally {
        setIsLoading(false);
      }
    },
    [activeRepo, maxHops, setEntities, setRelationships, setIsLoading, setError]
  );

  /**
   * Get all entities in a community
   */
  const getCommunityMembers = useCallback(
    async (_communityId: string): Promise<Entity[]> => {
      if (!activeRepo) {
        setError('No repository selected');
        return [];
      }

      setIsLoading(true);
      setError(null);

      try {
        setError('Community member lookup is not implemented for graph API yet');
        return [];
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to get community members';
        setError(message);
        return [];
      } finally {
        setIsLoading(false);
      }
    },
    [activeRepo, setIsLoading, setError]
  );

  /**
   * Select an entity and load its neighbors
   */
  const selectEntity = useCallback(
    async (entity: Entity | null) => {
      setSelectedEntity(entity);
      setSelectedCommunity(null);

      if (entity) {
        await getNeighbors(entity.entity_id);
      }
    },
    [setSelectedEntity, setSelectedCommunity, getNeighbors]
  );

  /**
   * Select a community and load its members
   */
  const selectCommunity = useCallback(
    async (community: Community | null) => {
      setSelectedCommunity(community);
      setSelectedEntity(null);

      if (community) {
        const members = await getCommunityMembers(community.community_id);
        setEntities(members);
        setRelationships([]);
      }
    },
    [setSelectedCommunity, setSelectedEntity, getCommunityMembers, setEntities, setRelationships]
  );

  /**
   * Filter entities by type
   */
  const getEntitiesByType = useCallback(
    (types: string[]): Entity[] => {
      if (types.length === 0) return entities;
      return entities.filter((e) => types.includes(e.entity_type));
    },
    [entities]
  );

  /**
   * Filter relationships by type
   */
  const getRelationshipsByType = useCallback(
    (types: string[]): Relationship[] => {
      if (types.length === 0) return relationships;
      return relationships.filter((r) => types.includes(r.relation_type));
    },
    [relationships]
  );

  /**
   * Load initial graph data when repo changes
   */
  const loadGraph = useCallback(async () => {
    if (!activeRepo) return;

    reset();
    await loadStats();
    await loadCommunities();
  }, [activeRepo, reset, loadStats, loadCommunities]);

  // Load graph when active repo changes
  useEffect(() => {
    if (activeRepo) {
      loadGraph();
    }
  }, [activeRepo, loadGraph]);

  return {
    // State
    entities,
    relationships,
    communities,
    stats,
    selectedEntity,
    selectedCommunity,
    isLoading,
    error,
    visibleEntityTypes,
    visibleRelationTypes,
    maxHops,

    // Actions
    loadStats,
    loadCommunities,
    loadGraph,
    searchEntities,
    getNeighbors,
    getCommunityMembers,
    selectEntity,
    selectCommunity,
    reset,

    // Filter controls
    setVisibleEntityTypes,
    setVisibleRelationTypes,
    setMaxHops,

    // Computed
    getEntitiesByType,
    getRelationshipsByType,

    // Derived
    entityCount: entities.length,
    relationshipCount: relationships.length,
    communityCount: communities.length,
    hasData: entities.length > 0 || communities.length > 0,
  };
}

export default useGraph;
