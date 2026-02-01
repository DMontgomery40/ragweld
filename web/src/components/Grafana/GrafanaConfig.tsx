// TriBridRAG - Grafana config (Pydantic-backed)
//
// IMPORTANT:
// - These values live in TriBridConfig.ui.* and are persisted through /api/config.
// - We do NOT store Grafana API keys/tokens in the frontend.

import { useConfigField } from '@/hooks/useConfig';

export function GrafanaConfig() {
  const [embedEnabledRaw, setEmbedEnabled, embedMeta] = useConfigField<number>('ui.grafana_embed_enabled', 1);
  const [baseUrl, setBaseUrl] = useConfigField<string>('ui.grafana_base_url', 'http://127.0.0.1:3001');
  const [dashboardUid, setDashboardUid] = useConfigField<string>('ui.grafana_dashboard_uid', 'tribrid-overview');
  const [dashboardSlug, setDashboardSlug] = useConfigField<string>('ui.grafana_dashboard_slug', 'tribrid-overview');
  const [kiosk, setKiosk] = useConfigField<string>('ui.grafana_kiosk', 'tv');
  const [orgId, setOrgId] = useConfigField<number>('ui.grafana_org_id', 1);
  const [refresh, setRefresh] = useConfigField<string>('ui.grafana_refresh', '10s');

  const embedEnabled = Boolean(embedEnabledRaw);
  const normalizedBase = String(baseUrl || '').replace(/\/$/, '');
  const normalizedUid = String(dashboardUid || '').trim();
  const normalizedSlug = String(dashboardSlug || normalizedUid).trim() || normalizedUid;

  return (
    <div style={{ maxWidth: '980px', margin: '0 auto', padding: '24px' }}>
      <h2 style={{ margin: '0 0 12px 0', fontSize: '20px', fontWeight: 700, color: 'var(--fg)' }}>
        Grafana
      </h2>
      <div style={{ marginBottom: '18px', fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.6 }}>
        Grafana is provisioned via Docker with anonymous access enabled by default, so the embedded dashboard works
        out of the box.
      </div>

      {embedMeta.error && (
        <div style={{
          padding: '12px 16px',
          background: 'rgba(255, 107, 107, 0.12)',
          border: '1px solid var(--err)',
          borderRadius: '8px',
          color: 'var(--err)',
          fontSize: '12px',
          marginBottom: '16px'
        }}>
          {embedMeta.error}
        </div>
      )}

      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '10px',
        padding: '20px',
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: '16px'
      }}>
        <div style={{ gridColumn: '1 / 3' }}>
          <label style={{ display: 'flex', gap: '10px', alignItems: 'center', fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>
            <input
              type="checkbox"
              checked={embedEnabled}
              onChange={(e) => setEmbedEnabled(e.target.checked ? 1 : 0)}
            />
            Enable embedded Grafana
          </label>
          <div style={{ marginTop: '6px', fontSize: '12px', color: 'var(--fg-muted)' }}>
            If disabled, the Grafana tab will show a simple message instead of an iframe.
          </div>
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '13px', fontWeight: 700, color: 'var(--fg)', marginBottom: '8px' }}>
            Grafana Base URL
          </label>
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="http://127.0.0.1:3001"
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '8px',
              fontSize: '13px'
            }}
          />
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '13px', fontWeight: 700, color: 'var(--fg)', marginBottom: '8px' }}>
            Org ID
          </label>
          <input
            type="number"
            min={1}
            value={orgId}
            onChange={(e) => {
              const n = Number.parseInt(e.target.value || '1', 10);
              setOrgId(Number.isFinite(n) && n > 0 ? n : 1);
            }}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '8px',
              fontSize: '13px'
            }}
          />
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '13px', fontWeight: 700, color: 'var(--fg)', marginBottom: '8px' }}>
            Dashboard UID
          </label>
          <input
            type="text"
            value={dashboardUid}
            onChange={(e) => setDashboardUid(e.target.value)}
            placeholder="tribrid-overview"
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '8px',
              fontSize: '13px'
            }}
          />
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '13px', fontWeight: 700, color: 'var(--fg)', marginBottom: '8px' }}>
            Dashboard Slug
          </label>
          <input
            type="text"
            value={dashboardSlug}
            onChange={(e) => setDashboardSlug(e.target.value)}
            placeholder="tribrid-overview"
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '8px',
              fontSize: '13px'
            }}
          />
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '13px', fontWeight: 700, color: 'var(--fg)', marginBottom: '8px' }}>
            Refresh
          </label>
          <input
            type="text"
            value={refresh}
            onChange={(e) => setRefresh(e.target.value)}
            placeholder="10s"
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '8px',
              fontSize: '13px'
            }}
          />
          <div style={{ marginTop: '6px', fontSize: '12px', color: 'var(--fg-muted)' }}>
            Examples: <code>5s</code>, <code>30s</code>, <code>1m</code>
          </div>
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '13px', fontWeight: 700, color: 'var(--fg)', marginBottom: '8px' }}>
            Kiosk mode
          </label>
          <select
            value={kiosk}
            onChange={(e) => setKiosk(e.target.value)}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '8px',
              fontSize: '13px'
            }}
          >
            <option value="">None</option>
            <option value="tv">tv</option>
            <option value="1">1 (minimal)</option>
          </select>
        </div>
      </div>

      <div style={{
        marginTop: '16px',
        display: 'flex',
        gap: '10px',
        flexWrap: 'wrap',
        alignItems: 'center'
      }}>
        <a
                href={normalizedBase || 'http://127.0.0.1:3001'}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            background: 'var(--bg-elev2)',
            color: 'var(--fg)',
            border: '1px solid var(--line)',
            padding: '8px 12px',
            borderRadius: '8px',
            fontSize: '12px',
            fontWeight: 700,
            textDecoration: 'none'
          }}
        >
          Open Grafana
        </a>

        {normalizedBase && normalizedUid && (
          <a
            href={`${normalizedBase}/d/${encodeURIComponent(normalizedUid)}/${encodeURIComponent(normalizedSlug)}`}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              background: 'var(--accent)',
              color: 'var(--accent-contrast)',
              border: 'none',
              padding: '8px 12px',
              borderRadius: '8px',
              fontSize: '12px',
              fontWeight: 800,
              textDecoration: 'none'
            }}
          >
            Open dashboard
          </a>
        )}

        <a
          href="http://localhost:9090"
          target="_blank"
          rel="noopener noreferrer"
          style={{
            background: 'var(--bg-elev2)',
            color: 'var(--fg)',
            border: '1px solid var(--line)',
            padding: '8px 12px',
            borderRadius: '8px',
            fontSize: '12px',
            fontWeight: 700,
            textDecoration: 'none'
          }}
        >
          Open Prometheus
        </a>
      </div>

      {embedMeta.loading && (
        <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--fg-muted)' }}>
          Loading config…
        </div>
      )}
    </div>
  );
}
