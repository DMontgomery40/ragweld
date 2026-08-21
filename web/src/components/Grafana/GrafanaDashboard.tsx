// TriBridRAG - Grafana Dashboard (embedded)
// Uses Pydantic-backed UI config fields plus the observability catalog.

import { useEffect, useMemo, useState } from 'react';
import { useConfigField } from '@/hooks/useConfig';
import * as DashAPI from '@/api/dashboard';
import { useActiveRepo } from '@/stores/useRepoStore';
import type { ObservabilityCatalogResponse, ObservabilityWorkbenchLink } from '@/types/generated';
import { GRAFANA_DASHBOARD_PRESETS, findGrafanaPreset } from './dashboardPresets';

type DashboardOption = {
  id: string;
  label: string;
  uid: string;
  slug: string;
  description: string;
  workbenchLinks: ObservabilityWorkbenchLink[];
};

export function GrafanaDashboard() {
  const activeRepo = useActiveRepo();

  const [baseUrl] = useConfigField<string>('ui.grafana_base_url', 'http://127.0.0.1:3301');
  const [dashboardUid, setDashboardUid] = useConfigField<string>('ui.grafana_dashboard_uid', 'ragweld-oncall-overview');
  const [dashboardSlug, setDashboardSlug] = useConfigField<string>('ui.grafana_dashboard_slug', 'on-call-overview');
  const [kiosk] = useConfigField<string>('ui.grafana_kiosk', 'tv');
  const [orgId] = useConfigField<number>('ui.grafana_org_id', 1);
  const [refresh] = useConfigField<string>('ui.grafana_refresh', '10s');
  const [embedEnabled] = useConfigField<boolean>('ui.grafana_embed_enabled', true);

  const [catalog, setCatalog] = useState<ObservabilityCatalogResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    const loadCatalog = async () => {
      try {
        const nextCatalog = await DashAPI.getObservabilityCatalog(String(activeRepo || '').trim() || undefined);
        if (!cancelled) setCatalog(nextCatalog);
      } catch {
        if (!cancelled) setCatalog(null);
      }
    };
    void loadCatalog();
    return () => {
      cancelled = true;
    };
  }, [activeRepo]);

  const presetOptions = useMemo<DashboardOption[]>(() => {
    const catalogDashboards = catalog?.dashboards || [];
    if (catalogDashboards.length > 0) {
      return catalogDashboards.map((dashboard) => ({
        id: String(dashboard.id || dashboard.uid || ''),
        label: String(dashboard.title || dashboard.uid || ''),
        uid: String(dashboard.uid || ''),
        slug: String(dashboard.slug || dashboard.uid || ''),
        description: String(dashboard.description || ''),
        workbenchLinks: dashboard.workbench_links || [],
      }));
    }
    return GRAFANA_DASHBOARD_PRESETS.map((preset) => ({
      id: preset.id,
      label: preset.label,
      uid: preset.uid,
      slug: preset.slug,
      description: preset.description,
      workbenchLinks: [],
    }));
  }, [catalog]);

  const activePreset =
    presetOptions.find((item) => item.uid === String(dashboardUid || '').trim() && item.slug === String(dashboardSlug || '').trim()) ||
    (() => {
      const fallback = findGrafanaPreset(String(dashboardUid || ''), String(dashboardSlug || ''));
      return fallback
        ? {
            id: fallback.id,
            label: fallback.label,
            uid: fallback.uid,
            slug: fallback.slug,
            description: fallback.description,
            workbenchLinks: [],
          }
        : null;
    })();

  function applyPreset(presetId: string) {
    const preset = presetOptions.find((item) => item.id === presetId);
    if (!preset) return;
    setDashboardUid(preset.uid);
    setDashboardSlug(preset.slug);
  }

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
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
          padding: '24px',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          background: 'var(--card-bg)',
          color: 'var(--fg)',
        }}
      >
        <div style={{ fontSize: '14px', fontWeight: 700 }}>Grafana embedding is disabled</div>
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
          Enable embedding in the Config subtab to load the dashboard iframe.
        </div>
      </div>
    );
  }

  if (!grafanaUrl) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
          padding: '24px',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          background: 'var(--card-bg)',
          color: 'var(--fg)',
        }}
      >
        <div style={{ fontSize: '14px', fontWeight: 700 }}>Grafana is not configured</div>
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
          Set `ui.grafana_base_url` and `ui.grafana_dashboard_uid` in the Config subtab.
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <div
        style={{
          padding: '16px 16px 0',
          borderBottom: '1px solid var(--line)',
          background: 'var(--bg-elev1)',
          display: 'grid',
          gap: 12,
          flexShrink: 0,
        }}
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: 10,
          }}
        >
          {presetOptions.map((preset) => {
            const isActive = preset.uid === String(dashboardUid || '').trim() && preset.slug === String(dashboardSlug || '').trim();
            return (
              <button
                key={preset.id}
                type="button"
                onClick={() => applyPreset(preset.id)}
                style={{
                  textAlign: 'left',
                  borderRadius: 12,
                  border: isActive ? '1px solid rgba(42, 157, 143, 0.52)' : '1px solid rgba(112, 130, 156, 0.18)',
                  background: isActive ? 'rgba(13, 43, 44, 0.88)' : 'rgba(9, 18, 27, 0.9)',
                  color: 'var(--fg)',
                  padding: '12px 14px',
                  cursor: 'pointer',
                }}
              >
                <div style={{ fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(180, 193, 210, 0.72)' }}>
                  dashboard family
                </div>
                <div style={{ marginTop: 6, fontSize: 15, fontWeight: 700 }}>{preset.label}</div>
                <div style={{ marginTop: 6, fontSize: 12, lineHeight: 1.5, color: 'var(--fg-muted)' }}>
                  {preset.description}
                </div>
              </button>
            );
          })}
        </div>

        {activePreset?.workbenchLinks?.length ? (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', paddingBottom: 4 }}>
            {activePreset.workbenchLinks.map((link) => (
              <a
                key={`${link.label}-${link.path}`}
                href={link.path}
                style={{
                  textDecoration: 'none',
                  borderRadius: 999,
                  border: '1px solid rgba(130, 154, 180, 0.24)',
                  background: 'rgba(10, 23, 35, 0.88)',
                  color: 'var(--fg)',
                  padding: '8px 12px',
                  fontSize: 12,
                  fontWeight: 600,
                }}
              >
                {link.label}
              </a>
            ))}
          </div>
        ) : null}
      </div>

      <div
        style={{
          padding: '10px 12px',
          borderBottom: '1px solid var(--line)',
          display: 'flex',
          gap: '12px',
          alignItems: 'center',
          background: 'var(--bg-elev1)',
          flexShrink: 0,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ flex: 1, fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>
          {activePreset?.label || 'Grafana'}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label style={{ fontSize: '12px', color: 'var(--fg-muted)', fontWeight: 600 }}>Dashboard</label>
          <select
            value={activePreset?.id || ''}
            onChange={(e) => applyPreset(e.target.value)}
            style={{
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '6px 8px',
              borderRadius: '6px',
              fontSize: '12px',
            }}
            aria-label="Grafana dashboard preset"
          >
            <option value="">Custom</option>
            {presetOptions.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label}
              </option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label style={{ fontSize: '12px', color: 'var(--fg-muted)', fontWeight: 600 }}>Range</label>
          <select
            value={timeRange}
            onChange={(e) => setTimeRange(e.target.value)}
            style={{
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '6px 8px',
              borderRadius: '6px',
              fontSize: '12px',
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
          onClick={() => setIframeKey((value) => value + 1)}
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
