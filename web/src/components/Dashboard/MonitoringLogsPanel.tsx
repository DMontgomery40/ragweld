// AGRO - Monitoring Logs Panel
// Shows recent alerts from Alertmanager webhook

import { useEffect, useState } from 'react';

export function MonitoringLogsPanel() {
  const [alertStatus, setAlertStatus] = useState('Loading...');
  const [alertHistory, setAlertHistory] = useState<any[]>([]);

  const loadAlerts = async () => {
    try {
      const response = await fetch('/webhooks/alertmanager/status');
      if (response.ok) {
        const data = await response.json();
        
        if (data.recent_alerts && data.recent_alerts.length > 0) {
          setAlertStatus(`${data.recent_alerts.length} active alert(s)`);
          setAlertHistory(data.recent_alerts.slice(0, 5));
        } else {
          setAlertStatus('No active alerts');
          setAlertHistory([]);
        }
      } else {
        setAlertStatus('Failed to load');
      }
    } catch (e) {
      setAlertStatus('Monitoring offline');
      setAlertHistory([]);
    }
  };

  useEffect(() => {
    loadAlerts();
    const interval = setInterval(loadAlerts, 60000); // Every minute
    
    const handleRefresh = () => loadAlerts();
    window.addEventListener('dashboard-refresh', handleRefresh);

    return () => {
      clearInterval(interval);
      window.removeEventListener('dashboard-refresh', handleRefresh);
    };
  }, []);

  return (
    <div
      className="settings-section"
      style={{
        background: 'var(--panel)',
        borderLeft: '3px solid var(--warn)',
      }}
    >
      <h3>📜 Monitoring Logs</h3>
      <p className="small" style={{ color: 'var(--fg-muted)', marginBottom: '8px' }}>
        Recent alerts and system notices from Alertmanager webhook log. Full controls are under Analytics.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', alignItems: 'start' }}>
        {/* Recent Alerts */}
        <div
          style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            padding: '12px',
          }}
        >
          <h4 style={{ margin: '0 0 8px 0', color: 'var(--accent)' }}>Recent Alerts</h4>
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
            padding: '12px',
          }}
        >
          <h4 style={{ margin: '0 0 8px 0', color: 'var(--link)' }}>Alert History</h4>
          <div id="alert-history-container" style={{ minHeight: '48px', fontSize: '12px', color: 'var(--fg)' }}>
            {alertHistory.length === 0 ? (
              'No recent alerts'
            ) : (
              <div>
                {alertHistory.map((alert, idx) => (
                  <div key={idx} style={{ marginBottom: '4px' }}>
                    <strong>{alert.labels?.alertname || 'Alert'}</strong>
                    <br />
                    <span style={{ fontSize: '10px', color: 'var(--fg-muted)' }}>
                      {new Date(alert.startsAt).toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

