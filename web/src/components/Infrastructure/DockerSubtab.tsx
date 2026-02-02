import { useState, useEffect, useCallback } from 'react';
import { useDockerStore, useConfigStore } from '@/stores';
import { useNotification } from '@/hooks/useNotification';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import type { DockerConfig } from '@/types/generated';

// Static display-only data for infrastructure services
// Updated for TriBridRAG: postgres + neo4j, no qdrant/redis
const INFRA_SERVICES = [
  { name: 'postgres', displayName: 'PostgreSQL', description: 'Vector database (pgvector)', port: 5432, color: 'var(--accent)' },
  { name: 'neo4j', displayName: 'Neo4j', description: 'Graph database', port: 7474, color: '#10b981' },
  { name: 'prometheus', displayName: 'Prometheus', description: 'Metrics', port: 9090, color: '#f59e0b' },
  { name: 'grafana', displayName: 'Grafana', description: 'Dashboard', port: 3000, color: '#f59e0b' },
] as const;

export function DockerSubtab() {
  // Docker runtime state from Zustand store
  const {
    status,
    containers,
    fetchStatus,
    fetchContainers,
    startContainer,
    stopContainer,
    restartContainer,
    getContainerLogs,
  } = useDockerStore();

  // Config state from Zustand store - PYDANTIC COMPLIANT
  // Read values directly from store, no local state duplication
  const { config, loadConfig, patchSection, saving } = useConfigStore();

  // Notifications for feedback
  const { success, error: notifyError, notifications, removeNotification } = useNotification();

  // Local UI state ONLY (not config values)
  const [_loading, setLoading] = useState(false);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [containerLogs, setContainerLogs] = useState<Record<string, string>>({});
  const [showLogsFor, setShowLogsFor] = useState<string | null>(null);
  const [settingsExpanded, setSettingsExpanded] = useState(false);

  // Pending config changes - accumulated until save
  const [pendingChanges, setPendingChanges] = useState<Record<string, number | boolean>>({});

  // Load config on mount
  useEffect(() => {
    if (!config) loadConfig();
  }, [config, loadConfig]);

  // Load Docker runtime status on mount
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      try {
        await Promise.all([fetchStatus(), fetchContainers()]);
      } catch (err) {
        notifyError('Failed to load Docker status');
      } finally {
        setLoading(false);
      }
    };

    loadData();

    // Refresh every 30 seconds
    const interval = setInterval(() => {
      fetchStatus();
      fetchContainers();
    }, 30000);

    return () => clearInterval(interval);
  }, [fetchStatus, fetchContainers, notifyError]);

  // Map display keys to Pydantic field names
  const keyMap: Record<string, keyof DockerConfig> = {
    'DOCKER_STATUS_TIMEOUT': 'docker_status_timeout',
    'DOCKER_CONTAINER_LIST_TIMEOUT': 'docker_container_list_timeout',
    'DOCKER_CONTAINER_ACTION_TIMEOUT': 'docker_container_action_timeout',
    'DOCKER_INFRA_UP_TIMEOUT': 'docker_infra_up_timeout',
    'DOCKER_INFRA_DOWN_TIMEOUT': 'docker_infra_down_timeout',
    'DOCKER_LOGS_TAIL': 'docker_logs_tail',
    'DOCKER_LOGS_TIMESTAMPS': 'docker_logs_timestamps',
  };

  // Get config value - pending change takes precedence over store value
  const getConfigValue = useCallback((key: string, defaultVal: number | boolean) => {
    if (key in pendingChanges) return pendingChanges[key];
    const dockerKey = keyMap[key];
    if (dockerKey && config?.docker) {
      const val = config.docker[dockerKey];
      if (val !== undefined) return val;
    }
    return defaultVal;
  }, [config, pendingChanges]);

  // Set pending config change
  const setConfigValue = useCallback((key: string, value: number | boolean) => {
    setPendingChanges(prev => ({ ...prev, [key]: value }));
  }, []);

  // Check if there are unsaved changes
  const hasChanges = Object.keys(pendingChanges).length > 0;

  // Save Docker settings via Pydantic-validated endpoint
  const handleSaveSettings = async () => {
    if (!hasChanges) return;

    try {
      // Convert pending changes to Pydantic field names
      const dockerUpdates: Record<string, number | boolean> = {};
      for (const [key, value] of Object.entries(pendingChanges)) {
        const pydanticKey = keyMap[key];
        if (pydanticKey) {
          dockerUpdates[pydanticKey] = value;
        }
      }
      await patchSection('docker', dockerUpdates);
      success('Docker settings saved');
      setPendingChanges({}); // Clear pending changes after successful save
    } catch (err) {
      notifyError('Failed to save Docker settings');
    }
  };

  // Handle service actions with proper error handling
  const handleServiceAction = async (serviceName: string, action: 'start' | 'stop' | 'restart') => {
    const container = getContainerForService(serviceName);
    if (!container) {
      notifyError(`Container for ${serviceName} not found`);
      return;
    }

    setActionInProgress(`${container.id}-${action}`);

    try {
      if (action === 'start') {
        await startContainer(container.id);
        success(`${serviceName} started`);
      } else if (action === 'stop') {
        await stopContainer(container.id);
        success(`${serviceName} stopped`);
      } else if (action === 'restart') {
        await restartContainer(container.id);
        success(`${serviceName} restarted`);
      }
    } catch (err) {
      notifyError(`Failed to ${action} ${serviceName}: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setActionInProgress(null);
    }
  };

  const handleStartAllInfrastructure = async () => {
    setActionInProgress('start-all');

    let started = 0;
    for (const service of INFRA_SERVICES) {
      const container = getContainerForService(service.name);
      if (container && container.state !== 'running') {
        try {
          await startContainer(container.id);
          started++;
        } catch (err) {
          notifyError(`Failed to start ${service.name}`);
        }
      }
    }

    if (started > 0) {
      success(`Started ${started} service${started > 1 ? 's' : ''}`);
    }
    setActionInProgress(null);
  };

  const handleStopAllInfrastructure = async () => {
    if (!confirm('Are you sure you want to stop all infrastructure services?')) return;

    setActionInProgress('stop-all');

    let stopped = 0;
    for (const service of INFRA_SERVICES) {
      const container = getContainerForService(service.name);
      if (container && container.state === 'running') {
        try {
          await stopContainer(container.id);
          stopped++;
        } catch (err) {
          notifyError(`Failed to stop ${service.name}`);
        }
      }
    }

    if (stopped > 0) {
      success(`Stopped ${stopped} service${stopped > 1 ? 's' : ''}`);
    }
    setActionInProgress(null);
  };

  const handleViewLogs = async (containerId: string) => {
    const tailLines = getConfigValue('DOCKER_LOGS_TAIL', 100) as number;
    try {
      const result = await getContainerLogs(containerId, tailLines);
      if (result.success) {
        setContainerLogs(prev => ({ ...prev, [containerId]: result.logs || 'No logs available' }));
        setShowLogsFor(containerId);
      } else {
        notifyError(result.error || 'Failed to fetch logs');
      }
    } catch (err) {
      notifyError(`Failed to fetch logs: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  const getContainerForService = (serviceName: string) => {
    const svc = serviceName.toLowerCase();

    // Prefer docker-compose metadata when available (avoids false matches like postgres-exporter).
    const byCompose = containers.find(c => (c.compose_service || '').toLowerCase() === svc);
    if (byCompose) return byCompose;

    // Fallback to our canonical docker-compose container names.
    const byName = containers.find(c => c.name.toLowerCase() === `tribrid-${svc}`);
    if (byName) return byName;

    // Last resort: substring match (avoid exporter for postgres).
    if (svc === 'postgres') {
      return containers.find(c => c.name.toLowerCase().includes('postgres') && !c.name.toLowerCase().includes('exporter'));
    }

    return containers.find(c => c.name.toLowerCase().includes(svc));
  };

  const getContainerStatus = (serviceName: string): 'running' | 'stopped' | 'unknown' => {
    const container = getContainerForService(serviceName);
    if (!container) return 'unknown';
    return container.state === 'running' ? 'running' : 'stopped';
  };

  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'running': return 'var(--ok)';
      case 'stopped':
      case 'exited': return 'var(--err)';
      default: return 'var(--fg-muted)';
    }
  };

  // Auto-dismiss notifications after 4 seconds
  useEffect(() => {
    if (notifications.length > 0) {
      const timer = setTimeout(() => {
        removeNotification(notifications[0].id);
      }, 4000);
      return () => clearTimeout(timer);
    }
  }, [notifications, removeNotification]);

  return (
    <div style={{ padding: '24px' }}>
      {/* Toast Notifications */}
      {notifications.length > 0 && (
        <div style={{
          position: 'fixed',
          top: '20px',
          right: '20px',
          zIndex: 10001,
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}>
          {notifications.map(n => (
            <div
              key={n.id}
              style={{
                padding: '12px 16px',
                borderRadius: '6px',
                background: n.type === 'success' ? 'var(--ok)' : n.type === 'error' ? 'var(--err)' : 'var(--accent)',
                color: '#fff',
                fontSize: '13px',
                fontWeight: 500,
                boxShadow: 'var(--shadow-md)',
                cursor: 'pointer',
              }}
              onClick={() => removeNotification(n.id)}
            >
              {n.message}
            </div>
          ))}
        </div>
      )}

      {/* Docker Settings - Collapsible Section */}
      <div className="settings-section" style={{ marginBottom: '24px' }}>
        <button
          className="settings-section-header"
          onClick={() => setSettingsExpanded(!settingsExpanded)}
          style={{
            width: '100%',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '16px',
            background: 'var(--bg-elev1)',
            border: '1px solid var(--line)',
            borderRadius: settingsExpanded ? '6px 6px 0 0' : '6px',
            cursor: 'pointer',
          }}
        >
          <h3 style={{ margin: 0, fontSize: '16px', color: 'var(--fg)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            Docker Settings <TooltipIcon name="DOCKER_SETTINGS" />
          </h3>
          <span style={{ fontSize: '14px', color: 'var(--fg-muted)', transform: settingsExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>▼</span>
        </button>

        {settingsExpanded && (
          <div className="settings-section-content" style={{
            background: 'var(--bg-elev1)',
            border: '1px solid var(--line)',
            borderTop: 'none',
            borderRadius: '0 0 6px 6px',
            padding: '16px',
          }}>
            {/* Timeout Settings Grid */}
            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '16px' }}>
              {/* Status Timeout */}
              <div className="input-group">
                <label style={{ fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  Status Timeout (s) <TooltipIcon name="DOCKER_STATUS_TIMEOUT" />
                </label>
                <input
                  type="number"
                  min={1}
                  max={30}
                  value={getConfigValue('DOCKER_STATUS_TIMEOUT', 5) as number}
                  onChange={e => setConfigValue('DOCKER_STATUS_TIMEOUT', Number(e.target.value))}
                  style={{ width: '100%', padding: '8px 12px', background: 'var(--bg-elev2)', border: '1px solid var(--line)', borderRadius: '4px', color: 'var(--fg)', fontSize: '13px' }}
                />
              </div>

              {/* Container List Timeout */}
              <div className="input-group">
                <label style={{ fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  Container List Timeout (s) <TooltipIcon name="DOCKER_CONTAINER_LIST_TIMEOUT" />
                </label>
                <input
                  type="number"
                  min={1}
                  max={60}
                  value={getConfigValue('DOCKER_CONTAINER_LIST_TIMEOUT', 10) as number}
                  onChange={e => setConfigValue('DOCKER_CONTAINER_LIST_TIMEOUT', Number(e.target.value))}
                  style={{ width: '100%', padding: '8px 12px', background: 'var(--bg-elev2)', border: '1px solid var(--line)', borderRadius: '4px', color: 'var(--fg)', fontSize: '13px' }}
                />
              </div>

              {/* Container Action Timeout */}
              <div className="input-group">
                <label style={{ fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  Action Timeout (s) <TooltipIcon name="DOCKER_CONTAINER_ACTION_TIMEOUT" />
                </label>
                <input
                  type="number"
                  min={5}
                  max={120}
                  value={getConfigValue('DOCKER_CONTAINER_ACTION_TIMEOUT', 30) as number}
                  onChange={e => setConfigValue('DOCKER_CONTAINER_ACTION_TIMEOUT', Number(e.target.value))}
                  style={{ width: '100%', padding: '8px 12px', background: 'var(--bg-elev2)', border: '1px solid var(--line)', borderRadius: '4px', color: 'var(--fg)', fontSize: '13px' }}
                />
              </div>

              {/* Infra Up Timeout */}
              <div className="input-group">
                <label style={{ fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  Infra Up Timeout (s) <TooltipIcon name="DOCKER_INFRA_UP_TIMEOUT" />
                </label>
                <input
                  type="number"
                  min={30}
                  max={300}
                  value={getConfigValue('DOCKER_INFRA_UP_TIMEOUT', 120) as number}
                  onChange={e => setConfigValue('DOCKER_INFRA_UP_TIMEOUT', Number(e.target.value))}
                  style={{ width: '100%', padding: '8px 12px', background: 'var(--bg-elev2)', border: '1px solid var(--line)', borderRadius: '4px', color: 'var(--fg)', fontSize: '13px' }}
                />
              </div>

              {/* Infra Down Timeout */}
              <div className="input-group">
                <label style={{ fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  Infra Down Timeout (s) <TooltipIcon name="DOCKER_INFRA_DOWN_TIMEOUT" />
                </label>
                <input
                  type="number"
                  min={10}
                  max={120}
                  value={getConfigValue('DOCKER_INFRA_DOWN_TIMEOUT', 30) as number}
                  onChange={e => setConfigValue('DOCKER_INFRA_DOWN_TIMEOUT', Number(e.target.value))}
                  style={{ width: '100%', padding: '8px 12px', background: 'var(--bg-elev2)', border: '1px solid var(--line)', borderRadius: '4px', color: 'var(--fg)', fontSize: '13px' }}
                />
              </div>

              {/* Logs Tail */}
              <div className="input-group">
                <label style={{ fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  Logs Tail Lines <TooltipIcon name="DOCKER_LOGS_TAIL" />
                </label>
                <input
                  type="number"
                  min={10}
                  max={1000}
                  value={getConfigValue('DOCKER_LOGS_TAIL', 100) as number}
                  onChange={e => setConfigValue('DOCKER_LOGS_TAIL', Number(e.target.value))}
                  style={{ width: '100%', padding: '8px 12px', background: 'var(--bg-elev2)', border: '1px solid var(--line)', borderRadius: '4px', color: 'var(--fg)', fontSize: '13px' }}
                />
              </div>
            </div>

            {/* Logs Timestamps Toggle */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
              <label className="toggle" style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={Boolean(getConfigValue('DOCKER_LOGS_TIMESTAMPS', true))}
                  onChange={e => setConfigValue('DOCKER_LOGS_TIMESTAMPS', e.target.checked ? 1 : 0)}
                />
                <span className="toggle-track"><span className="toggle-thumb" /></span>
                <span className="toggle-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  Include Timestamps in Logs <TooltipIcon name="DOCKER_LOGS_TIMESTAMPS" />
                </span>
              </label>
            </div>

            {/* Save Button */}
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                className="small-button"
                onClick={handleSaveSettings}
                disabled={saving || !hasChanges}
                style={{
                  padding: '8px 24px',
                  background: hasChanges ? 'var(--accent)' : 'var(--bg-elev2)',
                  color: hasChanges ? 'var(--accent-contrast)' : 'var(--fg-muted)',
                  border: 'none',
                  borderRadius: '4px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: saving || !hasChanges ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}
              >
                {saving && <span className="loading-spinner" style={{ width: '14px', height: '14px' }} />}
                {saving ? 'Saving...' : hasChanges ? 'Save Settings' : 'No Changes'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Infrastructure Services */}
      <div className="settings-section" style={{ marginBottom: '24px' }}>
        <div style={{ background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: '6px', padding: '16px' }}>
          <h3 style={{ margin: '0 0 16px 0', fontSize: '16px', color: 'var(--fg)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            Infrastructure Services <TooltipIcon name="DOCKER_INFRASTRUCTURE_SERVICES" />
          </h3>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '16px', marginBottom: '16px' }}>
            {INFRA_SERVICES.map(service => {
              const container = getContainerForService(service.name);
              const containerStatus = getContainerStatus(service.name);

              return (
                <div
                  key={service.name}
                  style={{
                    background: 'var(--bg-elev2)',
                    border: `1px solid ${service.color}`,
                    borderRadius: '6px',
                    padding: '16px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '12px' }}>
                    <div>
                      <div style={{ fontSize: '16px', fontWeight: 600, color: service.color, marginBottom: '4px' }}>
                        {service.displayName}
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
                        {service.description} • Port {service.port}
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', fontSize: '12px', color: getStatusColor(containerStatus), fontWeight: 500 }}>
                      <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: getStatusColor(containerStatus), marginRight: '6px' }} />
                      {containerStatus === 'running' ? 'Running' : containerStatus === 'stopped' ? 'Stopped' : 'Unknown'}
                    </div>
                  </div>

                  {container && (
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '12px' }}>
                      {container.status}
                    </div>
                  )}

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px' }}>
                    {containerStatus === 'running' ? (
                      <>
                        <button className="small-button" onClick={() => handleServiceAction(service.name, 'restart')} disabled={actionInProgress !== null} style={{ background: 'var(--bg-elev1)', color: 'var(--fg)', border: '1px solid var(--line)', padding: '6px', borderRadius: '4px', fontSize: '11px', cursor: actionInProgress !== null ? 'not-allowed' : 'pointer' }}>Restart</button>
                        <button className="small-button" onClick={() => handleServiceAction(service.name, 'stop')} disabled={actionInProgress !== null} style={{ background: 'var(--err)', color: '#fff', border: 'none', padding: '6px', borderRadius: '4px', fontSize: '11px', cursor: actionInProgress !== null ? 'not-allowed' : 'pointer' }}>Stop</button>
                        <button className="small-button" onClick={() => container && handleViewLogs(container.id)} style={{ background: 'var(--bg-elev1)', color: 'var(--fg)', border: '1px solid var(--line)', padding: '6px', borderRadius: '4px', fontSize: '11px', cursor: 'pointer' }}>Logs</button>
                      </>
                    ) : (
                      <button className="small-button" onClick={() => handleServiceAction(service.name, 'start')} disabled={actionInProgress !== null} style={{ background: 'var(--accent)', color: 'var(--accent-contrast)', border: 'none', padding: '6px', borderRadius: '4px', fontSize: '11px', cursor: actionInProgress !== null ? 'not-allowed' : 'pointer', gridColumn: '1 / -1' }}>Start</button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <div style={{ display: 'flex', gap: '12px' }}>
            <button className="small-button" onClick={handleStartAllInfrastructure} disabled={actionInProgress !== null} style={{ flex: 1, background: actionInProgress ? 'var(--bg-elev2)' : 'var(--accent)', color: actionInProgress ? 'var(--fg-muted)' : 'var(--accent-contrast)', border: 'none', padding: '12px', borderRadius: '4px', fontSize: '14px', fontWeight: 600, cursor: actionInProgress ? 'not-allowed' : 'pointer' }}>
              {actionInProgress === 'start-all' && <span className="loading-spinner" style={{ width: '14px', height: '14px', marginRight: '8px', display: 'inline-block' }} />}
              ▶ START ALL INFRASTRUCTURE
            </button>
            <button className="small-button" onClick={handleStopAllInfrastructure} disabled={actionInProgress !== null} style={{ flex: 1, background: actionInProgress ? 'var(--bg-elev2)' : 'var(--err)', color: actionInProgress ? 'var(--fg-muted)' : '#fff', border: 'none', padding: '12px', borderRadius: '4px', fontSize: '14px', fontWeight: 600, cursor: actionInProgress ? 'not-allowed' : 'pointer' }}>
              {actionInProgress === 'stop-all' && <span className="loading-spinner" style={{ width: '14px', height: '14px', marginRight: '8px', display: 'inline-block' }} />}
              ⏹ STOP ALL INFRASTRUCTURE
            </button>
          </div>
        </div>
      </div>

      {/* Docker Status */}
      <div className="settings-section" style={{ marginBottom: '24px' }}>
        <div style={{ background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: '6px', padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ margin: 0, fontSize: '16px', color: 'var(--fg)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              Docker Status <TooltipIcon name="DOCKER_STATUS" />
            </h3>
            <button
              id="btn-docker-refresh"
              className="small-button"
              onClick={() => { fetchStatus(); fetchContainers(); success('Refreshed Docker status'); }}
              style={{ background: 'var(--accent)', color: 'var(--accent-contrast)', border: 'none', padding: '6px 16px', borderRadius: '4px', fontSize: '12px', fontWeight: 500, cursor: 'pointer' }}
            >
              ↻ REFRESH ALL
            </button>
          </div>

          <div id="docker-status-display" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
            <div style={{ background: 'var(--bg-elev2)', border: '1px solid var(--line)', borderRadius: '4px', padding: '12px' }}>
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '6px' }}>Status:</div>
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <div style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: status?.running ? 'var(--ok)' : 'var(--err)', marginRight: '8px' }} />
                <span style={{ fontSize: '14px', fontWeight: 600, color: status?.running ? 'var(--ok)' : 'var(--err)' }}>{status?.running ? 'Running' : 'Not Running'}</span>
              </div>
            </div>

            <div style={{ background: 'var(--bg-elev2)', border: '1px solid var(--line)', borderRadius: '4px', padding: '12px' }}>
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '6px' }}>Runtime:</div>
              <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--fg)' }}>{status?.runtime || 'Unknown'}</div>
            </div>

            <div style={{ background: 'var(--bg-elev2)', border: '1px solid var(--line)', borderRadius: '4px', padding: '12px' }}>
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '6px' }}>Containers:</div>
              <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--fg)' }}>{status?.containers_count || 0}</div>
            </div>
          </div>
        </div>
      </div>

      {/* All Containers */}
      <div className="settings-section">
        <div style={{ background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: '6px', padding: '16px' }}>
          <h3 style={{ margin: '0 0 16px 0', fontSize: '16px', color: 'var(--fg)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            All Containers <TooltipIcon name="DOCKER_ALL_CONTAINERS" />
          </h3>

          {containers.length === 0 ? (
            <div style={{ color: 'var(--fg-muted)', fontSize: '13px', textAlign: 'center', padding: '40px' }}>
              No containers found
            </div>
          ) : (
            <div style={{ display: 'grid', gap: '12px' }}>
              {containers.map(container => (
                <div key={container.id} style={{ background: 'var(--bg-elev2)', border: '1px solid var(--line)', borderRadius: '4px', padding: '12px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '6px' }}>
                        <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: getStatusColor(container.state), marginRight: '8px' }} />
                        <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--fg)' }}>{container.name}</span>
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '4px' }}>{container.image}</div>
                      <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>{container.status}</div>
                      {container.ports && (Array.isArray(container.ports) ? container.ports.length > 0 : container.ports.length > 0) && (
                        <div style={{ fontSize: '11px', color: 'var(--accent)', marginTop: '4px' }}>
                          Ports: {Array.isArray(container.ports)
                            ? container.ports.map(p => `${p.PublicPort || p.PrivatePort}/${p.Type}`).join(', ')
                            : container.ports}
                        </div>
                      )}
                    </div>

                    <div style={{ display: 'flex', gap: '6px' }}>
                      {container.state === 'running' ? (
                        <>
                          <button className="small-button" onClick={() => restartContainer(container.id).then(() => success(`Restarted ${container.name}`))} disabled={actionInProgress !== null} style={{ background: 'var(--bg-elev1)', color: 'var(--fg)', border: '1px solid var(--line)', padding: '4px 12px', borderRadius: '4px', fontSize: '11px', cursor: actionInProgress ? 'not-allowed' : 'pointer' }}>Restart</button>
                          <button className="small-button" onClick={() => stopContainer(container.id).then(() => success(`Stopped ${container.name}`))} disabled={actionInProgress !== null} style={{ background: 'var(--err)', color: '#fff', border: 'none', padding: '4px 12px', borderRadius: '4px', fontSize: '11px', cursor: actionInProgress ? 'not-allowed' : 'pointer' }}>Stop</button>
                          <button className="small-button" onClick={() => handleViewLogs(container.id)} style={{ background: 'var(--accent)', color: 'var(--accent-contrast)', border: 'none', padding: '4px 12px', borderRadius: '4px', fontSize: '11px', cursor: 'pointer' }}>Logs</button>
                        </>
                      ) : (
                        <button className="small-button" onClick={() => startContainer(container.id).then(() => success(`Started ${container.name}`))} disabled={actionInProgress !== null} style={{ background: 'var(--accent)', color: 'var(--accent-contrast)', border: 'none', padding: '4px 12px', borderRadius: '4px', fontSize: '11px', cursor: actionInProgress ? 'not-allowed' : 'pointer' }}>Start</button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Logs Modal */}
      {showLogsFor && (
        <>
          <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.8)', zIndex: 9999 }} onClick={() => setShowLogsFor(null)} />
          <div style={{ position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: '8px', padding: '20px', zIndex: 10000, width: '80%', maxWidth: '800px', maxHeight: '600px', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ margin: 0, fontSize: '16px', color: 'var(--fg)' }}>Container Logs</h3>
              <button onClick={() => setShowLogsFor(null)} style={{ background: 'transparent', color: 'var(--fg)', border: 'none', fontSize: '20px', cursor: 'pointer', padding: '0 8px' }}>×</button>
            </div>
            <div style={{ background: '#000', color: '#0f0', fontFamily: 'monospace', fontSize: '12px', padding: '12px', borderRadius: '4px', flex: 1, overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
              {containerLogs[showLogsFor] || 'Loading logs...'}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
