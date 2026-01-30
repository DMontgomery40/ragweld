import type { DockerStatus } from '@web/types';

interface DockerStatusCardProps {
  status: DockerStatus | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}

export function DockerStatusCard({ status, loading, error, onRefresh }: DockerStatusCardProps) {
  const isRunning = status?.running;

  return (
    <div className="settings-section" style={{ borderLeft: `3px solid ${isRunning ? 'var(--ok)' : 'var(--err)'}` }}>
      <h3>
        <span>🐳</span>
        Docker Status
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
          <p style={{ fontSize: '12px', marginTop: '8px', color: 'var(--fg-muted)' }}>
            Docker daemon may not be running or backend server is offline.
          </p>
        </div>
      )}

      {!error && status && (
        <div className="cost-results">
          <div className="result-item">
            <span className="result-label">Status</span>
            <span
              className="result-value"
              style={{ color: isRunning ? 'var(--ok)' : 'var(--err)' }}
            >
              {isRunning ? '✓ Running' : '✗ Not Running'}
            </span>
          </div>

          {status.runtime && (
            <div className="result-item">
              <span className="result-label">Runtime</span>
              <span className="result-value" style={{ color: 'var(--link)' }}>
                {status.runtime}
              </span>
            </div>
          )}

          <div className="result-item">
            <span className="result-label">Containers</span>
            <span className="result-value" style={{ color: 'var(--warn)' }}>
              {status.containers_count || 0}
            </span>
          </div>
        </div>
      )}

      {!error && !status && !loading && (
        <p style={{ color: 'var(--fg-muted)', fontSize: '14px' }}>
          No Docker data available. Click refresh to check.
        </p>
      )}
    </div>
  );
}
