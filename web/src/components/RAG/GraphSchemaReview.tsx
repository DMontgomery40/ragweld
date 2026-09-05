import type { CSSProperties } from 'react';
import type { GraphSchemaProposal } from '@/types/generated';

type SchemaItem = Record<string, unknown>;
const rows = (value: unknown): SchemaItem[] => Array.isArray(value)
  ? value.filter((item): item is SchemaItem => typeof item === 'object' && item !== null && !Array.isArray(item))
  : [];
const summaryStyle: CSSProperties = { cursor: 'pointer', fontWeight: 600, color: 'var(--fg)', padding: '4px 0' };
const listStyle: CSSProperties = { display: 'grid', gap: 10, margin: '10px 0', paddingLeft: 20, overflowWrap: 'anywhere' };

/** The operator reviews a schema; serialization and provenance are optional detail. */
export function GraphSchemaReview({ proposal }: { proposal: GraphSchemaProposal }) {
  const schema = proposal.schema as Record<string, unknown>;
  const nodes = rows(schema.node_types);
  const relationships = rows(schema.relationship_types);
  const patterns: unknown[] = Array.isArray(schema.patterns) ? schema.patterns : [];
  const constraints: unknown[] = Array.isArray(schema.constraints) ? schema.constraints : [];
  const types = (items: SchemaItem[]) => items.map((item, index) => (
    <li key={`${String(item.label)}:${index}`}>
      <strong>{String(item.label ?? 'Unnamed type')}</strong>
      {typeof item.description === 'string' && <div style={{ color: 'var(--fg-muted)' }}>{item.description}</div>}
      {rows(item.properties).length > 0 && <div style={{ color: 'var(--fg-muted)', marginTop: 3 }}>
        {rows(item.properties).map((property) => `${String(property.name)}: ${String(property.type ?? 'value')}${property.required ? ' (required)' : ''}`).join(' · ')}
      </div>}
    </li>
  ));
  return <section data-testid="graph-schema-proposal" style={{ padding: 14, border: '1px solid var(--line)', borderRadius: 8, background: 'var(--bg)', fontSize: 13, minWidth: 0 }}>
    <div style={{ fontWeight: 650, color: 'var(--fg)' }}>Proposed graph schema</div>
    <div data-testid="graph-schema-overview" style={{ color: 'var(--fg-muted)', marginTop: 5 }}>
      {nodes.length} entity {nodes.length === 1 ? 'type' : 'types'} · {relationships.length} {relationships.length === 1 ? 'relationship' : 'relationships'} · {patterns.length} connection {patterns.length === 1 ? 'pattern' : 'patterns'}
    </div>
    <details data-testid="graph-schema-review" style={{ marginTop: 10 }}>
      <summary style={summaryStyle}>Review schema</summary>
      <div style={{ display: 'grid', gap: 8, marginTop: 8 }}>
        <details data-testid="graph-schema-node-types">
          <summary style={summaryStyle}>Entity types ({nodes.length})</summary>
          <ul style={listStyle}>{types(nodes)}</ul>
        </details>
        <details data-testid="graph-schema-relationship-types">
          <summary style={summaryStyle}>Relationships ({relationships.length})</summary>
          <ul style={listStyle}>{types(relationships)}</ul>
        </details>
        <details data-testid="graph-schema-patterns">
          <summary style={summaryStyle}>Connection patterns ({patterns.length})</summary>
          <ul style={listStyle}>{patterns.map((pattern, index) => <li key={index}>
            {Array.isArray(pattern) ? pattern.map(String).join(' → ') : typeof pattern === 'object' && pattern !== null
              ? [String((pattern as SchemaItem).source), String((pattern as SchemaItem).relationship), String((pattern as SchemaItem).target)].join(' → ')
              : String(pattern)}
          </li>)}</ul>
        </details>
        <details data-testid="graph-schema-constraints">
          <summary style={summaryStyle}>Constraints ({constraints.length})</summary>
          {constraints.length === 0 ? <p style={{ color: 'var(--fg-muted)' }}>No additional constraints.</p> : <ul style={listStyle}>
            {constraints.map((constraint, index) => {
              if (typeof constraint !== 'object' || constraint === null) return <li key={index}>{String(constraint)}</li>;
              const rule = constraint as SchemaItem;
              const properties = Array.isArray(rule.property_names) ? rule.property_names.map(String).join(', ') : '';
              const kind = String(rule.type).toLowerCase();
              const requirement = kind === 'existence' ? 'required' : kind === 'uniqueness' ? 'unique' : kind === 'key' ? 'required and unique' : kind;
              return <li key={index}><strong>{String(rule.node_type ?? rule.relationship_type ?? 'All types')}</strong>: {properties} — {requirement}</li>;
            })}
          </ul>}
        </details>
      </div>
    </details>
    <details data-testid="graph-schema-technical" style={{ marginTop: 6, color: 'var(--fg-muted)', fontSize: 12 }}>
      <summary style={{ cursor: 'pointer', padding: '4px 0' }}>Technical details</summary>
      <dl style={{ display: 'grid', gap: '4px 12px', gridTemplateColumns: 'auto minmax(0, 1fr)', margin: '12px 0', overflowWrap: 'anywhere' }}>
        <dt>Model</dt><dd style={{ margin: 0 }}>{proposal.model_alias}</dd>
        <dt>GraphRAG</dt><dd style={{ margin: 0 }}>{proposal.graphrag_version}</dd>
        <dt>Schema ID</dt><dd data-testid="graph-schema-hash" style={{ margin: 0, fontFamily: 'var(--font-mono)' }}>{proposal.schema_hash}</dd>
        <dt>Sampling</dt><dd style={{ margin: 0 }}>{proposal.sample.recipe}</dd>
      </dl>
      <details data-testid="graph-schema-sample">
        <summary style={{ cursor: 'pointer' }}>Source sample ({proposal.sample.chunk_ids.length} chunks)</summary>
        <ol style={listStyle}>{proposal.sample.chunk_ids.map((chunkId, index) => <li key={`${chunkId}:${index}`}>
          <code>{chunkId}</code><div>SHA-256 {proposal.sample.chunk_hashes[index]}</div>
        </li>)}</ol>
      </details>
      <details data-testid="graph-schema-json" style={{ marginTop: 10 }}>
        <summary style={{ cursor: 'pointer' }}>Raw schema JSON</summary>
        <pre style={{ padding: 12, maxHeight: 280, overflow: 'auto', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', background: 'var(--bg-elev2)', borderRadius: 6 }}>{JSON.stringify(schema, null, 2)}</pre>
      </details>
      <p>Approval applies to this schema and source version. Changes require another review.</p>
    </details>
  </section>;
}
