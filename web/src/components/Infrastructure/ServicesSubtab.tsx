import { useCallback, useEffect, useMemo } from 'react';
import {
  RAGWELD_DOCKER_SERVICES,
  type RagweldDockerService,
} from '@/api/docker';
import { useDockerStore } from '@/stores/useDockerStore';

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
    title: 'Application',
    description: 'Optional containerized API and database metrics exporter.',
    services: ['api', 'postgres-exporter'],
  },
  {
    title: 'Observability',
    description: 'Metrics, traces, logs, dashboards, and telemetry collection.',
    services: ['grafana', 'prometheus', 'loki', 'promtail', 'tempo', 'alloy'],
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
  api: 'Ragweld API',
  tempo: 'Tempo',
  alloy: 'Grafana Alloy',
};

function isKnownService(value: string | null | undefined): value is RagweldDockerService {
  return RAGWELD_DOCKER_SERVICES.includes(value as RagweldDockerService);
}

export function ServicesSubtab() {
  const { status, containers, loading, error, refreshDocker } = useDockerStore();

  const refresh = useCallback(async () => {
    await refreshDocker();
  }, [refreshDocker]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

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
              return (
                <article key={service} style={{ padding: '14px', border: '1px solid var(--line)', borderRadius: '6px', background: 'var(--bg-elev1)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                    <strong>{SERVICE_LABELS[service]}</strong>
                    <span style={{ color: running ? 'var(--ok)' : container ? 'var(--warn)' : 'var(--fg-muted)' }}>
                      {running ? '● Running' : container ? '○ Stopped' : '— Missing'}
                    </span>
                  </div>
                  <div className="small" style={{ color: 'var(--fg-muted)', marginTop: '8px' }}>
                    {container?.status || 'No managed container exists for this service.'}
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
