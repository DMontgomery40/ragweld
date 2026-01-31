import { useState, useEffect } from 'react';
import { apiClient, api } from '@/api/client';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { ApiKeyStatus } from '@/components/ui/ApiKeyStatus';
import { useConfig, useConfigField } from '@/hooks';

export function GeneralSubtab() {
  const { config, loading: configLoading, saveConfig } = useConfig();

  // Theme & Appearance
  const [themeMode, setThemeMode] = useConfigField<string>('ui.theme_mode', 'dark');

  // Legacy server/runtime fields (not part of TriBridConfig; retained as local UI only during migration)
  const [agroEdition, setAgroEdition] = useState('');
  const [threadId, setThreadId] = useState('');
  const [host, setHost] = useState('127.0.0.1');
  const [port, setPort] = useState(8012);
  const [agroPath, setAgroPath] = useState('');
  const [netlifyDomains, setNetlifyDomains] = useState('');

  // UI settings (TriBridConfig.ui)
  const [openBrowser, setOpenBrowser] = useConfigField<number>('ui.open_browser', 1);
  const [chatStreamingEnabled, setChatStreamingEnabled] = useConfigField<number>('ui.chat_streaming_enabled', 1);

  // Tracing & Observability
  const [tracingEnabled, setTracingEnabled] = useConfigField<number>('tracing.tracing_enabled', 1);
  const [traceSamplingRate, setTraceSamplingRate] = useConfigField<number>('tracing.trace_sampling_rate', 1.0);
  const [prometheusPort, setPrometheusPort] = useConfigField<number>('tracing.prometheus_port', 9090);
  const [metricsEnabled, setMetricsEnabled] = useConfigField<number>('tracing.metrics_enabled', 1);
  const [logLevel, setLogLevel] = useConfigField<string>('tracing.log_level', 'INFO');
  const [alertWebhookTimeout, setAlertWebhookTimeout] = useConfigField<number>('tracing.alert_webhook_timeout', 5);

  // Editor Settings
  const [editorEnabled, setEditorEnabled] = useConfigField<number>('ui.editor_enabled', 1);
  const [editorEmbedEnabled, setEditorEmbedEnabled] = useConfigField<number>('ui.editor_embed_enabled', 1);
  const [editorPort, setEditorPort] = useConfigField<number>('ui.editor_port', 4440);
  const [editorBind, setEditorBind] = useConfigField<string>('ui.editor_bind', 'local');

  // Webhooks
  const [webhookEnabled, setWebhookEnabled] = useState(true);
  const [webhookSevCritical, setWebhookSevCritical] = useState(true);
  const [webhookSevWarning, setWebhookSevWarning] = useState(true);
  const [webhookSevInfo, setWebhookSevInfo] = useState(false);
  const [webhookIncludeResolved, setWebhookIncludeResolved] = useState(true);
  const [webhookSaveStatus, setWebhookSaveStatus] = useState('');

  // MCP RAG Search
  const [mcpRagQuestion, setMcpRagQuestion] = useState('');
  const [mcpRagRepo, setMcpRagRepo] = useState('agro');
  const [mcpRagTopK, setMcpRagTopK] = useState(10);
  const [mcpRagForceLocal, setMcpRagForceLocal] = useState(false);
  const [mcpRagResults, setMcpRagResults] = useState('');

  // Loading states
  const [saving, setSaving] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Load webhook config (non-env config) on mount
  useEffect(() => {
    loadWebhookConfig();
  }, []);

  async function loadWebhookConfig() {
    try {
      const { data } = await apiClient.get(api('/monitoring/webhooks/config'));
      if (data) {
        setWebhookEnabled(data.alert_notify_enabled !== false);
        const severities = (data.alert_notify_severities || 'critical,warning').split(',');
        setWebhookSevCritical(severities.includes('critical'));
        setWebhookSevWarning(severities.includes('warning'));
        setWebhookSevInfo(severities.includes('info'));
        setWebhookIncludeResolved(data.alert_include_resolved !== false);
      }
    } catch (err) {
      console.error('Failed to load webhook config:', err);
    }
  }

  async function saveGeneralSettings() {
    if (!config) return;
    try {
      setSaving(true);
      setActionMessage('Saving general settings...');
      await saveConfig(config);
      setActionMessage('General settings saved successfully!');
    } catch (err) {
      console.error('Failed to save settings:', err);
      setActionMessage('Failed to save settings: ' + (err as Error).message);
    } finally {
      setSaving(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  }

  async function saveWebhookConfig() {
    try {
      setWebhookSaveStatus('Saving...');
      const severities = [];
      if (webhookSevCritical) severities.push('critical');
      if (webhookSevWarning) severities.push('warning');
      if (webhookSevInfo) severities.push('info');

      const payload: Record<string, any> = {
        alert_notify_enabled: webhookEnabled,
        alert_notify_severities: (severities.length ? severities : ['critical']).join(','),
        alert_include_resolved: webhookIncludeResolved,
        alert_webhook_timeout_seconds: alertWebhookTimeout,
      };

      await apiClient.post(api('/monitoring/webhooks/config'), payload);
      setWebhookSaveStatus('Saved successfully!');
      await loadWebhookConfig();
      setTimeout(() => setWebhookSaveStatus(''), 3000);
    } catch (err) {
      console.error('Failed to save webhook config:', err);
      setWebhookSaveStatus('Failed to save: ' + (err as Error).message);
    }
  }

  async function runMcpRagSearch() {
    try {
      setMcpRagResults('Running...');
      const params = new URLSearchParams({
        q: mcpRagQuestion,
        repo: mcpRagRepo,
        top_k: String(mcpRagTopK),
        force_local: String(mcpRagForceLocal),
      });
      const { data } = await apiClient.get(api(`/mcp/rag_search?${params}`));
      setMcpRagResults(JSON.stringify(data, null, 2));
    } catch (err) {
      setMcpRagResults('Error: ' + (err as Error).message);
    }
  }

  if (configLoading) {
    return <div style={{ padding: '20px' }}>Loading configuration...</div>;
  }

  return (
    <div style={{ padding: '20px' }}>
      {/* Action message */}
      {actionMessage && (
        <div style={{
          padding: '12px',
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          marginBottom: '16px',
          fontSize: '12px',
          color: 'var(--fg)'
        }}>
          {actionMessage}
        </div>
      )}

      {/* Theme & Appearance */}
      <div className="settings-section">
        <h3>Theme & Appearance</h3>
        <div className="input-row">
          <div className="input-group">
            <label>Theme Mode</label>
            <select value={themeMode} onChange={(e) => setThemeMode(e.target.value as 'auto' | 'dark' | 'light')}>
              <option value="auto">Auto (System)</option>
              <option value="dark">Dark</option>
              <option value="light">Light</option>
            </select>
            <p className="small">Controls light/dark theme globally. Top bar selector changes it live.</p>
          </div>
        </div>
      </div>

      {/* Server Settings */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)' }}>
        <h3>Server Settings</h3>
        <div className="input-row">
          <div className="input-group">
            <label>
              Agro Edition
              <TooltipIcon name="AGRO_EDITION" />
            </label>
            <input type="text" value={agroEdition} onChange={(e) => setAgroEdition(e.target.value)} placeholder="oss | pro | enterprise" />
          </div>
          <div className="input-group">
            <label>Thread ID</label>
            <input type="text" value={threadId} onChange={(e) => setThreadId(e.target.value)} placeholder="http or cli-chat" />
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <label>Serve Host</label>
            <input type="text" value={host} onChange={(e) => setHost(e.target.value)} />
          </div>
          <div className="input-group">
            <label>Serve Port</label>
            <input type="number" value={port} onChange={(e) => setPort(Number(e.target.value))} />
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <label>Open Browser on Start</label>
            <select value={openBrowser} onChange={(e) => setOpenBrowser(Number(e.target.value))}>
              <option value="1">On</option>
              <option value="0">Off</option>
            </select>
          </div>
          <div className="input-group">
            <label>agro Path</label>
            <input type="text" value={agroPath} onChange={(e) => setAgroPath(e.target.value)} />
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <ApiKeyStatus keyName="NETLIFY_API_KEY" label="Netlify API Key" />
          </div>
          <div className="input-group">
            <label>Netlify Domains</label>
            <input type="text" value={netlifyDomains} onChange={(e) => setNetlifyDomains(e.target.value)} />
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <label>
              Chat Streaming
              <TooltipIcon name="CHAT_STREAMING_ENABLED" />
            </label>
            <select value={chatStreamingEnabled} onChange={(e) => setChatStreamingEnabled(Number(e.target.value))}>
              <option value="1">Enabled</option>
              <option value="0">Disabled</option>
            </select>
          </div>
        </div>
      </div>

      {/* Tracing & Observability */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)' }}>
        <h3>Tracing & Observability</h3>
        <p className="small">Configure distributed tracing, metrics collection, and monitoring.</p>
        <div className="input-row">
          <div className="input-group">
            <label>
              Tracing Enabled
              <TooltipIcon name="TRACING_ENABLED" />
            </label>
            <select value={tracingEnabled} onChange={(e) => setTracingEnabled(Number(e.target.value))}>
              <option value="1">Enabled</option>
              <option value="0">Disabled</option>
            </select>
          </div>
          <div className="input-group">
            <label>
              Trace Sampling Rate
              <TooltipIcon name="TRACE_SAMPLING_RATE" />
            </label>
            <input
              type="number"
              value={traceSamplingRate}
              onChange={(e) => setTraceSamplingRate(Number(e.target.value))}
              min="0.0"
              max="1.0"
              step="0.1"
            />
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <label>Prometheus Port</label>
            <input
              type="number"
              value={prometheusPort}
              onChange={(e) => setPrometheusPort(Number(e.target.value))}
              min="1024"
              max="65535"
            />
          </div>
          <div className="input-group">
            <label>Metrics Enabled</label>
            <select value={metricsEnabled} onChange={(e) => setMetricsEnabled(Number(e.target.value))}>
              <option value="1">Enabled</option>
              <option value="0">Disabled</option>
            </select>
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <label>
              Log Level
              <TooltipIcon name="LOG_LEVEL" />
            </label>
            <select value={logLevel} onChange={(e) => setLogLevel(e.target.value)}>
              <option value="DEBUG">DEBUG</option>
              <option value="INFO">INFO</option>
              <option value="WARNING">WARNING</option>
              <option value="ERROR">ERROR</option>
            </select>
          </div>
          <div className="input-group">
            <label>Alert Webhook Timeout</label>
            <input
              type="number"
              value={alertWebhookTimeout}
              onChange={(e) => setAlertWebhookTimeout(Number(e.target.value))}
              min="1"
              max="30"
            />
          </div>
        </div>
      </div>

      {/* Embedded Editor */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)' }}>
        <h3>
          <span className="accent-blue">●</span> Embedded Editor
        </h3>
        <div className="input-row">
          <div className="input-group">
            <label className="toggle">
              <input
                type="checkbox"
                checked={editorEnabled === 1}
                onChange={(e) => setEditorEnabled(e.target.checked ? 1 : 0)}
              />
              <span className="toggle-track" aria-hidden="true">
                <span className="toggle-thumb"></span>
              </span>
              <span className="toggle-label">
                Enable Editor
                <TooltipIcon name="EDITOR_ENABLED" />
              </span>
            </label>
            <p className="small">Start OpenVSCode Server container on up.sh</p>
          </div>
          <div className="input-group">
            <label className="toggle">
              <input
                type="checkbox"
                checked={editorEmbedEnabled === 1}
                onChange={(e) => setEditorEmbedEnabled(e.target.checked ? 1 : 0)}
              />
              <span className="toggle-track" aria-hidden="true">
                <span className="toggle-thumb"></span>
              </span>
              <span className="toggle-label">
                Embed in GUI
                <TooltipIcon name="EDITOR_EMBED_ENABLED" />
              </span>
            </label>
            <p className="small">Show the editor inline in the GUI (hides automatically in CI)</p>
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <label>Editor Port</label>
            <input type="number" value={editorPort} onChange={(e) => setEditorPort(Number(e.target.value))} min="1024" max="65535" />
            <p className="small">Preferred port (auto-increments if busy)</p>
          </div>
          <div className="input-group">
            <label>Bind Mode</label>
            <select value={editorBind} onChange={(e) => setEditorBind(e.target.value)}>
              <option value="local">Local only (127.0.0.1)</option>
              <option value="public">Public (0.0.0.0)</option>
            </select>
            <p className="small">Local = secure; Public = accessible from network</p>
          </div>
        </div>
      </div>

      {/* Webhooks */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)' }}>
        <h3>
          <span style={{ color: 'var(--link)' }}>●</span> Alert Notifications (Slack/Discord)
        </h3>
        <p className="small">Webhook URLs are configured in .env. Use the status checks below and adjust notification settings here.</p>

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
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 400, margin: 0 }}>
                <input type="checkbox" checked={webhookEnabled} onChange={(e) => setWebhookEnabled(e.target.checked)} />
                <span>Enable notifications</span>
              </label>
              <div>
                <label>Notify on severity:</label>
                <div style={{ display: 'flex', gap: '12px', marginTop: '6px' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <input type="checkbox" checked={webhookSevCritical} onChange={(e) => setWebhookSevCritical(e.target.checked)} />
                    Critical
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <input type="checkbox" checked={webhookSevWarning} onChange={(e) => setWebhookSevWarning(e.target.checked)} />
                    Warning
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <input type="checkbox" checked={webhookSevInfo} onChange={(e) => setWebhookSevInfo(e.target.checked)} />
                    Info
                  </label>
                </div>
              </div>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 400, margin: 0 }}>
                <input type="checkbox" checked={webhookIncludeResolved} onChange={(e) => setWebhookIncludeResolved(e.target.checked)} />
                <span>Include resolved alerts</span>
              </label>
            </div>
          </div>
        </div>

        <div className="input-row">
          <button
            className="small-button"
            onClick={saveWebhookConfig}
            style={{ background: 'var(--accent)', color: 'var(--accent-contrast)', fontWeight: '600', width: '100%' }}
          >
            Save Webhook Configuration
          </button>
        </div>
        {webhookSaveStatus && (
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginTop: '8px' }}>{webhookSaveStatus}</div>
        )}
      </div>

      {/* MCP RAG Search Debug */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)' }}>
        <h3>
          <span style={{ color: 'var(--link)' }}>●</span> MCP RAG Search (debug)
        </h3>
        <p className="small">
          Runs the MCP server's <code>rag_search</code> tool to return file paths and line ranges. Falls back to local retrieval if
          MCP is unavailable.
        </p>
        <div className="input-row">
          <div className="input-group full-width">
            <label>Question</label>
            <input
              type="text"
              value={mcpRagQuestion}
              onChange={(e) => setMcpRagQuestion(e.target.value)}
              placeholder="e.g. Where is OAuth token validated?"
            />
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <label>Repository</label>
            <input type="text" value={mcpRagRepo} onChange={(e) => setMcpRagRepo(e.target.value)} placeholder="agro" />
          </div>
          <div className="input-group">
            <label>Top K</label>
            <input type="number" value={mcpRagTopK} onChange={(e) => setMcpRagTopK(Number(e.target.value))} min="1" max="50" />
          </div>
          <div className="input-group">
            <label>Force Local</label>
            <select value={mcpRagForceLocal ? 'true' : 'false'} onChange={(e) => setMcpRagForceLocal(e.target.value === 'true')}>
              <option value="false">No (use MCP if available)</option>
              <option value="true">Yes (bypass MCP)</option>
            </select>
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <button className="small-button" onClick={runMcpRagSearch}>
              Run
            </button>
          </div>
        </div>
        <pre className="result-display" style={{ minHeight: '120px', whiteSpace: 'pre-wrap', background: 'var(--code-bg)' }}>
          {mcpRagResults}
        </pre>
      </div>

      {/* Save All Button */}
      <div className="input-row" style={{ marginTop: '24px' }}>
        <button
          className="small-button"
          onClick={saveGeneralSettings}
          disabled={saving}
          style={{
            width: '100%',
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            fontWeight: '600',
            fontSize: '16px',
            padding: '12px',
          }}
        >
          {saving ? 'Saving...' : 'Save General Settings'}
        </button>
      </div>
    </div>
  );
}
