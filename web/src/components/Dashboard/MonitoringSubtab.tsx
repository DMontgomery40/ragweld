// TriBridRAG - Monitoring Subtab
// Logs, alerts, traces, and performance monitoring

import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import * as DashAPI from '@/api/dashboard';

const MONITORING_PATH = '/infrastructure?subtab=monitoring';

function alertTone(alert: DashAPI.AlertmanagerAlert): string {
  if (alert.silenced || alert.inhibited) return 'var(--fg-muted)';
  const severity = String(alert.severity || '').toLowerCase();
  if (severity === 'critical' || severity === 'page') return 'var(--err)';
  if (severity === 'warning') return 'var(--warn)';
  return 'var(--link)';
}

export function MonitoringSubtab() {
  const navigate = useNavigate();
  const [alertsResponse, setAlertsResponse] = useState<DashAPI.AlertmanagerAlertsResponse | null>(null);
  const [alertsError, setAlertsError] = useState<DashAPI.AlertsViewError | null>(null);
  const [traces, setTraces] = useState<DashAPI.Trace[]>([]);
  const [lokiStatus, setLokiStatus] = useState<DashAPI.LokiStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const loadMonitoringData = async () => {
    setLoading(true);

    try {
      // Load all monitoring data in parallel
      const [alertData, traceData, lokiData] = await Promise.allSettled([
        DashAPI.getAlertmanagerAlerts(),
        DashAPI.getTraces(10),
        DashAPI.getLokiStatus()
      ]);

      // Alerts: Alertmanager's own answer, or its own reason for not answering.
      if (alertData.status === 'fulfilled') {
        setAlertsResponse(alertData.value);
        setAlertsError(null);
      } else {
        setAlertsResponse(null);
        setAlertsError(DashAPI.toAlertsViewError(alertData.reason));
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
      {/* Alertmanager Section */}
      <div
        className="settings-section"
        data-testid="dash-alerts-panel"
        style={{ background: 'var(--panel)', borderLeft: '3px solid var(--warn)' }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px', flexWrap: 'wrap', marginBottom: '8px' }}>
          <h3 style={{ fontSize: '16px', margin: 0 }}>Alerts</h3>
          {alertsResponse ? (
            <span style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
              {alertsResponse.firing_count} firing of {alertsResponse.total_count} held by Alertmanager
            </span>
          ) : null}
        </div>
        <p className="small" style={{ color: 'var(--fg-muted)', marginBottom: '16px', lineHeight: '1.6', fontSize: '13px' }}>
          Read live from Alertmanager on every refresh.{' '}
          <button
            type="button"
            onClick={() => navigate(MONITORING_PATH)}
            data-testid="dash-alerts-monitoring-link"
            style={{
              background: 'none',
              border: 'none',
              padding: 0,
              font: 'inherit',
              color: 'var(--link)',
              textDecoration: 'underline',
              cursor: 'pointer'
            }}
          >
            Full controls are under Infrastructure - Monitoring
          </button>
          .
        </p>

        {loading ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--fg-muted)', fontSize: '14px' }}>
            Loading alerts...
          </div>
        ) : alertsError ? (
          <div
            data-testid="dash-alerts-error"
            style={{
              background: 'var(--card-bg)',
              border: '1px solid var(--err)',
              borderRadius: '6px',
              padding: '16px',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px'
            }}
          >
            <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--err)' }}>
              {alertsError.status ? `Alerts unavailable (HTTP ${alertsError.status})` : 'Alerts unavailable'}
            </div>
            <div style={{ fontSize: '13px', color: 'var(--fg)', lineHeight: 1.6 }}>{alertsError.message}</div>
            {alertsError.operatorHint ? (
              <div style={{ fontSize: '12.5px', color: 'var(--fg-muted)', lineHeight: 1.6 }}>
                {alertsError.operatorHint}
              </div>
            ) : null}
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              <button
                type="button"
                className="btn"
                data-testid="dash-alerts-retry"
                onClick={() => void loadMonitoringData()}
                style={{ fontSize: '13px' }}
              >
                Retry
              </button>
              <button
                type="button"
                className="btn"
                data-testid="dash-alerts-error-monitoring-link"
                onClick={() => navigate(alertsError.monitoringPath)}
                style={{ fontSize: '13px' }}
              >
                Open Infrastructure - Monitoring
              </button>
            </div>
          </div>
        ) : (alertsResponse?.alerts?.length ?? 0) === 0 ? (
          <div
            data-testid="dash-alerts-empty"
            style={{
              padding: '24px',
              textAlign: 'center',
              fontSize: '14px',
              color: 'var(--fg-muted)',
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              borderRadius: '6px'
            }}
          >
            No alerts are firing. Alertmanager at <code style={{ color: 'var(--link)' }}>{alertsResponse?.source_url}</code> is holding none.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {(alertsResponse?.alerts ?? []).map((alert) => (
              <div
                key={alert.fingerprint}
                data-testid="dash-alert-row"
                style={{
                  background: 'var(--card-bg)',
                  border: '1px solid var(--line)',
                  borderLeft: `3px solid ${alertTone(alert)}`,
                  borderRadius: '6px',
                  padding: '12px 14px'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--fg)' }}>{alert.name}</span>
                  <span style={{ fontSize: '11.5px', color: alertTone(alert), textTransform: 'uppercase', letterSpacing: '0.4px' }}>
                    {alert.severity}
                  </span>
                  {alert.silenced ? (
                    <span style={{ fontSize: '11.5px', color: 'var(--fg-muted)' }}>silenced</span>
                  ) : null}
                  {alert.inhibited ? (
                    <span style={{ fontSize: '11.5px', color: 'var(--fg-muted)' }}>inhibited</span>
                  ) : null}
                </div>
                {alert.summary ? (
                  <div style={{ fontSize: '13px', color: 'var(--fg)', marginTop: '6px', lineHeight: 1.55 }}>{alert.summary}</div>
                ) : null}
                {alert.description ? (
                  <div style={{ fontSize: '12.5px', color: 'var(--fg-muted)', marginTop: '4px', lineHeight: 1.55 }}>
                    {alert.description}
                  </div>
                ) : null}
                <div style={{ fontSize: '11.5px', color: 'var(--fg-muted)', marginTop: '8px' }}>
                  Firing since {new Date(alert.starts_at).toLocaleString()}
                </div>
              </div>
            ))}
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
          Recent Query Traces
        </h3>
        <p className="small" style={{ color: 'var(--fg-muted)', marginBottom: '16px', lineHeight: '1.6' }}>
          The last 10 search and chat queries. For detailed analysis, use the dedicated Analytics tab.
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
                      fontSize: '11.5px',
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
                      fontSize: '11.5px',
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
                      fontSize: '11.5px',
                      fontWeight: '600',
                      color: 'var(--fg-muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px'
                    }}
                  >
                    Repo
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
                    <td style={{ padding: '12px', fontSize: '11.5px', color: 'var(--fg-muted)', whiteSpace: 'nowrap' }}>
                      {/* Date + time, not time alone: these rows span more than one day and a
                          bare "6:33:18 AM" made the list look like it ran backwards (M-140). */}
                      {new Date(trace.timestamp).toLocaleString()}
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
                    <td style={{ padding: '12px', fontSize: '11.5px', color: 'var(--link)' }}>
                      {trace.repo || 'default'}
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
                  background: lokiStatus.reachable ? 'var(--ok)' : 'var(--err)',
                  boxShadow: lokiStatus.reachable ? '0 0 8px var(--ok)' : '0 0 8px var(--err)'
                }}
              />
              <span style={{ fontSize: '14px', fontWeight: '600' }}>
                Status: {lokiStatus.reachable ? 'Connected' : 'Disconnected'}
              </span>
            </div>
            {lokiStatus.url && (
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
                Endpoint: <code style={{ color: 'var(--link)' }}>{lokiStatus.url}</code>
              </div>
            )}
            {!lokiStatus.reachable && (
              <div style={{ fontSize: '12px', color: 'var(--err)', marginTop: '8px' }}>
                Detail: {lokiStatus.status}
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
