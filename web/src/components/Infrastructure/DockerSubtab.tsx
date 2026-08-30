import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RAGWELD_DOCKER_SERVICES,
  type RagweldDockerService,
} from '@/api/docker';
import { useNotification } from '@/hooks/useNotification';
import { useDockerStore } from '@/stores/useDockerStore';

const SERVICE_LABELS: Record<RagweldDockerService, string> = {
  postgres: 'PostgreSQL',
  'postgres-exporter': 'Postgres Exporter',
  neo4j: 'Neo4j',
  grafana: 'Grafana',
  prometheus: 'Prometheus',
  loki: 'Loki',
  promtail: 'Promtail',
  api: 'Ragweld API',
  tempo: 'Tempo',
  caddy: 'Caddy Secure Ingress',
  authelia: 'Authelia Authentication',
  cloudflared: 'Cloudflare Tunnel',
  alloy: 'Grafana Alloy',
  litellm: 'LiteLLM Gateway',
  qdrant: 'Qdrant Vector Store',
  mlflow: 'MLflow Tracking',
  flyte: 'Flyte Control Plane',
  mimir: 'Mimir Metrics Store',
  pyroscope: 'Pyroscope Profiling',
  alertmanager: 'Alertmanager',
  langfuse: 'Langfuse',
  'langfuse-worker': 'Langfuse Worker',
  'langfuse-postgres': 'Langfuse Postgres',
  'langfuse-clickhouse': 'Langfuse ClickHouse',
  'langfuse-redis': 'Langfuse Redis',
  'langfuse-minio': 'Langfuse MinIO',
};

const DEPLOYMENT_ONLY_SERVICES: ReadonlySet<RagweldDockerService> = new Set(['caddy', 'authelia', 'cloudflared']);

// Kept in step with ServicesSubtab: one absent container must not be "Missing"
// on one page and "expected" on the other.
const OPTIONAL_SERVICES: ReadonlySet<RagweldDockerService> = new Set(['api', 'postgres-exporter']);

function isRagweldService(value: string | null | undefined): value is RagweldDockerService {
  return RAGWELD_DOCKER_SERVICES.includes(value as RagweldDockerService);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function DockerSubtab() {
  const {
    status,
    containers,
    loading,
    error,
    refreshDocker,
    startService,
    stopService,
    restartService,
    getServiceLogs,
  } = useDockerStore();
  const { success, error: notifyError, notifications, removeNotification } = useNotification();
  const [action, setAction] = useState<string | null>(null);
  const [logs, setLogs] = useState<{ service: RagweldDockerService; text: string } | null>(null);

  const refresh = useCallback(async () => {
    await refreshDocker();
  }, [refreshDocker]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const containersByService = useMemo(() => {
    const scoped = new Map<RagweldDockerService, (typeof containers)[number]>();
    for (const container of containers) {
      if (container.managed && isRagweldService(container.compose_service)) {
        scoped.set(container.compose_service, container);
      }
    }
    return scoped;
  }, [containers]);

  const runAction = async (
    service: RagweldDockerService,
    operation: 'start' | 'stop' | 'restart',
  ) => {
    const actionKey = `${service}:${operation}`;
    setAction(actionKey);
    try {
      if (operation === 'start') await startService(service);
      if (operation === 'stop') await stopService(service);
      if (operation === 'restart') await restartService(service);
      success(`${SERVICE_LABELS[service]} ${operation} completed`);
    } catch (caught) {
      notifyError(`Could not ${operation} ${SERVICE_LABELS[service]}: ${errorMessage(caught)}`);
    } finally {
      setAction(null);
    }
  };

  const showLogs = async (service: RagweldDockerService) => {
    setAction(`${service}:logs`);
    try {
      const response = await getServiceLogs(service, 200);
      if (!response.success) throw new Error(response.error || 'The log request failed');
      setLogs({ service, text: response.logs || 'No logs available.' });
    } catch (caught) {
      notifyError(`Could not load ${SERVICE_LABELS[service]} logs: ${errorMessage(caught)}`);
    } finally {
      setAction(null);
    }
  };

  return (
    <div style={{ padding: '16px' }}>
      <div className="notification-container">
        {notifications.map((notification) => (
          <div key={notification.id} className={`notification notification-${notification.type}`}>
            <span>{notification.message}</span>
            <button onClick={() => removeNotification(notification.id)} aria-label="Dismiss notification">×</button>
          </div>
        ))}
      </div>

      <section className="settings-section" aria-labelledby="ragweld-docker-heading">
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', alignItems: 'start' }}>
          <div>
            <h3 id="ragweld-docker-heading" style={{ marginBottom: '6px' }}>Ragweld Docker Services</h3>
            <p className="small" style={{ color: 'var(--fg-muted)', margin: 0 }}>
              Only containers owned by the <code>ragweld</code> Compose project are visible or controllable here.
            </p>
          </div>
          <button className="small-button" onClick={() => void refresh()} disabled={loading}>
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '12px',
          marginTop: '16px',
        }}>
          <div style={{ padding: '12px', border: '1px solid var(--line)', borderRadius: '6px', background: 'var(--bg-elev2)' }}>
            <div className="small" style={{ color: 'var(--fg-muted)' }}>Docker daemon</div>
            <strong style={{ color: status?.running ? 'var(--ok)' : 'var(--err)' }}>
              {status?.running ? 'Available' : 'Unavailable'}
            </strong>
          </div>
          <div style={{ padding: '12px', border: '1px solid var(--line)', borderRadius: '6px', background: 'var(--bg-elev2)' }}>
            <div className="small" style={{ color: 'var(--fg-muted)' }}>Runtime</div>
            <strong>{status?.runtime || 'Unknown'}</strong>
          </div>
          <div style={{ padding: '12px', border: '1px solid var(--line)', borderRadius: '6px', background: 'var(--bg-elev2)' }}>
            <div className="small" style={{ color: 'var(--fg-muted)' }}>Managed services</div>
            <strong>{containers.length}</strong>
          </div>
        </div>

        {error && (
          <div role="alert" style={{ marginTop: '12px', color: 'var(--err)' }}>
            {error}
            {!status?.running && ' Start or select the host-owned Docker runtime, then refresh.'}
          </div>
        )}
      </section>

      <section className="settings-section" aria-label="Managed service controls">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px' }}>
          {RAGWELD_DOCKER_SERVICES.map((service) => {
            const container = containersByService.get(service);
            const running = container?.state === 'running';
            const deploymentOnly = DEPLOYMENT_ONLY_SERVICES.has(service);
            const optional = OPTIONAL_SERVICES.has(service);
            const busy = action !== null;
            return (
              <article key={service} style={{ padding: '14px', border: '1px solid var(--line)', borderRadius: '6px', background: 'var(--bg-elev1)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                  <div>
                    <strong>{SERVICE_LABELS[service]}</strong>
                    <div className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
                      {container?.status ||
                        (deploymentOnly
                          ? 'Created by the Proxmox deployment overlay; not expected in the default local topology.'
                          : optional
                            ? 'Optional container; the Ragweld API normally runs as a host process, so its absence is expected.'
                            : 'Not created in the Ragweld project')}
                    </div>
                  </div>
                  <span style={{ color: running ? 'var(--ok)' : container ? 'var(--warn)' : 'var(--fg-muted)' }}>
                    {running
                      ? '● Running'
                      : container
                        ? '○ Stopped'
                        : deploymentOnly
                          ? '— Deployment-only'
                          : optional
                            ? '— Optional, not deployed'
                            : '— Missing'}
                  </span>
                </div>

                <div style={{ display: 'flex', gap: '8px', marginTop: '14px', flexWrap: 'wrap' }}>
                  {!container && !deploymentOnly && !optional && (
                    <span className="small">
                      Run <code>{service === 'api' ? './start.sh --docker-backend' : ['postgres', 'neo4j'].includes(service) ? './start.sh' : './start.sh --with-observability'}</code> to create it.
                    </span>
                  )}
                  {container && !running && (
                    <>
                      <button className="small-button" disabled={busy} onClick={() => void runAction(service, 'start')}>
                        Start
                      </button>
                      <button className="small-button" disabled={busy} onClick={() => void showLogs(service)}>
                        Logs
                      </button>
                    </>
                  )}
                  {container && running && (
                    <>
                      <button className="small-button" disabled={busy} onClick={() => void runAction(service, 'restart')}>
                        Restart
                      </button>
                      <button className="small-button" disabled={busy} onClick={() => void runAction(service, 'stop')}>
                        Stop
                      </button>
                      <button className="small-button" disabled={busy} onClick={() => void showLogs(service)}>
                        Logs
                      </button>
                    </>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </section>

      {logs && (
        <div role="dialog" aria-modal="true" aria-labelledby="docker-logs-title">
          <button
            aria-label="Close logs"
            onClick={() => setLogs(null)}
            style={{ position: 'fixed', inset: 0, border: 0, background: 'rgba(0,0,0,0.75)', zIndex: 9998 }}
          />
          <div style={{ position: 'fixed', inset: '10% 8%', zIndex: 9999, background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: '8px', padding: '18px', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <h3 id="docker-logs-title" style={{ margin: 0 }}>{SERVICE_LABELS[logs.service]} logs</h3>
              <button className="small-button" onClick={() => setLogs(null)}>Close</button>
            </div>
            <pre style={{ flex: 1, overflow: 'auto', margin: 0, padding: '12px', background: '#050505', color: '#b7f7bf', borderRadius: '4px', whiteSpace: 'pre-wrap' }}>
              {logs.text}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
