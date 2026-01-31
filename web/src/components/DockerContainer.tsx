import type { DockerContainer as DockerContainerType } from '@web/types';

interface DockerContainerProps {
  container: DockerContainerType;
  onStart: () => void;
  onStop: () => void;
  onRestart: () => void;
}

export function DockerContainer({ container, onStart, onStop, onRestart }: DockerContainerProps) {
  const isRunning = container.state === 'running';
  const isPaused = container.state === 'paused';
  const isExited = container.state === 'exited';

  let statusColor = 'var(--fg-muted)';
  let statusIcon = '○';
  if (isRunning) {
    statusColor = 'var(--ok)';
    statusIcon = '●';
  } else if (isPaused) {
    statusColor = 'var(--warn)';
    statusIcon = '■';
  } else if (isExited) {
    statusColor = 'var(--err)';
    statusIcon = '✗';
  }

  return (
    <div className="settings-section" style={{ borderLeft: `3px solid ${statusColor}` }}>
      <h3 style={{ fontSize: '14px', marginBottom: '12px' }}>
        <span style={{ color: statusColor, marginRight: '8px' }}>{statusIcon}</span>
        {container.name}
      </h3>

      <div className="cost-results">
        <div className="result-item">
          <span className="result-label">Image</span>
          <span className="result-value" style={{ fontSize: '12px', color: 'var(--fg)' }}>
            {container.image}
          </span>
        </div>

        <div className="result-item">
          <span className="result-label">Status</span>
          <span className="result-value" style={{ fontSize: '12px', color: statusColor }}>
            {container.state}
          </span>
        </div>

        {container.ports && (
          <div className="result-item">
            <span className="result-label">Ports</span>
            <span className="result-value" style={{ fontSize: '11px', color: 'var(--link)' }}>
              {typeof container.ports === 'string'
                ? container.ports
                : container.ports.map((p: { PrivatePort: number; PublicPort?: number; Type: string }) =>
                    p.PublicPort ? `${p.PublicPort}:${p.PrivatePort}` : String(p.PrivatePort)
                  ).join(', ')
              }
            </span>
          </div>
        )}

        <div className="result-item">
          <span className="result-label">Container ID</span>
          <span className="result-value" style={{ fontSize: '10px', fontFamily: 'monospace', color: 'var(--fg-muted)' }}>
            {container.id.substring(0, 12)}
          </span>
        </div>
      </div>

      <div className="action-buttons" style={{ marginTop: '12px', gap: '8px' }}>
        {!isRunning && (
          <button onClick={onStart} style={{ fontSize: '12px', padding: '6px 12px' }}>
            ▶ Start
          </button>
        )}
        {isRunning && (
          <button onClick={onStop} style={{ fontSize: '12px', padding: '6px 12px' }}>
            ■ Stop
          </button>
        )}
        <button onClick={onRestart} style={{ fontSize: '12px', padding: '6px 12px' }}>
          🔄 Restart
        </button>
      </div>
    </div>
  );
}
