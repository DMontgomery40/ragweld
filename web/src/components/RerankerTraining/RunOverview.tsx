import { TooltipIcon } from '@/components/ui/TooltipIcon';
import type { RerankerTrainRun } from '@/types/generated';

type Props = {
  run: RerankerTrainRun | null;
  latestMetrics: Record<string, number> | null;
};

function metricLabel(metric: RerankerTrainRun['primary_metric'], k: number): string {
  if (metric === 'mrr') return `MRR@${k}`;
  if (metric === 'ndcg') return `nDCG@${k}`;
  return 'MAP';
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

  const k = Number(run.primary_k ?? 10);
  const label = metricLabel(run.primary_metric, k);
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

      {run.metric_profile?.rationale ? (
        <div className="studio-inline-help">
          <span className="studio-help-anchor" title={run.metric_profile.rationale}>
            Metric rationale
          </span>
          <TooltipIcon name="RERANKER_TRAIN_RECOMMENDED_METRIC" />
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
