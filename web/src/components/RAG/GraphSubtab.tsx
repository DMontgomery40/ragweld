import { useEffect, useMemo, useState } from 'react';
import { useGraph } from '@/hooks/useGraph';
import { useRepoStore } from '@/stores/useRepoStore';
import type { Community, Entity, Relationship } from '@/types/generated';

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
    relationships,
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

  useEffect(() => {
    if (!repos.length) void loadRepos();
  }, [repos.length, loadRepos]);

  const entityById = useMemo(() => {
    return new Map<string, Entity>((entities || []).map((e) => [e.entity_id, e]));
  }, [entities]);

  const filteredEntities = useMemo(() => {
    return getEntitiesByType(visibleEntityTypes);
  }, [getEntitiesByType, visibleEntityTypes]);

  const filteredRelationships = useMemo(() => {
    return getRelationshipsByType(visibleRelationTypes);
  }, [getRelationshipsByType, visibleRelationTypes]);

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

  return (
    <div className="subtab-panel" style={{ padding: '24px' }} data-testid="graph-subtab">
      <div style={{ marginBottom: '18px' }}>
        <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--fg)', margin: 0 }}>
          🕸️ Graph Explorer
        </h3>
        <div style={{ marginTop: '6px', fontSize: '13px', color: 'var(--fg-muted)' }}>
          Inspect entities, relationships, and communities stored in Neo4j for the active corpus.
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

        {/* Details */}
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
      </div>
    </div>
  );
}

