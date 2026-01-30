// AGRO - Monitoring Subtab
// Logs, alerts, traces, and performance monitoring

import { useState, useEffect } from 'react';
import * as DashAPI from '@/api/dashboard';

export function MonitoringSubtab() {
  const [alertStatus, setAlertStatus] = useState<string>('Loading...');
  const [alerts, setAlerts] = useState<DashAPI.Alert[]>([]);
  const [traces, setTraces] = useState<DashAPI.Trace[]>([]);
  const [lokiStatus, setLokiStatus] = useState<DashAPI.LokiStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const loadMonitoringData = async () => {
    setLoading(true);

    try {
      // Load all monitoring data in parallel
      const [alertData, traceData, lokiData] = await Promise.allSettled([
        DashAPI.getAlertStatus(),
        DashAPI.getTraces(10),
        DashAPI.getLokiStatus()
      ]);

      // Alerts
      if (alertData.status === 'fulfilled') {
        const a = alertData.value;
        if (a.recent_alerts && a.recent_alerts.length > 0) {
          setAlertStatus(`${a.recent_alerts.length} active alert(s)`);
          setAlerts(a.recent_alerts.slice(0, 5));
        } else {
          setAlertStatus('No active alerts');
          setAlerts([]);
        }
      } else {
        setAlertStatus('Failed to load');
      }

      // Traces - ensure it's always an array
      if (traceData.status === 'fulfilled') {
        const traces = traceData.value;
        setTraces(Array.isArray(traces) ? traces : []);
      } else {
        setTraces([]);
      }

      // Loki
      if (lokiData.status === 'fulfilled') {
        setLokiStatus(lokiData.value);
      }

      setLoading(false);
    } catch (err) {
      console.error('[MonitoringSubtab] Error loading data:', err);
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMonitoringData();

    // Poll every minute
    const interval = setInterval(loadMonitoringData, 60000);

    // Listen for manual refresh
    const handleRefresh = () => loadMonitoringData();
    window.addEventListener('dashboard-refresh', handleRefresh);

    return () => {
      clearInterval(interval);
      window.removeEventListener('dashboard-refresh', handleRefresh);
    };
  }, []);

  return (
    <div
      id="tab-dashboard-monitoring"
      className="dashboard-subtab"
      style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}
    >
      {/* Monitoring Logs Section */}
      <div className="settings-section" style={{ background: 'var(--panel)', borderLeft: '3px solid var(--warn)' }}>
        <h3
          style={{
            fontSize: '16px',
            marginBottom: '16px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px'
          }}
        >
          <span style={{ fontSize: '24px' }}>📜</span>
          Monitoring Logs
        </h3>
        <p className="small" style={{ color: 'var(--fg-muted)', marginBottom: '16px', lineHeight: '1.6' }}>
          Recent alerts and system notices from Alertmanager webhook log. Full controls are under Infrastructure → Monitoring.
        </p>

        {loading ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--fg-muted)' }}>
            Loading monitoring data...
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', alignItems: 'start' }}>
            {/* Recent Alerts */}
            <div
              style={{
                background: 'var(--card-bg)',
                border: '1px solid var(--line)',
                borderRadius: '6px',
                padding: '16px'
              }}
            >
              <h4 style={{ margin: '0 0 12px 0', color: 'var(--accent)', fontSize: '14px' }}>Recent Alerts</h4>
              <div id="alert-status-container" style={{ minHeight: '48px', fontSize: '12px', color: 'var(--fg)' }}>
                {alertStatus}
              </div>
            </div>

            {/* Alert History */}
            <div
              style={{
                background: 'var(--card-bg)',
                border: '1px solid var(--line)',
                borderRadius: '6px',
                padding: '16px'
              }}
            >
              <h4 style={{ margin: '0 0 12px 0', color: 'var(--link)', fontSize: '14px' }}>Alert History</h4>
              <div id="alert-history-container" style={{ minHeight: '48px', fontSize: '12px', color: 'var(--fg)' }}>
                {alerts.length === 0 ? (
                  <span style={{ color: 'var(--fg-muted)' }}>No recent alerts</span>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {alerts.map((alert, idx) => (
                      <div
                        key={idx}
                        style={{
                          padding: '8px',
                          background: 'var(--bg-elev1)',
                          borderRadius: '4px',
                          borderLeft: '3px solid var(--warn)'
                        }}
                      >
                        <div style={{ fontWeight: '600', marginBottom: '4px' }}>
                          {alert.labels?.alertname || 'Alert'}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--fg-muted)' }}>
                          {new Date(alert.startsAt).toLocaleString()}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Query Traces Section */}
      <div className="settings-section" style={{ background: 'var(--panel)', borderLeft: '3px solid var(--link)' }}>
        <h3
          style={{
            fontSize: '16px',
            marginBottom: '16px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px'
          }}
        >
          <span style={{ fontSize: '24px' }}>🔍</span>
          Recent Query Traces
        </h3>
        <p className="small" style={{ color: 'var(--fg-muted)', marginBottom: '16px', lineHeight: '1.6' }}>
          Last 10 search queries with timing and metadata. For detailed analysis, use the dedicated Analytics tab.
        </p>

        {loading ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--fg-muted)' }}>
            Loading traces...
          </div>
        ) : traces.length === 0 ? (
          <div
            style={{
              padding: '40px',
              textAlign: 'center',
              color: 'var(--fg-muted)',
              background: 'var(--card-bg)',
              borderRadius: '8px',
              border: '1px solid var(--line)'
            }}
          >
            No traces available. Queries will appear here after searches are performed.
          </div>
        ) : (
          <div
            style={{
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              borderRadius: '8px',
              overflow: 'hidden'
            }}
          >
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--bg-elev2)', borderBottom: '1px solid var(--line)' }}>
                  <th
                    style={{
                      padding: '12px',
                      textAlign: 'left',
                      fontSize: '11px',
                      fontWeight: '600',
                      color: 'var(--fg-muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px'
                    }}
                  >
                    Timestamp
                  </th>
                  <th
                    style={{
                      padding: '12px',
                      textAlign: 'left',
                      fontSize: '11px',
                      fontWeight: '600',
                      color: 'var(--fg-muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px'
                    }}
                  >
                    Query
                  </th>
                  <th
                    style={{
                      padding: '12px',
                      textAlign: 'left',
                      fontSize: '11px',
                      fontWeight: '600',
                      color: 'var(--fg-muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px'
                    }}
                  >
                    Repo
                  </th>
                  <th
                    style={{
                      padding: '12px',
                      textAlign: 'right',
                      fontSize: '11px',
                      fontWeight: '600',
                      color: 'var(--fg-muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px'
                    }}
                  >
                    Duration
                  </th>
                </tr>
              </thead>
              <tbody>
                {traces.map((trace, idx) => (
                  <tr
                    key={idx}
                    style={{
                      borderBottom: idx < traces.length - 1 ? '1px solid var(--bg-elev2)' : 'none',
                      transition: 'background 0.2s ease'
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'var(--bg-elev1)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'transparent';
                    }}
                  >
                    <td style={{ padding: '12px', fontSize: '11px', color: 'var(--fg-muted)' }}>
                      {new Date(trace.timestamp).toLocaleTimeString()}
                    </td>
                    <td
                      style={{
                        padding: '12px',
                        fontSize: '12px',
                        color: 'var(--fg)',
                        maxWidth: '400px',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                      }}
                      title={trace.query}
                    >
                      {trace.query}
                    </td>
                    <td style={{ padding: '12px', fontSize: '11px', color: 'var(--link)' }}>
                      {trace.repo || 'default'}
                    </td>
                    <td
                      style={{
                        padding: '12px',
                        textAlign: 'right',
                        fontSize: '11px',
                        fontFamily: "'SF Mono', monospace",
                        color: 'var(--ok)'
                      }}
                    >
                      {trace.duration_ms ? `${trace.duration_ms}ms` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Loki Integration Status */}
      <div className="settings-section" style={{ background: 'var(--panel)', borderLeft: '3px solid var(--accent)' }}>
        <h3
          style={{
            fontSize: '16px',
            marginBottom: '16px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px'
          }}
        >
          <span style={{ fontSize: '24px' }}>📊</span>
          Loki Log Aggregation
        </h3>

        {loading ? (
          <div style={{ padding: '20px', color: 'var(--fg-muted)' }}>Loading...</div>
        ) : lokiStatus ? (
          <div
            style={{
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              borderRadius: '6px',
              padding: '16px'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
              <div
                style={{
                  width: '12px',
                  height: '12px',
                  borderRadius: '50%',
                  background: lokiStatus.available ? 'var(--ok)' : 'var(--err)',
                  boxShadow: lokiStatus.available ? '0 0 8px var(--ok)' : '0 0 8px var(--err)'
                }}
              />
              <span style={{ fontSize: '14px', fontWeight: '600' }}>
                Status: {lokiStatus.available ? 'Connected' : 'Disconnected'}
              </span>
            </div>
            {lokiStatus.url && (
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
                Endpoint: <code style={{ color: 'var(--link)' }}>{lokiStatus.url}</code>
              </div>
            )}
            {lokiStatus.error && (
              <div style={{ fontSize: '12px', color: 'var(--err)', marginTop: '8px' }}>
                Error: {lokiStatus.error}
              </div>
            )}
          </div>
        ) : (
          <div style={{ padding: '20px', color: 'var(--fg-muted)' }}>
            Loki status unavailable
          </div>
        )}
      </div>
    </div>
  );
}
