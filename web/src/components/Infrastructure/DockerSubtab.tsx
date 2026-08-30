import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RAGWELD_DOCKER_SERVICES,
  type RagweldDockerService,
} from '@/api/docker';
import { useNotification } from '@/hooks/useNotification';
import { useDockerStore } from '@/stores/useDockerStore';
import { confirmDialog } from '@/components/ui/confirmDialog';

// Data and ingress tiers: stopping or restarting one takes a store or the front door offline
// for every corpus and operator, and dependent services fail while it is down. A stop/restart
// here demands a typed confirmation, not a single click among equal-weight buttons (E-47).
const CRITICAL_SERVICES: ReadonlySet<RagweldDockerService> = new Set([
  'postgres',
  'neo4j',
  'qdrant',
  'caddy',
  'authelia',
  'authelia-redis',
  'cloudflared',
  'langfuse-postgres',
  'langfuse-clickhouse',
  'langfuse-redis',
  'langfuse-minio',
]);

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
  'authelia-redis': 'Authelia Session Store',
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

const DEPLOYMENT_ONLY_SERVICES: ReadonlySet<RagweldDockerService> = new Set(['caddy', 'authelia', 'authelia-redis', 'cloudflared']);

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
    // `start` brings a service up (non-destructive); `stop`/`restart` take it down and must be
    // confirmed with the exact service named. Core data/ingress services additionally require the
    // operator to type the service key so a stray click cannot take a store offline.
    if (operation === 'stop' || operation === 'restart') {
      const label = SERVICE_LABELS[service];
      const critical = CRITICAL_SERVICES.has(service);
      const consequence =
        operation === 'stop'
          ? `Stopping ${label} takes it offline for every corpus and operator until it is started again`
          : `Restarting ${label} interrupts it while it bounces`;
      const proceed = await confirmDialog({
        title: `${operation === 'stop' ? 'Stop' : 'Restart'} ${label}`,
        message: critical
          ? `${consequence}. This is a core data or ingress service — dependent services will error while it is down. Continue?`
          : `${consequence}. Continue?`,
        confirmLabel: `${operation === 'stop' ? 'Stop' : 'Restart'} ${label}`,
        cancelLabel: 'Cancel',
        danger: true,
        requireTyped: critical
          ? { expected: service, label: `Type "${service}" to ${operation} this core service` }
          : undefined,
      });
      if (!proceed) return;
    }
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
                      {/* Logs is the primary, non-destructive control and leads the row; the
                          lifecycle controls follow, weighted as danger and pushed to the right
                          so a stop/restart is never the default target (E-47). */}
                      <button className="small-button" disabled={busy} onClick={() => void showLogs(service)}>
                        Logs
                      </button>
                      <button
                        className="small-button"
                        disabled={busy}
                        onClick={() => void runAction(service, 'restart')}
                        title={`Restart ${SERVICE_LABELS[service]}`}
                        style={{ marginLeft: 'auto', borderColor: 'var(--warn)', color: 'var(--warn)' }}
                      >
                        Restart
                      </button>
                      <button
                        className="small-button"
                        disabled={busy}
                        onClick={() => void runAction(service, 'stop')}
                        title={`Stop ${SERVICE_LABELS[service]}`}
                        style={{ borderColor: 'var(--err)', color: 'var(--err)' }}
                      >
                        Stop
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
