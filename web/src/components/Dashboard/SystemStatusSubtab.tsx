// AGRO - System Status Subtab
// Real-time system health, status, and quick overview

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import * as DashAPI from '@/api/dashboard';
import { QuickActions } from './QuickActions';
import { IndexDisplayPanels } from './IndexDisplayPanels';
import { useDockerStore } from '@/stores/useDockerStore';
import { StatusIndicator } from '@/components/ui/StatusIndicator';
import { useRepoStore } from '@/stores/useRepoStore';
import { TooltipIcon } from '@/components/ui/TooltipIcon';

export function SystemStatusSubtab() {
  const navigate = useNavigate();
  const [health, setHealth] = useState<string>('—');
  const [mcp, setMcp] = useState<string>('—');
  // const [autotune, setAutotune] = useState<string>('—'); // HIDDEN - Pro feature
  const [containers, setContainers] = useState<string>('—');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [topFolders, setTopFolders] = useState<
    Array<{ name: string; profile?: string; chunkCount: number; storageBytes: number }>
  >([]);

  // Corpus-first state (Zustand store backed by Pydantic `Corpus`)
  const repos = useRepoStore((s) => s.repos);
  const activeRepo = useRepoStore((s) => s.activeRepo);
  const reposInitialized = useRepoStore((s) => s.initialized);
  const reposLoading = useRepoStore((s) => s.loading);
  const loadRepos = useRepoStore((s) => s.loadRepos);

  const corporaDisplay = useMemo(() => {
    const count = Array.isArray(repos) ? repos.length : 0;
    if (count <= 0) return 'No corpora';
    const found = repos.find((r) => r.corpus_id === activeRepo || r.slug === activeRepo || r.name === activeRepo);
    const activeName = String(found?.name || activeRepo || '').trim() || '(unknown)';
    const countLabel = count === 1 ? '1 corpus' : `${count} corpora`;
    return `${activeName} (${countLabel})`;
  }, [repos, activeRepo]);

  // Dev Stack state from Zustand (Pydantic: DevStackStatusResponse)
  const {
    devStackStatus,
    devStackLoading,
    restartingFrontend,
    restartingBackend,
    restartingStack,
    clearingCache,
    fetchDevStackStatus,
    restartFrontend,
    restartBackend,
    restartStack,
    clearCacheAndRestart,
  } = useDockerStore();

  const formatBytes = (bytes: number) => {
    if (!bytes || bytes <= 0) return '0 B';
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
    const idx = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
    const value = bytes / Math.pow(1024, idx);
    return `${value.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
  };

  const refreshStatus = async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch all status data in parallel
      const [
        healthData,
        mcpData,
        // autotuneData, // HIDDEN - Pro feature
        dockerData,
        indexData
      ] = await Promise.allSettled([
        DashAPI.getHealth(),
        DashAPI.getMCPStatus(),
        // DashAPI.getAutotuneStatus(), // HIDDEN - Pro feature
        DashAPI.getDockerStatus(),
        DashAPI.getIndexStatus()
      ]);

      // Health
      if (healthData.status === 'fulfilled') {
        const h = healthData.value;
        setHealth(`${h.status}${h.graph_loaded ? ' (graph ready)' : ''}`);
      }

      if (indexData.status === 'fulfilled' && indexData.value.metadata) {
        // DashboardIndexStatusMetadata does not expose a per-corpus repo breakdown.
        // Keep this empty until the backend provides a deterministic schema.
        setTopFolders([]);
      }

      // MCP
      if (mcpData.status === 'fulfilled') {
        const m = mcpData.value;
        const parts = [];
        if (m.python_http) {
          const ph = m.python_http;
          parts.push(`py-http:${ph.host}:${ph.port} ${ph.running ? '✓' : '✗'}`);
        }
        if (m.node_http) {
          const nh = m.node_http;
          parts.push(`node-http:${nh.host}:${nh.port} ${nh.running ? '✓' : '✗'}`);
        }
        if (m.python_stdio_available !== undefined) {
          parts.push(`py-stdio:${m.python_stdio_available ? 'available' : 'missing'}`);
        }
        setMcp(parts.length > 0 ? parts.join(' | ') : 'unknown');
      }

      // Autotune - HIDDEN (Pro feature, implementing hardware-idle training)
      // if (autotuneData.status === 'fulfilled') {
      //   const a = autotuneData.value;
      //   setAutotune(a.enabled ? (a.current_mode || 'enabled') : 'disabled');
      // } else {
      //   setAutotune('Pro required');
      // }

      // Docker
      if (dockerData.status === 'fulfilled') {
        const d = dockerData.value;
        if (d.available && d.containers) {
          const managed = d.containers.filter((c) => c.agro_managed);
          const total = managed.length;
          const running = managed.filter(c => c.state === 'running').length;
          setContainers(`${running}/${total}`);
        } else {
          setContainers('unavailable');
        }
      }

      setLoading(false);
    } catch (err) {
      console.error('[SystemStatusSubtab] Error refreshing status:', err);
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshStatus();
    fetchDevStackStatus();
    if (!reposInitialized && !reposLoading) {
      loadRepos().catch(() => { /* store owns error state */ });
    }

    // Poll status every 30 seconds
    const interval = setInterval(() => {
      refreshStatus();
      fetchDevStackStatus();
    }, 30000);

    // Listen for manual refresh events
    const handleRefresh = () => {
      refreshStatus();
      fetchDevStackStatus();
    };
    window.addEventListener('dashboard-refresh', handleRefresh);

    return () => {
      clearInterval(interval);
      window.removeEventListener('dashboard-refresh', handleRefresh);
    };
  }, []); // Empty array - run once on mount, Zustand actions are stable

  return (
    <div
      id="tab-dashboard-system"
      className="dashboard-subtab active"
      style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}
    >
      {/* Compact Status + Quick Actions */}
      <div className="settings-section" style={{ background: 'var(--panel)', borderLeft: '3px solid var(--accent)' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: '24px', alignItems: 'start' }}>
          {/* Left: System Status */}
          <div>
            <h3
              style={{
                fontSize: '14px',
                marginBottom: '16px',
                color: 'var(--accent)',
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
              }}
            >
              <span
                style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  background: 'var(--accent)',
                  boxShadow: '0 0 8px var(--accent)'
                }}
              />
              System Status
            </h3>

            {loading && !health ? (
              <div style={{ color: 'var(--fg-muted)', fontSize: '12px', padding: '20px', textAlign: 'center' }}>
                Loading status...
              </div>
            ) : error ? (
              <div style={{ color: 'var(--err)', fontSize: '12px', padding: '20px' }}>
                Error: {error}
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <StatusItem label="Health" value={health} id="dash-health" color="var(--ok)" />
                <StatusItem
                  label={
                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      Corpora <TooltipIcon name="SYS_STATUS_CORPUS" />
                    </span>
                  }
                  value={corporaDisplay}
                  id="dash-corpora"
                  color="var(--fg)"
                />

                <div
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px',
                    padding: '10px 12px',
                    background: 'var(--card-bg)',
                    borderRadius: '4px',
                    border: '1px solid var(--line)'
                  }}
                >
                  <span
                    style={{
                      fontSize: '11px',
                      color: 'var(--fg-muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px'
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => navigate('/infrastructure?subtab=mcp')}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        padding: 0,
                        margin: 0,
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        fontSize: '11px',
                        color: 'var(--fg-muted)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.5px',
                        cursor: 'pointer',
                        textAlign: 'left',
                      }}
                      aria-label="Open Infrastructure MCP Servers"
                    >
                      MCP Servers <TooltipIcon name="SYS_STATUS_MCP_SERVERS" />
                    </button>
                  </span>
                  <div
                    id="dash-mcp"
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px',
                      fontSize: '10px',
                      fontFamily: "'SF Mono', monospace",
                      color: 'var(--link)'
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => navigate('/infrastructure?subtab=mcp')}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        padding: 0,
                        margin: 0,
                        color: 'var(--link)',
                        cursor: 'pointer',
                        textAlign: 'left',
                        fontFamily: "'SF Mono', monospace",
                        fontSize: '10px',
                      }}
                      aria-label="Open Infrastructure MCP Servers"
                    >
                      {mcp}
                    </button>
                  </div>
                </div>

                {/* HIDDEN: Auto-Tune feature - Pro feature. Re-enable when complete. */}
                {/* <StatusItem label="Auto-Tune" value={autotune} id="dash-autotune" color="var(--warn)" /> */}
                <StatusItem
                  label={
                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      Containers <TooltipIcon name="SYS_STATUS_CONTAINERS" />
                    </span>
                  }
                  value={
                    <button
                      type="button"
                      onClick={() => navigate('/infrastructure?subtab=docker')}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        padding: 0,
                        margin: 0,
                        color: 'var(--link)',
                        cursor: 'pointer',
                        fontWeight: 600,
                        fontSize: '12px',
                        fontFamily: "'SF Mono', monospace",
                      }}
                      aria-label="Open Infrastructure Docker Containers"
                    >
                      {containers}
                    </button>
                  }
                  id="dash-containers"
                  color="var(--link)"
                />

                {/* Dev Stack Controls - Pydantic: DevStackStatusResponse */}
                <div
                  className="dev-stack-section"
                  style={{
                    marginTop: '8px',
                    padding: '12px',
                    background: 'var(--card-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '4px',
                    borderLeft: '3px solid var(--link)',
                    transition: 'border-color var(--timing-fast) var(--ease-out), box-shadow var(--timing-fast) var(--ease-out)'
                  }}
                >
                  <span
                    style={{
                      fontSize: '11px',
                      color: 'var(--link)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      marginBottom: '10px'
                    }}
                  >
                    <span
                      style={{
                        width: '6px',
                        height: '6px',
                        borderRadius: '50%',
                        background: 'var(--link)',
                        boxShadow: '0 0 6px var(--link)'
                      }}
                    />
                    Dev Stack
                  </span>

                  {/* Status indicators */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '10px' }}>
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: '11px'
                      }}
                    >
                      <span style={{ color: 'var(--fg-muted)' }}>Frontend</span>
                    <span
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        fontWeight: 600,
                        fontFamily: "'SF Mono', monospace",
                        color: devStackLoading
                          ? 'var(--fg-muted)'
                          : devStackStatus
                            ? (devStackStatus.frontend_running ? 'var(--ok)' : 'var(--err)')
                            : 'var(--fg-muted)',
                      }}
                    >
                      <StatusIndicator
                        status={
                          devStackLoading
                            ? 'loading'
                            : devStackStatus
                              ? (devStackStatus.frontend_running ? 'online' : 'offline')
                              : 'idle'
                        }
                        showLabel={false}
                        size="sm"
                        pulse
                        ariaLabel="Dev frontend status"
                      />
                      {devStackLoading
                        ? 'checking'
                        : devStackStatus
                          ? (devStackStatus.frontend_running ? `running :${devStackStatus.frontend_port}` : 'stopped')
                          : 'unknown'}
                    </span>
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: '11px'
                      }}
                    >
                      <span style={{ color: 'var(--fg-muted)' }}>Backend</span>
                    <span
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        fontWeight: 600,
                        fontFamily: "'SF Mono', monospace",
                        color: devStackLoading
                          ? 'var(--fg-muted)'
                          : devStackStatus
                            ? (devStackStatus.backend_running ? 'var(--ok)' : 'var(--err)')
                            : 'var(--fg-muted)',
                      }}
                    >
                      <StatusIndicator
                        status={
                          devStackLoading
                            ? 'loading'
                            : devStackStatus
                              ? (devStackStatus.backend_running ? 'online' : 'offline')
                              : 'idle'
                        }
                        showLabel={false}
                        size="sm"
                        pulse
                        ariaLabel="Dev backend status"
                      />
                      {devStackLoading
                        ? 'checking'
                        : devStackStatus
                          ? (devStackStatus.backend_running ? `running :${devStackStatus.backend_port}` : 'stopped')
                          : 'unknown'}
                    </span>
                    </div>
                  </div>

                  {/* Restart buttons */}
                  <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                    <button
                      onClick={restartFrontend}
                      disabled={restartingFrontend || restartingStack || clearingCache}
                      className="dev-stack-btn"
                      style={{
                        flex: 1,
                        minWidth: '70px',
                        padding: '6px 8px',
                        background: 'var(--bg-elev2)',
                        color: 'var(--fg)',
                        border: '1px solid var(--line)',
                        borderRadius: '4px',
                        fontSize: '10px',
                        fontWeight: 500,
                        cursor: restartingFrontend || restartingStack || clearingCache ? 'wait' : 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '4px'
                      }}
                    >
                      {restartingFrontend && <span className="loading-spinner" style={{ width: '10px', height: '10px' }} />}
                      ↻ Frontend
                    </button>

                    <button
                      onClick={restartBackend}
                      disabled={restartingBackend || restartingStack || clearingCache}
                      className="dev-stack-btn"
                      style={{
                        flex: 1,
                        minWidth: '70px',
                        padding: '6px 8px',
                        background: 'var(--bg-elev2)',
                        color: 'var(--fg)',
                        border: '1px solid var(--line)',
                        borderRadius: '4px',
                        fontSize: '10px',
                        fontWeight: 500,
                        cursor: restartingBackend || restartingStack || clearingCache ? 'wait' : 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '4px'
                      }}
                    >
                      {restartingBackend && <span className="loading-spinner" style={{ width: '10px', height: '10px' }} />}
                      ↻ Backend
                    </button>

                    <button
                      onClick={restartStack}
                      disabled={restartingFrontend || restartingBackend || restartingStack || clearingCache}
                      className="dev-stack-btn btn-primary"
                      style={{
                        flex: 1,
                        minWidth: '80px',
                        padding: '6px 8px',
                        background: 'var(--accent)',
                        color: 'var(--accent-contrast)',
                        border: 'none',
                        borderRadius: '4px',
                        fontSize: '10px',
                        fontWeight: 600,
                        cursor: restartingFrontend || restartingBackend || restartingStack || clearingCache ? 'wait' : 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '4px'
                      }}
                    >
                      {restartingStack && <span className="loading-spinner" style={{ width: '10px', height: '10px', borderTopColor: 'var(--accent-contrast)' }} />}
                      ↻ Full Stack
                    </button>

                    <button
                      onClick={clearCacheAndRestart}
                      disabled={restartingFrontend || restartingBackend || restartingStack || clearingCache}
                      className="dev-stack-btn"
                      style={{
                        flex: 1,
                        minWidth: '120px',
                        padding: '6px 8px',
                        background: 'var(--warn)',
                        color: 'var(--bg)',
                        border: 'none',
                        borderRadius: '4px',
                        fontSize: '10px',
                        fontWeight: 600,
                        cursor: restartingFrontend || restartingBackend || restartingStack || clearingCache ? 'wait' : 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '4px'
                      }}
                    >
                      {clearingCache && <span className="loading-spinner" style={{ width: '10px', height: '10px', borderTopColor: 'var(--bg)' }} />}
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                        🗑 Clear Bytecode <TooltipIcon name="DEV_STACK_CLEAR_PYTHON_BYTECODE" />
                      </span>
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Manual Refresh Button */}
            <button
              onClick={refreshStatus}
              disabled={loading}
              style={{
                marginTop: '16px',
                width: '100%',
                padding: '8px',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)',
                fontSize: '12px',
                cursor: loading ? 'wait' : 'pointer',
                transition: 'all 0.2s ease'
              }}
            >
              {loading ? 'Refreshing...' : '↻ Refresh Status'}
            </button>
          </div>

          {/* Right: Quick Actions + Index Display */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <QuickActions />
            <div
              style={{
                background: 'var(--panel)',
                borderRadius: '8px',
                border: '1px solid var(--line)',
                padding: '18px',
                boxShadow: '0 15px 35px rgba(0,0,0,0.35)'
              }}
            >
              <IndexDisplayPanels />
            </div>
          </div>
        </div>
      </div>

      {/* Top Accessed Folders Section */}
      <div className="settings-section" style={{ background: 'var(--panel)', borderLeft: '3px solid var(--warn)' }}>
        <h3
          style={{
            fontSize: '14px',
            marginBottom: '16px',
            color: 'var(--warn)',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
          </svg>
          Top Folders (Last 5 Days)
        </h3>
        <div id="dash-top-folders-metrics" style={{ color: 'var(--fg-muted)', fontSize: '12px' }}>
          {topFolders.length === 0 ? (
            <span>No recent indexing metrics available.</span>
          ) : (
            <table
              style={{
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: '12px',
                color: 'var(--fg)'
              }}
            >
              <thead>
                <tr style={{ textTransform: 'uppercase', fontSize: '10px', color: 'var(--fg-muted)' }}>
                  <th style={{ textAlign: 'left', padding: '6px 0' }}>Folder</th>
                  <th style={{ textAlign: 'left', padding: '6px 0' }}>Profile</th>
                  <th style={{ textAlign: 'right', padding: '6px 0' }}>Chunks</th>
                  <th style={{ textAlign: 'right', padding: '6px 0' }}>Storage</th>
                </tr>
              </thead>
              <tbody>
                {topFolders.map(folder => (
                  <tr key={`${folder.profile || 'default'}-${folder.name}`}>
                    <td style={{ padding: '4px 0', fontWeight: 600, color: 'var(--accent)' }}>
                      {folder.name}
                    </td>
                    <td style={{ padding: '4px 0', color: 'var(--fg-muted)' }}>
                      {folder.profile || 'default'}
                    </td>
                    <td style={{ padding: '4px 0', textAlign: 'right', fontFamily: "'SF Mono', monospace" }}>
                      {folder.chunkCount.toLocaleString()}
                    </td>
                    <td style={{ padding: '4px 0', textAlign: 'right', fontFamily: "'SF Mono', monospace" }}>
                      {formatBytes(folder.storageBytes)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

type StatusItemProps = {
  label: ReactNode;
  value: ReactNode;
  id?: string;
  color: string;
};

function StatusItem({ label, value, id, color }: StatusItemProps) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '8px 12px',
        background: 'var(--card-bg)',
        borderRadius: '4px',
        border: '1px solid var(--line)'
      }}
    >
      <span
        style={{
          fontSize: '11px',
          color: 'var(--fg-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.5px'
        }}
      >
        {label}
      </span>
      <span id={id} className="mono" style={{ color, fontWeight: '600', fontSize: '12px' }}>
        {value}
      </span>
    </div>
  );
}
