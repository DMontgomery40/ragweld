/**
 * Intent Matrix JSON Editor Component
 *
 * Monaco-based JSON editor for the layer_bonus.intent_matrix config.
 * Allows advanced users to edit intent-to-layer bonus multipliers.
 *
 * Config Path: layer_bonus.intent_matrix
 */

import { useState, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import { useConfigField } from '@/hooks';
import { TooltipIcon } from '@/components/ui/TooltipIcon';

// Default intent matrix (must match Pydantic defaults in tribrid_config_model.py)
const DEFAULT_INTENT_MATRIX: Record<string, Record<string, number>> = {
  gui: { gui: 1.2, web: 1.2, server: 0.9, retrieval: 0.8, indexer: 0.8 },
  retrieval: { retrieval: 1.3, server: 1.15, common: 1.1, web: 0.7, gui: 0.6 },
  indexer: { indexer: 1.3, retrieval: 1.15, common: 1.1, web: 0.7, gui: 0.6 },
  eval: { eval: 1.3, retrieval: 1.15, server: 1.1, web: 0.8, gui: 0.7 },
  infra: { infra: 1.3, scripts: 1.15, server: 1.1, web: 0.9 },
  server: { server: 1.3, retrieval: 1.15, common: 1.1, web: 0.7, gui: 0.6 }
};

const EDITOR_ACTION_BUTTON_STYLE = {
  padding: '10px 12px',
  borderRadius: 8,
  border: '1px solid var(--line)',
  background: 'var(--bg-elev1)',
  color: 'var(--fg)',
  cursor: 'pointer',
  fontSize: 12,
  fontWeight: 600,
};

export function IntentMatrixEditor() {
  const [matrix, setMatrix] = useConfigField<Record<string, Record<string, number>>>(
    'layer_bonus.intent_matrix',
    DEFAULT_INTENT_MATRIX
  );

  // Local state for editor value (allows editing without immediate saves)
  const [editorValue, setEditorValue] = useState<string>('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [isDirty, setIsDirty] = useState(false);

  // Sync editor value when matrix changes from external source
  useEffect(() => {
    if (matrix && !isDirty) {
      setEditorValue(JSON.stringify(matrix, null, 2));
    }
  }, [matrix, isDirty]);

  const handleEditorChange = (value: string | undefined) => {
    const newValue = value || '{}';
    setEditorValue(newValue);
    setIsDirty(true);

    // Validate JSON on every change
    try {
      const parsed = JSON.parse(newValue);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setJsonError('Must be a JSON object');
        return;
      }

      // Validate structure: Dict[str, Dict[str, number]]
      for (const [intent, layers] of Object.entries(parsed)) {
        if (typeof layers !== 'object' || layers === null || Array.isArray(layers)) {
          setJsonError(`Intent "${intent}" must map to an object`);
          return;
        }
        for (const [layer, bonus] of Object.entries(layers as Record<string, unknown>)) {
          if (typeof bonus !== 'number') {
            setJsonError(`"${intent}.${layer}" must be a number`);
            return;
          }
        }
      }

      setJsonError(null);
    } catch (e) {
      setJsonError('Invalid JSON syntax');
    }
  };

  const handleApply = () => {
    if (jsonError) return;

    try {
      const parsed = JSON.parse(editorValue);
      setMatrix(parsed);
      setIsDirty(false);
    } catch {
      setJsonError('Invalid JSON');
    }
  };

  const handleReset = () => {
    setMatrix(DEFAULT_INTENT_MATRIX);
    setEditorValue(JSON.stringify(DEFAULT_INTENT_MATRIX, null, 2));
    setJsonError(null);
    setIsDirty(false);
  };

  return (
    <div className="input-group" style={{ gridColumn: '1 / -1', marginTop: '16px' }}>
      <div className="editor-panel-header">
        <label className="editor-panel-title">
          Intent Matrix (Advanced)
          <TooltipIcon name="LAYER_INTENT_MATRIX" />
        </label>
        <div className="editor-panel-actions">
          <button
            type="button"
            data-testid="intent-matrix-reset"
            onClick={handleReset}
            style={EDITOR_ACTION_BUTTON_STYLE}
          >
            Reset to Default
          </button>
          <button
            type="button"
            data-testid="intent-matrix-apply"
            onClick={handleApply}
            disabled={!!jsonError || !isDirty}
            style={{
              ...EDITOR_ACTION_BUTTON_STYLE,
              border: `1px solid ${isDirty && !jsonError ? 'var(--accent)' : 'var(--line)'}`,
              background: isDirty && !jsonError ? 'rgba(var(--accent-rgb), 0.12)' : 'var(--bg-elev1)',
              color: isDirty && !jsonError ? 'var(--accent)' : 'var(--fg)',
              cursor: !!jsonError || !isDirty ? 'not-allowed' : 'pointer',
              opacity: !!jsonError || !isDirty ? 0.6 : 1,
            }}
          >
            Apply Changes
          </button>
        </div>
      </div>

      <div className={`editor-panel ${jsonError ? 'has-error' : ''}`}>
        <Editor
          height="280px"
          language="json"
          theme="vs-dark"
          value={editorValue}
          onChange={handleEditorChange}
          options={{
            minimap: { enabled: false },
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            fontSize: 12,
            fontFamily: "'SF Mono', 'Monaco', 'Consolas', monospace",
            padding: { top: 8, bottom: 8 },
            renderLineHighlight: 'line',
            automaticLayout: true
          }}
        />
      </div>

      {jsonError && (
        <div className="editor-error">
          <span aria-hidden="true">⚠</span>
          {jsonError}
        </div>
      )}

      <p className="editor-help">
        Maps query intents to layer bonus multipliers. Values {'>'} 1.0 boost that layer for the intent;
        {'<'} 1.0 penalizes. Intents: gui, retrieval, indexer, eval, infra, server.
      </p>
    </div>
  );
}
