import { useEffect, useMemo, useState } from 'react';
import Editor from '@monaco-editor/react';

import { useConfigControlPlaneData, useConfigFieldSave } from './configControlPlane';
import { confirmDialog } from '@/components/ui/confirmDialog';

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
  // The last loaded/saved JSON for this section. `Cancel` reverts to it; a raw overwrite is
  // only offered when the draft actually differs from it (E-39: the whole section used to be a
  // live textarea, so a stray keypress while scrolling silently corrupted the buffer).
  const [original, setOriginal] = useState('');
  const [editing, setEditing] = useState(false);
  const [jsonError, setJsonError] = useState<string | null>(null);
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
    const serialized = JSON.stringify(next ?? {}, null, 2);
    setDraft(serialized);
    setOriginal(serialized);
    // Switching section (or a fresh load) drops out of edit mode: the operator opts back in
    // deliberately before the buffer is writable again.
    setEditing(false);
    setJsonError(null);
    setRawError(null);
  }, [config, section]);

  useEffect(() => {
    if (selectedSection && sections.includes(selectedSection)) {
      setSection(selectedSection);
    }
  }, [sections, selectedSection]);

  const validate = (value: string): string | null => {
    if (!value.trim()) return null; // empty -> {} on save
    let parsed: unknown;
    try {
      parsed = JSON.parse(value);
    } catch (err) {
      return err instanceof Error ? `Invalid JSON: ${err.message}` : 'Invalid JSON';
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return 'A config section must be a JSON object.';
    }
    return null;
  };

  const dirty = editing && draft !== original;

  const handleEditorChange = (value: string | undefined) => {
    const next = value ?? '';
    setDraft(next);
    setJsonError(validate(next));
    setStatus(null);
  };

  const handleEdit = () => {
    setEditing(true);
    setStatus(null);
    setRawError(null);
  };

  const handleCancel = () => {
    setDraft(original);
    setEditing(false);
    setJsonError(null);
    setRawError(null);
    setStatus(null);
  };

  const handleSave = async () => {
    const problem = validate(draft);
    if (problem) {
      setJsonError(problem);
      return;
    }
    // A raw overwrite replaces the ENTIRE section exactly as parsed; confirm that consequence
    // before the write (T7: raw config overwrite is a deliberate, named action, not a keystroke).
    const proceed = await confirmDialog({
      title: `Replace the "${section}" section`,
      message:
        `Overwrite the entire "${section}" config section with the edited JSON exactly as parsed. ` +
        `Any field you removed from the JSON reverts to nothing for this section. This is a raw ` +
        `write with no per-field validation beyond the schema. Replace the section?`,
      confirmLabel: 'Replace section',
      cancelLabel: 'Keep editing',
      danger: true,
    });
    if (!proceed) return;
    try {
      const parsed = draft.trim() ? JSON.parse(draft) : {};
      await replaceSection(section, parsed);
      await reload();
      setRawError(null);
      setEditing(false);
      setStatus('Section saved');
      window.setTimeout(() => setStatus(null), 1600);
    } catch (err) {
      setRawError(err instanceof Error ? err.message : 'Unable to save this section.');
    }
  };

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

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        <select
          value={section}
          onChange={(event) => setSection(event.target.value)}
          data-testid="raw-section-select"
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
        <span
          data-testid="raw-editor-mode"
          style={{
            fontSize: 12,
            fontWeight: 700,
            padding: '4px 10px',
            borderRadius: 999,
            border: `1px solid ${editing ? 'var(--accent)' : 'var(--line)'}`,
            color: editing ? 'var(--accent-text, var(--accent))' : 'var(--fg-muted)',
            background: editing ? 'rgba(0,0,0,0.04)' : 'transparent',
          }}
        >
          {editing ? 'Editing' : 'Read-only'}
        </span>
      </div>

      <div
        data-testid="raw-editor-panel"
        style={{
          border: `1px solid ${jsonError ? 'var(--err)' : editing ? 'var(--accent)' : 'var(--line)'}`,
          borderRadius: 12,
          overflow: 'hidden',
          // A read-only buffer reads as inert so it is visibly not a live edit surface.
          opacity: editing ? 1 : 0.92,
        }}
      >
        <Editor
          height="360px"
          language="json"
          theme="vs-dark"
          value={draft}
          onChange={handleEditorChange}
          options={{
            readOnly: !editing,
            domReadOnly: !editing,
            minimap: { enabled: false },
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            fontSize: 12,
            fontFamily: "'SF Mono', 'Monaco', 'Consolas', monospace",
            padding: { top: 8, bottom: 8 },
            renderValidationDecorations: 'on',
            automaticLayout: true,
          }}
        />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', marginTop: 12, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
          Section `{section}` will be replaced exactly as parsed JSON.
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {editing ? (
            <>
              <button
                type="button"
                data-testid="raw-editor-cancel"
                onClick={handleCancel}
                style={{
                  padding: '10px 14px',
                  borderRadius: 10,
                  border: '1px solid var(--line)',
                  background: 'transparent',
                  color: 'var(--fg)',
                  cursor: 'pointer',
                  fontWeight: 600,
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                data-testid="raw-editor-save"
                onClick={() => void handleSave()}
                disabled={saving || !section || !!jsonError || !dirty}
                title={jsonError ? jsonError : !dirty ? 'No changes to save' : 'Replace this section'}
                style={{
                  padding: '10px 14px',
                  borderRadius: 10,
                  border: `1px solid ${!jsonError && dirty ? 'var(--accent)' : 'var(--line)'}`,
                  background: !jsonError && dirty ? 'var(--accent)' : 'var(--bg-elev2)',
                  color: !jsonError && dirty ? 'var(--accent-contrast, #fff)' : 'var(--fg-muted)',
                  cursor: saving || !!jsonError || !dirty ? 'not-allowed' : 'pointer',
                  fontWeight: 700,
                }}
              >
                {saving ? 'Saving…' : 'Save Section'}
              </button>
            </>
          ) : (
            <button
              type="button"
              data-testid="raw-editor-edit"
              onClick={handleEdit}
              style={{
                padding: '10px 14px',
                borderRadius: 10,
                border: '1px solid var(--accent)',
                background: 'transparent',
                color: 'var(--accent-text, var(--accent))',
                cursor: 'pointer',
                fontWeight: 700,
              }}
            >
              Edit section
            </button>
          )}
        </div>
      </div>

      {jsonError ? <div data-testid="raw-editor-json-error" style={{ marginTop: 10, color: 'var(--err)', fontSize: 12 }}>{jsonError}</div> : null}
      {rawError ? <div style={{ marginTop: 10, color: 'var(--err)', fontSize: 12 }}>{rawError}</div> : null}
      {status ? <div style={{ marginTop: 10, color: 'var(--ok)', fontSize: 12 }}>{status}</div> : null}
    </div>
  );
}
