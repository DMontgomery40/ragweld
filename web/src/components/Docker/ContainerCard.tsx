/**
 * Container Card Component
 * Displays Docker container status with action buttons and collapsible logs
 */

import React from 'react';
import type { DockerContainer } from '@web/types';

interface ContainerCardProps {
  container: DockerContainer;
  isLogsExpanded: boolean;
  logs: string;
  isLoadingLogs: boolean;
  onToggleLogs: (id: string) => void;
  onRefreshLogs: (id: string) => void;
  onDownloadLogs: (id: string, name: string) => void;
  onStart: (id: string) => void;
  onStop: (id: string) => void;
  onPause: (id: string) => void;
  onUnpause: (id: string) => void;
  onRemove: (id: string) => void;
}

/**
 * Format and colorize log lines
 */
function formatLogs(rawLogs: string): React.ReactNode {
  if (!rawLogs || rawLogs.trim() === '') {
    return <span style={{ color: 'var(--fg-muted)' }}>No logs available</span>;
  }

  const lines = rawLogs.split('\n');

  return (
    <>
      {lines.map((line, index) => {
        if (!line.trim()) return null;

        // Try to extract timestamp
        let timestamp = '';
        let logContent = line;

        // ISO timestamp pattern
        const isoMatch = line.match(/^(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)/);
        if (isoMatch) {
          const date = new Date(isoMatch[1]);
          timestamp = date.toLocaleString('en-US', {
            hour12: false,
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
          });
          logContent = line.substring(isoMatch[0].length).trim();
        }
        // Docker timestamp pattern
        else if (line.match(/^\[?\d{4}-\d{2}-\d{2}/)) {
          const parts = line.split(/\s+/, 2);
          timestamp = parts[0].replace(/[\[\]]/g, '');
          logContent = line.substring(parts[0].length).trim();
        }

        // Determine color based on log level
        let color = 'var(--accent)'; // default green
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
          <div key={index} style={{ color, marginBottom: '2px' }}>
            {timestamp && (
              <span style={{ color: 'var(--fg-muted)' }}>[{timestamp}] </span>
            )}
            {logContent}
          </div>
        );
      })}
    </>
  );
}

/**
 * Format port mappings for display
 */
function formatPorts(container: DockerContainer): string {
  if (!container.ports || container.ports.length === 0) {
    return '';
  }

  return container.ports
    .map(p => {
      if (p.PublicPort) {
        return `${p.PublicPort}:${p.PrivatePort}/${p.Type}`;
      }
      return `${p.PrivatePort}/${p.Type}`;
    })
    .join(', ');
}

export function ContainerCard({
  container,
  isLogsExpanded,
  logs,
  isLoadingLogs,
  onToggleLogs,
  onRefreshLogs,
  onDownloadLogs,
  onStart,
  onStop,
  onPause,
  onUnpause,
  onRemove,
}: ContainerCardProps) {
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

  const ports = formatPorts(container);

  return (
    <div
      style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '16px',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '8px',
        }}
      >
        <div style={{ fontWeight: 600, color: 'var(--fg)' }}>{container.name}</div>
        <div style={{ fontSize: '10px', color: statusColor }}>
          {statusIcon} {container.state.toUpperCase()}
        </div>
      </div>

      {/* Image */}
      <div
        style={{
          fontSize: '11px',
          color: 'var(--fg-muted)',
          fontFamily: "'SF Mono', monospace",
          marginBottom: '8px',
        }}
      >
        {container.image}
      </div>

      {/* Ports */}
      {ports && (
        <div style={{ fontSize: '10px', color: 'var(--link)', marginBottom: '8px' }}>
          {ports}
        </div>
      )}

      {/* Action Buttons */}
      <div style={{ display: 'flex', gap: '4px', marginTop: '12px' }}>
        {isRunning && (
          <>
            <button
              className="small-button"
              onClick={() => onPause(container.id)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--warn)',
                border: '1px solid var(--warn)',
                padding: '6px',
                fontSize: '10px',
              }}
            >
              ⏸ Pause
            </button>
            <button
              className="small-button"
              onClick={() => onStop(container.id)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--err)',
                border: '1px solid var(--err)',
                padding: '6px',
                fontSize: '10px',
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
              onClick={() => onUnpause(container.id)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--ok)',
                border: '1px solid var(--ok)',
                padding: '6px',
                fontSize: '10px',
              }}
            >
              ▶ Unpause
            </button>
            <button
              className="small-button"
              onClick={() => onStop(container.id)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--err)',
                border: '1px solid var(--err)',
                padding: '6px',
                fontSize: '10px',
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
              onClick={() => onStart(container.id)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--ok)',
                border: '1px solid var(--ok)',
                padding: '6px',
                fontSize: '10px',
              }}
            >
              ▶ Start
            </button>
            <button
              className="small-button"
              onClick={() => onRemove(container.id)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--err)',
                border: '1px solid var(--err)',
                padding: '6px',
                fontSize: '10px',
              }}
            >
              🗑 Remove
            </button>
          </>
        )}

        <button
          className="small-button"
          onClick={() => onToggleLogs(container.id)}
          style={{
            flex: 1,
            background: 'var(--bg-elev1)',
            color: 'var(--link)',
            border: '1px solid var(--link)',
            padding: '6px',
            fontSize: '10px',
          }}
        >
          📄 Logs {isLogsExpanded ? '▲' : '▼'}
        </button>
      </div>

      {/* Collapsible Logs Section */}
      {isLogsExpanded && (
        <div
          style={{
            marginTop: '12px',
            borderTop: '1px solid var(--line)',
            paddingTop: '12px',
          }}
        >
          <div
            style={{
              background: 'var(--code-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              padding: '12px',
              maxHeight: '400px',
              overflowY: 'auto',
              fontFamily: "'SF Mono', Consolas, monospace",
              fontSize: '11px',
              lineHeight: '1.4',
            }}
          >
            <div style={{ color: 'var(--code-fg)' }}>
              {isLoadingLogs ? (
                <span style={{ color: 'var(--warn)' }}>Loading logs...</span>
              ) : (
                formatLogs(logs)
              )}
            </div>
          </div>

          {/* Log Action Buttons */}
          <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
            <button
              className="small-button"
              onClick={() => onRefreshLogs(container.id)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--link)',
                border: '1px solid var(--link)',
                padding: '6px',
                fontSize: '10px',
              }}
            >
              ↻ Refresh Logs
            </button>
            <button
              className="small-button"
              onClick={() => onDownloadLogs(container.id, container.name)}
              style={{
                flex: 1,
                background: 'var(--bg-elev1)',
                color: 'var(--ok)',
                border: '1px solid var(--ok)',
                padding: '6px',
                fontSize: '10px',
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
