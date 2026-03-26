import { useEffect, useMemo, useState } from 'react';

import { useConfigControlPlaneData, useConfigFieldSave } from './configControlPlane';

type ConfigRawSubtabProps = {
  selectedSection?: string;
};

export function ConfigRawSubtab({ selectedSection }: ConfigRawSubtabProps) {
  const { registry, loading, error, reload } = useConfigControlPlaneData();
  const { config, replaceSection, saving } = useConfigFieldSave();
  const sections = useMemo(() => {
    const values = new Set((registry?.fields || []).map((field) => field.section));
    return Array.from(values).sort();
  }, [registry]);
  const [section, setSection] = useState<string>(selectedSection || '');
  const [draft, setDraft] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [rawError, setRawError] = useState<string | null>(null);

  useEffect(() => {
    if (!section && sections.length > 0) {
      setSection(selectedSection && sections.includes(selectedSection) ? selectedSection : sections[0]);
    }
  }, [section, sections, selectedSection]);

  useEffect(() => {
    if (!config || !section) return;
    const next = (config as unknown as Record<string, unknown>)[section];
    setDraft(JSON.stringify(next ?? {}, null, 2));
    setRawError(null);
  }, [config, section]);

  useEffect(() => {
    if (selectedSection && sections.includes(selectedSection)) {
      setSection(selectedSection);
    }
  }, [sections, selectedSection]);

  if (loading) {
    return <div className="settings-section">Loading raw section editor…</div>;
  }

  if (error) {
    return <div className="settings-section" style={{ color: 'var(--err)' }}>Unable to load raw editor: {error}</div>;
  }

  return (
    <div className="settings-section">
      <h2 style={{ marginBottom: 8 }}>Raw Section Editor</h2>
      <p className="small" style={{ marginBottom: 18, maxWidth: 860 }}>
        Complete fallback coverage for every top-level config section. This editor replaces the entire selected section, so it is the escape hatch for complex arrays, objects, and expert-only fields.
      </p>

      <div style={{ marginBottom: 12 }}>
        <select
          value={section}
          onChange={(event) => setSection(event.target.value)}
          style={{
            minWidth: 240,
            padding: '10px 12px',
            borderRadius: 10,
            border: '1px solid var(--line)',
            background: 'var(--bg)',
            color: 'var(--fg)',
          }}
        >
          {sections.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </div>

      <textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        spellCheck={false}
        rows={22}
        style={{
          width: '100%',
          padding: 14,
          borderRadius: 12,
          border: '1px solid var(--line)',
          background: 'var(--bg)',
          color: 'var(--fg)',
          fontFamily: 'var(--font-mono)',
          fontSize: 12,
        }}
      />

      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', marginTop: 12, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
          Section `{section}` will be replaced exactly as parsed JSON.
        </div>
        <button
          type="button"
          onClick={() => {
            void (async () => {
              try {
                const parsed = draft.trim() ? JSON.parse(draft) : {};
                await replaceSection(section, parsed);
                await reload();
                setRawError(null);
                setStatus('Section saved');
                window.setTimeout(() => setStatus(null), 1600);
              } catch (err) {
                setRawError(err instanceof Error ? err.message : 'Unable to save this section.');
              }
            })();
          }}
          disabled={saving || !section}
          style={{
            padding: '10px 14px',
            borderRadius: 10,
            border: '1px solid var(--line)',
            background: 'var(--bg-elev2)',
            color: 'var(--fg)',
            cursor: 'pointer',
            fontWeight: 700,
          }}
        >
          {saving ? 'Saving…' : 'Save Section'}
        </button>
      </div>

      {rawError ? <div style={{ marginTop: 10, color: 'var(--err)', fontSize: 12 }}>{rawError}</div> : null}
      {status ? <div style={{ marginTop: 10, color: 'var(--ok)', fontSize: 12 }}>{status}</div> : null}
    </div>
  );
}
