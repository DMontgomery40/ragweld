// AGRO - Grafana Dashboard Component
// Embedded Grafana iframe with time range controls
// Reference: /assets/grafana-dashboard-subtab.png, /assets/grafana-metrics.png

import { useState, useEffect } from 'react';
import { useAPI } from '@/hooks';

interface GrafanaConfig {
  baseUrl: string;
  dashboardUid: string;
  dashboardSlug: string;
  refresh?: string;
  kiosk?: string;
  authMode?: string;
  orgId?: number;
  embedEnabled?: boolean;
  authToken?: string;
}

const DEFAULT_GRAFANA: GrafanaConfig = {
  baseUrl: 'http://127.0.0.1:3000',
  dashboardUid: 'agro-overview',
  dashboardSlug: 'agro-overview',
  refresh: '10s',
  kiosk: 'tv',
  authMode: 'anonymous',
  orgId: 1,
  embedEnabled: true,
  authToken: ''
};

export function GrafanaDashboard() {
  const { api } = useAPI();
  const [config, setConfig] = useState<GrafanaConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState('5m');
  const [refreshInterval, setRefreshInterval] = useState(30);
  const [fullscreen, setFullscreen] = useState(true);
  const [iframeKey, setIframeKey] = useState(0);

  // Load Grafana configuration
  useEffect(() => {
    void loadConfig();
  }, []);

  const loadConfig = async () => {
    setLoading(true);
    try {
      const response = await fetch(api('/grafana/config'));
      if (response.ok) {
        const data = await response.json();
        setConfig({
          baseUrl: data.url || DEFAULT_GRAFANA.baseUrl,
          dashboardUid: data.dashboardUid || DEFAULT_GRAFANA.dashboardUid,
          dashboardSlug: data.dashboardSlug || data.dashboardId || DEFAULT_GRAFANA.dashboardSlug,
          refresh: data.refresh || DEFAULT_GRAFANA.refresh,
          kiosk: data.kiosk || DEFAULT_GRAFANA.kiosk,
          authMode: data.authMode || DEFAULT_GRAFANA.authMode,
          orgId: data.orgId !== undefined ? Number(data.orgId) : DEFAULT_GRAFANA.orgId,
          embedEnabled: Boolean(data.embedEnabled ?? DEFAULT_GRAFANA.embedEnabled),
          authToken: data.authToken || DEFAULT_GRAFANA.authToken
        });
      } else {
        setConfig(DEFAULT_GRAFANA);
      }
    } catch (error) {
      console.error('[GrafanaDashboard] Failed to load config:', error);
      setConfig(DEFAULT_GRAFANA);
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = () => {
    // Force iframe reload by changing key
    setIframeKey(prev => prev + 1);
  };

  const handleFullscreen = () => {
    setFullscreen(!fullscreen);
  };

  const getGrafanaUrl = () => {
    if (!config) return '';

    const baseUrl = config.baseUrl.replace(/\/$/, '');
    const slug = config.dashboardSlug || config.dashboardUid;
    const authToken = config.authToken && config.authToken.includes('•') ? '' : (config.authToken || '');
    const params = new URLSearchParams({
      from: `now-${timeRange}`,
      to: 'now',
      refresh: `${refreshInterval}s`,
      kiosk: config.kiosk || 'tv',
      theme: 'dark',
    });
    if (config.orgId) params.set('orgId', String(config.orgId));
    if (authToken && (config.authMode || '').toLowerCase() === 'token') {
      params.set('auth_token', authToken);
    }

    return `${baseUrl}/d/${encodeURIComponent(config.dashboardUid)}/${encodeURIComponent(slug)}?${params.toString()}`;
  };

  if (loading) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '70vh',
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        color: 'var(--fg-muted)',
        fontSize: '14px'
      }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{
            width: '40px',
            height: '40px',
            border: '3px solid var(--line)',
            borderTopColor: 'var(--accent)',
            borderRadius: '50%',
            animation: 'spin 1s linear infinite',
            margin: '0 auto 12px'
          }} />
          Loading Grafana configuration...
        </div>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (!config) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '70vh',
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        flexDirection: 'column',
        gap: '12px'
      }}>
        <div style={{ fontSize: '48px' }}>📊</div>
        <div style={{ fontSize: '16px', color: 'var(--fg)' }}>Grafana Not Configured</div>
        <div style={{ fontSize: '13px', color: 'var(--fg-muted)' }}>
          Configure Grafana connection in the Config tab
        </div>
      </div>
    );
  }

  if (config.embedEnabled === false) {
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
        padding: '24px',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        background: 'var(--card-bg)'
      }}>
        <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--fg)' }}>Grafana embedding is disabled</div>
        <div style={{ fontSize: '13px', color: 'var(--fg-muted)' }}>
          Enable embedding in the Config subtab to load the dashboard iframe.
        </div>
      </div>
    );
  }

  const containerStyle: React.CSSProperties = fullscreen ? {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    zIndex: 9999,
    background: 'var(--bg)',
    display: 'flex',
    flexDirection: 'column'
  } : {
    display: 'flex',
    flexDirection: 'column',
    height: '70vh',
    border: '1px solid var(--line)',
    borderRadius: '6px',
    overflow: 'hidden',
    background: 'var(--card-bg)'
  };

  return (
    <div style={containerStyle}>
      {/* Controls Bar */}
      <div style={{
        padding: '12px 16px',
        borderBottom: '1px solid var(--line)',
        display: 'flex',
        gap: '12px',
        alignItems: 'center',
        background: 'var(--bg-elev1)',
        flexShrink: 0
      }}>
        <div style={{ flex: 1, fontSize: '14px', fontWeight: '600', color: 'var(--fg)' }}>
          📊 Grafana Metrics
        </div>

        {/* Time Range Selector */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label style={{
            fontSize: '12px',
            color: 'var(--fg-muted)',
            fontWeight: '600'
          }}>
            Time Range:
          </label>
          <select
            value={timeRange}
            onChange={(e) => setTimeRange(e.target.value)}
            style={{
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '4px 8px',
              borderRadius: '4px',
              fontSize: '12px'
            }}
            aria-label="Time range selector"
            title="Select how far back Grafana should query data for the embedded dashboard"
          >
            <option value="5m">Last 5 minutes</option>
            <option value="15m">Last 15 minutes</option>
            <option value="30m">Last 30 minutes</option>
            <option value="1h">Last 1 hour</option>
            <option value="3h">Last 3 hours</option>
            <option value="6h">Last 6 hours</option>
            <option value="12h">Last 12 hours</option>
            <option value="24h">Last 24 hours</option>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
          </select>
        </div>

        {/* Refresh Interval */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label style={{
            fontSize: '12px',
            color: 'var(--fg-muted)',
            fontWeight: '600'
          }}>
            Refresh:
          </label>
          <select
            value={refreshInterval}
            onChange={(e) => setRefreshInterval(parseInt(e.target.value))}
            style={{
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '4px 8px',
              borderRadius: '4px',
              fontSize: '12px'
            }}
            aria-label="Refresh interval selector"
            title="How often the embedded dashboard should auto-refresh"
          >
            <option value="5">5s</option>
            <option value="10">10s</option>
            <option value="30">30s</option>
            <option value="60">1m</option>
            <option value="300">5m</option>
            <option value="0">Off</option>
          </select>
        </div>

        {/* Refresh Button */}
        <button
          onClick={handleRefresh}
          style={{
            background: 'var(--bg-elev2)',
            color: 'var(--fg)',
            border: '1px solid var(--line)',
            padding: '4px 12px',
            borderRadius: '4px',
            fontSize: '12px',
            fontWeight: '600',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '4px'
          }}
          aria-label="Refresh dashboard"
          title="Force the Grafana iframe to reload now"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="23 4 23 10 17 10" />
            <polyline points="1 20 1 14 7 14" />
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
          </svg>
          Refresh
        </button>

        {/* Fullscreen Toggle */}
        <button
          onClick={handleFullscreen}
          style={{
            background: 'var(--bg-elev2)',
            color: 'var(--fg)',
            border: '1px solid var(--line)',
            padding: '4px 12px',
            borderRadius: '4px',
            fontSize: '12px',
            fontWeight: '600',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '4px'
          }}
          aria-label={fullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
          title={fullscreen ? 'Exit fullscreen view' : 'Open Grafana iframe fullscreen'}
        >
          {fullscreen ? (
            <>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3" />
              </svg>
              Exit
            </>
          ) : (
            <>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
              </svg>
              Fullscreen
            </>
          )}
        </button>

        {/* Open in New Tab */}
        <a
          href={getGrafanaUrl()}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            border: 'none',
            padding: '4px 12px',
            borderRadius: '4px',
            fontSize: '12px',
            fontWeight: '600',
            cursor: 'pointer',
            textDecoration: 'none',
            display: 'flex',
            alignItems: 'center',
            gap: '4px'
          }}
          title="Open this dashboard in a new browser tab"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
            <polyline points="15 3 21 3 21 9" />
            <line x1="10" y1="14" x2="21" y2="3" />
          </svg>
          Open
        </a>
      </div>

      {/* Grafana Iframe */}
      <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        <iframe
          key={iframeKey}
          src={getGrafanaUrl()}
          id="grafana-iframe"
          style={{
            width: '100%',
            height: '100%',
            border: 'none',
            background: '#1a1a1a'
          }}
          title="Grafana Dashboard"
          onLoad={() => {
            console.log('[GrafanaDashboard] Iframe loaded');
          }}
          onError={() => {
            console.error('[GrafanaDashboard] Iframe failed to load');
          }}
        />

        {/* Loading Skeleton (shows while iframe is loading) */}
        <div style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'var(--card-bg)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          pointerEvents: 'none',
          opacity: 0.5,
          zIndex: -1
        }}>
          <div style={{
            width: '40px',
            height: '40px',
            border: '3px solid var(--line)',
            borderTopColor: 'var(--accent)',
            borderRadius: '50%',
            animation: 'spin 1s linear infinite'
          }} />
        </div>
      </div>

      {fullscreen && (
        <div style={{
          padding: '8px 16px',
          borderTop: '1px solid var(--line)',
          background: 'var(--bg-elev1)',
          fontSize: '11px',
          color: 'var(--fg-muted)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>Press ESC or click Exit Fullscreen to return</span>
          <span>Dashboard: {config.dashboardUid}</span>
        </div>
      )}

      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
