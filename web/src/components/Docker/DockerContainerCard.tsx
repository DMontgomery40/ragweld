import { useState } from 'react';
import type { DockerContainer as DockerContainerType } from '@web/types';
import { useDockerStore } from '@/stores';

interface DockerContainerCardProps {
  container: DockerContainerType;
}

export function DockerContainerCard({ container }: DockerContainerCardProps) {
  const [logsVisible, setLogsVisible] = useState(false);
  const [logs, setLogs] = useState<string>('');
  const [loadingLogs, setLoadingLogs] = useState(false);

  const {
    startContainer,
    stopContainer,
    pauseContainer,
    unpauseContainer,
    removeContainer,
    getContainerLogs
  } = useDockerStore();

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
    statusIcon = '⏸';
  } else if (isExited) {
    statusColor = 'var(--err)';
    statusIcon = '■';
  }

  const handleToggleLogs = async () => {
    if (!logsVisible) {
      setLogsVisible(true);
      await refreshLogs();
    } else {
      setLogsVisible(false);
    }
  };

  const refreshLogs = async () => {
    setLoadingLogs(true);
    const result = await getContainerLogs(container.id);
    if (result.success) {
      setLogs(result.logs);
    } else {
      setLogs(`Error loading logs: ${result.error}`);
    }
    setLoadingLogs(false);
  };

  const downloadLogs = async () => {
    const result = await getContainerLogs(container.id, 1000);
    if (result.success) {
      const blob = new Blob([result.logs], { type: 'text/plain' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${container.name}-${new Date().toISOString().slice(0,19).replace(/:/g,'-')}.log`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    }
  };

  const formatLogs = (rawLogs: string) => {
    if (!rawLogs) return <span style={{ color: 'var(--fg-muted)' }}>No logs available</span>;

    const lines = rawLogs.split('\n');
    return lines.map((line, i) => {
      if (!line.trim()) return null;

      let color = 'var(--accent)';
      const upperLine = line.toUpperCase();

      if (upperLine.includes('ERROR') || upperLine.includes('FATAL') || upperLine.includes('CRITICAL')) {
        color = 'var(--err)';
      } else if (upperLine.includes('WARN') || upperLine.includes('WARNING')) {
        color = 'var(--warn)';
      } else if (upperLine.includes('INFO')) {
        color = 'var(--link)';
      } else if (upperLine.includes('DEBUG') || upperLine.includes('TRACE')) {
        color = 'var(--fg-muted)';
      }

      return (
        <div key={i} style={{ color, marginBottom: '2px', fontSize: '11px' }}>
          {line}
        </div>
      );
    });
  };

  return (
    <div style={{
      background: 'var(--card-bg)',
      border: '1px solid var(--line)',
      borderRadius: '6px',
      padding: '16px'
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '8px'
      }}>
        <div style={{ fontWeight: 600, color: 'var(--fg)' }}>{container.name}</div>
        <div style={{ fontSize: '10px', color: statusColor }}>
          {statusIcon} {container.state.toUpperCase()}
        </div>
      </div>

      <div style={{
        fontSize: '11px',
        color: 'var(--fg-muted)',
        fontFamily: "'SF Mono', monospace",
        marginBottom: '8px'
      }}>
        {container.image}
      </div>

      {container.ports && (
        <div style={{ fontSize: '10px', color: 'var(--link)', marginBottom: '8px' }}>
          {typeof container.ports === 'string'
            ? container.ports
            : container.ports.map((p: { PrivatePort: number; PublicPort?: number; Type: string }) =>
                `${p.PublicPort ? `${p.PublicPort}:` : ''}${p.PrivatePort}/${p.Type}`
              ).join(', ')
          }
        </div>
      )}

      <div style={{ display: 'flex', gap: '4px', marginTop: '12px' }}>
        {isRunning && (
          <>
            <button
              className="small-button"
              onClick={() => pauseContainer(container.id)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--warn)',
                border: '1px solid var(--warn)',
                padding: '6px',
                fontSize: '10px'
              }}
            >
              ⏸ Pause
            </button>
            <button
              className="small-button"
              onClick={() => stopContainer(container.id)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--err)',
                border: '1px solid var(--err)',
                padding: '6px',
                fontSize: '10px'
              }}
            >
              ■ Stop
            </button>
          </>
        )}
        {isPaused && (
          <>
            <button
              className="small-button"
              onClick={() => unpauseContainer(container.id)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--ok)',
                border: '1px solid var(--ok)',
                padding: '6px',
                fontSize: '10px'
              }}
            >
              ▶ Unpause
            </button>
            <button
              className="small-button"
              onClick={() => stopContainer(container.id)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--err)',
                border: '1px solid var(--err)',
                padding: '6px',
                fontSize: '10px'
              }}
            >
              ■ Stop
            </button>
          </>
        )}
        {isExited && (
          <>
            <button
              className="small-button"
              onClick={() => startContainer(container.id)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--ok)',
                border: '1px solid var(--ok)',
                padding: '6px',
                fontSize: '10px'
              }}
            >
              ▶ Start
            </button>
            <button
              className="small-button"
              onClick={() => removeContainer(container.id)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--err)',
                border: '1px solid var(--err)',
                padding: '6px',
                fontSize: '10px'
              }}
            >
              🗑 Remove
            </button>
          </>
        )}
        <button
          className="small-button"
          onClick={handleToggleLogs}
          style={{
            flex: 1,
            background: 'var(--bg-elev1)',
            color: 'var(--link)',
            border: '1px solid var(--link)',
            padding: '6px',
            fontSize: '10px'
          }}
        >
          📄 Logs {logsVisible ? '▲' : '▼'}
        </button>
      </div>

      {logsVisible && (
        <div style={{
          marginTop: '12px',
          borderTop: '1px solid var(--line)',
          paddingTop: '12px'
        }}>
          <div style={{
            background: 'var(--code-bg)',
            border: '1px solid var(--line)',
            borderRadius: '4px',
            padding: '12px',
            maxHeight: '400px',
            overflowY: 'auto',
            fontFamily: "'SF Mono', Consolas, monospace",
            fontSize: '11px',
            lineHeight: '1.4'
          }}>
            {loadingLogs ? (
              <span style={{ color: 'var(--warn)' }}>Loading logs...</span>
            ) : (
              formatLogs(logs)
            )}
          </div>
          <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
            <button
              className="small-button"
              onClick={refreshLogs}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--link)',
                border: '1px solid var(--link)',
                padding: '6px',
                fontSize: '10px'
              }}
            >
              ↻ Refresh Logs
            </button>
            <button
              className="small-button"
              onClick={downloadLogs}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--ok)',
                border: '1px solid var(--ok)',
                padding: '6px',
                fontSize: '10px'
              }}
            >
              ⬇ Download Full Logs
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
