import { useEffect, useState } from 'react';
import * as DashAPI from '@/api/dashboard';
import { useActiveRepo } from '@/stores/useRepoStore';
import type { ObservabilityIncident, ObservabilityIncidentsResponse } from '@/types/generated';

type Props = {
  title?: string;
  subtitle?: string;
  corpusId?: string | null;
};

function toneStyles(severity: string): { border: string; background: string } {
  if (severity === 'critical') {
    return {
      border: '1px solid rgba(239, 68, 68, 0.45)',
      background: 'rgba(71, 18, 18, 0.72)',
    };
  }
  if (severity === 'warning') {
    return {
      border: '1px solid rgba(245, 158, 11, 0.35)',
      background: 'rgba(61, 36, 6, 0.68)',
    };
  }
  return {
    border: '1px solid rgba(112, 130, 156, 0.22)',
    background: 'rgba(10, 23, 35, 0.82)',
  };
}

function renderLinks(
  incident: ObservabilityIncident
): Array<{ key: string; href: string; label: string; external: boolean }> {
  const links: Array<{ key: string; href: string; label: string; external: boolean }> = [];
  for (const link of incident.workbench_links || []) {
    const href = String(link?.path || '').trim();
    const label = String(link?.label || '').trim();
    if (!href || !label) continue;
    links.push({ key: `wb:${label}:${href}`, href, label, external: false });
  }
  for (const link of incident.links || []) {
    const href = String(link?.url || '').trim();
    const label = String(link?.label || '').trim();
    if (!href || !label) continue;
    links.push({ key: `ext:${label}:${href}`, href, label, external: true });
  }
  return links;
}

export function ObservabilityIncidentsBoard({
  title = 'Incident Feed',
  subtitle = 'Unified incident truth across infrastructure, workflow, retrieval, eval, benchmark, and prompt regression signals.',
  corpusId,
}: Props) {
  const activeRepo = useActiveRepo();
  const scopedCorpusId = String(corpusId ?? activeRepo ?? '').trim();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [payload, setPayload] = useState<ObservabilityIncidentsResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const nextPayload = await DashAPI.getObservabilityIncidents(scopedCorpusId || undefined);
        if (cancelled) return;
        setPayload(nextPayload);
        if (!nextPayload) {
          setError('Incident feed did not respond.');
        }
      } catch (incidentError) {
        if (cancelled) return;
        setError(incidentError instanceof Error ? incidentError.message : 'Failed to load incident feed');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    const interval = window.setInterval(() => void load(), 30000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [scopedCorpusId]);

  const incidents = payload?.incidents || [];

  return (
    <section
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 16,
        padding: 24,
        borderRadius: 18,
        border: '1px solid rgba(112, 130, 156, 0.22)',
        background:
          'radial-gradient(circle at top right, rgba(244, 162, 97, 0.12), transparent 24%), linear-gradient(180deg, rgba(13, 26, 38, 0.94), rgba(9, 18, 27, 0.98))',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 10, letterSpacing: '0.18em', textTransform: 'uppercase', color: 'rgba(180, 193, 210, 0.72)' }}>
            Grafana Workspace
          </div>
          <h3 style={{ margin: '6px 0 8px', fontSize: 24, color: 'var(--fg)' }}>{title}</h3>
          <p style={{ margin: 0, maxWidth: 72 * 8, fontSize: 13, lineHeight: 1.6, color: 'rgba(198, 209, 222, 0.78)' }}>
            {subtitle}
          </p>
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: 'rgba(180, 193, 210, 0.78)' }}>
            critical={payload?.critical_count || 0}
          </span>
          <span style={{ fontSize: 12, color: 'rgba(180, 193, 210, 0.78)' }}>
            total={payload?.total_count || 0}
          </span>
          <span style={{ fontSize: 12, color: 'rgba(180, 193, 210, 0.78)' }}>
            corpus={scopedCorpusId || 'global'}
          </span>
        </div>
      </div>

      {loading ? (
        <div style={{ fontSize: 12, color: 'rgba(180, 193, 210, 0.78)' }}>Refreshing incident feed…</div>
      ) : null}
      {error ? (
        <div
          style={{
            padding: '10px 12px',
            borderRadius: 12,
            border: '1px solid rgba(239, 68, 68, 0.35)',
            background: 'rgba(71, 18, 18, 0.7)',
            color: 'rgba(255, 224, 224, 0.94)',
            fontSize: 12,
          }}
        >
          {error}
        </div>
      ) : null}

      {!error && incidents.length === 0 ? (
        <div
          style={{
            padding: '14px 16px',
            borderRadius: 14,
            border: '1px solid rgba(42, 157, 143, 0.28)',
            background: 'rgba(14, 46, 43, 0.58)',
            color: 'rgba(212, 240, 236, 0.92)',
            fontSize: 13,
          }}
        >
          No active incidents in the current payload. This is where on-call would see infrastructure, workflow, retrieval, eval, benchmark, and prompt-regression trouble when it appears.
        </div>
      ) : null}

      <div style={{ display: 'grid', gap: 12 }}>
        {incidents.map((incident) => {
          const links = renderLinks(incident);
          return (
            <article
              key={incident.id}
              style={{
                ...toneStyles(String(incident.severity || 'warning')),
                borderRadius: 14,
                padding: 16,
                display: 'grid',
                gap: 10,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                <div>
                  <div style={{ fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(180, 193, 210, 0.72)' }}>
                    {incident.source} · {incident.status}
                  </div>
                  <div style={{ marginTop: 4, fontSize: 18, fontWeight: 700, color: 'var(--fg)' }}>{incident.title}</div>
                </div>
                <div style={{ fontSize: 12, color: 'rgba(180, 193, 210, 0.82)' }}>
                  severity={incident.severity} · slo={incident.slo_state}
                </div>
              </div>

              <div style={{ fontSize: 14, lineHeight: 1.5, color: 'rgba(225, 233, 241, 0.92)' }}>{incident.summary}</div>
              {incident.operator_hint ? (
                <div style={{ fontSize: 12, lineHeight: 1.5, color: 'rgba(198, 209, 222, 0.82)' }}>
                  {incident.operator_hint}
                </div>
              ) : null}

              {incident.change_correlation?.length ? (
                <div style={{ display: 'grid', gap: 6 }}>
                  {incident.change_correlation.map((change) => (
                    <div
                      key={`${incident.id}-${change.kind}-${change.label}`}
                      style={{
                        padding: '8px 10px',
                        borderRadius: 10,
                        background: 'rgba(8, 18, 29, 0.48)',
                        border: '1px solid rgba(112, 130, 156, 0.18)',
                        fontSize: 12,
                        color: 'rgba(198, 209, 222, 0.84)',
                      }}
                    >
                      <strong>{change.label}</strong>
                      {change.previous_value || change.current_value
                        ? ` · ${change.previous_value || 'unknown'} -> ${change.current_value || 'unknown'}`
                        : ''}
                      {change.detail ? ` · ${change.detail}` : ''}
                    </div>
                  ))}
                </div>
              ) : null}

              {links.length ? (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {links.map((link) => (
                    <a
                      key={link.key}
                      href={link.href}
                      target={link.external ? '_blank' : undefined}
                      rel={link.external ? 'noreferrer' : undefined}
                      style={{
                        textDecoration: 'none',
                        borderRadius: 999,
                        border: '1px solid rgba(130, 154, 180, 0.24)',
                        background: 'rgba(10, 23, 35, 0.88)',
                        color: 'var(--fg)',
                        padding: '8px 12px',
                        fontSize: 12,
                        fontWeight: 600,
                      }}
                    >
                      {link.label}
                    </a>
                  ))}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export default ObservabilityIncidentsBoard;
