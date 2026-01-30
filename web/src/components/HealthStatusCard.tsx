import type { HealthStatus } from '@web/types';

interface HealthStatusCardProps {
  status: HealthStatus | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}

export function HealthStatusCard({ status, loading, error, onRefresh }: HealthStatusCardProps) {
  const isHealthy = status?.ok || status?.status === 'healthy';

  return (
    <div className="settings-section" style={{ borderLeft: `3px solid ${isHealthy ? 'var(--ok)' : 'var(--err)'}` }}>
      <h3>
        <span>🏥</span>
        System Health
        <button
          onClick={onRefresh}
          disabled={loading}
          className="small-button"
          style={{ marginLeft: 'auto', width: 'auto', marginTop: 0 }}
        >
          {loading ? 'Checking...' : 'Refresh'}
        </button>
      </h3>

      {error && (
        <div style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--err)',
          borderRadius: '6px',
          padding: '12px',
          marginBottom: '12px',
          color: 'var(--err)'
        }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {!error && status && (
        <div className="cost-results">
          <div className="result-item">
            <span className="result-label">Status</span>
            <span
              className="result-value"
              style={{ color: isHealthy ? 'var(--ok)' : 'var(--err)' }}
            >
              {isHealthy ? '✓ Healthy' : '✗ Unhealthy'}
            </span>
          </div>

          {status.ts && (
            <div className="result-item">
              <span className="result-label">Last Check</span>
              <span className="result-value" style={{ color: 'var(--fg-muted)', fontSize: '12px' }}>
                {new Date(status.ts).toLocaleString()}
              </span>
            </div>
          )}
        </div>
      )}

      {!error && !status && !loading && (
        <p style={{ color: 'var(--fg-muted)', fontSize: '14px' }}>
          No health data available. Click refresh to check.
        </p>
      )}
    </div>
  );
}
