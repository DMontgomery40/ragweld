// AGRO - Integrations Subtab Component
// External service integrations and webhooks
// API keys are configured in .env ONLY - never written programmatically

import { useState } from 'react';
import { webhooksApi } from '@/api/webhooks';
import { ApiKeyStatus } from '@/components/ui/ApiKeyStatus';
import { useConfig, useConfigField } from '@/hooks';

export function IntegrationsSubtab() {
  const { config, saveConfig } = useConfig();

  // LangSmith settings (non-secret config only)
  const [langsmithEndpoint, setLangsmithEndpoint] = useConfigField<string>(
    'tracing.langchain_endpoint',
    'https://api.smith.langchain.com'
  );
  const [langsmithProject, setLangsmithProject] = useConfigField<string>(
    'tracing.langchain_project',
    'tribrid'
  );
  const [langchainTracingV2, setLangchainTracingV2] = useConfigField<number>(
    'tracing.langchain_tracing_v2',
    0
  );

  // Grafana settings (non-secret config only)
  const [grafanaUrl, setGrafanaUrl] = useConfigField<string>(
    'ui.grafana_base_url',
    'http://127.0.0.1:3000'
  );

  // VS Code settings
  const [vscodeEnabled, setVscodeEnabled] = useState(false);
  const [vscodePort, setVscodePort] = useState('4440');

  // MCP & Channels
  const [httpModel, setHttpModel] = useConfigField<string>('generation.gen_model_http', '');
  const [mcpModel, setMcpModel] = useConfigField<string>('generation.gen_model_mcp', '');
  const [cliModel, setCliModel] = useConfigField<string>('generation.gen_model_cli', '');
  const [mcpHttpHost, setMcpHttpHost] = useState('0.0.0.0');
  const [mcpHttpPort, setMcpHttpPort] = useState('8013');
  const [mcpHttpPath, setMcpHttpPath] = useState('/mcp');

  // Alert Notifications (webhook URLs are secrets - configured in .env only)
  const [notificationsEnabled, setNotificationsEnabled] = useState(true);
  const [notifyCritical, setNotifyCritical] = useState(true);
  const [notifyWarning, setNotifyWarning] = useState(true);
  const [notifyInfo, setNotifyInfo] = useState(false);
  const [includeResolved, setIncludeResolved] = useState(true);

  // Status
  const [saveStatus, setSaveStatus] = useState<string>('');

  async function saveIntegrationSettings() {
    setSaveStatus('');
    try {
      if (!config) return;
      await saveConfig(config);
      setSaveStatus('Integration settings saved successfully!');
      setTimeout(() => setSaveStatus(''), 3000);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      setSaveStatus(`Error saving integration settings: ${message}`);
    }
  }

  async function testLangSmith() {
    alert(`Testing connection to LangSmith at ${langsmithEndpoint}...`);
  }

  async function testGrafana() {
    try {
      const response = await fetch(grafanaUrl + '/api/health');
      if (response.ok) {
        alert('Grafana connection successful!');
      } else {
        alert('Grafana connection failed');
      }
    } catch (error: any) {
      alert(`Grafana test failed: ${error.message}`);
    }
  }

  async function testVSCode() {
    try {
      const response = await fetch(`http://127.0.0.1:${vscodePort}`);
      if (response.ok) {
        alert('VS Code server is running!');
      } else {
        alert('VS Code server not responding');
      }
    } catch (error: any) {
      alert(`VS Code test failed: ${error.message}`);
    }
  }

  async function saveWebhooks() {
    setSaveStatus('');

    // Webhook URLs are secrets - configured in .env only
    // Only save the non-secret settings
    const config = {
      enabled: notificationsEnabled,
      severity: {
        critical: notifyCritical,
        warning: notifyWarning,
        info: notifyInfo
      },
      include_resolved: includeResolved
    };

    try {
      const result = await webhooksApi.save(config);
      if (result.status === 'success') {
        setSaveStatus(result.message || 'Webhook settings saved! URLs must be configured in .env file.');
        setTimeout(() => setSaveStatus(''), 3000);
      } else {
        setSaveStatus('Failed to save webhook settings');
      }
    } catch (error: any) {
      setSaveStatus(`Error saving webhook settings: ${error.message}`);
    }
  }

  return (
    <div className="settings-section">
      <h2>Integrations</h2>
      <p className="small" style={{ marginBottom: '24px' }}>
        Configure external services and integrations.
      </p>

      {/* Status Messages */}
      {saveStatus && (
        <div
          data-testid="integrations-save-status"
          style={{
            padding: '12px',
            marginBottom: '16px',
            borderRadius: '6px',
            background: saveStatus.includes('Error') || saveStatus.includes('Failed') ? 'var(--err)' : 'var(--ok)',
            color: 'var(--accent-contrast)',
            fontWeight: '500'
          }}
        >
          {saveStatus}
        </div>
      )}

      {/* MCP & Channels */}
      <div
        style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '20px',
          marginBottom: '20px'
        }}
      >
        <h3 style={{ marginTop: 0 }}>MCP & Channels</h3>
        <p className="small" style={{ marginBottom: '16px' }}>
          Set per-channel inference models. Provider is inferred from the model name.
        </p>

        <div className="input-row">
          <div className="input-group">
            <label>HTTP Responses Model</label>
            <input
              type="text"
              value={httpModel}
              onChange={(e) => setHttpModel(e.target.value)}
              placeholder="override HTTP model"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
          </div>
          <div className="input-group">
            <label>MCP stdio Model</label>
            <input
              type="text"
              value={mcpModel}
              onChange={(e) => setMcpModel(e.target.value)}
              placeholder="override MCP model"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>CLI Chat Model</label>
            <input
              type="text"
              value={cliModel}
              onChange={(e) => setCliModel(e.target.value)}
              placeholder="override CLI model"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
          </div>
          <div className="input-group">
            <label>MCP HTTP Configuration</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                type="text"
                value={mcpHttpHost}
                onChange={(e) => setMcpHttpHost(e.target.value)}
                placeholder="Host"
                style={{
                  width: '40%',
                  padding: '8px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '4px',
                  color: 'var(--fg)'
                }}
              />
              <input
                type="number"
                value={mcpHttpPort}
                onChange={(e) => setMcpHttpPort(e.target.value)}
                placeholder="Port"
                style={{
                  width: '30%',
                  padding: '8px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '4px',
                  color: 'var(--fg)'
                }}
              />
              <input
                type="text"
                value={mcpHttpPath}
                onChange={(e) => setMcpHttpPath(e.target.value)}
                placeholder="Path"
                style={{
                  width: '30%',
                  padding: '8px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '4px',
                  color: 'var(--fg)'
                }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* LangSmith Integration */}
      <div
        style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '20px',
          marginBottom: '20px'
        }}
      >
        <h3 style={{ marginTop: 0 }}>LangSmith Integration</h3>

        <div className="input-row">
          <div className="input-group">
            <label>LangSmith Endpoint</label>
            <input
              type="text"
              value={langsmithEndpoint}
              onChange={(e) => setLangsmithEndpoint(e.target.value)}
              placeholder="https://api.smith.langchain.com"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
          </div>
          <div className="input-group">
            <label>LangSmith Project</label>
            <input
              type="text"
              value={langsmithProject}
              onChange={(e) => setLangsmithProject(e.target.value)}
              placeholder="agro"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
          </div>
        </div>

        {/* API Keys - configured in .env only, never entered in GUI */}
        <div className="input-row">
          <div className="input-group">
            <ApiKeyStatus keyName="LANGSMITH_API_KEY" label="LangSmith API Key" />
          </div>
          <div className="input-group">
            <ApiKeyStatus keyName="LANGCHAIN_API_KEY" label="LangChain API Key" />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input
                type="checkbox"
                checked={langchainTracingV2 === 1}
                onChange={(e) => setLangchainTracingV2(e.target.checked ? 1 : 0)}
              />
              <span>Enable LangChain Tracing V2</span>
            </label>
          </div>
        </div>

        <button
          className="small-button"
          onClick={testLangSmith}
          style={{
            width: '100%',
            background: 'var(--link)',
            color: 'var(--accent-contrast)',
            fontWeight: '600',
            marginTop: '12px'
          }}
        >
          Test Connection
        </button>
      </div>

      {/* Grafana Integration */}
      <div
        style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '20px',
          marginBottom: '20px'
        }}
      >
        <h3 style={{ marginTop: 0 }}>Grafana Integration</h3>

        <div className="input-row">
          <div className="input-group">
            <label>Grafana URL</label>
            <input
              type="text"
              value={grafanaUrl}
              onChange={(e) => setGrafanaUrl(e.target.value)}
              placeholder="http://127.0.0.1:3000"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
          </div>
          <div className="input-group">
            <ApiKeyStatus keyName="GRAFANA_API_KEY" label="Grafana API Key" />
          </div>
        </div>

        <button
          className="small-button"
          onClick={testGrafana}
          style={{
            width: '100%',
            background: 'var(--warn)',
            color: 'var(--accent-contrast)',
            fontWeight: '600',
            marginTop: '12px'
          }}
        >
          Test Connection
        </button>
      </div>

      {/* VS Code Settings */}
      <div
        style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '20px',
          marginBottom: '20px'
        }}
      >
        <h3 style={{ marginTop: 0 }}>VS Code Integration</h3>

        <div className="input-row">
          <div className="input-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input
                type="checkbox"
                checked={vscodeEnabled}
                onChange={(e) => setVscodeEnabled(e.target.checked)}
              />
              <span>Enable VS Code Server</span>
            </label>
          </div>
          <div className="input-group">
            <label>VS Code Port</label>
            <input
              type="number"
              value={vscodePort}
              onChange={(e) => setVscodePort(e.target.value)}
              placeholder="4440"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
          </div>
        </div>

        <button
          className="small-button"
          onClick={testVSCode}
          style={{
            width: '100%',
            background: 'var(--link)',
            color: 'var(--accent-contrast)',
            fontWeight: '600',
            marginTop: '12px'
          }}
        >
          Test Connection
        </button>
      </div>

      {/* Alert Notifications */}
      <div
        style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '20px',
          marginBottom: '20px'
        }}
      >
        <h3 style={{ marginTop: 0 }}>Alert Notifications (Slack/Discord)</h3>
        <p className="small" style={{ marginBottom: '16px' }}>
          Configure webhook URLs for alert notifications. Leave blank to disable.
        </p>

        {/* Webhook URLs - configured in .env only */}
        <div className="input-row">
          <div className="input-group">
            <ApiKeyStatus keyName="SLACK_WEBHOOK_URL" label="Slack Webhook URL" />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <ApiKeyStatus keyName="DISCORD_WEBHOOK_URL" label="Discord Webhook URL" />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>Notification Settings</label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '8px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="checkbox"
                  checked={notificationsEnabled}
                  onChange={(e) => setNotificationsEnabled(e.target.checked)}
                />
                <span>Enable notifications</span>
              </label>
              <div>
                <label>Notify on severity:</label>
                <div style={{ display: 'flex', gap: '12px', marginTop: '6px' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <input
                      type="checkbox"
                      checked={notifyCritical}
                      onChange={(e) => setNotifyCritical(e.target.checked)}
                    />
                    Critical
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <input
                      type="checkbox"
                      checked={notifyWarning}
                      onChange={(e) => setNotifyWarning(e.target.checked)}
                    />
                    Warning
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <input
                      type="checkbox"
                      checked={notifyInfo}
                      onChange={(e) => setNotifyInfo(e.target.checked)}
                    />
                    Info
                  </label>
                </div>
              </div>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="checkbox"
                  checked={includeResolved}
                  onChange={(e) => setIncludeResolved(e.target.checked)}
                />
                <span>Include resolved alerts</span>
              </label>
            </div>
          </div>
        </div>

        <button
          className="small-button"
          onClick={saveWebhooks}
          style={{
            width: '100%',
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            fontWeight: '600',
            marginTop: '12px'
          }}
        >
          Save Webhook Configuration
        </button>
      </div>

      {/* Save All Settings */}
      <button
        className="small-button"
        onClick={saveIntegrationSettings}
        data-testid="save-integrations-btn"
        style={{
          width: '100%',
          background: 'var(--accent)',
          color: 'var(--accent-contrast)',
          fontWeight: '600',
          padding: '12px'
        }}
      >
        Save All Integration Settings
      </button>
    </div>
  );
}
