import { useEffect, useMemo, useState } from 'react';

import { useAPI } from '@/hooks';
import type { ObservabilityStatusResponse, TriBridConfig } from '@/types/generated';

type SecretStatus = Record<string, boolean>;
type TracingConfig = NonNullable<TriBridConfig['tracing']>;
type UiConfig = NonNullable<TriBridConfig['ui']>;

const SECRET_KEYS = ['LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY', 'GRAFANA_API_KEY'] as const;

const EMPTY_STATUS: ObservabilityStatusResponse = {
  ok: false,
  mode: 'off',
  components: [],
  links: [],
  operator_hint: 'Observability status has not loaded yet.'
};

function asBool(value: boolean | number | null | undefined): boolean {
  return value === true || value === 1;
}

export function Integrations() {
  const { api } = useAPI();
  const [config, setConfig] = useState<TriBridConfig | null>(null);
  const [status, setStatus] = useState<ObservabilityStatusResponse>(EMPTY_STATUS);
  const [secrets, setSecrets] = useState<SecretStatus>({});
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    setError('');
    try {
      const [configResp, statusResp, secretsResp] = await Promise.all([
        fetch(api('/config')),
        fetch(api('/observability/status')),
        fetch(api(`/secrets/check?keys=${SECRET_KEYS.join(',')}`))
      ]);

      if (!configResp.ok) {
        throw new Error(`Config load failed (${configResp.status})`);
      }
      if (!statusResp.ok) {
        throw new Error(`Observability status load failed (${statusResp.status})`);
      }
      if (!secretsResp.ok) {
        throw new Error(`Secrets status load failed (${secretsResp.status})`);
      }

      setConfig(await configResp.json());
      setStatus(await statusResp.json());
      setSecrets(await secretsResp.json());
    } catch (loadError) {
      console.error('[Integrations] Failed to load observability settings:', loadError);
      setError(loadError instanceof Error ? loadError.message : 'Failed to load observability settings');
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const updateTracing = <K extends keyof TracingConfig>(key: K, value: TracingConfig[K]) => {
    setConfig((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        tracing: {
          ...(current.tracing || {}),
          [key]: value
        } as TracingConfig
      };
    });
  };

  const updateUi = <K extends keyof UiConfig>(key: K, value: UiConfig[K]) => {
    setConfig((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        ui: {
          ...(current.ui || {}),
          [key]: value
        } as UiConfig
      };
    });
  };

  const handleSave = async () => {
    if (!config) {
      return;
    }
    setSaving(true);
    setSaveMessage('');
    setError('');
    try {
      const response = await fetch(api('/config'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });
      if (!response.ok) {
        throw new Error(`Save failed (${response.status})`);
      }
      setConfig(await response.json());
      await load();
      setSaveMessage('Observability settings saved.');
    } catch (saveError) {
      console.error('[Integrations] Failed to save observability settings:', saveError);
      setError(saveError instanceof Error ? saveError.message : 'Failed to save observability settings');
    } finally {
      setSaving(false);
      window.setTimeout(() => setSaveMessage(''), 3000);
    }
  };

  const secretBadges = useMemo(
    () =>
      SECRET_KEYS.map((key) => ({
        key,
        present: Boolean(secrets[key])
      })),
    [secrets]
  );

  if (!config) {
    return (
      <div style={{ padding: '24px', color: 'var(--fg-muted)' }}>
        Loading observability settings...
      </div>
    );
  }

  const tracing = (config.tracing || {}) as TracingConfig;
  const ui = (config.ui || {}) as UiConfig;
  const components = status.components || [];
  const links = status.links || [];

  return (
    <div style={{ maxWidth: '1000px', margin: '0 auto', padding: '24px' }}>
      <h2 style={{ margin: '0 0 12px 0', fontSize: '20px', fontWeight: 600, color: 'var(--fg)' }}>
        Observability Integrations
      </h2>
      <p style={{ margin: '0 0 24px 0', color: 'var(--fg-muted)', fontSize: '13px', lineHeight: 1.5 }}>
        This surface is the real operator control plane for OTel, Langfuse, Tempo, Alloy, and Grafana.
        The old LangSmith and LangTrace integration path is gone.
      </p>

      {(error || saveMessage) && (
        <div
          style={{
            marginBottom: '20px',
            padding: '12px 14px',
            borderRadius: '6px',
            border: `1px solid ${error ? 'var(--danger)' : 'var(--success)'}`,
            color: error ? 'var(--danger)' : 'var(--success)',
            background: 'var(--card-bg)'
          }}
        >
          {error || saveMessage}
        </div>
      )}

      <div
        style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '20px',
          marginBottom: '24px'
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', alignItems: 'center' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600, color: 'var(--fg)' }}>
              Live Readiness
            </h3>
            <p style={{ margin: '6px 0 0 0', color: 'var(--fg-muted)', fontSize: '13px' }}>
              Mode: <strong style={{ color: 'var(--fg)' }}>{status.mode}</strong>
            </p>
          </div>
          <div
            style={{
              padding: '6px 10px',
              borderRadius: '999px',
              background: status.ok ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
              color: status.ok ? 'var(--success)' : 'var(--danger)',
              fontSize: '12px',
              fontWeight: 600
            }}
          >
            {status.ok ? 'Ready' : 'Needs Attention'}
          </div>
        </div>
        <p style={{ margin: '12px 0 0 0', color: 'var(--fg-muted)', fontSize: '13px', lineHeight: 1.5 }}>
          {status.operator_hint}
        </p>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: '12px',
            marginTop: '16px'
          }}
        >
          {components.map((component) => (
            <div
              key={component.id}
              style={{
                border: '1px solid var(--line)',
                borderRadius: '6px',
                padding: '12px',
                background: 'var(--bg-secondary)'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center' }}>
                <strong style={{ color: 'var(--fg)', fontSize: '13px' }}>{component.label}</strong>
                <span
                  style={{
                    color:
                      component.reachable === false ? 'var(--danger)' : component.enabled ? 'var(--success)' : 'var(--fg-muted)',
                    fontSize: '12px'
                  }}
                >
                  {component.reachable === false ? 'Down' : component.enabled ? 'On' : 'Off'}
                </span>
              </div>
              <div style={{ marginTop: '6px', color: 'var(--fg-muted)', fontSize: '12px', lineHeight: 1.4 }}>
                {component.detail || 'No additional detail.'}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div
        style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '20px',
          marginBottom: '24px'
        }}
      >
        <h3 style={{ margin: '0 0 16px 0', fontSize: '16px', fontWeight: 600, color: 'var(--fg)' }}>
          OTel and Langfuse
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px', color: 'var(--fg-muted)' }}>
            Tracing Mode
            <select
              value={tracing.tracing_mode || 'off'}
              onChange={(event) => updateTracing('tracing_mode', event.target.value)}
              style={{ background: 'var(--input-bg)', border: '1px solid var(--line)', color: 'var(--fg)', padding: '8px 12px', borderRadius: '4px' }}
            >
              <option value="off">Off</option>
              <option value="local">Local</option>
              <option value="otel">OTel</option>
              <option value="otel_langfuse">OTel + Langfuse</option>
            </select>
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px', color: 'var(--fg-muted)' }}>
            OTLP Endpoint
            <input
              type="text"
              value={tracing.otlp_endpoint || ''}
              onChange={(event) => updateTracing('otlp_endpoint', event.target.value)}
              placeholder="http://localhost:4318/v1/traces"
              style={{ background: 'var(--input-bg)', border: '1px solid var(--line)', color: 'var(--fg)', padding: '8px 12px', borderRadius: '4px' }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px', color: 'var(--fg-muted)' }}>
            OTLP Headers
            <input
              type="text"
              value={tracing.otlp_headers || ''}
              onChange={(event) => updateTracing('otlp_headers', event.target.value)}
              placeholder="Authorization=Bearer token"
              style={{ background: 'var(--input-bg)', border: '1px solid var(--line)', color: 'var(--fg)', padding: '8px 12px', borderRadius: '4px' }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px', color: 'var(--fg-muted)' }}>
            Service Name
            <input
              type="text"
              value={tracing.otel_service_name || ''}
              onChange={(event) => updateTracing('otel_service_name', event.target.value)}
              placeholder="ragweld-api"
              style={{ background: 'var(--input-bg)', border: '1px solid var(--line)', color: 'var(--fg)', padding: '8px 12px', borderRadius: '4px' }}
            />
          </label>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px', marginTop: '16px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: 'var(--fg)' }}>
            <input
              type="checkbox"
              checked={asBool(tracing.otel_export_enabled)}
              onChange={(event) => updateTracing('otel_export_enabled', event.target.checked ? 1 : 0)}
            />
            Enable OTLP Export
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: 'var(--fg)' }}>
            <input
              type="checkbox"
              checked={asBool(tracing.langfuse_enabled)}
              onChange={(event) => updateTracing('langfuse_enabled', event.target.checked ? 1 : 0)}
            />
            Enable Langfuse
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: 'var(--fg)' }}>
            <input
              type="checkbox"
              checked={asBool(tracing.cost_tracking_enabled)}
              onChange={(event) => updateTracing('cost_tracking_enabled', event.target.checked ? 1 : 0)}
            />
            Track Online Cost
          </label>
        </div>
      </div>

      <div
        style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '20px',
          marginBottom: '24px'
        }}
      >
        <h3 style={{ margin: '0 0 16px 0', fontSize: '16px', fontWeight: 600, color: 'var(--fg)' }}>
          Tempo, Alloy, and Grafana
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px', color: 'var(--fg-muted)' }}>
            Langfuse Base URL
            <input
              type="text"
              value={tracing.langfuse_base_url || ''}
              onChange={(event) => updateTracing('langfuse_base_url', event.target.value)}
              placeholder="https://langfuse.example.com"
              style={{ background: 'var(--input-bg)', border: '1px solid var(--line)', color: 'var(--fg)', padding: '8px 12px', borderRadius: '4px' }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px', color: 'var(--fg-muted)' }}>
            Langfuse Project
            <input
              type="text"
              value={tracing.langfuse_project || ''}
              onChange={(event) => updateTracing('langfuse_project', event.target.value)}
              placeholder="ragweld"
              style={{ background: 'var(--input-bg)', border: '1px solid var(--line)', color: 'var(--fg)', padding: '8px 12px', borderRadius: '4px' }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px', color: 'var(--fg-muted)' }}>
            Tempo Base URL
            <input
              type="text"
              value={tracing.tempo_base_url || ''}
              onChange={(event) => updateTracing('tempo_base_url', event.target.value)}
              placeholder="http://localhost:53200"
              style={{ background: 'var(--input-bg)', border: '1px solid var(--line)', color: 'var(--fg)', padding: '8px 12px', borderRadius: '4px' }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px', color: 'var(--fg-muted)' }}>
            Alloy Base URL
            <input
              type="text"
              value={tracing.alloy_base_url || ''}
              onChange={(event) => updateTracing('alloy_base_url', event.target.value)}
              placeholder="http://localhost:52345"
              style={{ background: 'var(--input-bg)', border: '1px solid var(--line)', color: 'var(--fg)', padding: '8px 12px', borderRadius: '4px' }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px', color: 'var(--fg-muted)' }}>
            Grafana Base URL
            <input
              type="text"
              value={ui.grafana_base_url || ''}
              onChange={(event) => updateUi('grafana_base_url', event.target.value)}
              placeholder="http://localhost:3301"
              style={{ background: 'var(--input-bg)', border: '1px solid var(--line)', color: 'var(--fg)', padding: '8px 12px', borderRadius: '4px' }}
            />
          </label>
        </div>
      </div>

      <div
        style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '20px',
          marginBottom: '24px'
        }}
      >
        <h3 style={{ margin: '0 0 16px 0', fontSize: '16px', fontWeight: 600, color: 'var(--fg)' }}>
          Secret Presence
        </h3>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
          {secretBadges.map((item) => (
            <div
              key={item.key}
              style={{
                padding: '8px 12px',
                borderRadius: '999px',
                border: '1px solid var(--line)',
                background: item.present ? 'rgba(34,197,94,0.12)' : 'rgba(148,163,184,0.12)',
                color: item.present ? 'var(--success)' : 'var(--fg-muted)',
                fontSize: '12px',
                fontWeight: 600
              }}
            >
              {item.key}: {item.present ? 'present' : 'missing'}
            </div>
          ))}
        </div>
        {links.length > 0 && (
          <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {links.map((link) => (
              <a
                key={`${link.kind}-${link.url}`}
                href={link.url}
                target="_blank"
                rel="noreferrer"
                style={{ color: 'var(--accent)', fontSize: '13px' }}
              >
                {link.label}
              </a>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            border: 'none',
            padding: '10px 24px',
            borderRadius: '4px',
            fontSize: '14px',
            fontWeight: 600,
            cursor: saving ? 'not-allowed' : 'pointer',
            opacity: saving ? 0.6 : 1
          }}
        >
          {saving ? 'Saving...' : 'Save Observability Settings'}
        </button>
      </div>
    </div>
  );
}
