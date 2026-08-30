/**
 * useGraph - Hook for knowledge graph operations
 *
 * Uses public wire types from generated.ts:
 * - Entity, Relationship, Community, GraphStats
 *
 * USAGE:
 *   const {
 *     entities,
 *     relationships,
 *     communities,
 *     stats,
 *     loadGraph,
  *     loadSubgraph,
 *     getNeighbors,
 *     selectEntity,
 *     selectCommunity,
 *   } = useGraph();
 */
import { useCallback, useEffect } from 'react';
import { DEFAULT_ENTITY_LIMIT, useGraphStore } from '@/stores/useGraphStore';
import { useRepoStore } from '@/stores';
import type { Entity, Relationship, Community, GraphStats, GraphNeighborsResponse } from '@/types/generated';

const GRAPH_API_BASE = '/api/graph';

/**
 * The server's own `detail` for a failed graph call. The operator needs to read
 * which id or corpus the backend rejected; a bare status code is not actionable
 * and swallowing the failure silently is what made M-01 invisible.
 */
async function failureDetail(response: Response, action: string): Promise<string> {
  let detail = '';
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body?.detail === 'string') detail = body.detail.trim();
  } catch {
    detail = '';
  }
  return detail ? `${action}: ${detail}` : `${action} (HTTP ${response.status})`;
}

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
    expansion,
    viewMode,
    totalMatched,
    activeQuery,
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
    setExpansion,
    setTotalMatched,
    setActiveQuery,
    setViewMode,
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
   * Get neighbors of an entity within N hops
   */
  const getNeighbors = useCallback(
    async (entityId: string, hops: number = maxHops): Promise<{ entities: Entity[]; relationships: Relationship[] } | null> => {
      if (!activeRepo) {
        setError('No repository selected');
        return null;
      }

      setIsLoading(true);
      setError(null);

      try {
        const safeHops = Math.max(1, Math.min(5, Number.isFinite(hops) ? Math.floor(hops) : maxHops));
        const params = new URLSearchParams({
          entity_id: entityId,
          max_hops: String(safeHops),
          limit: String(200),
        });
        const url = `${GRAPH_API_BASE}/${encodeURIComponent(activeRepo)}/entity/neighbors?${params.toString()}`;

        const response = await fetch(url);
        if (!response.ok) {
          // A failed expansion leaves the operator's results and graph exactly as
          // they were and reports the server's reason. Blanking the view on 404
          // destroyed the search results and told nobody why (M-01).
          const message = await failureDetail(response, 'Could not expand this entity');
          setError(message);
          setExpansion({ entityId, status: 'failed', detail: message });
          return null;
        }

        const data: GraphNeighborsResponse = await response.json();
        const ents = Array.isArray(data.entities) ? data.entities : [];
        const rels = Array.isArray(data.relationships) ? data.relationships : [];

        setEntities(ents);
        setRelationships(rels);
        setExpansion({ entityId, status: 'ok', detail: '' });
        return { entities: ents, relationships: rels };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Could not expand this entity';
        setError(message);
        setExpansion({ entityId, status: 'failed', detail: message });
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [activeRepo, maxHops, setEntities, setRelationships, setIsLoading, setError, setExpansion]
  );

  /**
   * Get a community subgraph (members + edges between members)
   */
  const getCommunitySubgraph = useCallback(
    async (
      communityId: string,
      limit: number = 200
    ): Promise<{ entities: Entity[]; relationships: Relationship[] } | null> => {
      if (!activeRepo) {
        setError('No repository selected');
        return null;
      }

      setIsLoading(true);
      setError(null);

      try {
        const url = `${GRAPH_API_BASE}/${encodeURIComponent(activeRepo)}/community/${encodeURIComponent(communityId)}/subgraph` +
          `?limit=${encodeURIComponent(String(limit))}`;

        const response = await fetch(url);
        if (!response.ok) {
          setError(await failureDetail(response, 'Could not load this community'));
          return null;
        }

        const data: GraphNeighborsResponse = await response.json();
        const ents = Array.isArray(data.entities) ? data.entities : [];
        const rels = Array.isArray(data.relationships) ? data.relationships : [];
        return { entities: ents, relationships: rels };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Could not load this community';
        setError(message);
        return null;
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
      setExpansion(null);

      if (entity) {
        await getNeighbors(entity.entity_id);
      }
    },
    [setSelectedEntity, setSelectedCommunity, setExpansion, getNeighbors]
  );

  /**
   * Select a community and load its members
   */
  const selectCommunity = useCallback(
    async (community: Community | null) => {
      setSelectedCommunity(community);
      setSelectedEntity(null);
      setExpansion(null);

      if (community) {
        const sub = await getCommunitySubgraph(community.community_id, 250);
        if (sub === null) return;
        setEntities(sub.entities);
        setRelationships(sub.relationships);
      }
    },
    [
      setSelectedCommunity,
      setSelectedEntity,
      setExpansion,
      getCommunitySubgraph,
      setEntities,
      setRelationships,
    ]
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
  /**
   * Load the whole-corpus induced subgraph (best-connected entities + the edges
   * between them). The entity list alone carried no relationships, so the
   * corpus-level visualizer drew "N nodes • 0 edges" (2026-08-25 finding G2).
   */
  const loadSubgraph = useCallback(
    async (
      limit: number = DEFAULT_ENTITY_LIMIT,
      query: string = ''
    ): Promise<{ entities: Entity[]; relationships: Relationship[] } | null> => {
      if (!activeRepo) {
        setError('No repository selected');
        return null;
      }
      setIsLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({ limit: String(limit) });
        const q = query.trim();
        if (q) params.set('q', q);
        const url = `${GRAPH_API_BASE}/${encodeURIComponent(activeRepo)}/subgraph?${params.toString()}`;
        const response = await fetch(url);
        if (!response.ok) {
          setError(await failureDetail(response, 'Could not load the corpus graph'));
          return null;
        }
        const data: GraphNeighborsResponse = await response.json();
        const ents = Array.isArray(data.entities) ? data.entities : [];
        const rels = Array.isArray(data.relationships) ? data.relationships : [];
        setEntities(ents);
        setRelationships(rels);
        setTotalMatched(Number(data.total_matched ?? ents.length));
        setActiveQuery(q);
        setSelectedEntity(null);
        setExpansion(null);
        return { entities: ents, relationships: rels };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Could not load the corpus graph';
        setError(message);
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [
      activeRepo,
      setEntities,
      setRelationships,
      setTotalMatched,
      setActiveQuery,
      setSelectedEntity,
      setExpansion,
      setIsLoading,
      setError,
    ]
  );

  const loadGraph = useCallback(async () => {
    if (!activeRepo) return;

    reset();
    await Promise.all([loadStats(), loadCommunities(), loadSubgraph(DEFAULT_ENTITY_LIMIT, '')]);
  }, [activeRepo, reset, loadStats, loadCommunities, loadSubgraph]);

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
    expansion,
    viewMode,
    totalMatched,
    activeQuery,
    visibleEntityTypes,
    visibleRelationTypes,
    maxHops,

    // Actions
    loadStats,
    loadCommunities,
    loadGraph,
    loadSubgraph,
    getNeighbors,
    getCommunitySubgraph,
    selectEntity,
    selectCommunity,
    reset,

    // Filter controls
    setVisibleEntityTypes,
    setVisibleRelationTypes,
    setMaxHops,
    setViewMode,

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
