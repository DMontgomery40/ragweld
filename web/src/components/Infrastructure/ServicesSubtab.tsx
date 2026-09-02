import { useCallback, useEffect, useMemo, useState } from 'react';
import * as DashAPI from '@/api/dashboard';
import {
  RAGWELD_DOCKER_SERVICES,
  type RagweldDockerService,
} from '@/api/docker';
import { useConfigField } from '@/hooks/useConfig';
import { useDockerStore } from '@/stores/useDockerStore';
import type { ObservabilityStatusResponse } from '@/types/generated';

/**
 * Which observability component owns each service's operator surface.
 *
 * The Monitoring subtab already resolves these URLs from config; the cards here
 * reuse them so an operator who lands on Services to check MLflow can open it
 * without knowing to go somewhere else.
 */
const SERVICE_SURFACE_COMPONENT: Partial<Record<RagweldDockerService, string>> = {
  grafana: 'grafana',
  tempo: 'tempo',
  alloy: 'alloy',
  mimir: 'mimir',
  pyroscope: 'pyroscope',
  alertmanager: 'alertmanager',
  langfuse: 'langfuse',
  qdrant: 'haystack_docling_qdrant',
  litellm: 'litellm',
  mlflow: 'mlflow',
  flyte: 'flyte',
};

const LOOPBACK = /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:|\/|$)/i;


const SERVICE_GROUPS: Array<{
  title: string;
  description: string;
  services: RagweldDockerService[];
}> = [
  {
    title: 'Data plane',
    description: 'Stores used by retrieval, vector search, lineage, and graph operations.',
    services: ['postgres', 'neo4j'],
  },
  {
    title: 'Application containers',
    description:
      'Optional containerized API and database metrics exporter. The Ragweld API normally runs as a host process (see Host processes above), so an absent API container is expected in development.',
    services: ['api', 'postgres-exporter'],
  },
  {
    title: 'Secure Ingress',
    description:
      'Public edge ingress, authentication, and tunnel services for protected operator access in the Proxmox deployment overlay. Authelia keeps its sessions in its own Redis, so an operator signed out unexpectedly should look there first.',
    services: ['caddy', 'authelia', 'authelia-redis', 'cloudflared'],
  },
  {
    title: 'Gateway and serving',
    description:
      'The only supported generation path: LiteLLM routes model aliases upstream. The local alias targets the host local-model server (127.0.0.1:58080, started by ./start.sh when chat.vllm is enabled), not a container; Admin > Runtime shows whether that lane is on for this host.',
    services: ['litellm'],
  },
  {
    title: 'Vector store',
    description: 'Qdrant holds the dense + sparse vectors for every corpus on the Haystack/Docling/Qdrant retrieval lane.',
    services: ['qdrant'],
  },
  {
    title: 'MLOps tracking and orchestration',
    description:
      'MLflow records Learning Agent runs, metrics, and artifacts when tracking=mlflow is selected; Flyte owns launch/status/cancel when workflow=flyte is selected (start with ./start.sh --with-flyte).',
    services: ['mlflow', 'flyte'],
  },
  {
    title: 'Observability',
    description:
      'Metrics, traces, logs, dashboards, and telemetry collection. Mimir keeps long-range metrics (Prometheus remote-writes into it), Pyroscope receives host-API CPU profiles, Alertmanager receives Prometheus alert rules, and Alloy also hosts the Faro RUM collector for the workbench frontend.',
    services: ['grafana', 'prometheus', 'loki', 'promtail', 'tempo', 'alloy', 'mimir', 'pyroscope', 'alertmanager'],
  },
  {
    title: 'LLM trace drilldown (Langfuse)',
    description:
      'Langfuse v4 records generation-level traces (prompt, output, usage, cost) for chat, reranker, eval, benchmark, and synthetic generations. The web UI publishes 127.0.0.1:53000; Postgres, ClickHouse, Redis, and MinIO are its private dependency plane inside the VM.',
    services: ['langfuse', 'langfuse-worker', 'langfuse-postgres', 'langfuse-clickhouse', 'langfuse-redis', 'langfuse-minio'],
  },
];

const SERVICE_LABELS: Record<RagweldDockerService, string> = {
  postgres: 'PostgreSQL',
  'postgres-exporter': 'Postgres Exporter',
  neo4j: 'Neo4j',
  grafana: 'Grafana',
  prometheus: 'Prometheus',
  loki: 'Loki',
  promtail: 'Promtail',
  api: 'API container (optional)',
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

function isKnownService(value: string | null | undefined): value is RagweldDockerService {
  return RAGWELD_DOCKER_SERVICES.includes(value as RagweldDockerService);
}

const OPTIONAL_SERVICES: ReadonlySet<RagweldDockerService> = new Set(['api', 'postgres-exporter']);

export function ServicesSubtab() {
  const { status, containers, loading, error, refreshDocker, devStackStatus, fetchDevStackStatus } = useDockerStore();

  const refresh = useCallback(async () => {
    await Promise.all([refreshDocker(), fetchDevStackStatus()]);
  }, [refreshDocker, fetchDevStackStatus]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const [observability, setObservability] = useState<ObservabilityStatusResponse | null>(null);
  const [lokiStatus, setLokiStatus] = useState<DashAPI.LokiStatus | null>(null);
  const [prometheusBaseUrl] = useConfigField<string>('tracing.prometheus_base_url', '');

  useEffect(() => {
    let cancelled = false;
    void Promise.all([DashAPI.getObservabilityStatus(), DashAPI.getLokiStatus()]).then(
      ([nextObservability, nextLoki]) => {
        if (cancelled) return;
        setObservability(nextObservability);
        setLokiStatus(nextLoki);
      }
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const surfaceUrlByService = useMemo(() => {
    const byComponent = new Map((observability?.components || []).map((item) => [item.id, item.url || '']));
    const result = new Map<RagweldDockerService, string>();
    for (const [service, componentId] of Object.entries(SERVICE_SURFACE_COMPONENT)) {
      const url = byComponent.get(String(componentId)) || '';
      if (url) result.set(service as RagweldDockerService, url);
    }
    // Prometheus and Loki have no observability *status* component, but both
    // are named in the defect row and both hrefs already exist: Prometheus in
    // `tracing.prometheus_base_url` (the Monitoring subtab reads the same
    // field), Loki as the resolved base URL `/api/loki/status` returns.
    const prometheus = String(prometheusBaseUrl || '').trim();
    if (prometheus) result.set('prometheus', prometheus);
    const loki = String(lokiStatus?.url || '').trim();
    if (loki) result.set('loki', loki);
    return result;
  }, [observability, prometheusBaseUrl, lokiStatus]);

  const frontendMode = devStackStatus?.frontend_mode;
  const frontendLabel = frontendMode === 'dev_server' ? 'Host frontend (Vite dev server)' : 'Served frontend';
  // Until the probe answers, the card says nothing rather than guessing. The
  // first cut read `frontend_mode !== 'absent'`, which is true of `undefined`,
  // so it painted "Running" in --ok above "status not loaded yet".
  const frontendStatusWord =
    frontendMode === 'dev_server'
      ? '● Dev server running'
      : frontendMode === 'built_bundle'
        ? '● Served from build'
        : frontendMode === 'absent'
          ? '○ Not built and no dev server'
          : '— Checking…';
  const frontendDetail =
    frontendMode === 'dev_server'
      ? devStackStatus?.frontend_url || `port ${devStackStatus?.frontend_port ?? '55173'}`
      : frontendMode === 'built_bundle'
        ? `Built bundle at ${devStackStatus?.frontend_bundle_path ?? 'web/dist'}${
            devStackStatus?.frontend_bundle_built_at
              ? `, built ${new Date(devStackStatus.frontend_bundle_built_at).toLocaleString()}`
              : ''
          }; the reverse proxy serves it. No Vite dev server on this host, which is expected here.`
        : 'No built bundle and no dev server: run npm run build in web/, or start the dev server.';

  const containersByService = useMemo(() => {
    const result = new Map<RagweldDockerService, (typeof containers)[number]>();
    for (const container of containers) {
      if (container.managed && isKnownService(container.compose_service)) {
        result.set(container.compose_service, container);
      }
    }
    return result;
  }, [containers]);

  return (
    <div style={{ padding: '16px' }}>
      <section className="settings-section" aria-labelledby="service-readiness-heading">
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', alignItems: 'start' }}>
          <div>
            <h3 id="service-readiness-heading" style={{ marginBottom: '6px' }}>Container State</h3>
            <p className="small" style={{ color: 'var(--fg-muted)', margin: 0 }}>
              Read-only status for the Ragweld Compose project. Lifecycle controls live in the Docker subtab.
            </p>
          </div>
          <button className="small-button" onClick={() => void refresh()} disabled={loading}>
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>

        <div style={{ marginTop: '16px', color: status?.running ? 'var(--ok)' : 'var(--err)' }}>
          {status?.running ? '● Docker runtime available' : '○ Docker runtime unavailable'}
        </div>
        {error && (
          <p role="alert" className="small" style={{ color: 'var(--err)' }}>
            {error}
            {!status?.running && ' Ragweld does not start or replace your Docker runtime; start it on the host and refresh.'}
          </p>
        )}
      </section>

      <section className="settings-section" aria-labelledby="host-processes-heading">
        <h3 id="host-processes-heading" style={{ marginBottom: '4px' }}>Host processes</h3>
        <p className="small" style={{ color: 'var(--fg-muted)', marginTop: 0 }}>
          The FastAPI backend runs directly on the host. The frontend is either a Vite dev server or, on a
          deployed host, the built bundle the reverse proxy serves. Status comes from live probes and the
          bundle on disk, not from container state, and it reports whether a process is up - not whether it
          is fully configured (Admin - Dependencies reports that).
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
          {[
            {
              key: 'backend',
              label: 'Host API (FastAPI)',
              running: devStackStatus?.backend_running === true,
              status: undefined as string | undefined,
              detail: devStackStatus?.backend_url || `port ${devStackStatus?.backend_port ?? '58012'}`,
            },
            {
              key: 'frontend',
              label: frontendLabel,
              running: frontendMode !== undefined && frontendMode !== 'absent',
              status: frontendStatusWord,
              detail: frontendDetail,
            },
          ].map((proc) => (
            <article key={proc.key} style={{ padding: '14px', border: '1px solid var(--line)', borderRadius: '6px', background: 'var(--bg-elev1)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                <strong>{proc.label}</strong>
                <span
                  style={{
                    color: devStackStatus === null || devStackStatus === undefined
                      ? 'var(--fg-muted)'
                      : proc.running
                        ? 'var(--ok)'
                        : 'var(--err)',
                  }}
                  data-testid={`host-process-${proc.key}-status`}
                >
                  {proc.status ?? (proc.running ? '● Running' : '○ Not running')}
                </span>
              </div>
              <div className="small" style={{ color: 'var(--fg-muted)', marginTop: '8px' }}>
                {devStackStatus ? proc.detail : 'Host process status not loaded yet.'}
              </div>
            </article>
          ))}
        </div>
      </section>

      {SERVICE_GROUPS.map((group) => (
        <section key={group.title} className="settings-section" aria-labelledby={`service-group-${group.title.toLowerCase().replace(/\s+/g, '-')}`}>
          <h3 id={`service-group-${group.title.toLowerCase().replace(/\s+/g, '-')}`} style={{ marginBottom: '4px' }}>
            {group.title}
          </h3>
          <p className="small" style={{ color: 'var(--fg-muted)', marginTop: 0 }}>{group.description}</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
            {group.services.map((service) => {
              const container = containersByService.get(service);
              const running = container?.state === 'running';
              const deploymentOnly = DEPLOYMENT_ONLY_SERVICES.has(service);
              const optional = OPTIONAL_SERVICES.has(service);
              const surfaceUrl = surfaceUrlByService.get(service) || '';
              const hostInternal = Boolean(surfaceUrl) && LOOPBACK.test(surfaceUrl);
              return (
                <article key={service} style={{ padding: '14px', border: '1px solid var(--line)', borderRadius: '6px', background: 'var(--bg-elev1)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                    {surfaceUrl ? (
                      <a
                        href={surfaceUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        data-testid={`open-service-${service}`}
                        title={
                          hostInternal
                            ? `Opens ${surfaceUrl} in a new tab. This address is host-internal: it resolves only on the Ragweld host.`
                            : `Opens ${surfaceUrl} in a new tab.`
                        }
                        style={{ color: 'var(--link)', fontWeight: 700, textDecoration: 'underline' }}
                      >
                        {SERVICE_LABELS[service]}
                        {hostInternal ? ' (host-internal)' : ''}
                      </a>
                    ) : (
                      <strong>{SERVICE_LABELS[service]}</strong>
                    )}
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
                  <div className="small" style={{ color: 'var(--fg-muted)', marginTop: '8px' }}>
                    {container?.status ||
                      (deploymentOnly
                        ? 'Created by the Proxmox deployment overlay; not expected in default local development.'
                        : optional
                          ? 'Optional container; not part of the default development topology.'
                          : 'No managed container exists for this service.')}
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
