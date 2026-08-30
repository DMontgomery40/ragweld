// TriBridRAG - System Status Subtab
// Real-time system health, status, and quick overview

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import * as DashAPI from '@/api/dashboard';
import { QuickActions } from './QuickActions';
import { IndexDisplayPanels } from './IndexDisplayPanels';
import { useDockerStore } from '@/stores/useDockerStore';
import { StatusIndicator } from '@/components/ui/StatusIndicator';
import { useRepoStore } from '@/stores/useRepoStore';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import type { IndexRunSummary } from '@/types/generated';

export function SystemStatusSubtab() {
  const navigate = useNavigate();
  const [health, setHealth] = useState<string>('—');
  const [mcp, setMcp] = useState<string>('—');
  // const [autotune, setAutotune] = useState<string>('—'); // HIDDEN - Pro feature
  const [containers, setContainers] = useState<string>('—');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // One row per corpus: its latest persisted run, "never indexed" (404), or why it could not
  // be read. `run: null` and `error` are different answers and the panel says which.
  const [recentRuns, setRecentRuns] = useState<
    Array<{ corpusId: string; name: string; run: IndexRunSummary | null; error: string | null }>
  >([]);
  const [recentRunsLoading, setRecentRunsLoading] = useState(false);
  // Guards the fan-out against out-of-order settles; see refreshRecentRuns.
  const recentRunsGenerationRef = useRef(0);

  // Corpus-first state (Zustand store backed by Pydantic `Corpus`)
  const repos = useRepoStore((s) => s.repos);
  const activeRepo = useRepoStore((s) => s.activeRepo);
  const reposInitialized = useRepoStore((s) => s.initialized);
  const reposLoading = useRepoStore((s) => s.loading);
  const reposError = useRepoStore((s) => s.error);
  const loadRepos = useRepoStore((s) => s.loadRepos);

  const corporaInfo = useMemo(() => {
    const count = Array.isArray(repos) ? repos.length : 0;
    const found = repos.find((r) => r.corpus_id === activeRepo || r.slug === activeRepo || r.name === activeRepo);
    const activeName = String(found?.name || activeRepo || '').trim() || '(none)';
    const activeDisplay =
      found && found.name && String(found.name).trim() && String(found.name).trim() !== String(activeRepo || '').trim()
        ? `${found.name} (${activeRepo})`
        : activeName;
    const totalLabel = count === 1 ? '1 corpus' : `${count} corpora`;
    return { count, totalLabel, activeDisplay };
  }, [repos, activeRepo]);

  // Dev Stack state from Zustand (Pydantic: DevStackStatusResponse)
  const {
    devStackStatus,
    devStackLoading,
    fetchDevStackStatus,
  } = useDockerStore();

  const refreshStatus = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch all status data in parallel
      const [
        healthData,
        mcpData,
        // autotuneData, // HIDDEN - Pro feature
        dockerData
      ] = await Promise.allSettled([
        DashAPI.getHealth(),
        DashAPI.getMCPStatus(),
        // DashAPI.getAutotuneStatus(), // HIDDEN - Pro feature
        DashAPI.getDockerStatus()
      ]);

      // Health
      if (healthData.status === 'fulfilled') {
        const h = healthData.value;
        setHealth(`${h.status}`);
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
        if (d.status.running) {
          if (d.inventoryAvailable) {
            const managed = d.containers.filter((c) => c.managed);
            const total = managed.length;
            const running = managed.filter((c) => c.state === 'running').length;
            setContainers(`${running}/${total}`);
          } else {
            setContainers('inventory unavailable');
          }
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
  }, []);

  /**
   * The latest run of every corpus, one request each, in parallel.
   *
   * Deliberately NOT on the 30s status poll: nothing here changes without an indexing run,
   * and N corpora x every 30 seconds is real load against an endpoint that flushes the run
   * event queue. Mount and the explicit refresh action are enough.
   */
  const refreshRecentRuns = useCallback(async () => {
    // Each fan-out claims a generation; only the newest one may publish. Corpus count varies
    // and every request is a separate round trip, so an earlier slow fan-out can settle after
    // a later fast one and repaint the panel with what the corpus list used to be.
    const generation = recentRunsGenerationRef.current + 1;
    recentRunsGenerationRef.current = generation;

    const corpora = Array.isArray(repos) ? repos : [];
    if (corpora.length === 0) {
      setRecentRuns([]);
      setRecentRunsLoading(false);
      return;
    }
    setRecentRunsLoading(true);
    const settled = await Promise.allSettled(
      corpora.map((corpus) => DashAPI.getLatestIndexRun(corpus.corpus_id))
    );
    if (recentRunsGenerationRef.current !== generation) return;
    setRecentRuns(
      corpora.map((corpus, i) => {
        const outcome = settled[i];
        return {
          corpusId: corpus.corpus_id,
          name: String(corpus.name || corpus.corpus_id),
          run: outcome.status === 'fulfilled' ? outcome.value : null,
          error:
            outcome.status === 'rejected'
              ? outcome.reason instanceof Error
                ? outcome.reason.message
                : String(outcome.reason)
              : null,
        };
      })
    );
    setRecentRunsLoading(false);
  }, [repos]);

  useEffect(() => {
    refreshRecentRuns();
    const handleRefresh = () => {
      refreshRecentRuns();
    };
    window.addEventListener('dashboard-refresh', handleRefresh);
    return () => {
      window.removeEventListener('dashboard-refresh', handleRefresh);
    };
  }, [refreshRecentRuns]);

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
  }, [fetchDevStackStatus, loadRepos, refreshStatus, reposInitialized, reposLoading]);

  // If the dashboard mounted while the backend was down, `loadRepos()` can fail and the store
  // intentionally marks itself initialized to avoid retry loops. When the backend comes back,
  // retry once so the rest of the dashboard (index stats, active corpus display) can recover.
  useEffect(() => {
    if (reposLoading) return;
    if (!reposError) return;
    if (!devStackStatus?.backend_running) return;
    loadRepos().catch(() => {
      /* store owns error state */
    });
  }, [reposLoading, reposError, devStackStatus?.backend_running, loadRepos]);

  return (
    <div
      id="tab-dashboard-system"
      className="dashboard-subtab active"
      style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}
    >
      {/* Compact Status + Quick Actions */}
      <div className="settings-section" style={{ background: 'var(--panel)', borderLeft: '3px solid var(--accent)' }}>
        <div className="dashboard-grid">
          {/* Left: System Status */}
          <div>
            <h3
              style={{
                fontSize: '14px',
                marginBottom: '16px',
                color: 'var(--accent-text)',
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
                      Active corpus <TooltipIcon name="SYS_STATUS_CORPUS" />
                    </span>
                  }
                  value={corporaInfo.activeDisplay}
                  id="dash-active-corpus"
                  color="var(--fg)"
                />
                <StatusItem
                  label={
                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      Total corpora <TooltipIcon name="SYS_STATUS_CORPUS" />
                    </span>
                  }
                  value={corporaInfo.totalLabel}
                  id="dash-total-corpora"
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
                    Local Runtime
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

      {/* Recent index runs: the latest persisted run of every corpus */}
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
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3 2" />
          </svg>
          Recent Index Runs
        </h3>
        <div data-testid="dash-recent-runs" style={{ color: 'var(--fg-muted)', fontSize: '12px' }}>
          {recentRuns.length === 0 ? (
            <span>{recentRunsLoading ? 'Loading index runs…' : 'No corpora yet.'}</span>
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
                {/* 11.5px, not the 10px the deleted panel used: the operator's displays are
                    dpr-1 at ~93 PPI, where 10px uppercase muted text is the exact combination
                    that turns into grey mush. The legibility floor outranks style parity. */}
                <tr style={{ textTransform: 'uppercase', fontSize: '11.5px', color: 'var(--fg-muted)' }}>
                  <th style={{ textAlign: 'left', padding: '6px 0' }}>Corpus</th>
                  <th style={{ textAlign: 'left', padding: '6px 0' }}>Status</th>
                  <th style={{ textAlign: 'left', padding: '6px 0' }}>Completed</th>
                  <th style={{ textAlign: 'right', padding: '6px 0' }}>Chunks</th>
                  <th style={{ textAlign: 'right', padding: '6px 0' }}>Figures</th>
                  <th style={{ textAlign: 'right', padding: '6px 0' }}>Cost</th>
                </tr>
              </thead>
              <tbody>
                {recentRuns.map((row) => (
                  <tr key={row.corpusId} data-testid={`dash-recent-run-${row.corpusId}`}>
                    <td style={{ padding: '4px 0', fontWeight: 600, color: 'var(--accent-text)' }}>{row.name}</td>
                    <td style={{ padding: '4px 0', color: runStatusColor(row) }}>{runStatusLabel(row)}</td>
                    <td style={{ padding: '4px 0', color: 'var(--fg-muted)' }}>
                      {row.run?.completed_at ? new Date(row.run.completed_at).toLocaleString() : '—'}
                    </td>
                    <td style={{ padding: '4px 0', textAlign: 'right', fontFamily: "'SF Mono', monospace" }}>
                      {row.run ? Number(row.run.total_chunks || 0).toLocaleString() : '—'}
                    </td>
                    <td style={{ padding: '4px 0', textAlign: 'right', fontFamily: "'SF Mono', monospace" }}>
                      {formatRunFigures(row.run)}
                    </td>
                    <td style={{ padding: '4px 0', textAlign: 'right', fontFamily: "'SF Mono', monospace" }}>
                      {row.run?.figure_description_cost_usd != null
                        ? `\u2264 $${Number(row.run.figure_description_cost_usd).toFixed(4)}`
                        : '\u2014'}
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

type RecentRunRow = { corpusId: string; name: string; run: IndexRunSummary | null; error: string | null };

/** "never indexed" (no run) and "could not be read" (request failed) are different answers. */
function runStatusLabel(row: RecentRunRow): string {
  if (row.error) return 'unavailable';
  if (!row.run) return 'never indexed';
  return String(row.run.status || 'unknown');
}

function runStatusColor(row: RecentRunRow): string {
  if (row.error) return 'var(--err)';
  if (!row.run) return 'var(--fg-muted)';
  if (row.run.status === 'complete') return 'var(--ok)';
  if (row.run.status === 'error') return 'var(--err)';
  return 'var(--warn)';
}

/**
 * Figures are shown only when the run actually had a figure phase: every corpus indexed
 * before figures existed reports zeroes, and a column of "0/0" would be noise on the one
 * panel meant to show what each run did.
 */
function formatRunFigures(run: IndexRunSummary | null): string {
  if (!run) return '\u2014';
  const described = Number(run.figures_described || 0);
  const failed = Number(run.figures_failed || 0);
  if (described <= 0 && failed <= 0) return '\u2014';
  return failed > 0 ? `${described.toLocaleString()} (${failed.toLocaleString()} failed)` : described.toLocaleString();
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
