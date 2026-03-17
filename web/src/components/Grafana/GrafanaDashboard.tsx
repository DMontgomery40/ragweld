// TriBridRAG - Grafana Dashboard (embedded)
// Uses Pydantic-backed UI config fields: ui.grafana_*

import { useMemo, useState } from 'react';
import { useConfigField } from '@/hooks/useConfig';
import { GRAFANA_DASHBOARD_PRESETS, findGrafanaPreset } from './dashboardPresets';

export function GrafanaDashboard() {
  // Pydantic-derived config (renders immediately using defaults while config loads)
  const [baseUrl] = useConfigField<string>('ui.grafana_base_url', 'http://127.0.0.1:3001');
  const [dashboardUid, setDashboardUid] = useConfigField<string>('ui.grafana_dashboard_uid', 'tribrid-overview');
  const [dashboardSlug, setDashboardSlug] = useConfigField<string>('ui.grafana_dashboard_slug', 'tribrid-overview');
  const [kiosk] = useConfigField<string>('ui.grafana_kiosk', 'tv');
  const [orgId] = useConfigField<number>('ui.grafana_org_id', 1);
  const [refresh] = useConfigField<string>('ui.grafana_refresh', '10s');
  const [embedEnabledRaw] = useConfigField<number>('ui.grafana_embed_enabled', 1);

  const embedEnabled = Boolean(embedEnabledRaw);
  const activePreset = findGrafanaPreset(String(dashboardUid || ''), String(dashboardSlug || ''));

  function applyPreset(presetId: string) {
    const preset = GRAFANA_DASHBOARD_PRESETS.find((item) => item.id === presetId);
    if (!preset) return;
    setDashboardUid(preset.uid);
    setDashboardSlug(preset.slug);
  }

  // Local view controls (not persisted)
  const [timeRange, setTimeRange] = useState('1h');
  const [iframeKey, setIframeKey] = useState(0);

  const grafanaUrl = useMemo(() => {
    const base = String(baseUrl || '').replace(/\/$/, '');
    const uid = String(dashboardUid || '').trim();
    const slug = String(dashboardSlug || uid).trim() || uid;
    if (!base || !uid) return '';

    const params = new URLSearchParams({
      from: `now-${timeRange}`,
      to: 'now',
      theme: 'dark',
    });
    const r = String(refresh || '').trim();
    if (r) params.set('refresh', r);
    const k = String(kiosk || '').trim();
    if (k) params.set('kiosk', k);
    const org = Number(orgId || 0);
    if (org > 0) params.set('orgId', String(org));
    if (base.startsWith('/')) params.set('embed', '1');

    return `${base}/d/${encodeURIComponent(uid)}/${encodeURIComponent(slug)}?${params.toString()}`;
  }, [baseUrl, dashboardUid, dashboardSlug, kiosk, orgId, refresh, timeRange]);

  if (!embedEnabled) {
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
        padding: '24px',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        background: 'var(--card-bg)',
        color: 'var(--fg)'
      }}>
        <div style={{ fontSize: '14px', fontWeight: 700 }}>Grafana embedding is disabled</div>
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
          Enable embedding in the Config subtab to load the dashboard iframe.
        </div>
      </div>
    );
  }

  if (!grafanaUrl) {
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
        padding: '24px',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        background: 'var(--card-bg)',
        color: 'var(--fg)'
      }}>
        <div style={{ fontSize: '14px', fontWeight: 700 }}>Grafana is not configured</div>
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
          Set `ui.grafana_base_url` and `ui.grafana_dashboard_uid` in the Config subtab.
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      {/* Controls Bar */}
      <div style={{
        padding: '10px 12px',
        borderBottom: '1px solid var(--line)',
        display: 'flex',
        gap: '12px',
        alignItems: 'center',
        background: 'var(--bg-elev1)',
        flexShrink: 0
      }}>
        <div style={{ flex: 1, fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>
          {activePreset?.label || 'Grafana'}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label style={{ fontSize: '12px', color: 'var(--fg-muted)', fontWeight: 600 }}>
            Dashboard
          </label>
          <select
            value={activePreset?.id || ''}
            onChange={(e) => applyPreset(e.target.value)}
            style={{
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '6px 8px',
              borderRadius: '6px',
              fontSize: '12px'
            }}
            aria-label="Grafana dashboard preset"
          >
            <option value="">Custom</option>
            {GRAFANA_DASHBOARD_PRESETS.map((preset) => (
              <option key={preset.id} value={preset.id}>{preset.label}</option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label style={{ fontSize: '12px', color: 'var(--fg-muted)', fontWeight: 600 }}>
            Range
          </label>
          <select
            value={timeRange}
            onChange={(e) => setTimeRange(e.target.value)}
            style={{
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '6px 8px',
              borderRadius: '6px',
              fontSize: '12px'
            }}
            aria-label="Grafana time range"
          >
            <option value="5m">5m</option>
            <option value="15m">15m</option>
            <option value="30m">30m</option>
            <option value="1h">1h</option>
            <option value="3h">3h</option>
            <option value="6h">6h</option>
            <option value="12h">12h</option>
            <option value="24h">24h</option>
            <option value="7d">7d</option>
            <option value="30d">30d</option>
          </select>
        </div>

        <button
          onClick={() => setIframeKey((k) => k + 1)}
          style={{
            background: 'var(--bg-elev2)',
            color: 'var(--fg)',
            border: '1px solid var(--line)',
            padding: '6px 10px',
            borderRadius: '6px',
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer',
          }}
          aria-label="Reload Grafana iframe"
          title="Force iframe reload"
        >
          Reload
        </button>

        <a
          href={grafanaUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            border: 'none',
            padding: '6px 10px',
            borderRadius: '6px',
            fontSize: '12px',
            fontWeight: 700,
            cursor: 'pointer',
            textDecoration: 'none',
          }}
          title="Open in Grafana"
        >
          Open
        </a>
      </div>

      {/* Iframe */}
      <div style={{ flex: 1, minHeight: 0, position: 'relative', overflow: 'hidden' }}>
        <iframe
          key={iframeKey}
          src={grafanaUrl}
          id="grafana-iframe"
          style={{
            width: '100%',
            height: '100%',
            border: 'none',
            background: '#111',
          }}
          title="Grafana Dashboard"
        />
      </div>
    </div>
  );
}
