import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';

import { ConfigFieldEditor, useConfigControlPlaneData, useConfigFieldSave } from './configControlPlane';

type ConfigExplorerSubtabProps = {
  onOpenRaw: (section: string) => void;
};

export function ConfigExplorerSubtab({ onOpenRaw }: ConfigExplorerSubtabProps) {
  const { registry, loading, error, reload } = useConfigControlPlaneData();
  const { config, saveField, saving } = useConfigFieldSave();
  const saveAndRefresh = async (path: string, value: unknown) => {
    await saveField(path, value);
    await reload();
  };
  // `?q=<dotted.path>` deep-links from the global settings search (Ctrl+K).
  const location = useLocation();
  const requestedPath = useMemo(() => new URLSearchParams(location.search || '').get('q') || '', [location.search]);
  const [query, setQuery] = useState(requestedPath);
  const highlightRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (requestedPath) setQuery(requestedPath);
  }, [requestedPath]);
  const [integrationFilter, setIntegrationFilter] = useState('all');
  const [scopeFilter, setScopeFilter] = useState('all');
  const [impactFilter, setImpactFilter] = useState('all');
  const [surfaceFilter, setSurfaceFilter] = useState('all');

  const integrations = useMemo(() => {
    const values = new Set((registry?.fields || []).map((field) => field.integration));
    return ['all', ...Array.from(values).sort()];
  }, [registry]);

  const surfaces = useMemo(() => {
    const values = new Set((registry?.fields || []).map((field) => field.ui_surface));
    return ['all', ...Array.from(values).sort()];
  }, [registry]);

  const filteredFields = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (registry?.fields || []).filter((field) => {
      if (integrationFilter !== 'all' && field.integration !== integrationFilter) return false;
      if (scopeFilter !== 'all' && field.scope !== scopeFilter) return false;
      if (impactFilter !== 'all' && field.impact !== impactFilter) return false;
      if (surfaceFilter !== 'all' && field.ui_surface !== surfaceFilter) return false;
      if (!needle) return true;
      const haystack = [
        field.path,
        field.label,
        field.integration,
        field.ui_surface,
        field.description || '',
      ]
        .join(' ')
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [impactFilter, integrationFilter, query, registry, scopeFilter, surfaceFilter]);

  useEffect(() => {
    if (!requestedPath || loading) return;
    const handle = window.setTimeout(() => {
      highlightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 150);
    return () => window.clearTimeout(handle);
  }, [loading, requestedPath, filteredFields.length]);

  if (loading) {
    return <div className="settings-section">Loading advanced configuration explorer…</div>;
  }

  if (error) {
    return (
      <div className="settings-section">
        <div style={{ color: 'var(--err)', marginBottom: 12 }}>Unable to load config explorer: {error}</div>
        <button type="button" onClick={() => { void reload(); }}>Retry</button>
      </div>
    );
  }

  return (
    <div className="settings-section">
      <h2 style={{ marginBottom: 8 }}>Advanced Explorer</h2>
      <p className="small" style={{ marginBottom: 18, maxWidth: 860 }}>
        Search the full classified config surface by path, description, integration, scope, impact, or UI surface. This is the complete registry view, not a hand-picked settings form.
      </p>

      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', marginBottom: 18 }}>
        <input
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search fields, paths, or descriptions"
          style={{
            gridColumn: '1 / -1',
            padding: '10px 12px',
            borderRadius: 10,
            border: '1px solid var(--line)',
            background: 'var(--bg)',
            color: 'var(--fg)',
          }}
        />

        <select value={integrationFilter} onChange={(event) => setIntegrationFilter(event.target.value)}>
          {integrations.map((value) => (
            <option key={value} value={value}>
              {value === 'all' ? 'All integrations' : value}
            </option>
          ))}
        </select>

        <select value={scopeFilter} onChange={(event) => setScopeFilter(event.target.value)}>
          <option value="all">All scopes</option>
          <option value="global">Global</option>
          <option value="corpus">Corpus</option>
        </select>

        <select value={impactFilter} onChange={(event) => setImpactFilter(event.target.value)}>
          <option value="all">All impacts</option>
          <option value="live">Live</option>
          <option value="restart">Restart</option>
          <option value="reindex">Reindex</option>
          <option value="redeploy">Redeploy</option>
        </select>

        <select value={surfaceFilter} onChange={(event) => setSurfaceFilter(event.target.value)}>
          {surfaces.map((value) => (
            <option key={value} value={value}>
              {value === 'all' ? 'All surfaces' : value}
            </option>
          ))}
        </select>
      </div>

      <div style={{ marginBottom: 16, fontSize: 13, color: 'var(--fg-muted)' }}>
        Showing {filteredFields.length.toLocaleString()} of {(registry?.fields || []).length.toLocaleString()} registered fields.
      </div>

      <div style={{ display: 'grid', gap: 12 }}>
        {filteredFields.map((field) => {
          const highlighted = Boolean(requestedPath) && field.path === requestedPath;
          return (
            <div
              key={field.path}
              ref={highlighted ? highlightRef : undefined}
              data-testid={`config-field-${field.path}`}
              data-highlighted={highlighted ? 'true' : undefined}
              style={highlighted ? { outline: '2px solid var(--accent)', outlineOffset: 4, borderRadius: 12 } : undefined}
            >
              <ConfigFieldEditor
                field={field}
                config={config}
                onSave={saveAndRefresh}
                onOpenRaw={onOpenRaw}
                saving={saving}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
