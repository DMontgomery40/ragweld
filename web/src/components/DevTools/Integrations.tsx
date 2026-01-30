// AGRO - Integrations Component
// Configure external integrations: LangSmith, Grafana, VS Code, Webhooks
// Reference: /assets/dev tools - integrations subtab.png

import { useState, useEffect } from 'react';
import { useAPI } from '@/hooks';

interface Integration {
  name: string;
  enabled: boolean;
  config: Record<string, any>;
  status: 'connected' | 'disconnected' | 'error' | 'unknown';
}

export function Integrations() {
  const { api } = useAPI();

  // LangSmith state
  const [langsmithProject, setLangsmithProject] = useState('');
  const [langsmithApiKey, setLangsmithApiKey] = useState('');
  const [langsmithEnabled, setLangsmithEnabled] = useState(false);
  const [langsmithStatus, setLangsmithStatus] = useState<'connected' | 'disconnected' | 'testing'>('disconnected');

  // Grafana state
  const [grafanaUrl, setGrafanaUrl] = useState('http://localhost:3000');
  const [grafanaApiKey, setGrafanaApiKey] = useState('');
  const [grafanaEnabled, setGrafanaEnabled] = useState(false);
  const [grafanaStatus, setGrafanaStatus] = useState<'connected' | 'disconnected' | 'testing'>('disconnected');

  // VS Code state
  const [vscodeEnabled, setVscodeEnabled] = useState(false);
  const [vscodePort, setVscodePort] = useState('8013');
  const [vscodeStatus, setVscodeStatus] = useState<'connected' | 'disconnected'>('disconnected');

  // Webhooks state
  const [webhooks, setWebhooks] = useState<Array<{ url: string; events: string[] }>>([]);
  const [newWebhookUrl, setNewWebhookUrl] = useState('');
  const [webhookEvents, setWebhookEvents] = useState<string[]>([]);

  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');

  const availableEvents = [
    { id: 'indexing.started', name: 'Indexing Started' },
    { id: 'indexing.completed', name: 'Indexing Completed' },
    { id: 'indexing.failed', name: 'Indexing Failed' },
    { id: 'query.executed', name: 'Query Executed' },
    { id: 'reranking.completed', name: 'Reranking Completed' }
  ];

  useEffect(() => {
    loadIntegrations();
  }, []);

  const loadIntegrations = async () => {
    try {
      const response = await fetch(api('/integrations/config'));
      if (response.ok) {
        const data = await response.json();

        // Load LangSmith config
        if (data.langsmith) {
          setLangsmithProject(data.langsmith.project || '');
          setLangsmithApiKey(data.langsmith.apiKey || '');
          setLangsmithEnabled(data.langsmith.enabled || false);
          setLangsmithStatus(data.langsmith.status || 'disconnected');
        }

        // Load Grafana config
        if (data.grafana) {
          setGrafanaUrl(data.grafana.url || 'http://localhost:3000');
          setGrafanaApiKey(data.grafana.apiKey || '');
          setGrafanaEnabled(data.grafana.enabled || false);
          setGrafanaStatus(data.grafana.status || 'disconnected');
        }

        // Load VS Code config
        if (data.vscode) {
          setVscodeEnabled(data.vscode.enabled || false);
          setVscodePort(data.vscode.port || '8013');
          setVscodeStatus(data.vscode.status || 'disconnected');
        }

        // Load Webhooks
        if (data.webhooks) {
          setWebhooks(data.webhooks || []);
        }
      }
    } catch (error) {
      console.error('[Integrations] Failed to load config:', error);
    }
  };

  const testLangSmithConnection = async () => {
    setLangsmithStatus('testing');
    try {
      const response = await fetch(api('/integrations/langsmith/test'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project: langsmithProject,
          apiKey: langsmithApiKey
        })
      });

      if (response.ok) {
        const data = await response.json();
        setLangsmithStatus(data.connected ? 'connected' : 'disconnected');
      } else {
        setLangsmithStatus('disconnected');
      }
    } catch (error) {
      console.error('[Integrations] LangSmith test failed:', error);
      setLangsmithStatus('disconnected');
    }
  };

  const testGrafanaConnection = async () => {
    setGrafanaStatus('testing');
    try {
      const response = await fetch(api('/integrations/grafana/test'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: grafanaUrl,
          apiKey: grafanaApiKey
        })
      });

      if (response.ok) {
        const data = await response.json();
        setGrafanaStatus(data.connected ? 'connected' : 'disconnected');
      } else {
        setGrafanaStatus('disconnected');
      }
    } catch (error) {
      console.error('[Integrations] Grafana test failed:', error);
      setGrafanaStatus('disconnected');
    }
  };

  const addWebhook = () => {
    if (newWebhookUrl.trim() && webhookEvents.length > 0) {
      setWebhooks([...webhooks, { url: newWebhookUrl.trim(), events: [...webhookEvents] }]);
      setNewWebhookUrl('');
      setWebhookEvents([]);
    }
  };

  const removeWebhook = (index: number) => {
    setWebhooks(webhooks.filter((_, idx) => idx !== index));
  };

  const toggleWebhookEvent = (eventId: string) => {
    if (webhookEvents.includes(eventId)) {
      setWebhookEvents(webhookEvents.filter(e => e !== eventId));
    } else {
      setWebhookEvents([...webhookEvents, eventId]);
    }
  };

  const testWebhook = async (url: string) => {
    try {
      const response = await fetch(api('/integrations/webhook/test'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
      });

      if (response.ok) {
        alert('Webhook test successful!');
      } else {
        alert('Webhook test failed');
      }
    } catch (error) {
      console.error('[Integrations] Webhook test failed:', error);
      alert('Webhook test failed');
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveMessage('');

    try {
      const response = await fetch(api('/integrations/config'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          langsmith: {
            project: langsmithProject,
            apiKey: langsmithApiKey,
            enabled: langsmithEnabled
          },
          grafana: {
            url: grafanaUrl,
            apiKey: grafanaApiKey,
            enabled: grafanaEnabled
          },
          vscode: {
            enabled: vscodeEnabled,
            port: vscodePort
          },
          webhooks
        })
      });

      if (response.ok) {
        setSaveMessage('Integration settings saved successfully!');
      } else {
        setSaveMessage('Failed to save integration settings');
      }
    } catch (error) {
      console.error('[Integrations] Failed to save:', error);
      setSaveMessage('Failed to save integration settings');
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMessage(''), 3000);
    }
  };

  return (
    <div style={{
      maxWidth: '1000px',
      margin: '0 auto',
      padding: '24px'
    }}>
      <h2 style={{
        margin: '0 0 24px 0',
        fontSize: '20px',
        fontWeight: '600',
        color: 'var(--fg)'
      }}>
        External Integrations
      </h2>

      {/* LangSmith Integration */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '20px',
        marginBottom: '24px'
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '16px'
        }}>
          <h3 style={{
            margin: 0,
            fontSize: '16px',
            fontWeight: '600',
            color: 'var(--fg)'
          }}>
            LangSmith Configuration
          </h3>
          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            cursor: 'pointer',
            fontSize: '13px'
          }}>
            <input
              type="checkbox"
              checked={langsmithEnabled}
              onChange={(e) => setLangsmithEnabled(e.target.checked)}
              style={{ width: '16px', height: '16px', cursor: 'pointer' }}
            />
            Enable
          </label>
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{
            display: 'block',
            fontSize: '12px',
            fontWeight: '600',
            color: 'var(--fg-muted)',
            marginBottom: '6px'
          }}>
            Project Name
          </label>
          <input
            type="text"
            value={langsmithProject}
            onChange={(e) => setLangsmithProject(e.target.value)}
            placeholder="my-rag-project"
            disabled={!langsmithEnabled}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '8px 12px',
              borderRadius: '4px',
              fontSize: '13px',
              opacity: langsmithEnabled ? 1 : 0.5
            }}
          />
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{
            display: 'block',
            fontSize: '12px',
            fontWeight: '600',
            color: 'var(--fg-muted)',
            marginBottom: '6px'
          }}>
            API Key
          </label>
          <input
            type="password"
            value={langsmithApiKey}
            onChange={(e) => setLangsmithApiKey(e.target.value)}
            placeholder="ls_********"
            disabled={!langsmithEnabled}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '8px 12px',
              borderRadius: '4px',
              fontSize: '13px',
              opacity: langsmithEnabled ? 1 : 0.5
            }}
          />
        </div>

        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <button
            onClick={testLangSmithConnection}
            disabled={!langsmithEnabled || langsmithStatus === 'testing'}
            style={{
              background: 'var(--accent)',
              color: 'var(--accent-contrast)',
              border: 'none',
              padding: '8px 16px',
              borderRadius: '4px',
              fontSize: '13px',
              fontWeight: '600',
              cursor: langsmithEnabled && langsmithStatus !== 'testing' ? 'pointer' : 'not-allowed',
              opacity: langsmithEnabled && langsmithStatus !== 'testing' ? 1 : 0.5
            }}
          >
            {langsmithStatus === 'testing' ? 'Testing...' : 'Test Connection'}
          </button>
          {langsmithStatus !== 'testing' && (
            <span style={{
              fontSize: '12px',
              color: langsmithStatus === 'connected' ? 'var(--success)' : 'var(--fg-muted)'
            }}>
              {langsmithStatus === 'connected' ? '✓ Connected' : 'Not connected'}
            </span>
          )}
        </div>
      </div>

      {/* Grafana Integration */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '20px',
        marginBottom: '24px'
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '16px'
        }}>
          <h3 style={{
            margin: 0,
            fontSize: '16px',
            fontWeight: '600',
            color: 'var(--fg)'
          }}>
            Grafana Configuration
          </h3>
          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            cursor: 'pointer',
            fontSize: '13px'
          }}>
            <input
              type="checkbox"
              checked={grafanaEnabled}
              onChange={(e) => setGrafanaEnabled(e.target.checked)}
              style={{ width: '16px', height: '16px', cursor: 'pointer' }}
            />
            Enable
          </label>
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{
            display: 'block',
            fontSize: '12px',
            fontWeight: '600',
            color: 'var(--fg-muted)',
            marginBottom: '6px'
          }}>
            Grafana URL
          </label>
          <input
            type="text"
            value={grafanaUrl}
            onChange={(e) => setGrafanaUrl(e.target.value)}
            placeholder="http://localhost:3000"
            disabled={!grafanaEnabled}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '8px 12px',
              borderRadius: '4px',
              fontSize: '13px',
              opacity: grafanaEnabled ? 1 : 0.5
            }}
          />
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{
            display: 'block',
            fontSize: '12px',
            fontWeight: '600',
            color: 'var(--fg-muted)',
            marginBottom: '6px'
          }}>
            API Key
          </label>
          <input
            type="password"
            value={grafanaApiKey}
            onChange={(e) => setGrafanaApiKey(e.target.value)}
            placeholder="glsa_********"
            disabled={!grafanaEnabled}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '8px 12px',
              borderRadius: '4px',
              fontSize: '13px',
              opacity: grafanaEnabled ? 1 : 0.5
            }}
          />
        </div>

        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <button
            onClick={testGrafanaConnection}
            disabled={!grafanaEnabled || grafanaStatus === 'testing'}
            style={{
              background: 'var(--accent)',
              color: 'var(--accent-contrast)',
              border: 'none',
              padding: '8px 16px',
              borderRadius: '4px',
              fontSize: '13px',
              fontWeight: '600',
              cursor: grafanaEnabled && grafanaStatus !== 'testing' ? 'pointer' : 'not-allowed',
              opacity: grafanaEnabled && grafanaStatus !== 'testing' ? 1 : 0.5
            }}
          >
            {grafanaStatus === 'testing' ? 'Testing...' : 'Test Connection'}
          </button>
          {grafanaStatus !== 'testing' && (
            <span style={{
              fontSize: '12px',
              color: grafanaStatus === 'connected' ? 'var(--success)' : 'var(--fg-muted)'
            }}>
              {grafanaStatus === 'connected' ? '✓ Connected' : 'Not connected'}
            </span>
          )}
        </div>
      </div>

      {/* VS Code Extension Settings */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '20px',
        marginBottom: '24px'
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '16px'
        }}>
          <h3 style={{
            margin: 0,
            fontSize: '16px',
            fontWeight: '600',
            color: 'var(--fg)'
          }}>
            VS Code Extension
          </h3>
          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            cursor: 'pointer',
            fontSize: '13px'
          }}>
            <input
              type="checkbox"
              checked={vscodeEnabled}
              onChange={(e) => setVscodeEnabled(e.target.checked)}
              style={{ width: '16px', height: '16px', cursor: 'pointer' }}
            />
            Enable
          </label>
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{
            display: 'block',
            fontSize: '12px',
            fontWeight: '600',
            color: 'var(--fg-muted)',
            marginBottom: '6px'
          }}>
            Extension Port
          </label>
          <input
            type="text"
            value={vscodePort}
            onChange={(e) => setVscodePort(e.target.value)}
            placeholder="8013"
            disabled={!vscodeEnabled}
            style={{
              width: '200px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '8px 12px',
              borderRadius: '4px',
              fontSize: '13px',
              opacity: vscodeEnabled ? 1 : 0.5
            }}
          />
          <div style={{
            fontSize: '11px',
            color: 'var(--fg-muted)',
            marginTop: '4px'
          }}>
            Port for VS Code extension to connect to (default: 8013)
          </div>
        </div>
      </div>

      {/* Webhook Configuration */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '20px',
        marginBottom: '24px'
      }}>
        <h3 style={{
          margin: '0 0 16px 0',
          fontSize: '16px',
          fontWeight: '600',
          color: 'var(--fg)'
        }}>
          Webhook Configuration
        </h3>

        <div style={{ marginBottom: '16px' }}>
          <label style={{
            display: 'block',
            fontSize: '12px',
            fontWeight: '600',
            color: 'var(--fg-muted)',
            marginBottom: '6px'
          }}>
            Webhook URL
          </label>
          <input
            type="text"
            value={newWebhookUrl}
            onChange={(e) => setNewWebhookUrl(e.target.value)}
            placeholder="https://your-webhook-endpoint.com/hook"
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '8px 12px',
              borderRadius: '4px',
              fontSize: '13px'
            }}
          />
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{
            display: 'block',
            fontSize: '12px',
            fontWeight: '600',
            color: 'var(--fg-muted)',
            marginBottom: '8px'
          }}>
            Events to Trigger
          </label>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: '8px'
          }}>
            {availableEvents.map(event => (
              <label
                key={event.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  padding: '8px 12px',
                  background: webhookEvents.includes(event.id) ? 'var(--bg-elev2)' : 'var(--bg-elev1)',
                  border: `1px solid ${webhookEvents.includes(event.id) ? 'var(--accent)' : 'var(--line)'}`,
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '12px'
                }}
              >
                <input
                  type="checkbox"
                  checked={webhookEvents.includes(event.id)}
                  onChange={() => toggleWebhookEvent(event.id)}
                  style={{ width: '14px', height: '14px', cursor: 'pointer' }}
                />
                {event.name}
              </label>
            ))}
          </div>
        </div>

        <button
          onClick={addWebhook}
          disabled={!newWebhookUrl.trim() || webhookEvents.length === 0}
          style={{
            background: newWebhookUrl.trim() && webhookEvents.length > 0 ? 'var(--accent)' : 'var(--bg-elev2)',
            color: newWebhookUrl.trim() && webhookEvents.length > 0 ? 'var(--accent-contrast)' : 'var(--fg-muted)',
            border: 'none',
            padding: '8px 16px',
            borderRadius: '4px',
            fontSize: '13px',
            fontWeight: '600',
            cursor: newWebhookUrl.trim() && webhookEvents.length > 0 ? 'pointer' : 'not-allowed'
          }}
        >
          Add Webhook
        </button>

        {/* Webhooks List */}
        {webhooks.length > 0 && (
          <div style={{ marginTop: '20px' }}>
            <h4 style={{
              margin: '0 0 12px 0',
              fontSize: '13px',
              fontWeight: '600',
              color: 'var(--fg-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.5px'
            }}>
              Configured Webhooks
            </h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {webhooks.map((webhook, idx) => (
                <div
                  key={idx}
                  style={{
                    background: 'var(--bg-elev1)',
                    border: '1px solid var(--line)',
                    borderRadius: '4px',
                    padding: '12px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start'
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <div style={{
                      fontSize: '13px',
                      fontWeight: '600',
                      color: 'var(--fg)',
                      marginBottom: '6px',
                      wordBreak: 'break-all'
                    }}>
                      {webhook.url}
                    </div>
                    <div style={{
                      fontSize: '11px',
                      color: 'var(--fg-muted)'
                    }}>
                      Events: {webhook.events.map(e =>
                        availableEvents.find(ae => ae.id === e)?.name || e
                      ).join(', ')}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', marginLeft: '12px' }}>
                    <button
                      onClick={() => testWebhook(webhook.url)}
                      style={{
                        background: 'var(--bg-elev2)',
                        color: 'var(--fg)',
                        border: '1px solid var(--line)',
                        padding: '4px 12px',
                        borderRadius: '4px',
                        fontSize: '11px',
                        fontWeight: '600',
                        cursor: 'pointer',
                        whiteSpace: 'nowrap'
                      }}
                    >
                      Test
                    </button>
                    <button
                      onClick={() => removeWebhook(idx)}
                      style={{
                        background: 'var(--err)',
                        color: 'white',
                        border: 'none',
                        padding: '4px 12px',
                        borderRadius: '4px',
                        fontSize: '11px',
                        fontWeight: '600',
                        cursor: 'pointer',
                        whiteSpace: 'nowrap'
                      }}
                    >
                      Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Save Button */}
      <div style={{
        display: 'flex',
        justifyContent: 'flex-end',
        marginTop: '24px'
      }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            background: saving ? 'var(--bg-elev2)' : 'var(--accent)',
            color: saving ? 'var(--fg-muted)' : 'var(--accent-contrast)',
            border: 'none',
            padding: '12px 32px',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: '600',
            cursor: saving ? 'wait' : 'pointer',
            opacity: saving ? 0.7 : 1
          }}
        >
          {saving ? 'Saving...' : 'Save All Integrations'}
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
    </div>
  );
}
