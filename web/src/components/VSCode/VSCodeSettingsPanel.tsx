import { useEffect, useState } from 'react';
import { useAPI } from '@/hooks';

interface EditorSettings {
  enabled: boolean;
  embed_enabled: boolean;
  port: number;
  bind: string;
  host: string;
  image?: string;
}

const DEFAULT_SETTINGS: EditorSettings = {
  enabled: true,
  embed_enabled: true,
  port: 4440,
  bind: 'local',
  host: '127.0.0.1',
};

export function VSCodeSettingsPanel() {
  const { api } = useAPI();
  const [settings, setSettings] = useState<EditorSettings>(DEFAULT_SETTINGS);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string>('');

  useEffect(() => {
    void loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      setLoading(true);
      const resp = await fetch(api('/api/editor/settings'));
      if (resp.ok) {
        const data = await resp.json();
        setSettings({
          enabled: data.enabled !== false,
          embed_enabled: data.embed_enabled !== false,
          port: Number(data.port ?? DEFAULT_SETTINGS.port),
          bind: String(data.bind ?? DEFAULT_SETTINGS.bind),
          host: String(data.host ?? DEFAULT_SETTINGS.host),
          image: data.image,
        });
      }
    } catch (e) {
      setMessage('Failed to load editor settings');
    } finally {
      setLoading(false);
    }
  };

  const saveSettings = async () => {
    try {
      setSaving(true);
      const resp = await fetch(api('/api/editor/settings'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: settings.enabled,
          embed_enabled: settings.embed_enabled,
          port: settings.port,
          bind: settings.bind,
          host: settings.host,
          image: settings.image,
        }),
      });
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      setMessage('Editor settings saved');
      setTimeout(() => setMessage(''), 2000);
    } catch (e) {
      setMessage('Failed to save editor settings');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="settings-section" style={{ padding: '24px' }}>
      <h3 id="editor-settings-anchor" style={{ marginTop: 0, marginBottom: '16px' }}>Editor Settings</h3>
      <p className="small" style={{ color: 'var(--fg-muted)', marginTop: 0, marginBottom: '16px' }}>
        Enable or disable the embedded VS Code server and configure its port/bind address. These values are stored in agro_config.json and served via the new editor settings API.
      </p>

      <div style={{ display: 'grid', gap: '16px', maxWidth: '640px' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
          <input
            type="checkbox"
            name="EDITOR_ENABLED"
            checked={settings.enabled}
            onChange={(e) => setSettings(prev => ({ ...prev, enabled: e.target.checked }))}
            title="Turn the embedded editor on or off"
          />
          Enable embedded editor
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
          <input
            type="checkbox"
            name="EDITOR_EMBED_ENABLED"
            checked={settings.embed_enabled}
            onChange={(e) => setSettings(prev => ({ ...prev, embed_enabled: e.target.checked }))}
            title="Show or hide the editor iframe inside the app (useful to disable in CI)"
          />
          Show editor iframe in UI
        </label>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>
              Port
            </label>
            <input
              type="number"
              name="EDITOR_PORT"
              min={1024}
              max={65535}
              value={settings.port}
              onChange={(e) => setSettings(prev => ({ ...prev, port: Number(e.target.value) }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: '4px', border: '1px solid var(--line)' }}
              title="Port used by the embedded VS Code server (default 4440)"
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>
              Bind
            </label>
            <input
              type="text"
              name="EDITOR_BIND"
              value={settings.bind}
              onChange={(e) => setSettings(prev => ({ ...prev, bind: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: '4px', border: '1px solid var(--line)' }}
              title="Bind mode for the editor (e.g., local, 0.0.0.0)"
            />
          </div>
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>
            Host (legacy)
          </label>
          <input
            type="text"
            name="EDITOR_HOST"
            value={settings.host}
            onChange={(e) => setSettings(prev => ({ ...prev, host: e.target.value }))}
            style={{ width: '100%', padding: '10px 12px', borderRadius: '4px', border: '1px solid var(--line)' }}
            title="Host used for iframe URL fallback"
          />
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>
            Docker image (optional)
          </label>
          <input
            type="text"
            name="EDITOR_IMAGE"
            value={settings.image || ''}
            onChange={(e) => setSettings(prev => ({ ...prev, image: e.target.value }))}
            style={{ width: '100%', padding: '10px 12px', borderRadius: '4px', border: '1px solid var(--line)' }}
            placeholder="agro-vscode:latest"
            title="Override the VS Code server image if needed"
          />
        </div>
      </div>

      <div style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
        <button
          onClick={saveSettings}
          disabled={saving}
          className="small-button"
          style={{ background: 'var(--accent)', color: 'var(--accent-contrast)', border: 'none', padding: '10px 16px', borderRadius: '6px' }}
        >
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
        <button
          onClick={loadSettings}
          disabled={loading}
          className="small-button"
          style={{ background: 'var(--bg-elev2)', color: 'var(--fg)', border: '1px solid var(--line)', padding: '10px 16px', borderRadius: '6px' }}
        >
          {loading ? 'Refreshing...' : 'Reload'}
        </button>
      </div>

      {message && (
        <div style={{ marginTop: '12px', fontSize: '13px', color: 'var(--fg-muted)' }}>
          {message}
        </div>
      )}
    </div>
  );
}
