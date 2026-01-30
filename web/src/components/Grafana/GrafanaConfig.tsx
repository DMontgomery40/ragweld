// AGRO - Grafana Configuration Component
// Configure Grafana connection settings
// Reference: /assets/grafana-config-subtab.png

import { useState, useEffect } from 'react';
import { useAPI } from '@/hooks';

interface GrafanaConfig {
  baseUrl: string;
  dashboardUid: string;
  dashboardSlug: string;
  embedEnabled: boolean;
  refresh: string;
  kiosk: string;
  authMode: string;
  orgId: number;
  apiKey: string;
  authToken: string;
}

const DEFAULT_CONFIG: GrafanaConfig = {
  baseUrl: 'http://127.0.0.1:3000',
  dashboardUid: 'agro-overview',
  dashboardSlug: 'agro-overview',
  embedEnabled: true,
  refresh: '10s',
  kiosk: 'tv',
  authMode: 'anonymous',
  orgId: 1,
  apiKey: '',
  authToken: ''
};

export function GrafanaConfig() {
  const { api } = useAPI();
  const [config, setConfig] = useState<GrafanaConfig>(DEFAULT_CONFIG);
  const [showApiKey, setShowApiKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<'unknown' | 'success' | 'error'>('unknown');
  const [statusMessage, setStatusMessage] = useState('');
  const [saveMessage, setSaveMessage] = useState('');

  // Load config on mount
  useEffect(() => {
    void loadConfig();
  }, []);

  const loadConfig = async () => {
    try {
      const response = await fetch(api('/grafana/config'));
      if (response.ok) {
        const data = await response.json();
        setConfig({
          baseUrl: data.url || DEFAULT_CONFIG.baseUrl,
          dashboardUid: data.dashboardUid || DEFAULT_CONFIG.dashboardUid,
          dashboardSlug: data.dashboardSlug || DEFAULT_CONFIG.dashboardSlug,
          embedEnabled: Boolean(data.embedEnabled ?? DEFAULT_CONFIG.embedEnabled),
          refresh: data.refresh || DEFAULT_CONFIG.refresh,
          kiosk: data.kiosk || DEFAULT_CONFIG.kiosk,
          authMode: data.authMode || DEFAULT_CONFIG.authMode,
          orgId: data.orgId !== undefined ? Number(data.orgId) : DEFAULT_CONFIG.orgId,
          apiKey: data.apiKey || '',
          authToken: data.authToken || ''
        });
      }
    } catch (error) {
      console.error('[GrafanaConfig] Failed to load config:', error);
    }
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setConnectionStatus('unknown');
    setStatusMessage('');

    try {
      const response = await fetch(api('/grafana/test'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: config.baseUrl,
          apiKey: config.apiKey,
          authToken: config.authToken
        })
      });

      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          setConnectionStatus('success');
          setStatusMessage('Successfully connected to Grafana!');
        } else {
          setConnectionStatus('error');
          setStatusMessage(data.error || 'Connection failed');
        }
      } else {
        setConnectionStatus('error');
        setStatusMessage('Connection test failed');
      }
    } catch (error) {
      console.error('[GrafanaConfig] Test connection failed:', error);
      setConnectionStatus('error');
      setStatusMessage(error instanceof Error ? error.message : 'Connection test failed');
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveMessage('');

    try {
      const response = await fetch(api('/grafana/config'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: config.baseUrl,
          dashboardUid: config.dashboardUid,
          dashboardSlug: config.dashboardSlug,
          embedEnabled: config.embedEnabled,
          refresh: config.refresh,
          kiosk: config.kiosk,
          authMode: config.authMode,
          orgId: config.orgId,
          apiKey: config.apiKey,
          authToken: config.authToken
        })
      });

      if (response.ok) {
        setSaveMessage('Configuration saved successfully!');
      } else {
        setSaveMessage('Failed to save configuration');
      }
    } catch (error) {
      console.error('[GrafanaConfig] Failed to save config:', error);
      setSaveMessage('Failed to save configuration');
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMessage(''), 3000);
    }
  };

  const handleOpenInNewTab = () => {
    const baseUrl = config.baseUrl.replace(/\/$/, '');
    const fullUrl = `${baseUrl}/d/${config.dashboardUid}/${config.dashboardSlug}`;
    window.open(fullUrl, '_blank', 'noopener,noreferrer');
  };

  return (
    <div style={{
      maxWidth: '900px',
      margin: '0 auto',
      padding: '24px'
    }}>
      <h2 style={{
        margin: '0 0 24px 0',
        fontSize: '20px',
        fontWeight: '600',
        color: 'var(--fg)'
      }}>
        Grafana Configuration
      </h2>

      {/* Configuration Form */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '24px',
        marginBottom: '24px',
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: '16px'
      }}>
        <div style={{ gridColumn: '1 / 3' }}>
          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontSize: '13px',
            fontWeight: '600',
            color: 'var(--fg)',
            marginBottom: '8px'
          }}>
            <input
              type="checkbox"
              name="GRAFANA_EMBED_ENABLED"
              checked={config.embedEnabled}
              onChange={(e) => setConfig(prev => ({ ...prev, embedEnabled: e.target.checked }))}
              aria-label="Enable embedded Grafana"
              title="Toggle to show/hide the embedded Grafana iframe inside the app"
            />
            Enable Embedded Grafana
          </label>
        </div>

        <div>
          <label style={{
            display: 'block',
            fontSize: '13px',
            fontWeight: '600',
            color: 'var(--fg)',
            marginBottom: '8px'
          }}>
            Grafana Base URL
          </label>
          <input
            type="text"
            name="GRAFANA_BASE_URL"
            value={config.baseUrl}
            onChange={(e) => setConfig(prev => ({ ...prev, baseUrl: e.target.value }))}
            placeholder="http://127.0.0.1:3000"
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '4px',
              fontSize: '14px'
            }}
            aria-label="Grafana URL"
            title="The root URL of your Grafana instance (e.g., http://127.0.0.1:3000)"
          />
        </div>

        <div>
          <label style={{
            display: 'block',
            fontSize: '13px',
            fontWeight: '600',
            color: 'var(--fg)',
            marginBottom: '8px'
          }}>
            Dashboard UID
          </label>
          <input
            type="text"
            name="GRAFANA_DASHBOARD_UID"
            value={config.dashboardUid}
            onChange={(e) => setConfig(prev => ({ ...prev, dashboardUid: e.target.value }))}
            placeholder="agro-overview"
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '4px',
              fontSize: '14px'
            }}
            aria-label="Dashboard UID"
            title="The Grafana dashboard UID (first segment after /d/ in the URL)"
          />
        </div>

        <div>
          <label style={{
            display: 'block',
            fontSize: '13px',
            fontWeight: '600',
            color: 'var(--fg)',
            marginBottom: '8px'
          }}>
            Dashboard Slug
          </label>
          <input
            type="text"
            name="GRAFANA_DASHBOARD_SLUG"
            value={config.dashboardSlug}
            onChange={(e) => setConfig(prev => ({ ...prev, dashboardSlug: e.target.value }))}
            placeholder="agro-overview"
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '4px',
              fontSize: '14px'
            }}
            aria-label="Dashboard Slug"
            title="The Grafana dashboard slug (second segment after /d/<uid>/ in the URL)"
          />
        </div>

        <div>
          <label style={{
            display: 'block',
            fontSize: '13px',
            fontWeight: '600',
            color: 'var(--fg)',
            marginBottom: '8px'
          }}>
            Org ID
          </label>
          <input
            type="number"
            min={1}
            name="GRAFANA_ORG_ID"
            value={config.orgId}
            onChange={(e) => setConfig(prev => ({ ...prev, orgId: parseInt(e.target.value || '1', 10) }))}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '4px',
              fontSize: '14px'
            }}
            aria-label="Grafana Org ID"
            title="Grafana organization ID to use when rendering the dashboard"
          />
        </div>

        <div>
          <label style={{
            display: 'block',
            fontSize: '13px',
            fontWeight: '600',
            color: 'var(--fg)',
            marginBottom: '8px'
          }}>
            Refresh Interval
          </label>
          <input
            type="text"
            name="GRAFANA_REFRESH"
            value={config.refresh}
            onChange={(e) => setConfig(prev => ({ ...prev, refresh: e.target.value }))}
            placeholder="10s"
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '4px',
              fontSize: '14px'
            }}
            aria-label="Refresh Interval"
            title="Default dashboard auto-refresh interval (e.g., 5s, 30s, 1m)"
          />
        </div>

        <div>
          <label style={{
            display: 'block',
            fontSize: '13px',
            fontWeight: '600',
            color: 'var(--fg)',
            marginBottom: '8px'
          }}>
            Kiosk Mode
          </label>
          <select
            name="GRAFANA_KIOSK"
            value={config.kiosk}
            onChange={(e) => setConfig(prev => ({ ...prev, kiosk: e.target.value }))}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '4px',
              fontSize: '14px'
            }}
            aria-label="Kiosk mode"
            title="Grafana kiosk/display mode passed to the dashboard URL"
          >
            <option value="">None</option>
            <option value="tv">TV (no side nav)</option>
            <option value="1">Minimal</option>
          </select>
        </div>

        <div>
          <label style={{
            display: 'block',
            fontSize: '13px',
            fontWeight: '600',
            color: 'var(--fg)',
            marginBottom: '8px'
          }}>
            Auth Mode
          </label>
          <select
            name="GRAFANA_AUTH_MODE"
            value={config.authMode}
            onChange={(e) => setConfig(prev => ({ ...prev, authMode: e.target.value }))}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '4px',
              fontSize: '14px'
            }}
            aria-label="Auth mode"
            title="Choose anonymous (default) or token-based embedding"
          >
            <option value="anonymous">Anonymous</option>
            <option value="token">Service Account Token</option>
          </select>
        </div>

        <div>
          <label style={{
            display: 'block',
            fontSize: '13px',
            fontWeight: '600',
            color: 'var(--fg)',
            marginBottom: '8px'
          }}>
            API Key (Optional)
          </label>
          <div style={{ position: 'relative' }}>
            <input
              type={showApiKey ? 'text' : 'password'}
              name="GRAFANA_API_KEY"
              value={config.apiKey}
              onChange={(e) => setConfig(prev => ({ ...prev, apiKey: e.target.value }))}
              placeholder="Enter Grafana API key..."
              style={{
                width: '100%',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '10px 40px 10px 12px',
                borderRadius: '4px',
                fontSize: '14px'
              }}
              aria-label="API key"
              title="Service account API key for the Grafana HTTP API"
            />
            <button
              onClick={() => setShowApiKey(!showApiKey)}
              style={{
                position: 'absolute',
                right: '8px',
                top: '50%',
                transform: 'translateY(-50%)',
                background: 'none',
                border: 'none',
                color: 'var(--fg-muted)',
                cursor: 'pointer',
                padding: '4px 8px',
                fontSize: '12px'
              }}
              aria-label={showApiKey ? 'Hide API key' : 'Show API key'}
              title={showApiKey ? 'Hide API key' : 'Show API key'}
            >
              {showApiKey ? '👁️' : '👁️‍🗨️'}
            </button>
          </div>
          <div style={{
            fontSize: '11px',
            color: 'var(--fg-muted)',
            marginTop: '4px'
          }}>
            Required when anonymous access is disabled. Create under Grafana Settings → API Keys.
          </div>
        </div>

        <div>
          <label style={{
            display: 'block',
            fontSize: '13px',
            fontWeight: '600',
            color: 'var(--fg)',
            marginBottom: '8px'
          }}>
            Auth Token (Optional)
          </label>
          <input
            type="text"
            name="GRAFANA_AUTH_TOKEN"
            value={config.authToken}
            onChange={(e) => setConfig(prev => ({ ...prev, authToken: e.target.value }))}
            placeholder="Token for auth_token=..."
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '4px',
              fontSize: '14px'
            }}
            aria-label="Auth token"
            title="Embedding auth_token passed via the iframe URL when using token auth"
          />
          <div style={{
            fontSize: '11px',
            color: 'var(--fg-muted)',
            marginTop: '4px'
          }}>
            Optional if you pass auth_token in the iframe URL instead of an API key header.
          </div>
        </div>
      </div>

      {/* Connection Test */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '24px',
        marginBottom: '24px'
      }}>
        <h3 style={{
          margin: '0 0 16px 0',
          fontSize: '16px',
          fontWeight: '600',
          color: 'var(--fg)'
        }}>
          Connection Test
        </h3>

        <button
          onClick={handleTestConnection}
          disabled={testing || !config.baseUrl}
          style={{
            background: testing ? 'var(--bg-elev2)' : 'var(--accent)',
            color: testing ? 'var(--fg-muted)' : 'var(--accent-contrast)',
            border: 'none',
            padding: '10px 24px',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: '600',
            cursor: testing || !config.baseUrl ? 'not-allowed' : 'pointer',
            opacity: testing || !config.baseUrl ? 0.5 : 1,
            marginBottom: '16px'
          }}
          aria-label="Test connection"
          title="Ping Grafana /api/health and list datasources using the credentials above"
        >
          {testing ? 'Testing Connection...' : 'Test Connection'}
        </button>

        {connectionStatus !== 'unknown' && (
          <div style={{
            padding: '12px 16px',
            borderRadius: '6px',
            background: connectionStatus === 'success' ? 'var(--success)' : 'var(--err)',
            color: 'white',
            fontSize: '14px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            {connectionStatus === 'success' ? (
              <>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                Connection successful!
              </>
            ) : (
              <>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="15" y1="9" x2="9" y2="15" />
                  <line x1="9" y1="9" x2="15" y2="15" />
                </svg>
                {statusMessage || 'Connection failed'}
              </>
            )}
          </div>
        )}
      </div>

      {/* Action Buttons */}
      <div style={{
        display: 'flex',
        gap: '12px',
        justifyContent: 'flex-end'
      }}>
        <button
          onClick={handleOpenInNewTab}
          disabled={!config.baseUrl || !config.dashboardUid}
          style={{
            background: 'var(--bg-elev2)',
            color: 'var(--fg)',
            border: '1px solid var(--line)',
            padding: '10px 20px',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: '600',
            cursor: !config.baseUrl || !config.dashboardUid ? 'not-allowed' : 'pointer',
            opacity: !config.baseUrl || !config.dashboardUid ? 0.5 : 1,
            display: 'flex',
            alignItems: 'center',
            gap: '6px'
          }}
          aria-label="Open in new tab"
          title="Open the configured dashboard directly in Grafana"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
            <polyline points="15 3 21 3 21 9" />
            <line x1="10" y1="14" x2="21" y2="3" />
          </svg>
          Open in New Tab
        </button>

        <button
          onClick={handleSave}
          disabled={saving || !config.baseUrl}
          style={{
            background: saving ? 'var(--bg-elev2)' : 'var(--accent)',
            color: saving ? 'var(--fg-muted)' : 'var(--accent-contrast)',
            border: 'none',
            padding: '10px 32px',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: '600',
            cursor: saving || !config.baseUrl ? 'not-allowed' : 'pointer',
            opacity: saving || !config.baseUrl ? 0.5 : 1
          }}
          aria-label="Save configuration"
          title="Persist Grafana settings to agro_config.json and .env"
        >
          {saving ? 'Saving...' : 'Save Configuration'}
        </button>
      </div>

      {saveMessage && (
        <div style={{
          marginTop: '16px',
          padding: '12px 16px',
          borderRadius: '6px',
          background: saveMessage.includes('success') ? 'var(--success)' : 'var(--err)',
          color: 'white',
          fontSize: '14px',
          textAlign: 'center'
        }}>
          {saveMessage}
        </div>
      )}

      {/* Info Section */}
      <div style={{
        marginTop: '24px',
        padding: '16px',
        background: 'var(--bg-elev1)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        fontSize: '12px',
        color: 'var(--fg-muted)'
      }}>
        <h4 style={{
          margin: '0 0 8px 0',
          fontSize: '13px',
          fontWeight: '600',
          color: 'var(--fg)'
        }}>
          ℹ️ Configuration Help
        </h4>
        <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
          <li style={{ marginBottom: '4px' }}>
            Ensure Grafana is running (docker-compose up) and accessible at the base URL.
          </li>
          <li style={{ marginBottom: '4px' }}>
            UID/Slug come from the dashboard URL: /d/&lt;uid&gt;/&lt;slug&gt;.
          </li>
          <li style={{ marginBottom: '4px' }}>
            Use token or API key if anonymous access is disabled.
          </li>
          <li style={{ marginBottom: '4px' }}>
            Click Test Connection before saving to verify Prometheus/Loki datasources are reachable.
          </li>
        </ul>
      </div>
    </div>
  );
}
