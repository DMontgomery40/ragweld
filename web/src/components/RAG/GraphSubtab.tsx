import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import ForceGraph2D from 'react-force-graph-2d';
import { useGraph } from '@/hooks/useGraph';
import { useIndexing } from '@/hooks/useIndexing';
import { SyntheticCallout } from '@/components/RAG/SyntheticCallout';
import { useRepoStore } from '@/stores/useRepoStore';
import { DEFAULT_ENTITY_LIMIT, ENTITY_LIMIT_CHOICES } from '@/stores/useGraphStore';
import type { Community, Entity, IndexStatus, Relationship } from '@/types/generated';

/** Node with computed degree for importance labeling */
type NodeWithDegree = Entity & { __degree?: number };

/**
 * The one legend. It reads the entity types actually present in the rendered
 * graph, so the inline panel and the fullscreen modal can never disagree and the
 * palette can never describe data that is not on screen (M-59: the inline legend
 * was a hardcoded person/org/location/event/concept NER palette on a code graph).
 */
function GraphLegend({
  types,
  colorOf,
  testId,
}: {
  types: string[];
  colorOf: (type: string) => string;
  testId: string;
}) {
  if (!types.length) return null;
  return (
    <div
      style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '11.5px', flexWrap: 'wrap' }}
      data-testid={testId}
    >
      {types.map((type) => (
        <span key={type} style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', color: 'var(--fg-muted)' }}>
          <span
            style={{
              width: '10px',
              height: '10px',
              borderRadius: '999px',
              background: colorOf(type),
              display: 'inline-block',
            }}
          />
          {type}
        </span>
      ))}
    </div>
  );
}

function formatEntityLabel(e: Entity): string {
  const name = String(e.name || '').trim();
  const type = String(e.entity_type || '').trim();
  return type ? `${name} (${type})` : name;
}

function formatRelProvenance(r: Relationship): string {
  const props = (r.properties || {}) as Record<string, unknown>;
  const chunk = String(props.chunk_id || '').trim();
  const filePath = String(props.file_path || '').trim();
  const runId = String(props.run_id || '').trim();
  const model = String(props.model || '').trim();
  const bits: string[] = [];
  if (chunk) bits.push(`chunk:${chunk}`);
  if (filePath) bits.push(`file:${filePath}`);
  if (runId) bits.push(`run:${runId}`);
  if (model) bits.push(`model:${model}`);
  if (!bits.length) return 'No provenance';
  return bits.join(' • ');
}

/**
 * Paint hub labels in a pass that runs AFTER every node and link, with a pill
 * backdrop and rectangle-collision rejection. Painting them inside
 * `nodeCanvasObject` put each label under every node drawn later, which sliced
 * the dense centre into `fusi...y.at` / `onfi...ore.py` fragments (M-149 / C-40).
 */
function makeLabelPainter(
  nodes: NodeWithDegree[],
  labelledIds: Set<string>
): (ctx: CanvasRenderingContext2D, globalScale: number) => void {
  return (ctx, globalScale) => {
    if (!labelledIds.size || globalScale < 0.4) return;
    const placed: Array<[number, number, number, number]> = [];
    const ordered = nodes
      .filter((n) => labelledIds.has(n.entity_id))
      .sort((a, b) => (b.__degree || 0) - (a.__degree || 0));

    ctx.save();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (const node of ordered) {
      const pos = node as NodeWithDegree & { x?: number; y?: number };
      if (typeof pos.x !== 'number' || typeof pos.y !== 'number') continue;
      const label = node.name || node.entity_id;
      const fontSize = Math.min(26, Math.max(11.5, 12 / globalScale));
      ctx.font = `600 ${fontSize}px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`;

      const padding = 4 / globalScale;
      const width = ctx.measureText(label).width + padding * 3;
      const height = fontSize + padding * 2;
      const nodeRadius = 4 * Math.min(2.5, 1 + (node.__degree || 0) * 0.15);
      const left = pos.x - width / 2;
      const top = pos.y - nodeRadius - height - 4 / globalScale;

      const overlaps = placed.some(
        ([l, t, w, h]) => left < l + w && left + width > l && top < t + h && top + height > t
      );
      if (overlaps) continue;
      placed.push([left, top, width, height]);

      ctx.fillStyle = 'rgba(12, 12, 18, 0.92)';
      ctx.beginPath();
      ctx.roundRect(left, top, width, height, height / 2);
      ctx.fill();
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.28)';
      ctx.lineWidth = 1 / globalScale;
      ctx.stroke();
      ctx.fillStyle = '#f4f4f5';
      ctx.fillText(label, pos.x + 0, top + height / 2);
    }
    ctx.restore();
  };
}

/** Hand the operator a file. Nothing on the Graph Explorer could be taken off the page (M-149 / C-42). */
function downloadBlob(filename: string, mime: string, body: BlobPart): void {
  const url = URL.createObjectURL(new Blob([body], { type: mime }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function toCsv(headers: string[], rows: unknown[][]): string {
  return [headers, ...rows].map((row) => row.map(csvCell).join(',')).join('\n') + '\n';
}

const controlButtonStyle: React.CSSProperties = {
  padding: '6px 10px',
  background: 'var(--bg-elev2)',
  border: '1px solid var(--line)',
  borderRadius: '8px',
  color: 'var(--fg)',
  fontSize: '11.5px',
  fontWeight: 700,
  cursor: 'pointer',
};

/** Zoom as a percentage the operator can actually read at both ends of the range. */
function formatZoom(k: number): string {
  const percent = k * 100;
  if (percent >= 100) return `${Math.round(percent)}%`;
  if (percent >= 10) return `${percent.toFixed(0)}%`;
  return `${percent.toFixed(1)}%`;
}

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: '12px',
  tableLayout: 'auto',
};

const thStyle: React.CSSProperties = {
  position: 'sticky',
  top: 0,
  textAlign: 'left',
  padding: '8px 10px',
  background: 'var(--bg-elev2)',
  borderBottom: '1px solid var(--line)',
  color: 'var(--fg)',
  fontSize: '11.5px',
  fontWeight: 700,
  whiteSpace: 'nowrap',
};

const tdStyle: React.CSSProperties = {
  padding: '8px 10px',
  borderBottom: '1px solid var(--line)',
  color: 'var(--fg-muted)',
  verticalAlign: 'top',
};

export function GraphSubtab() {
  const { repos, activeRepo, loadRepos, setActiveRepo } = useRepoStore();
  const {
    status: activeIndexStatus,
    stats: activeIndexSnapshot,
    fetchStatus: fetchIndexStatus,
    fetchStats: fetchIndexStats,
  } = useIndexing();
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
    maxHops,
    totalMatched,
    activeQuery,
    visibleEntityTypes,
    visibleRelationTypes,
    loadSubgraph,
    loadGraph,
    selectEntity,
    selectCommunity,
    setViewMode,
    setMaxHops,
    setVisibleEntityTypes,
    setVisibleRelationTypes,
    getEntitiesByType,
    getRelationshipsByType,
  } = useGraph();

  const [entityQuery, setEntityQuery] = useState('');
  // How many entities the visualizer draws. View state: a per-session display
  // choice, not a persisted operator tunable (M-61).
  const [entityLimit, setEntityLimit] = useState<number>(DEFAULT_ENTITY_LIMIT);
  const [accentColor, setAccentColor] = useState<string>('#00ff88');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [fullscreenAnimating, setFullscreenAnimating] = useState(false);
  const lastSeenIndexStateRef = useRef<IndexStatus['status'] | null>(null);
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
    if (!activeRepo) {
      lastSeenIndexStateRef.current = null;
      return;
    }

    let cancelled = false;
    let timer: number | null = null;

    const poll = async () => {
      try {
        const [nextStatus] = await Promise.all([
          fetchIndexStatus(activeRepo, { quiet: true }).catch(() => null),
          fetchIndexStats(activeRepo, { quiet: true }).catch(() => null),
        ]);
        if (cancelled) return;

        const previousState = lastSeenIndexStateRef.current;
        const currentState = nextStatus?.status ?? null;
        lastSeenIndexStateRef.current = currentState;

        if (previousState === 'indexing' && currentState === 'complete') {
          await loadGraph();
        }

        const delayMs = currentState === 'indexing' ? 3000 : 15000;
        timer = window.setTimeout(() => {
          void poll();
        }, delayMs);
      } catch {
        if (cancelled) return;
        timer = window.setTimeout(() => {
          void poll();
        }, 15000);
      }
    };

    void poll();

    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [activeRepo, fetchIndexStatus, fetchIndexStats, loadGraph]);

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

  // Zoom readouts. The modal promised "Scroll to zoom" with nothing on screen to
  // confirm it happened, and the inline panel offered no zoom at all (M-63, M-64).
  const [vizZoom, setVizZoom] = useState(1);
  const [fullscreenZoom, setFullscreenZoom] = useState(1);

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

  /** The inline panel is a fraction of the modal's area: fewer labels, or it is a smear. */
  const inlineLabelledIds = useMemo(() => {
    const ranked = Array.from(nodeDegreeMap.entries())
      .filter(([, deg]) => deg >= 3)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6);
    return new Set(ranked.map(([id]) => id));
  }, [nodeDegreeMap]);

  const vizNodesWithDegree = useMemo<NodeWithDegree[]>(
    () => filteredEntities.map((e) => ({ ...e, __degree: nodeDegreeMap.get(e.entity_id) || 0 })),
    [filteredEntities, nodeDegreeMap]
  );

  // NOTE: this must stay memoized. ForceGraph2D re-seeds its simulation (and resets the
  // zoom transform) whenever `graphData` is a new object, and `onZoom` re-renders on every
  // zoom tick - an inline object literal here makes the panel un-zoomable.
  const vizGraphData = useMemo(() => {
    return { nodes: vizNodesWithDegree, links: vizRelationships };
  }, [vizNodesWithDegree, vizRelationships]);

  // Fullscreen graph data with degree annotations for custom rendering
  const fullscreenGraphData = useMemo(() => {
    const nodesWithDegree: NodeWithDegree[] = filteredEntities.map((e) => ({
      ...e,
      __degree: nodeDegreeMap.get(e.entity_id) || 0,
    }));
    return { nodes: nodesWithDegree, links: vizRelationships };
  }, [filteredEntities, vizRelationships, nodeDegreeMap]);

  // Observe the canvas host, not just window resizes: the grid settles after the first
  // paint (and the entity list changes its column's demand), so a one-shot measurement
  // left the inline canvas frozen at whatever width it had on mount - 2px at 1280 wide,
  // before minmax(0, 1fr) (M-63). Layout size, not getBoundingClientRect: a transformed
  // ancestor would size the canvas short.
  useEffect(() => {
    if (viewMode !== 'viz') return;
    const el = vizCanvasRef.current;
    if (!el) return;

    const update = () => {
      const w = Math.max(1, Math.floor(el.clientWidth));
      const h = Math.max(1, Math.floor(el.clientHeight));
      setVizSize((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
    };

    update();
    const observer = new ResizeObserver(() => update());
    observer.observe(el);
    window.addEventListener('resize', update);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', update);
    };
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

  // Fullscreen canvas sizing: observe the canvas element itself so the graph
  // follows the modal's real size (the modal scales in over 200ms; a one-shot
  // measurement mid-transition left the canvas at thumbnail size — G3).
  useEffect(() => {
    if (!isFullscreen) {
      setFullscreenSize({ w: 0, h: 0 });
      return;
    }
    const el = fullscreenCanvasRef.current;
    if (!el) return;

    const update = () => {
      // Layout size, not getBoundingClientRect: the modal opens with a
      // scale(0.95) transform and a transformed rect would size the canvas 5% short.
      const w = Math.max(1, Math.floor(el.clientWidth));
      const h = Math.max(1, Math.floor(el.clientHeight));
      setFullscreenSize((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
    };

    update();
    const observer = new ResizeObserver(() => update());
    observer.observe(el);
    window.addEventListener('resize', update);
    return () => {
      observer.disconnect();
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

  // Fullscreen open/close handlers with animation
  useEffect(() => {
    if (!isFullscreen || fullscreenSize.w <= 1 || fullscreenSize.h <= 1) return;
    const handle = window.setTimeout(() => {
      try {
        fullscreenFgRef.current?.zoomToFit?.(400, 80);
      } catch {
        // no-op
      }
    }, 300);
    return () => window.clearTimeout(handle);
  }, [isFullscreen, fullscreenSize.w, fullscreenSize.h]);

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
      case 'person':
        return '#f97316';
      case 'org':
        return '#0ea5e9';
      case 'location':
        return '#10b981';
      case 'event':
        return '#eab308';
      default:
        return '#9fb1c7';
    }
  };

  const legendColor = useCallback(
    (type: string): string => nodeColor({ entity_id: '', name: '', entity_type: type } as Entity),
    [nodeColor]
  );

  // Custom node rendering for fullscreen mode - shows labels for important nodes
  const fullscreenNodeCanvasObject = useCallback(
    (node: any, ctx: CanvasRenderingContext2D) => {
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

      // Labels are NOT drawn here: a label painted with its node is overdrawn by every
      // node painted after it. They go in the post-render pass below (M-149).
    },
    [selectedEntity, accentColor, importantNodeIds, nodeColor]
  );

  const paintFullscreenLabels = useMemo(
    () => makeLabelPainter(fullscreenGraphData.nodes, importantNodeIds),
    [fullscreenGraphData.nodes, importantNodeIds]
  );

  const paintInlineLabels = useMemo(
    () => makeLabelPainter(vizNodesWithDegree, inlineLabelledIds),
    [vizNodesWithDegree, inlineLabelledIds]
  );

  // Types actually drawn right now — what both legends describe (M-59).
  const renderedEntityTypes = useMemo(() => {
    return Array.from(new Set(filteredEntities.map((e) => String(e.entity_type || '').trim()).filter(Boolean))).sort(
      (a, b) => a.localeCompare(b)
    );
  }, [filteredEntities]);

  const entityTypes = useMemo(() => {
    const types = new Set<string>();
    Object.keys(stats?.entity_breakdown || {}).forEach((k) => {
      if (k) types.add(String(k));
    });
    (entities || []).forEach((e) => {
      const t = String(e.entity_type || '').trim();
      if (t) types.add(t);
    });
    return Array.from(types).sort((a, b) => a.localeCompare(b));
  }, [stats, entities]);

  const relationTypes = useMemo(() => {
    const types = new Set<string>();
    Object.keys(stats?.relationship_breakdown || {}).forEach((k) => {
      if (k) types.add(String(k));
    });
    (relationships || []).forEach((r) => {
      const t = String(r.relation_type || '').trim();
      if (t) types.add(t);
    });
    return Array.from(types).sort((a, b) => a.localeCompare(b));
  }, [stats, relationships]);

  /**
   * An honest count. "200 shown" against 5,179 entities told the operator nothing
   * about what they were not seeing and offered no way to reach entity 201 (M-61).
   */
  const entityCountLabel = useMemo(() => {
    const shown = filteredEntities.length;
    const fmt = (n: number) => n.toLocaleString();
    if (selectedCommunity) return `${fmt(shown)} in this community`;
    if (expansion?.status === 'ok' && selectedEntity) return `${fmt(shown)} in this neighborhood`;
    const total = Math.max(totalMatched, shown);
    const scope = activeQuery ? `matching \u201c${activeQuery}\u201d` : 'in this corpus';
    const hidden = visibleEntityTypes.length ? ' (type filter applied)' : '';
    return shown < total
      ? `Showing ${fmt(shown)} of ${fmt(total)} ${scope}${hidden}`
      : `${fmt(shown)} ${scope}${hidden}`;
  }, [
    filteredEntities.length,
    totalMatched,
    activeQuery,
    selectedCommunity,
    selectedEntity,
    expansion,
    visibleEntityTypes.length,
  ]);

  /**
   * Communities are absent for three different reasons and the operator needs the
   * right one. The old copy was a hardcoded string claiming the graph "has no
   * linked entities yet" and prescribing an expensive Force re-index, printed two
   * inches under a Stats panel reading 5,179 entities / 11,779 relationships (M-60).
   */
  const communitiesEmptyReason = useMemo(() => {
    const entities = stats?.total_entities ?? 0;
    const relationships = stats?.total_relationships ?? 0;
    if (!stats) return 'No graph stats for this corpus yet.';
    if (entities === 0) {
      return 'No communities: this corpus has no entity graph. Enable Semantic KG (concepts + relations) or code-entity indexing in RAG > Indexing, then re-index.';
    }
    if (relationships === 0) {
      return `No communities: this graph has ${entities.toLocaleString()} entities but no relationships between them, so there is nothing to cluster. Semantic KG relation extraction produced no edges on this corpus.`;
    }
    return `No communities: ${entities.toLocaleString()} entities and ${relationships.toLocaleString()} relationships are stored, but community detection has not produced any clusters for this graph generation. Communities are written during indexing - re-index this corpus to run detection over the current graph.`;
  }, [stats]);

  /**
   * Why the relationships table is empty. The old copy said "No relationships loaded.
   * Select an entity to load its neighborhood." even to an operator who had just
   * selected one - and whose selection had 404ed (M-65, M-01).
   */
  const relationshipsEmptyReason = useMemo(() => {
    if (expansion?.status === 'failed') {
      return `Could not load this entity's neighborhood. ${expansion.detail} Your entity list is unchanged - pick another entity or press Reset.`;
    }
    if (selectedEntity) {
      return `${selectedEntity.name} has no relationships in this graph generation. It is an isolated node.`;
    }
    if (selectedCommunity) return 'No relationships between the members of this community.';
    if (!filteredEntities.length) return 'Nothing is loaded yet.';
    if (visibleRelationTypes.length) {
      return 'No relationships of the selected types. Clear the relationship-type filter to see the rest.';
    }
    return 'These entities have no relationships between them. Click one to load its neighborhood.';
  }, [expansion, selectedEntity, selectedCommunity, filteredEntities.length, visibleRelationTypes.length]);

  const entitiesEmptyReason = useMemo(() => {
    if (visibleEntityTypes.length) return 'No entities of the selected types. Clear the entity-type filter to see the rest.';
    if (activeQuery) return `No entity name matches \u201c${activeQuery}\u201d in this corpus graph.`;
    if (selectedCommunity) return 'No entities in this community.';
    return 'This corpus has no entity graph yet.';
  }, [visibleEntityTypes.length, activeQuery, selectedCommunity]);

  const indexProgressPercent = useMemo(() => {
    const raw = Number(activeIndexStatus?.progress ?? 0);
    return Math.max(0, Math.min(100, Math.round(raw * 100)));
  }, [activeIndexStatus?.progress]);

  const isGraphPromotionPending = activeIndexStatus?.status === 'indexing';
  const promotedSnapshotTime = String(activeIndexSnapshot?.last_indexed || '').trim();
  const activeIndexStartedAt = String(activeIndexStatus?.started_at || '').trim();
  const promotedGraphIsStale =
    isGraphPromotionPending &&
    (!!activeIndexSnapshot?.last_indexed || (stats?.total_entities ?? 0) === 0);

  const handleSearch = async () => {
    await loadSubgraph(entityLimit, entityQuery);
  };

  const handleClear = async () => {
    setEntityQuery('');
    setEntityLimit(DEFAULT_ENTITY_LIMIT);
    await loadGraph();
  };

  const handleLimitChange = async (next: number) => {
    setEntityLimit(next);
    await loadSubgraph(next, activeQuery);
  };

  const handlePickCommunity = async (c: Community | null) => {
    await selectCommunity(c);
  };

  const handlePickEntity = async (e: Entity | null) => {
    await selectEntity(e);
  };

  const stepZoom = useCallback((ref: React.MutableRefObject<any>, factor: number) => {
    const graph = ref.current;
    if (!graph?.zoom) return;
    const next = Math.max(0.05, Math.min(40, Number(graph.zoom()) * factor));
    graph.zoom(next, 200);
  }, []);

  const exportBaseName = useMemo(() => {
    const scope = activeQuery ? `-${activeQuery.replace(/[^a-z0-9]+/gi, '-')}` : '';
    return `graph-${activeRepo || 'corpus'}${scope}`;
  }, [activeRepo, activeQuery]);

  const exportPng = useCallback(
    (host: HTMLDivElement | null) => {
      const canvas = host?.querySelector('canvas');
      if (!canvas) return;
      canvas.toBlob((blob) => {
        if (blob) downloadBlob(`${exportBaseName}.png`, 'image/png', blob);
      }, 'image/png');
    },
    [exportBaseName]
  );

  const exportEntitiesCsv = useCallback(() => {
    downloadBlob(
      `${exportBaseName}-entities.csv`,
      'text/csv;charset=utf-8',
      toCsv(
        ['entity_id', 'name', 'entity_type', 'file_path', 'connections', 'description'],
        filteredEntities.map((e) => [
          e.entity_id,
          e.name,
          e.entity_type,
          e.file_path || '',
          nodeDegreeMap.get(e.entity_id) || 0,
          e.description || '',
        ])
      )
    );
  }, [exportBaseName, filteredEntities, nodeDegreeMap]);

  const exportRelationshipsCsv = useCallback(() => {
    downloadBlob(
      `${exportBaseName}-relationships.csv`,
      'text/csv;charset=utf-8',
      toCsv(
        ['source_id', 'relation_type', 'target_id', 'weight', 'provenance'],
        filteredRelationships.map((r) => [
          r.source_id,
          r.relation_type,
          r.target_id,
          r.weight,
          formatRelProvenance(r),
        ])
      )
    );
  }, [exportBaseName, filteredRelationships]);

  const exportJson = useCallback(() => {
    downloadBlob(
      `${exportBaseName}.json`,
      'application/json',
      JSON.stringify(
        {
          corpus_id: activeRepo,
          query: activeQuery || null,
          entities: filteredEntities,
          relationships: filteredRelationships,
        },
        null,
        2
      )
    );
  }, [exportBaseName, activeRepo, activeQuery, filteredEntities, filteredRelationships]);

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
              color: viewMode === 'viz' ? 'var(--accent-text)' : 'var(--fg-muted)',
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
              color: viewMode === 'table' ? 'var(--accent-text)' : 'var(--fg-muted)',
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

      <SyntheticCallout context="graph" />

      {promotedGraphIsStale ? (
        <div
          style={{
            background: 'rgba(var(--accent-rgb), 0.08)',
            border: '1px solid rgba(var(--accent-rgb), 0.28)',
            borderRadius: '12px',
            padding: '14px 16px',
            marginBottom: '16px',
          }}
          data-testid="graph-staging-banner"
        >
          <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--fg)' }}>
            GraphRAG reindex is still building in staging.
          </div>
          <div style={{ marginTop: '6px', fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.55 }}>
            This panel shows the last promoted graph. During an active reindex, graph stats can stay at zero until the
            new run finishes and promotes.
          </div>
          <div
            style={{
              display: 'flex',
              gap: '14px',
              flexWrap: 'wrap',
              marginTop: '10px',
              fontSize: '12px',
            }}
          >
            <span style={{ color: 'var(--fg)' }}>
              <strong style={{ color: 'var(--accent-text)' }}>{indexProgressPercent}%</strong> complete
            </span>
            {activeIndexStatus?.current_file ? (
              <span style={{ color: 'var(--fg-muted)' }}>
                Current file: <span style={{ color: 'var(--fg)' }}>{activeIndexStatus.current_file}</span>
              </span>
            ) : null}
            {activeIndexStartedAt ? (
              <span style={{ color: 'var(--fg-muted)' }}>
                Started: <span style={{ color: 'var(--fg)' }}>{new Date(activeIndexStartedAt).toLocaleString()}</span>
              </span>
            ) : null}
            {promotedSnapshotTime ? (
              <span style={{ color: 'var(--fg-muted)' }}>
                Last promoted: <span style={{ color: 'var(--fg)' }}>{new Date(promotedSnapshotTime).toLocaleString()}</span>
              </span>
            ) : null}
          </div>
        </div>
      ) : null}

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
            <>
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
                  { label: 'Documents', value: String(stats.total_documents ?? 0), icon: '📄' },
                  { label: 'Chunks', value: String(stats.total_chunks ?? 0), icon: '🧱' },
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

              {(stats.total_entities ?? 0) === 0 && (stats.total_chunks ?? 0) > 0 ? (
                <div
                  style={{
                    marginTop: '12px',
                    padding: '10px 12px',
                    borderRadius: '10px',
                    border: '1px solid var(--line)',
                    background: 'rgba(var(--accent-rgb), 0.06)',
                    color: 'var(--fg-muted)',
                    fontSize: '12px',
                  }}
                  data-testid="graph-entity-empty-hint"
                >
                  Chunk graph is present, but the entity graph is empty. Enable Semantic KG (concepts + relations) or
                  index code entities to populate entities/communities.
                </div>
              ) : null}
            </>
          ) : (
            <div
              style={{ marginTop: '12px', fontSize: '12px', color: 'var(--fg-muted)' }}
              data-testid="graph-stats-empty"
            >
              No graph stats available for this corpus yet.
            </div>
          )}
        </div>
      </div>

      {/* `1fr` is `minmax(auto, 1fr)`: the entity list's ids
          (`server/retrieval/rerank.py::Reranker`) are unbreakable min-content, so they
          pushed the visualization column down to 2px wide at 1280x720 - the "solid grey
          hairball in a ~320x300 box" of M-63. minmax(0, 1fr) is what makes the panel a
          panel. */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns:
            viewMode === 'table' ? '320px minmax(0, 1fr)' : '320px minmax(0, 1fr) minmax(0, 1.5fr)',
          gap: '16px',
          alignItems: 'start',
        }}
      >
        {/* Communities */}
        <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '12px', padding: '16px', minWidth: 0 }}>
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
                  <div style={{ fontSize: '13px', fontWeight: 700, color: active ? 'var(--accent-text)' : 'var(--fg)' }}>
                    {c.name}
                  </div>
                  <div style={{ marginTop: '4px', fontSize: '11px', color: 'var(--fg-muted)' }}>
                    {count} members • level {c.level}
                  </div>
                </button>
              );
            })}
            {!communities?.length && (
              <div style={{ fontSize: '12.5px', color: 'var(--fg-muted)', lineHeight: 1.55 }} data-testid="graph-communities-empty">
                {communitiesEmptyReason}
              </div>
            )}
          </div>
        </div>

        {/* Entities */}
        <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '12px', padding: '16px', minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
            <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Entities</div>
            <div style={{ fontSize: '11.5px', color: 'var(--fg-muted)' }} data-testid="graph-entity-count">
              {entityCountLabel}
            </div>
          </div>

          <div
            style={{
              marginTop: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: '8px',
              fontSize: '11.5px',
              color: 'var(--fg-muted)',
            }}
          >
            <label htmlFor="graph-entity-limit">Draw at most</label>
            <select
              id="graph-entity-limit"
              value={entityLimit}
              onChange={(e) => void handleLimitChange(Number(e.target.value))}
              style={{
                padding: '6px 8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '6px',
                color: 'var(--fg)',
                fontSize: '11.5px',
              }}
              data-testid="graph-entity-limit"
            >
              {ENTITY_LIMIT_CHOICES.map((n) => (
                <option key={n} value={n}>
                  {n.toLocaleString()}
                </option>
              ))}
            </select>
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
                  <div style={{ fontSize: '13px', fontWeight: 700, color: active ? 'var(--accent-text)' : 'var(--fg)', wordBreak: 'break-word' }}>
                    {formatEntityLabel(e)}
                  </div>
                  <div style={{ marginTop: '4px', fontSize: '11.5px', color: 'var(--fg-muted)', wordBreak: 'break-all' }}>
                    {e.file_path || '—'}
                  </div>
                </button>
              );
            })}
            {!filteredEntities.length && (
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.5 }} data-testid="graph-entities-empty">
                {entitiesEmptyReason}
              </div>
            )}
          </div>
        </div>

        {viewMode === 'table' ? (
          /* Tables: the entities and relationships currently loaded, as actual tables.
             "Table" used to render one Details card plus an empty-state that told the
             operator to select an entity to load its neighborhood - the thing they had
             just done, and which 404ed - over two thirds of empty viewport (M-65). */
          <div
            style={{
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              borderRadius: '12px',
              padding: '16px',
              minWidth: 0,
            }}
            data-testid="graph-table-panel"
          >
            {selectedEntity ? (
              <div style={{ marginBottom: '16px' }} data-testid="graph-entity-details">
                <div style={{ fontSize: '14px', fontWeight: 800, color: 'var(--fg)' }}>{selectedEntity.name}</div>
                <div style={{ marginTop: '6px', fontSize: '12px', color: 'var(--fg-muted)', wordBreak: 'break-all' }}>
                  <span style={{ fontFamily: 'var(--font-mono)' }}>{selectedEntity.entity_id}</span>
                </div>
                <div style={{ marginTop: '8px', display: 'flex', gap: '16px', flexWrap: 'wrap', fontSize: '12px', color: 'var(--fg)' }}>
                  <span>
                    <strong>Type:</strong> {selectedEntity.entity_type}
                  </span>
                  <span>
                    <strong>File:</strong> {selectedEntity.file_path || '—'}
                  </span>
                  <span>
                    <strong>Connections:</strong> {nodeDegreeMap.get(selectedEntity.entity_id) || 0}
                  </span>
                </div>
                {selectedEntity.description && (
                  <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.5 }}>
                    {selectedEntity.description}
                  </div>
                )}
              </div>
            ) : selectedCommunity ? (
              <div style={{ marginBottom: '16px' }} data-testid="graph-community-details">
                <div style={{ fontSize: '14px', fontWeight: 800, color: 'var(--fg)' }}>{selectedCommunity.name}</div>
                <div style={{ marginTop: '6px', fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.5 }}>
                  {selectedCommunity.summary || '—'}
                </div>
              </div>
            ) : null}

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '10px' }}>
              <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Entities</div>
              <div style={{ fontSize: '11.5px', color: 'var(--fg-muted)' }}>{entityCountLabel}</div>
            </div>
            <div style={{ marginTop: '8px', maxHeight: '300px', overflow: 'auto' }}>
              <table style={tableStyle} data-testid="graph-entities-table">
                <thead>
                  <tr>
                    <th style={thStyle}>Name</th>
                    <th style={thStyle}>Type</th>
                    <th style={thStyle}>File</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>Connections</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredEntities.map((e) => {
                    const active = selectedEntity?.entity_id === e.entity_id;
                    return (
                      <tr
                        key={e.entity_id}
                        onClick={() => void handlePickEntity(active ? null : e)}
                        style={{
                          cursor: 'pointer',
                          background: active ? 'rgba(var(--accent-rgb), 0.12)' : 'transparent',
                        }}
                        data-testid={`graph-entity-row-${e.entity_id}`}
                      >
                        <td style={{ ...tdStyle, color: active ? 'var(--accent-text)' : 'var(--fg)', fontWeight: 600 }}>
                          {e.name}
                        </td>
                        <td style={tdStyle}>{e.entity_type}</td>
                        <td style={{ ...tdStyle, fontFamily: 'var(--font-mono)', wordBreak: 'break-all' }}>
                          {e.file_path || '—'}
                        </td>
                        <td style={{ ...tdStyle, textAlign: 'right' }}>{nodeDegreeMap.get(e.entity_id) || 0}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {!filteredEntities.length && (
                <div style={{ padding: '10px 2px', fontSize: '12px', color: 'var(--fg-muted)' }} data-testid="graph-entities-table-empty">
                  {entitiesEmptyReason}
                </div>
              )}
            </div>

            <div style={{ marginTop: '18px', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '10px' }}>
              <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Relationships</div>
              <div style={{ fontSize: '11.5px', color: 'var(--fg-muted)' }} data-testid="graph-relationship-count">
                {filteredRelationships.length.toLocaleString()} edges
              </div>
            </div>
            <div style={{ marginTop: '8px', maxHeight: '320px', overflow: 'auto' }}>
              <table style={tableStyle} data-testid="graph-relationships-table">
                <thead>
                  <tr>
                    <th style={thStyle}>Source</th>
                    <th style={thStyle}>Relation</th>
                    <th style={thStyle}>Target</th>
                    <th style={thStyle}>Provenance</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRelationships.map((r, idx) => (
                    <tr key={`${r.source_id}-${r.relation_type}-${r.target_id}-${idx}`}>
                      <td style={{ ...tdStyle, color: 'var(--fg)' }}>
                        {entityById.get(r.source_id)?.name || r.source_id}
                      </td>
                      <td style={{ ...tdStyle, fontFamily: 'var(--font-mono)' }}>{r.relation_type}</td>
                      <td style={{ ...tdStyle, color: 'var(--fg)' }}>
                        {entityById.get(r.target_id)?.name || r.target_id}
                      </td>
                      <td style={{ ...tdStyle, wordBreak: 'break-all' }}>{formatRelProvenance(r)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!filteredRelationships.length && (
                <div style={{ padding: '10px 2px', fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.5 }} data-testid="graph-relationships-empty">
                  {relationshipsEmptyReason}
                </div>
              )}
            </div>
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
              minWidth: 0,
            }}
            data-testid="graph-viz-panel"
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
              <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Visualization</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
                  {filteredEntities.length} nodes • {vizRelationships.length} edges
                </div>
                <GraphLegend types={renderedEntityTypes} colorOf={legendColor} testId="graph-legend" />
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <button type="button" style={controlButtonStyle} onClick={() => stepZoom(fgRef, 1 / 1.4)} data-testid="graph-zoom-out" title="Zoom out">
                    -
                  </button>
                  <span style={{ fontSize: '11.5px', color: 'var(--fg-muted)', minWidth: '46px', textAlign: 'center' }} data-testid="graph-zoom-level">
                    {formatZoom(vizZoom)}
                  </span>
                  <button type="button" style={controlButtonStyle} onClick={() => stepZoom(fgRef, 1.4)} data-testid="graph-zoom-in" title="Zoom in">
                    +
                  </button>
                  <button
                    type="button"
                    style={controlButtonStyle}
                    onClick={() => fgRef.current?.zoomToFit?.(400, 60)}
                    data-testid="graph-zoom-fit"
                    title="Fit the whole graph"
                  >
                    Fit
                  </button>
                </div>
                <select
                  value=""
                  onChange={(e) => {
                    const choice = e.target.value;
                    e.target.value = '';
                    if (choice === 'png') exportPng(vizCanvasRef.current);
                    else if (choice === 'entities') exportEntitiesCsv();
                    else if (choice === 'relationships') exportRelationshipsCsv();
                    else if (choice === 'json') exportJson();
                  }}
                  style={{
                    padding: '6px 8px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '8px',
                    color: 'var(--fg)',
                    fontSize: '11.5px',
                    fontWeight: 700,
                  }}
                  data-testid="graph-export"
                  aria-label="Export the rendered graph"
                >
                  <option value="">Export...</option>
                  <option value="png">Visualization (PNG)</option>
                  <option value="entities">Entities (CSV)</option>
                  <option value="relationships">Relationships (CSV)</option>
                  <option value="json">Entities + relationships (JSON)</option>
                </select>
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
                    color: 'var(--accent-text)',
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
                  onRenderFramePost={paintInlineLabels}
                  onZoom={(t: { k: number }) => setVizZoom(t.k)}
                  enableZoomInteraction={true}
                  enablePanInteraction={true}
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

            {filteredEntities.length > 0 && vizRelationships.length === 0 ? (
              <div
                style={{
                  marginTop: '10px',
                  padding: '10px 12px',
                  borderRadius: '10px',
                  border: '1px solid var(--line)',
                  background: 'rgba(var(--accent-rgb), 0.06)',
                  fontSize: '11.5px',
                  color: 'var(--fg-muted)',
                  lineHeight: 1.5,
                }}
                data-testid="graph-no-edges-note"
              >
                No relationships run between these {filteredEntities.length.toLocaleString()} entities, so they are
                drawn as unconnected nodes. Click one to load its neighborhood, or Reset for the whole-corpus graph.
              </div>
            ) : (
              <div style={{ marginTop: '10px', fontSize: '11.5px', color: 'var(--fg-muted)' }} data-testid="graph-viz-hint">
                Scroll or use the zoom controls to zoom, drag to pan, hover a node for its name, click a node to load
                its neighborhood. Expand opens the same graph full screen.
              </div>
            )}
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
            {/* Modal container - 85% of viewport. The visualizer paints white
                edges and dark label pills, so the modal keeps the dark token
                set under every theme (Light theme made the edges invisible). */}
            <div
              style={{
                ['--bg' as string]: '#09090b',
                ['--bg-elev1' as string]: '#0f0f12',
                ['--bg-elev2' as string]: '#18181b',
                ['--line' as string]: '#3f3f46',
                ['--fg' as string]: '#e4e4e7',
                ['--fg-muted' as string]: '#a1a1aa',
                color: '#e4e4e7',
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
                  {/* Same legend component as the inline panel: one source of truth (M-59). */}
                  <GraphLegend types={renderedEntityTypes} colorOf={legendColor} testId="graph-fullscreen-legend" />

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
                    nodePointerAreaPaint={(node: any, color: string, ctx: CanvasRenderingContext2D) => {
                      // Hit area must match the painted circle (custom painters get no default hit shape).
                      const degree = (node as NodeWithDegree).__degree || 0;
                      const radius = 4 * Math.min(2.5, 1 + degree * 0.15) + 2;
                      ctx.fillStyle = color;
                      ctx.beginPath();
                      ctx.arc(node.x ?? 0, node.y ?? 0, radius, 0, 2 * Math.PI);
                      ctx.fill();
                    }}
                    onRenderFramePost={paintFullscreenLabels}
                    onZoom={(t: { k: number }) => setFullscreenZoom(t.k)}
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
                    <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--accent-text)' }}>
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
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    fontSize: '11.5px',
                    color: 'var(--fg-muted)',
                    background: 'rgba(20, 20, 30, 0.92)',
                    padding: '8px 12px',
                    borderRadius: '8px',
                  }}
                  data-testid="graph-fullscreen-hint"
                >
                  <button type="button" style={controlButtonStyle} onClick={() => stepZoom(fullscreenFgRef, 1 / 1.4)} data-testid="graph-fullscreen-zoom-out" title="Zoom out">
                    -
                  </button>
                  <span style={{ minWidth: '46px', textAlign: 'center' }} data-testid="graph-fullscreen-zoom-level">
                    {formatZoom(fullscreenZoom)}
                  </span>
                  <button type="button" style={controlButtonStyle} onClick={() => stepZoom(fullscreenFgRef, 1.4)} data-testid="graph-fullscreen-zoom-in" title="Zoom in">
                    +
                  </button>
                  <button type="button" style={controlButtonStyle} onClick={() => fullscreenFgRef.current?.zoomToFit?.(400, 80)} data-testid="graph-fullscreen-zoom-fit" title="Fit the whole graph">
                    Fit
                  </button>
                  <button type="button" style={controlButtonStyle} onClick={() => exportPng(fullscreenCanvasRef.current)} data-testid="graph-fullscreen-export-png" title="Download this render as a PNG">
                    PNG
                  </button>
                  <span>Scroll or +/- to zoom, drag to pan, click a node for details, Esc to close</span>
                </div>
              </div>
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}
