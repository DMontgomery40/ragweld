// AGRO - System Status Subtab
// Real-time system health, status, and quick overview

import { useState, useEffect } from 'react';
import * as DashAPI from '@/api/dashboard';
import { QuickActions } from './QuickActions';
import { IndexDisplayPanels } from './IndexDisplayPanels';
import { useDockerStore } from '@/stores/useDockerStore';

export function SystemStatusSubtab() {
  const [health, setHealth] = useState<string>('—');
  const [repo, setRepo] = useState<string>('—');
  const [branch, setBranch] = useState<string>('—');
  const [chunkSummaries, setChunkSummaries] = useState<string>('—');
  const [mcp, setMcp] = useState<string>('—');
  // const [autotune, setAutotune] = useState<string>('—'); // HIDDEN - Pro feature
  const [docker, setDocker] = useState<string>('—');
  const [gitHooks, setGitHooks] = useState<string>('—');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [topFolders, setTopFolders] = useState<
    Array<{ name: string; profile?: string; chunkCount: number; storageBytes: number }>
  >([]);

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
        configData,
        cardsData,
        mcpData,
        // autotuneData, // HIDDEN - Pro feature
        dockerData,
        gitData,
        indexData
      ] = await Promise.allSettled([
        DashAPI.getHealth(),
        DashAPI.getConfig(),
        DashAPI.getCards(),
        DashAPI.getMCPStatus(),
        // DashAPI.getAutotuneStatus(), // HIDDEN - Pro feature
        DashAPI.getDockerStatus(),
        DashAPI.getGitHookStatus(),
        DashAPI.getIndexStatus()
      ]);

      // Health
      if (healthData.status === 'fulfilled') {
        const h = healthData.value;
        setHealth(`${h.status}${h.graph_loaded ? ' (graph ready)' : ''}`);
      }

      // Config (repo, branch)
      if (configData.status === 'fulfilled') {
        const c = configData.value;
        const repoName = (c.env?.REPO || c.default_repo || '(none)');
        const reposCount = (c.repos || []).length;
        setRepo(`${repoName} (${reposCount} repos)`);
        const branchName = c.env?.GIT_BRANCH || c.env?.BRANCH || c.git_branch;
        if (branchName) {
          setBranch(branchName);
        }
      }

      if (indexData.status === 'fulfilled' && indexData.value.metadata) {
        const metadata = indexData.value.metadata;
        if (metadata.current_branch) {
          setBranch(metadata.current_branch);
        }

        if (metadata.repos && metadata.repos.length > 0) {
          const sortedByActivity = metadata.repos
            .map(repo => {
              const chunkCount = repo.chunk_count || 0;
              const storageBytes =
                (repo.sizes?.chunks || 0) + (repo.sizes?.bm25 || 0) + (repo.sizes?.cards || 0);
              return {
                name: repo.name,
                profile: repo.profile,
                chunkCount,
                storageBytes
              };
            })
            .sort((a, b) => {
              if (b.chunkCount === a.chunkCount) {
                return b.storageBytes - a.storageBytes;
              }
              return b.chunkCount - a.chunkCount;
            })
            .slice(0, 5);

          setTopFolders(sortedByActivity);
        } else {
          setTopFolders([]);
        }
      }

      // Chunk Summaries (formerly "cards")
      if (cardsData.status === 'fulfilled') {
        const summaryCount = cardsData.value.count || 0;
        setChunkSummaries(`${summaryCount} summaries`);
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
          const running = d.containers.filter(c => c.state === 'running').length;
          setDocker(`${running}/${d.containers.length} running`);
        } else {
          setDocker('unavailable');
        }
      }

      // Git Hooks
      if (gitData.status === 'fulfilled') {
        const g = gitData.value;
        setGitHooks(g.installed ? `installed (${g.hooks?.length || 0})` : 'not installed');
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
                <StatusItem label="Corpus" value={repo} id="dash-repo" color="var(--fg)" />
                <StatusItem label="Branch" value={branch} id="dash-branch" color="var(--link)" />
                <StatusItem label="Summaries" value={chunkSummaries} id="dash-summaries" color="var(--link)" />

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
                    MCP Servers
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
                    <span>{mcp}</span>
                  </div>
                </div>

                {/* HIDDEN: Auto-Tune feature - Pro feature, implementing hardware-idle training detection
                    Backend stub remains at /api/autotune/status for future implementation
                    Re-enable when feature is complete */}
                {/* <StatusItem label="Auto-Tune" value={autotune} id="dash-autotune" color="var(--warn)" /> */}
                <StatusItem label="Docker" value={docker} id="dash-docker" color="var(--link)" />
                <StatusItem label="Git Hooks" value={gitHooks} id="dash-git-hooks" color="var(--ok)" />

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
                        className={devStackStatus?.frontend_running ? 'status-running' : 'status-stopped'}
                        style={{
                          color: devStackStatus?.frontend_running ? 'var(--ok)' : 'var(--err)',
                          fontWeight: 600,
                          fontFamily: "'SF Mono', monospace"
                        }}
                      >
                        {devStackLoading ? '...' : devStackStatus?.frontend_running ? `running :${devStackStatus.frontend_port}` : 'stopped'}
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
                        className={devStackStatus?.backend_running ? 'status-running' : 'status-stopped'}
                        style={{
                          color: devStackStatus?.backend_running ? 'var(--ok)' : 'var(--err)',
                          fontWeight: 600,
                          fontFamily: "'SF Mono', monospace"
                        }}
                      >
                        {devStackLoading ? '...' : devStackStatus?.backend_running ? `running :${devStackStatus.backend_port}` : 'stopped'}
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
                      title="Clear Python bytecode cache (__pycache__, .pyc) and restart backend"
                      style={{
                        flex: 1,
                        minWidth: '90px',
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
                      🗑 Clear Cache
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

interface StatusItemProps {
  label: string;
  value: string;
  id?: string;
  color: string;
}

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
