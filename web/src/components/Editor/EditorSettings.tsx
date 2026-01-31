import type { EditorSettings as EditorSettingsType, EditorTheme } from '../../hooks/useEditor';

interface EditorSettingsProps {
  settings: EditorSettingsType;
  onUpdate: (updates: Partial<EditorSettingsType>) => void;
  onReset: () => void;
}

/**
 * Editor settings panel component
 * Provides UI for configuring editor appearance and behavior
 */
export function EditorSettings({ settings, onUpdate, onReset }: EditorSettingsProps) {
  return (
    <div style={{ padding: '16px', background: 'var(--bg-elev1)', borderRadius: '6px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600 }}>Editor Settings</h3>
        <button
          onClick={onReset}
          className="small-button"
          style={{ background: 'var(--bg-elev2)', color: 'var(--fg-muted)', border: '1px solid var(--line)' }}
        >
          Reset to Defaults
        </button>
      </div>

      <div style={{ display: 'grid', gap: '16px' }}>
        {/* Theme Selection */}
        <div>
          <label style={{ display: 'block', marginBottom: '8px', fontSize: '13px', fontWeight: 500 }}>
            Theme
          </label>
          <select
            value={settings.theme}
            onChange={(e) => onUpdate({ theme: e.target.value as EditorTheme })}
            style={{
              width: '100%',
              padding: '8px',
              borderRadius: '4px',
              border: '1px solid var(--line)',
              background: 'var(--bg-elev2)',
              color: 'var(--fg)'
            }}
          >
            <option value="vs-dark">Dark</option>
            <option value="vs-light">Light</option>
            <option value="hc-black">High Contrast</option>
          </select>
        </div>

        {/* Font Size */}
        <div>
          <label style={{ display: 'block', marginBottom: '8px', fontSize: '13px', fontWeight: 500 }}>
            Font Size: {settings.fontSize}px
          </label>
          <input
            type="range"
            min="10"
            max="24"
            value={settings.fontSize}
            onChange={(e) => onUpdate({ fontSize: parseInt(e.target.value) })}
            style={{ width: '100%' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
            <span>10px</span>
            <span>24px</span>
          </div>
        </div>

        {/* Tab Size */}
        <div>
          <label style={{ display: 'block', marginBottom: '8px', fontSize: '13px', fontWeight: 500 }}>
            Tab Size: {settings.tabSize} spaces
          </label>
          <input
            type="range"
            min="2"
            max="8"
            step="2"
            value={settings.tabSize}
            onChange={(e) => onUpdate({ tabSize: parseInt(e.target.value) })}
            style={{ width: '100%' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
            <span>2</span>
            <span>4</span>
            <span>6</span>
            <span>8</span>
          </div>
        </div>

        {/* Auto-save Delay */}
        {settings.autoSave && (
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '13px', fontWeight: 500 }}>
              Auto-save Delay: {settings.autoSaveDelay}ms
            </label>
            <input
              type="range"
              min="500"
              max="5000"
              step="500"
              value={settings.autoSaveDelay}
              onChange={(e) => onUpdate({ autoSaveDelay: parseInt(e.target.value) })}
              style={{ width: '100%' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
              <span>500ms</span>
              <span>2500ms</span>
              <span>5000ms</span>
            </div>
          </div>
        )}

        {/* Toggle Settings */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '12px', paddingTop: '8px' }}>
          <ToggleSetting
            label="Word Wrap"
            checked={settings.wordWrap}
            onChange={(checked) => onUpdate({ wordWrap: checked })}
          />
          <ToggleSetting
            label="Minimap"
            checked={settings.minimap}
            onChange={(checked) => onUpdate({ minimap: checked })}
          />
          <ToggleSetting
            label="Line Numbers"
            checked={settings.lineNumbers}
            onChange={(checked) => onUpdate({ lineNumbers: checked })}
          />
          <ToggleSetting
            label="Auto Save"
            checked={settings.autoSave}
            onChange={(checked) => onUpdate({ autoSave: checked })}
          />
          <ToggleSetting
            label="Format on Save"
            checked={settings.formatOnSave}
            onChange={(checked) => onUpdate({ formatOnSave: checked })}
          />
          <ToggleSetting
            label="Show Whitespace"
            checked={typeof settings.renderWhitespace === 'boolean' ? settings.renderWhitespace : settings.renderWhitespace !== 'none'}
            onChange={(checked) => onUpdate({ renderWhitespace: checked })}
          />
          <ToggleSetting
            label="Scroll Beyond Last Line"
            checked={settings.scrollBeyondLastLine}
            onChange={(checked) => onUpdate({ scrollBeyondLastLine: checked })}
          />
        </div>
      </div>
    </div>
  );
}

/**
 * Reusable toggle setting component
 */
function ToggleSetting({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        cursor: 'pointer',
        padding: '8px',
        borderRadius: '4px',
        background: checked ? 'var(--bg-elev2)' : 'transparent',
        border: '1px solid var(--line)',
        transition: 'all 0.2s'
      }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        style={{
          width: '16px',
          height: '16px',
          cursor: 'pointer'
        }}
      />
      <span style={{ fontSize: '13px', userSelect: 'none' }}>{label}</span>
    </label>
  );
}
