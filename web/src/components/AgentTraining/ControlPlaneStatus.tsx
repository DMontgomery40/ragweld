import type { AgentTrainControlPlaneStatusResponse } from '@/types/generated';

type Props = {
  status: AgentTrainControlPlaneStatusResponse | null;
  loading: boolean;
  error: string | null;
};

function componentStateChipClass(state: string | null | undefined): string {
  if (state === 'ready') return 'studio-chip studio-chip-ok';
  if (state === 'degraded' || state === 'unconfigured') return 'studio-chip studio-chip-warn';
  return 'studio-chip';
}

export function ControlPlaneStatus({ status, loading, error }: Props) {
  return (
    <section className="studio-panel studio-compact-panel" data-testid="learning-agent-control-plane-status">
      <header className="studio-panel-header">
        <div>
          <h3 className="studio-panel-title">Training Control Plane</h3>
          <p className="studio-panel-subtitle">
            Target lane:{' '}
            <span className="studio-mono">
              {status?.lane === 'flyte_mlflow_unsloth' ? 'Flyte + MLflow + Unsloth' : 'Legacy local'}
            </span>
          </p>
        </div>
        <span className={componentStateChipClass(status?.ready ? 'ready' : status?.lane === 'legacy_local' ? 'disabled' : 'degraded')}>
          {loading ? 'loading' : status?.ready ? 'ready' : status?.lane === 'legacy_local' ? 'legacy' : 'not ready'}
        </span>
      </header>

      {error ? <div className="studio-callout studio-callout-err">{error}</div> : null}
      {!error && loading ? <div className="studio-callout">Checking Flyte / MLflow / Unsloth status…</div> : null}

      {status ? (
        <>
          {status.operator_hint ? <div className="studio-callout">{status.operator_hint}</div> : null}

          <div className="studio-chip-row">
            <span className="studio-chip">workflow={status.workflow_backend}</span>
            <span className="studio-chip">tracking={status.tracking_backend}</span>
            <span className="studio-chip">execution={status.execution_backend}</span>
          </div>

          <div className="studio-metric-grid">
            {(status.components || []).map((component) => (
              <article key={component.kind} className="studio-metric-card">
                <span className="studio-metric-name">{component.label}</span>
                <span className={`studio-metric-value studio-mono ${component.state === 'ready' ? '' : ''}`}>
                  {component.state}
                </span>
                <p className="studio-panel-subtitle">{component.detail || '—'}</p>
                {(component.links || []).length ? (
                  <div className="studio-mini-grid">
                    {(component.links || []).map((link) => (
                      <a key={`${component.kind}-${link.label}-${link.url}`} href={link.url} target="_blank" rel="noreferrer" className="studio-mono">
                        {link.label}
                      </a>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        </>
      ) : null}
    </section>
  );
}
