import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import ForceGraph2D from 'react-force-graph-2d';
import { useGraph } from '@/hooks/useGraph';
import { useRepoStore } from '@/stores/useRepoStore';
import type { Community, Entity, Relationship } from '@/types/generated';

/** Node with computed degree for importance labeling */
type NodeWithDegree = Entity & { __degree?: number };

function formatEntityLabel(e: Entity): string {
  const name = String(e.name || '').trim();
  const type = String(e.entity_type || '').trim();
  return type ? `${name} (${type})` : name;
}

function formatRelLabel(r: Relationship, byId: Map<string, Entity>): string {
  const src = byId.get(r.source_id);
  const dst = byId.get(r.target_id);
  const srcName = src ? src.name : r.source_id;
  const dstName = dst ? dst.name : r.target_id;
  return `${srcName} ─ ${r.relation_type} → ${dstName}`;
}

export function GraphSubtab() {
  const { repos, activeRepo, loadRepos, setActiveRepo } = useRepoStore();
  const {
    entities,
    communities,
    stats,
    selectedEntity,
    selectedCommunity,
    isLoading,
    error,
    maxHops,
    visibleEntityTypes,
    visibleRelationTypes,
    searchEntities,
    loadGraph,
    selectEntity,
    selectCommunity,
    setMaxHops,
    setVisibleEntityTypes,
    setVisibleRelationTypes,
    getEntitiesByType,
    getRelationshipsByType,
  } = useGraph();

  const [entityQuery, setEntityQuery] = useState('');
  const [viewMode, setViewMode] = useState<'table' | 'viz'>('table');
  const [accentColor, setAccentColor] = useState<string>('#00ff88');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [fullscreenAnimating, setFullscreenAnimating] = useState(false);
  const fgRef = useRef<any>(null);
  const fullscreenFgRef = useRef<any>(null);
  const vizCanvasRef = useRef<HTMLDivElement | null>(null);
  const fullscreenCanvasRef = useRef<HTMLDivElement | null>(null);
  const [vizSize, setVizSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
  const [fullscreenSize, setFullscreenSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 });

  useEffect(() => {
    if (!repos.length) void loadRepos();
  }, [repos.length, loadRepos]);

  useEffect(() => {
    // Pull the CSS theme accent into canvas-land (ForceGraph uses canvas fillStyles).
    const v = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
    if (v) setAccentColor(v);
  }, []);

  const entityById = useMemo(() => {
    return new Map<string, Entity>((entities || []).map((e) => [e.entity_id, e]));
  }, [entities]);

  const filteredEntities = useMemo(() => {
    return getEntitiesByType(visibleEntityTypes);
  }, [getEntitiesByType, visibleEntityTypes]);

  const filteredRelationships = useMemo(() => {
    return getRelationshipsByType(visibleRelationTypes);
  }, [getRelationshipsByType, visibleRelationTypes]);

  const vizEntityIdSet = useMemo(() => {
    return new Set<string>(filteredEntities.map((e) => e.entity_id));
  }, [filteredEntities]);

  const vizRelationships = useMemo(() => {
    // Ensure we don't create “phantom nodes” when filters hide endpoints.
    return filteredRelationships.filter(
      (r) => vizEntityIdSet.has(r.source_id) && vizEntityIdSet.has(r.target_id)
    );
  }, [filteredRelationships, vizEntityIdSet]);

  const vizGraphData = useMemo(() => {
    return { nodes: filteredEntities, links: vizRelationships };
  }, [filteredEntities, vizRelationships]);

  // Compute node degrees for importance-based labeling
  const nodeDegreeMap = useMemo(() => {
    const degreeMap = new Map<string, number>();
    for (const entity of filteredEntities) {
      degreeMap.set(entity.entity_id, 0);
    }
    for (const rel of vizRelationships) {
      degreeMap.set(rel.source_id, (degreeMap.get(rel.source_id) || 0) + 1);
      degreeMap.set(rel.target_id, (degreeMap.get(rel.target_id) || 0) + 1);
    }
    return degreeMap;
  }, [filteredEntities, vizRelationships]);

  // Determine which nodes are "important" (top 15% by connectivity, min 3 connections)
  const importantNodeIds = useMemo(() => {
    if (nodeDegreeMap.size === 0) return new Set<string>();

    const degrees = Array.from(nodeDegreeMap.entries())
      .filter(([, deg]) => deg >= 3) // Must have at least 3 connections
      .sort((a, b) => b[1] - a[1]);

    // Take top 15% of nodes, but cap at 12 labels to avoid clutter
    const topCount = Math.min(12, Math.max(1, Math.ceil(degrees.length * 0.15)));
    return new Set(degrees.slice(0, topCount).map(([id]) => id));
  }, [nodeDegreeMap]);

  // Fullscreen graph data with degree annotations for custom rendering
  const fullscreenGraphData = useMemo(() => {
    const nodesWithDegree: NodeWithDegree[] = filteredEntities.map((e) => ({
      ...e,
      __degree: nodeDegreeMap.get(e.entity_id) || 0,
    }));
    return { nodes: nodesWithDegree, links: vizRelationships };
  }, [filteredEntities, vizRelationships, nodeDegreeMap]);

  useEffect(() => {
    if (viewMode !== 'viz') return;
    const el = vizCanvasRef.current;
    if (!el) return;

    const update = () => {
      const rect = el.getBoundingClientRect();
      setVizSize({
        w: Math.max(1, Math.floor(rect.width)),
        h: Math.max(1, Math.floor(rect.height)),
      });
    };

    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, [viewMode]);

  useEffect(() => {
    if (viewMode !== 'viz') return;
    const handle = window.setTimeout(() => {
      try {
        fgRef.current?.zoomToFit?.(400, 60);
      } catch {
        // no-op
      }
    }, 250);
    return () => window.clearTimeout(handle);
  }, [viewMode, vizGraphData.nodes.length, vizGraphData.links.length]);

  // Fullscreen canvas resize observer
  useEffect(() => {
    if (!isFullscreen) return;
    const el = fullscreenCanvasRef.current;
    if (!el) return;

    const update = () => {
      const rect = el.getBoundingClientRect();
      setFullscreenSize({
        w: Math.max(1, Math.floor(rect.width)),
        h: Math.max(1, Math.floor(rect.height)),
      });
    };

    // Small delay to let CSS transition complete
    const initialTimeout = window.setTimeout(update, 50);
    window.addEventListener('resize', update);

    return () => {
      window.clearTimeout(initialTimeout);
      window.removeEventListener('resize', update);
    };
  }, [isFullscreen]);

  // Fullscreen graph auto-fit
  useEffect(() => {
    if (!isFullscreen) return;
    const handle = window.setTimeout(() => {
      try {
        fullscreenFgRef.current?.zoomToFit?.(400, 80);
      } catch {
        // no-op
      }
    }, 300);
    return () => window.clearTimeout(handle);
  }, [isFullscreen, fullscreenGraphData.nodes.length, fullscreenGraphData.links.length]);

  // Escape key to close fullscreen
  useEffect(() => {
    if (!isFullscreen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        handleCloseFullscreen();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isFullscreen, handleCloseFullscreen]);

  // Fullscreen open/close handlers with animation
  const handleOpenFullscreen = useCallback(() => {
    setFullscreenAnimating(true);
    setIsFullscreen(true);
    // Let the fade-in animation play
    window.setTimeout(() => setFullscreenAnimating(false), 200);
  }, []);

  const handleCloseFullscreen = useCallback(() => {
    setFullscreenAnimating(true);
    // Let fade-out animation start
    window.setTimeout(() => {
      setIsFullscreen(false);
      setFullscreenAnimating(false);
    }, 150);
  }, []);

  // Custom node rendering for fullscreen mode - shows labels for important nodes
  const fullscreenNodeCanvasObject = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const entity = node as NodeWithDegree;
      const x = node.x ?? 0;
      const y = node.y ?? 0;

      // Node size based on degree (more connections = larger node)
      const baseSize = 4;
      const degree = entity.__degree || 0;
      const sizeMultiplier = Math.min(2.5, 1 + degree * 0.15);
      const nodeSize = baseSize * sizeMultiplier;

      // Draw node circle
      ctx.beginPath();
      ctx.arc(x, y, nodeSize, 0, 2 * Math.PI);
      ctx.fillStyle =
        selectedEntity?.entity_id === entity.entity_id
          ? accentColor
          : nodeColor(entity);
      ctx.fill();

      // Draw subtle glow for important nodes
      if (importantNodeIds.has(entity.entity_id)) {
        ctx.beginPath();
        ctx.arc(x, y, nodeSize + 2, 0, 2 * Math.PI);
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Draw label for important nodes (only when zoomed in enough)
      if (importantNodeIds.has(entity.entity_id) && globalScale >= 0.4) {
        const label = entity.name || entity.entity_id;
        const fontSize = Math.max(10, 12 / globalScale);
        ctx.font = `600 ${fontSize}px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`;

        // Background pill for readability
        const textWidth = ctx.measureText(label).width;
        const padding = 4 / globalScale;
        const pillHeight = fontSize + padding * 2;
        const pillWidth = textWidth + padding * 3;
        const pillY = y - nodeSize - pillHeight - 4 / globalScale;

        ctx.fillStyle = 'rgba(20, 20, 30, 0.85)';
        ctx.beginPath();
        const radius = pillHeight / 2;
        ctx.roundRect(x - pillWidth / 2, pillY, pillWidth, pillHeight, radius);
        ctx.fill();

        // Border
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
        ctx.lineWidth = 1 / globalScale;
        ctx.stroke();

        // Text
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = 'rgba(255, 255, 255, 0.95)';
        ctx.fillText(label, x, pillY + pillHeight / 2);
      }
    },
    [selectedEntity, accentColor, importantNodeIds, nodeColor]
  );

  const entityTypes = useMemo(() => {
    return ['function', 'class', 'module', 'variable', 'concept'];
  }, []);

  const relationTypes = useMemo(() => {
    return ['calls', 'imports', 'inherits', 'contains', 'references', 'related_to'];
  }, []);

  const handleSearch = async () => {
    await searchEntities(entityQuery, 200);
  };

  const handleClear = async () => {
    setEntityQuery('');
    await loadGraph();
  };

  const handlePickCommunity = async (c: Community | null) => {
    await selectCommunity(c);
  };

  const handlePickEntity = async (e: Entity | null) => {
    await selectEntity(e);
  };

  const nodeColor = (e: Entity): string => {
    if (selectedEntity?.entity_id === e.entity_id) return accentColor;
    switch (e.entity_type) {
      case 'function':
        return '#22c55e';
      case 'class':
        return '#60a5fa';
      case 'module':
        return '#fbbf24';
      case 'variable':
        return '#a78bfa';
      case 'concept':
        return '#94a3b8';
      default:
        return '#9fb1c7';
    }
  };

  return (
    <div className="subtab-panel" style={{ padding: '24px' }} data-testid="graph-subtab">
      <div style={{ marginBottom: '18px' }}>
        <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--fg)', margin: 0 }}>
          🕸️ Graph Explorer
        </h3>
        <div style={{ marginTop: '6px', fontSize: '13px', color: 'var(--fg-muted)' }}>
          Inspect entities, relationships, and communities stored in Neo4j for the active corpus.
        </div>
        <div style={{ marginTop: '12px', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <button
            onClick={() => setViewMode('viz')}
            style={{
              padding: '8px 10px',
              background: viewMode === 'viz' ? 'rgba(var(--accent-rgb), 0.14)' : 'transparent',
              color: viewMode === 'viz' ? 'var(--accent)' : 'var(--fg-muted)',
              border: viewMode === 'viz' ? '1px solid var(--accent)' : '1px solid var(--line)',
              borderRadius: '10px',
              cursor: 'pointer',
              fontWeight: 800,
              fontSize: '12px',
            }}
            data-testid="graph-view-visualization"
          >
            Visualization
          </button>
          <button
            onClick={() => setViewMode('table')}
            style={{
              padding: '8px 10px',
              background: viewMode === 'table' ? 'rgba(var(--accent-rgb), 0.14)' : 'transparent',
              color: viewMode === 'table' ? 'var(--accent)' : 'var(--fg-muted)',
              border: viewMode === 'table' ? '1px solid var(--accent)' : '1px solid var(--line)',
              borderRadius: '10px',
              cursor: 'pointer',
              fontWeight: 800,
              fontSize: '12px',
            }}
            data-testid="graph-view-table"
          >
            Table
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{
            background: 'rgba(var(--error-rgb), 0.1)',
            border: '1px solid var(--error)',
            borderRadius: '8px',
            padding: '12px 16px',
            marginBottom: '16px',
            color: 'var(--error)',
            fontSize: '13px',
          }}
          data-testid="graph-error"
        >
          {error}
        </div>
      )}

      {/* Corpus selection + stats */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 2fr',
          gap: '16px',
          marginBottom: '16px',
          alignItems: 'stretch',
        }}
      >
        <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '12px', padding: '16px' }}>
          <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)', marginBottom: '10px' }}>Corpus</div>
          <select
            value={activeRepo}
            onChange={(e) => void setActiveRepo(e.target.value)}
            style={{
              width: '100%',
              padding: '10px 12px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '6px',
              color: 'var(--fg)',
              fontSize: '13px',
            }}
            data-testid="graph-corpus-select"
          >
            {!repos.length ? (
              <option value="">No corpora</option>
            ) : (
              repos.map((r) => (
                <option key={r.corpus_id} value={r.corpus_id}>
                  {r.name || r.corpus_id}
                </option>
              ))
            )}
          </select>

          <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--fg-muted)' }}>
            Max hops
          </div>
          <input
            type="number"
            min={1}
            max={5}
            value={maxHops}
            onChange={(e) => setMaxHops(Math.max(1, Math.min(5, parseInt(e.target.value || '2', 10))))}
            style={{
              width: '100%',
              padding: '10px 12px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '6px',
              color: 'var(--fg)',
              fontSize: '13px',
              marginTop: '6px',
            }}
            data-testid="graph-max-hops"
          />
        </div>

        <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '12px', padding: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
            <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Stats</div>
            <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }} data-testid="graph-loading">
              {isLoading ? 'Loading…' : ''}
            </div>
          </div>

          {stats ? (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                gap: '12px',
                marginTop: '12px',
              }}
              data-testid="graph-stats"
            >
              {[
                { label: 'Entities', value: String(stats.total_entities ?? 0), icon: '🧩' },
                { label: 'Relationships', value: String(stats.total_relationships ?? 0), icon: '🔗' },
                { label: 'Communities', value: String(stats.total_communities ?? 0), icon: '🧭' },
              ].map((item) => (
                <div
                  key={item.label}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    padding: '10px',
                    background: 'var(--bg)',
                    borderRadius: '10px',
                    border: '1px solid var(--line)',
                  }}
                >
                  <span style={{ fontSize: '20px' }}>{item.icon}</span>
                  <div>
                    <div style={{ fontSize: '14px', fontWeight: 800, color: 'var(--fg)' }}>{item.value}</div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>{item.label}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--fg-muted)' }} data-testid="graph-stats-empty">
              No graph stats available for this corpus yet.
            </div>
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr 1fr', gap: '16px' }}>
        {/* Communities */}
        <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '12px', padding: '16px' }}>
          <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)', marginBottom: '10px' }}>
            Communities
          </div>
          <div style={{ maxHeight: '420px', overflowY: 'auto', display: 'grid', gap: '8px' }} data-testid="graph-communities">
            {(communities || []).map((c) => {
              const active = selectedCommunity?.community_id === c.community_id;
              const count = Array.isArray(c.member_ids) ? c.member_ids.length : 0;
              return (
                <button
                  key={c.community_id}
                  onClick={() => void handlePickCommunity(active ? null : c)}
                  style={{
                    textAlign: 'left',
                    padding: '10px 12px',
                    background: active ? 'rgba(var(--accent-rgb), 0.12)' : 'var(--bg-elev2)',
                    border: active ? '1px solid var(--accent)' : '1px solid var(--line)',
                    borderRadius: '10px',
                    cursor: 'pointer',
                  }}
                  data-testid={`graph-community-${c.community_id}`}
                >
                  <div style={{ fontSize: '13px', fontWeight: 700, color: active ? 'var(--accent)' : 'var(--fg)' }}>
                    {c.name}
                  </div>
                  <div style={{ marginTop: '4px', fontSize: '11px', color: 'var(--fg-muted)' }}>
                    {count} members • level {c.level}
                  </div>
                </button>
              );
            })}
            {!communities?.length && (
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>No communities found.</div>
            )}
          </div>
        </div>

        {/* Entities */}
        <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '12px', padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
            <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Entities</div>
            <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }} data-testid="graph-entity-count">
              {filteredEntities.length} shown
            </div>
          </div>

          <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
            <input
              value={entityQuery}
              onChange={(e) => setEntityQuery(e.target.value)}
              placeholder="Search entities by name…"
              style={{
                flex: 1,
                padding: '10px 12px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '6px',
                color: 'var(--fg)',
                fontSize: '13px',
              }}
              data-testid="graph-entity-search"
              onKeyDown={(e) => {
                if (e.key === 'Enter') void handleSearch();
              }}
            />
            <button
              onClick={() => void handleSearch()}
              style={{
                padding: '10px 12px',
                background: 'var(--accent)',
                color: 'var(--accent-contrast)',
                border: 'none',
                borderRadius: '6px',
                cursor: 'pointer',
                fontWeight: 800,
                fontSize: '12px',
              }}
              data-testid="graph-search-btn"
            >
              Search
            </button>
            <button
              onClick={() => void handleClear()}
              style={{
                padding: '10px 12px',
                background: 'transparent',
                color: 'var(--fg-muted)',
                border: '1px solid var(--line)',
                borderRadius: '6px',
                cursor: 'pointer',
                fontWeight: 700,
                fontSize: '12px',
              }}
              data-testid="graph-clear-btn"
            >
              Reset
            </button>
          </div>

          <details style={{ marginTop: '12px' }}>
            <summary style={{ cursor: 'pointer', fontSize: '12px', fontWeight: 700, color: 'var(--fg)' }}>
              Filters
            </summary>
            <div style={{ marginTop: '10px', display: 'grid', gap: '12px' }}>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '6px' }}>Entity types</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                  {entityTypes.map((t) => {
                    const checked = visibleEntityTypes.includes(t);
                    return (
                      <label key={t} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--fg)' }}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            const next = e.target.checked
                              ? Array.from(new Set([...visibleEntityTypes, t]))
                              : visibleEntityTypes.filter((x) => x !== t);
                            setVisibleEntityTypes(next);
                          }}
                        />
                        {t}
                      </label>
                    );
                  })}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '6px' }}>Relationship types</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                  {relationTypes.map((t) => {
                    const checked = visibleRelationTypes.includes(t);
                    return (
                      <label key={t} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--fg)' }}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            const next = e.target.checked
                              ? Array.from(new Set([...visibleRelationTypes, t]))
                              : visibleRelationTypes.filter((x) => x !== t);
                            setVisibleRelationTypes(next);
                          }}
                        />
                        {t}
                      </label>
                    );
                  })}
                </div>
              </div>
            </div>
          </details>

          <div
            style={{
              marginTop: '12px',
              maxHeight: '420px',
              overflowY: 'auto',
              display: 'grid',
              gap: '8px',
            }}
            data-testid="graph-entities"
          >
            {filteredEntities.map((e) => {
              const active = selectedEntity?.entity_id === e.entity_id;
              return (
                <button
                  key={e.entity_id}
                  onClick={() => void handlePickEntity(active ? null : e)}
                  style={{
                    textAlign: 'left',
                    padding: '10px 12px',
                    background: active ? 'rgba(var(--accent-rgb), 0.12)' : 'var(--bg-elev2)',
                    border: active ? '1px solid var(--accent)' : '1px solid var(--line)',
                    borderRadius: '10px',
                    cursor: 'pointer',
                  }}
                  data-testid={`graph-entity-${e.entity_id}`}
                >
                  <div style={{ fontSize: '13px', fontWeight: 700, color: active ? 'var(--accent)' : 'var(--fg)' }}>
                    {formatEntityLabel(e)}
                  </div>
                  <div style={{ marginTop: '4px', fontSize: '11px', color: 'var(--fg-muted)' }}>
                    {e.file_path || '—'}
                  </div>
                </button>
              );
            })}
            {!filteredEntities.length && (
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
                {selectedCommunity
                  ? 'No entities in this community.'
                  : 'Search for entities to begin, or select a community.'}
              </div>
            )}
          </div>
        </div>

        {viewMode === 'table' ? (
          /* Details */
          <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '12px', padding: '16px' }}>
            <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)', marginBottom: '10px' }}>Details</div>

            {selectedEntity ? (
              <div data-testid="graph-entity-details">
                <div style={{ fontSize: '14px', fontWeight: 800, color: 'var(--fg)' }}>{selectedEntity.name}</div>
                <div style={{ marginTop: '6px', fontSize: '12px', color: 'var(--fg-muted)' }}>
                  <span style={{ fontFamily: 'var(--font-mono)' }}>{selectedEntity.entity_id}</span>
                </div>
                <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--fg)' }}>
                  <strong>Type:</strong> {selectedEntity.entity_type}
                </div>
                <div style={{ marginTop: '6px', fontSize: '12px', color: 'var(--fg)' }}>
                  <strong>File:</strong> {selectedEntity.file_path || '—'}
                </div>
                {selectedEntity.description && (
                  <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.5 }}>
                    {selectedEntity.description}
                  </div>
                )}

                <div style={{ marginTop: '14px', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <div style={{ fontSize: '12px', fontWeight: 800, color: 'var(--fg)' }}>Relationships</div>
                  <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }} data-testid="graph-relationship-count">
                    {filteredRelationships.length} edges
                  </div>
                </div>

                <div style={{ marginTop: '10px', maxHeight: '360px', overflowY: 'auto', display: 'grid', gap: '8px' }} data-testid="graph-relationships">
                  {filteredRelationships.map((r, idx) => (
                    <div
                      key={`${r.source_id}-${r.relation_type}-${r.target_id}-${idx}`}
                      style={{
                        padding: '10px 12px',
                        background: 'var(--bg-elev2)',
                        border: '1px solid var(--line)',
                        borderRadius: '10px',
                        fontSize: '12px',
                        color: 'var(--fg)',
                      }}
                    >
                      <div style={{ fontFamily: 'var(--font-mono)' }}>{formatRelLabel(r, entityById)}</div>
                    </div>
                  ))}
                  {!filteredRelationships.length && (
                    <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
                      No relationships loaded. Select an entity to load its neighborhood.
                    </div>
                  )}
                </div>
              </div>
            ) : selectedCommunity ? (
              <div data-testid="graph-community-details">
                <div style={{ fontSize: '14px', fontWeight: 800, color: 'var(--fg)' }}>{selectedCommunity.name}</div>
                <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.5 }}>
                  {selectedCommunity.summary || '—'}
                </div>
                <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--fg)' }}>
                  <strong>Members:</strong> {selectedCommunity.member_ids?.length || 0}
                </div>
                <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--fg-muted)' }}>
                  Click a member in the Entities list to load its neighbors.
                </div>
              </div>
            ) : (
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }} data-testid="graph-details-empty">
                Select a community or entity to view details.
              </div>
            )}
          </div>
        ) : (
          /* Visualization */
          <div
            style={{
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              borderRadius: '12px',
              padding: '16px',
              overflow: 'hidden',
            }}
            data-testid="graph-viz-panel"
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
              <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Visualization</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
                  {filteredEntities.length} nodes • {vizRelationships.length} edges
                </div>
                <button
                  onClick={handleOpenFullscreen}
                  disabled={filteredEntities.length === 0}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 10px',
                    background: 'rgba(var(--accent-rgb), 0.1)',
                    border: '1px solid var(--accent)',
                    borderRadius: '8px',
                    color: 'var(--accent)',
                    fontSize: '11px',
                    fontWeight: 700,
                    cursor: filteredEntities.length === 0 ? 'not-allowed' : 'pointer',
                    opacity: filteredEntities.length === 0 ? 0.5 : 1,
                    transition: 'all 0.15s ease',
                  }}
                  onMouseEnter={(e) => {
                    if (filteredEntities.length > 0) {
                      e.currentTarget.style.background = 'rgba(var(--accent-rgb), 0.2)';
                      e.currentTarget.style.transform = 'scale(1.02)';
                    }
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'rgba(var(--accent-rgb), 0.1)';
                    e.currentTarget.style.transform = 'scale(1)';
                  }}
                  data-testid="graph-expand-btn"
                  title="Expand graph to fullscreen view"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="15 3 21 3 21 9" />
                    <polyline points="9 21 3 21 3 15" />
                    <line x1="21" y1="3" x2="14" y2="10" />
                    <line x1="3" y1="21" x2="10" y2="14" />
                  </svg>
                  Expand
                </button>
              </div>
            </div>

            <div
              ref={vizCanvasRef}
              style={{
                marginTop: '12px',
                height: '520px',
                background: 'var(--bg)',
                border: '1px solid var(--line)',
                borderRadius: '10px',
                overflow: 'hidden',
              }}
              data-testid="graph-viz-canvas"
            >
              {/* Inspired by Neumann’s force-graph UI (MIT). */}
              {vizSize.w > 0 && vizSize.h > 0 && filteredEntities.length > 0 ? (
                <ForceGraph2D
                  ref={fgRef}
                  width={vizSize.w}
                  height={vizSize.h}
                  graphData={vizGraphData as any}
                  nodeId="entity_id"
                  linkSource="source_id"
                  linkTarget="target_id"
                  nodeLabel={(n: any) => formatEntityLabel(n as Entity)}
                  linkLabel={(l: any) => String((l as Relationship).relation_type || '')}
                  nodeColor={(n: any) => nodeColor(n as Entity)}
                  linkColor={() => 'rgba(255, 255, 255, 0.15)'}
                  linkWidth={1}
                  backgroundColor="rgba(0,0,0,0)"
                  onNodeClick={(n: any) => {
                    const e = n as Entity;
                    const active = selectedEntity?.entity_id === e.entity_id;
                    void handlePickEntity(active ? null : e);
                  }}
                />
              ) : (
                <div style={{ padding: '12px', fontSize: '12px', color: 'var(--fg-muted)' }}>
                  Select an entity (or a community) to render a subgraph.
                </div>
              )}
            </div>

            <div style={{ marginTop: '10px', fontSize: '11px', color: 'var(--fg-muted)' }}>
              Tip: click a node to load its neighborhood.
            </div>
          </div>
        )}
      </div>

      {/* Fullscreen Graph Modal */}
      {isFullscreen &&
        createPortal(
          <div
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 9999,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: fullscreenAnimating
                ? 'rgba(0, 0, 0, 0)'
                : 'rgba(0, 0, 0, 0.75)',
              backdropFilter: fullscreenAnimating ? 'blur(0px)' : 'blur(8px)',
              transition: 'background 0.2s ease, backdrop-filter 0.2s ease',
            }}
            onClick={handleCloseFullscreen}
            role="dialog"
            aria-modal="true"
            aria-label="Fullscreen graph visualization"
            data-testid="graph-fullscreen-overlay"
          >
            {/* Modal container - 85% of viewport */}
            <div
              style={{
                width: '85vw',
                height: '85vh',
                maxWidth: '1800px',
                maxHeight: '1100px',
                background: 'var(--bg-elev1)',
                borderRadius: '20px',
                border: '1px solid var(--line)',
                boxShadow: '0 25px 80px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.05)',
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
                transform: fullscreenAnimating ? 'scale(0.95)' : 'scale(1)',
                opacity: fullscreenAnimating ? 0 : 1,
                transition: 'transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease',
              }}
              onClick={(e) => e.stopPropagation()}
              data-testid="graph-fullscreen-modal"
            >
              {/* Header */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '16px 24px',
                  borderBottom: '1px solid var(--line)',
                  background: 'var(--bg-elev2)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span style={{ fontSize: '20px' }}>🕸️</span>
                  <div>
                    <div style={{ fontSize: '16px', fontWeight: 700, color: 'var(--fg)' }}>
                      Knowledge Graph
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                      {filteredEntities.length} nodes • {vizRelationships.length} edges
                      {importantNodeIds.size > 0 && ` • ${importantNodeIds.size} hub${importantNodeIds.size === 1 ? '' : 's'} labeled`}
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  {/* Legend */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '11px' }}>
                    {[
                      { type: 'function', color: '#22c55e' },
                      { type: 'class', color: '#60a5fa' },
                      { type: 'module', color: '#fbbf24' },
                      { type: 'variable', color: '#a78bfa' },
                      { type: 'concept', color: '#94a3b8' },
                    ].map(({ type, color }) => (
                      <div key={type} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <div
                          style={{
                            width: '10px',
                            height: '10px',
                            borderRadius: '50%',
                            background: color,
                          }}
                        />
                        <span style={{ color: 'var(--fg-muted)' }}>{type}</span>
                      </div>
                    ))}
                  </div>

                  {/* Close button */}
                  <button
                    onClick={handleCloseFullscreen}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: '36px',
                      height: '36px',
                      background: 'rgba(255, 255, 255, 0.05)',
                      border: '1px solid var(--line)',
                      borderRadius: '10px',
                      color: 'var(--fg-muted)',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'rgba(255, 255, 255, 0.1)';
                      e.currentTarget.style.color = 'var(--fg)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
                      e.currentTarget.style.color = 'var(--fg-muted)';
                    }}
                    data-testid="graph-fullscreen-close"
                    title="Close (Esc)"
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </button>
                </div>
              </div>

              {/* Graph canvas */}
              <div
                ref={fullscreenCanvasRef}
                style={{
                  flex: 1,
                  background: 'radial-gradient(ellipse at center, var(--bg-elev1) 0%, var(--bg) 100%)',
                  position: 'relative',
                }}
                data-testid="graph-fullscreen-canvas"
              >
                {fullscreenSize.w > 0 && fullscreenSize.h > 0 && (
                  <ForceGraph2D
                    ref={fullscreenFgRef}
                    width={fullscreenSize.w}
                    height={fullscreenSize.h}
                    graphData={fullscreenGraphData as any}
                    nodeId="entity_id"
                    linkSource="source_id"
                    linkTarget="target_id"
                    nodeLabel={(n: any) => formatEntityLabel(n as Entity)}
                    linkLabel={(l: any) => String((l as Relationship).relation_type || '')}
                    nodeCanvasObject={fullscreenNodeCanvasObject}
                    linkColor={() => 'rgba(255, 255, 255, 0.12)'}
                    linkWidth={1.5}
                    backgroundColor="rgba(0,0,0,0)"
                    enableNodeDrag={true}
                    enableZoomInteraction={true}
                    enablePanInteraction={true}
                    cooldownTime={2000}
                    d3AlphaDecay={0.02}
                    d3VelocityDecay={0.3}
                    onNodeClick={(n: any) => {
                      const e = n as Entity;
                      const active = selectedEntity?.entity_id === e.entity_id;
                      void handlePickEntity(active ? null : e);
                    }}
                  />
                )}

                {/* Selected entity indicator */}
                {selectedEntity && (
                  <div
                    style={{
                      position: 'absolute',
                      bottom: '20px',
                      left: '20px',
                      background: 'rgba(20, 20, 30, 0.9)',
                      border: '1px solid var(--accent)',
                      borderRadius: '12px',
                      padding: '12px 16px',
                      maxWidth: '300px',
                      backdropFilter: 'blur(8px)',
                    }}
                  >
                    <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--accent)' }}>
                      {selectedEntity.name}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
                      {selectedEntity.entity_type} • {nodeDegreeMap.get(selectedEntity.entity_id) || 0} connections
                    </div>
                    {selectedEntity.file_path && (
                      <div
                        style={{
                          fontSize: '10px',
                          color: 'var(--fg-muted)',
                          marginTop: '4px',
                          fontFamily: 'var(--font-mono)',
                          opacity: 0.8,
                        }}
                      >
                        {selectedEntity.file_path}
                      </div>
                    )}
                  </div>
                )}

                {/* Instructions tooltip */}
                <div
                  style={{
                    position: 'absolute',
                    bottom: '20px',
                    right: '20px',
                    fontSize: '11px',
                    color: 'var(--fg-muted)',
                    background: 'rgba(20, 20, 30, 0.7)',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    backdropFilter: 'blur(4px)',
                  }}
                >
                  Scroll to zoom • Drag to pan • Click node for details • Esc to close
                </div>
              </div>
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}

