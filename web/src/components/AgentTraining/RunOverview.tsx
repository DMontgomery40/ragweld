import { TooltipIcon } from '@/components/ui/TooltipIcon';
import type { AgentTrainRun } from '@/types/generated';

type Props = {
  run: AgentTrainRun | null;
  latestMetrics: Record<string, number> | null;
};

function metricLabel(metric: string | null | undefined, goal: AgentTrainRun['primary_goal']): string {
  const m = String(metric || '').trim() || 'metric';
  const g = goal === 'maximize' ? 'maximize' : 'minimize';
  return `${m} (${g})`;
}

function formatMetricValue(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  if (v === 0) return '0.0000';
  if (Math.abs(v) < 1) return v.toFixed(4);
  return v.toFixed(3);
}

export function RunOverview({ run, latestMetrics }: Props) {
  if (!run) {
    return (
      <section className="studio-panel studio-compact-panel">
        <header className="studio-panel-header">
          <h3 className="studio-panel-title">Run Overview</h3>
        </header>
        <p className="studio-empty">Select a run to see details.</p>
      </section>
    );
  }

  const label = metricLabel(run.primary_metric, run.primary_goal);
  const best = run.summary?.primary_metric_best ?? null;
  const final = run.summary?.primary_metric_final ?? null;
  const headline = best ?? final;

  return (
    <section className="studio-panel studio-compact-panel" data-testid="studio-run-overview">
      <header className="studio-panel-header">
        <div>
          <h3 className="studio-panel-title">Run Overview</h3>
          <p className="studio-panel-subtitle studio-mono">{run.run_id}</p>
        </div>
        <div className="studio-overview-headline">
          <span className="studio-overview-label">{label}</span>
          <span className="studio-overview-value studio-mono">{headline == null ? '—' : formatMetricValue(headline)}</span>
        </div>
      </header>

      <div className="studio-inline-help">
        <span className="studio-help-anchor" title="Agent training uses next-token prediction loss on assistant tokens.">
          Metric: eval loss
        </span>
        <TooltipIcon name="RAGWELD_AGENT_PROMOTE_IF_IMPROVES" />
      </div>

      <div className="studio-chip-row">
        <span className="studio-chip">workflow={String(run.workflow_backend || 'local')}</span>
        <span className="studio-chip">tracking={String(run.tracking_backend || 'local')}</span>
        <span className="studio-chip">execution={String(run.execution_backend || 'mlx_qwen3')}</span>
        {run.workflow_run_id ? <span className="studio-chip">workflow_run={run.workflow_run_id}</span> : null}
        {run.tracking_run_id ? <span className="studio-chip">tracking_run={run.tracking_run_id}</span> : null}
      </div>

      {run.operator_hint ? <div className="studio-callout">{run.operator_hint}</div> : null}

      {(run.external_links || []).length ? (
        <div className="studio-mini-grid">
          {(run.external_links || []).map((link) => (
            <a key={`${link.label}-${link.url}`} href={link.url} target="_blank" rel="noreferrer" className="studio-mono">
              {link.label}
            </a>
          ))}
        </div>
      ) : null}

      <div className="studio-metric-grid">
        {(run.metrics_available || []).map((key) => (
          <article key={key} className="studio-metric-card">
            <span className="studio-metric-name">{key}</span>
            <span className="studio-metric-value studio-mono">
              {latestMetrics && latestMetrics[key] != null ? formatMetricValue(Number(latestMetrics[key])) : '—'}
            </span>
          </article>
        ))}
      </div>
    </section>
  );
}
