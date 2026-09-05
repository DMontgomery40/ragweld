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
import { DEFAULT_ENTITY_LIMIT, useGraphStore, type GraphRequest, type GraphRequestKind } from '@/stores/useGraphStore';
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
    scope,
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
    beginRequest,
    isCurrentRequest,
    finishRequest,
    setError,
    setExpansion,
    setScope,
    setTotalMatched,
    setActiveQuery,
    setViewMode,
    setVisibleEntityTypes,
    setVisibleRelationTypes,
    setMaxHops,
    reset,
  } = useGraphStore();

  const begin = useCallback((kind: GraphRequestKind): GraphRequest | null => {
    // A callback from a departing corpus must not reclaim the shared graph.
    if (!activeRepo || useRepoStore.getState().activeRepo !== activeRepo) return null;
    return beginRequest(activeRepo, kind);
  }, [activeRepo, beginRequest]);

  const current = useCallback((request: GraphRequest): boolean => (
    useRepoStore.getState().activeRepo === request.corpusId && isCurrentRequest(request)
  ), [isCurrentRequest]);

  /**
   * Load graph statistics for the current repository
   */
  const loadStats = useCallback(async (): Promise<GraphStats | null> => {
    if (!activeRepo) {
      setError('No repository selected');
      return null;
    }

    const request = begin('stats');
    if (!request) return null;
    setError(null);

    try {
      const response = await fetch(`${GRAPH_API_BASE}/${encodeURIComponent(activeRepo)}/stats`);
      if (!response.ok) {
        throw new Error(`Failed to load graph stats: ${response.status}`);
      }
      const data: GraphStats = await response.json();
      if (!current(request)) return null;
      setStats(data);
      return data;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load graph stats';
      if (current(request)) setError(message);
      return null;
    } finally {
      finishRequest(request);
    }
  }, [activeRepo, setStats, begin, current, finishRequest, setError]);

  /**
   * Load all communities for the current repository
   */
  const loadCommunities = useCallback(async (): Promise<Community[]> => {
    if (!activeRepo) {
      setError('No repository selected');
      return [];
    }

    const request = begin('communities');
    if (!request) return [];
    setError(null);

    try {
      const response = await fetch(`${GRAPH_API_BASE}/${encodeURIComponent(activeRepo)}/communities`);
      if (!response.ok) {
        throw new Error(`Failed to load communities: ${response.status}`);
      }
      const data: Community[] = await response.json();
      if (!current(request)) return [];
      setCommunities(data);
      return data;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load communities';
      if (current(request)) setError(message);
      return [];
    } finally {
      finishRequest(request);
    }
  }, [activeRepo, setCommunities, begin, current, finishRequest, setError]);

  /**
   * Get neighbors of an entity within N hops
   */
  const getNeighbors = useCallback(
    async (entityId: string, hops: number = maxHops, ticket?: GraphRequest): Promise<{ entities: Entity[]; relationships: Relationship[] } | null> => {
      if (!activeRepo) {
        setError('No repository selected');
        return null;
      }

      const request = ticket ?? begin('view');
      if (!request || !current(request)) return null;
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
          // One surface per failure: the expansion banner carries this one. Mirroring it
          // into `error` too rendered the same sentence in two stacked red boxes (F-02).
          const detail = await failureDetail(response, 'Could not expand this entity');
          if (!current(request)) return null;
          setExpansion({
            entityId,
            status: 'failed',
            detail,
          });
          return null;
        }

        const data: GraphNeighborsResponse = await response.json();
        if (!current(request)) return null;
        const ents = Array.isArray(data.entities) ? data.entities : [];
        const rels = Array.isArray(data.relationships) ? data.relationships : [];

        setEntities(ents);
        setRelationships(rels);
        setExpansion({ entityId, status: 'ok', detail: '' });
        setScope({ kind: 'neighborhood', entityId });
        return { entities: ents, relationships: rels };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Could not expand this entity';
        if (current(request)) setExpansion({ entityId, status: 'failed', detail: message });
        return null;
      } finally {
        finishRequest(request);
      }
    },
    [
      activeRepo,
      maxHops,
      setEntities,
      setRelationships,
      begin,
      current,
      finishRequest,
      setError,
      setExpansion,
      setScope,
    ]
  );

  /**
   * Get a community subgraph (members + edges between members)
   */
  const getCommunitySubgraph = useCallback(
    async (
      communityId: string,
      limit: number = 200,
      ticket?: GraphRequest
    ): Promise<{ entities: Entity[]; relationships: Relationship[] } | null> => {
      if (!activeRepo) {
        setError('No repository selected');
        return null;
      }

      const request = ticket ?? begin('view');
      if (!request || !current(request)) return null;
      setError(null);

      try {
        const url = `${GRAPH_API_BASE}/${encodeURIComponent(activeRepo)}/community/${encodeURIComponent(communityId)}/subgraph` +
          `?limit=${encodeURIComponent(String(limit))}`;

        const response = await fetch(url);
        if (!response.ok) {
          const detail = await failureDetail(response, 'Could not load this community');
          if (current(request)) setError(detail);
          return null;
        }

        const data: GraphNeighborsResponse = await response.json();
        if (!current(request)) return null;
        const ents = Array.isArray(data.entities) ? data.entities : [];
        const rels = Array.isArray(data.relationships) ? data.relationships : [];
        return { entities: ents, relationships: rels };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Could not load this community';
        if (current(request)) setError(message);
        return null;
      } finally {
        finishRequest(request);
      }
    },
    [activeRepo, begin, current, finishRequest, setError]
  );

  /**
   * Select an entity and load its neighbors
   */
  const selectEntity = useCallback(
    async (entity: Entity | null) => {
      const request = begin('view');
      if (!request) return;
      setExpansion(null);
      if (!entity) {
        setSelectedEntity(null);
        finishRequest(request);
        return;
      }
      // Nothing about the current view changes until the neighborhood is on screen.
      // Moving the selection first, or clearing the community first, would leave the
      // previous scope's rows on screen under the new entity's name and under the
      // corpus denominator (M-01 keeps the results; F-01 keeps them correctly labelled).
      const loaded = await getNeighbors(entity.entity_id, maxHops, request);
      if (!loaded || !current(request)) return;
      setSelectedEntity(entity);
      setSelectedCommunity(null);
    },
    [begin, current, finishRequest, maxHops, setSelectedEntity, setSelectedCommunity, setExpansion, getNeighbors]
  );

  /**
   * Select a community and load its members
   */
  const selectCommunity = useCallback(
    async (community: Community | null) => {
      const request = begin('view');
      if (!request) return;
      setExpansion(null);
      if (!community) {
        setSelectedCommunity(null);
        finishRequest(request);
        return;
      }
      const sub = await getCommunitySubgraph(community.community_id, 250, request);
      if (sub === null || !current(request)) return;
      setEntities(sub.entities);
      setRelationships(sub.relationships);
      setSelectedCommunity(community);
      setSelectedEntity(null);
      setScope({ kind: 'community', communityId: community.community_id });
    },
    [
      begin,
      current,
      finishRequest,
      setSelectedCommunity,
      setSelectedEntity,
      setExpansion,
      setScope,
      getCommunitySubgraph,
      setEntities,
      setRelationships,
    ]
  );

  /**
   * Filter entities by type
   */
  const getEntitiesByType = useCallback(
    (types: string[] | null): Entity[] => {
      if (types === null) return entities;
      return entities.filter((e) => types.includes(e.entity_type));
    },
    [entities]
  );

  /**
   * Filter relationships by type
   */
  const getRelationshipsByType = useCallback(
    (types: string[] | null): Relationship[] => {
      if (types === null) return relationships;
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
      const request = begin('view');
      if (!request) return null;
      setError(null);
      try {
        const params = new URLSearchParams({ limit: String(limit) });
        const q = query.trim();
        if (q) params.set('q', q);
        const url = `${GRAPH_API_BASE}/${encodeURIComponent(activeRepo)}/subgraph?${params.toString()}`;
        const response = await fetch(url);
        if (!response.ok) {
          const detail = await failureDetail(response, 'Could not load the corpus graph');
          if (current(request)) setError(detail);
          return null;
        }
        const data: GraphNeighborsResponse = await response.json();
        if (!current(request)) return null;
        const ents = Array.isArray(data.entities) ? data.entities : [];
        const rels = Array.isArray(data.relationships) ? data.relationships : [];
        setEntities(ents);
        setRelationships(rels);
        setTotalMatched(Number(data.total_matched ?? ents.length));
        setActiveQuery(q);
        setSelectedEntity(null);
        setSelectedCommunity(null);
        setExpansion(null);
        setScope(q ? { kind: 'search', query: q } : { kind: 'corpus' });
        return { entities: ents, relationships: rels };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Could not load the corpus graph';
        if (current(request)) setError(message);
        return null;
      } finally {
        finishRequest(request);
      }
    },
    [
      activeRepo,
      setEntities,
      setRelationships,
      setTotalMatched,
      setActiveQuery,
      setSelectedEntity,
      setSelectedCommunity,
      setExpansion,
      setScope,
      begin,
      current,
      finishRequest,
      setError,
    ]
  );

  const loadGraph = useCallback(async () => {
    if (!activeRepo || useRepoStore.getState().activeRepo !== activeRepo) return;

    reset();
    await Promise.all([loadStats(), loadCommunities(), loadSubgraph(DEFAULT_ENTITY_LIMIT, '')]);
  }, [activeRepo, reset, loadStats, loadCommunities, loadSubgraph]);

  // Load graph when active repo changes
  useEffect(() => {
    if (activeRepo) {
      loadGraph();
    } else {
      // Deleting the last corpus must also invalidate its in-flight responses.
      reset();
    }
  }, [activeRepo, loadGraph, reset]);

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
    scope,
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
