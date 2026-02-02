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
      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 14,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Run overview</div>
        <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Select a run to see details.</div>
      </div>
    );
  }

  const k = Number(run.primary_k ?? 10);
  const label = metricLabel(run.primary_metric, k);

  const best = run.summary?.primary_metric_best ?? null;
  const final = run.summary?.primary_metric_final ?? null;
  const headlineVal = best ?? final;

  const rationale = run.metric_profile?.rationale ?? '';

  return (
    <div
      style={{
        background: 'var(--bg-elev1)',
        border: '1px solid var(--line)',
        borderRadius: 10,
        padding: 14,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Run overview</div>
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
            <span style={{ fontFamily: 'var(--font-mono)' }}>{run.run_id}</span>
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Primary metric</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--fg)' }}>
            {label}:{' '}
            <span style={{ fontFamily: 'var(--font-mono)' }}>
              {headlineVal == null ? '—' : formatMetricValue(Number(headlineVal))}
            </span>
          </div>
          {rationale && (
            <div style={{ marginTop: 6, fontSize: 12, color: 'var(--fg-muted)' }}>
              <span title={rationale} style={{ cursor: 'help', textDecoration: 'underline' }}>
                Why?
              </span>
            </div>
          )}
        </div>
      </div>

      <div style={{ marginTop: 12 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Other metrics (latest)</div>
        {!latestMetrics ? (
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>No metrics events yet.</div>
        ) : (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
              gap: 10,
            }}
          >
            {(run.metrics_available || []).map((key) => (
              <div
                key={key}
                style={{
                  border: '1px solid var(--line)',
                  borderRadius: 10,
                  padding: 10,
                  background: 'var(--bg-elev2)',
                }}
              >
                <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>{key}</div>
                <div style={{ fontSize: 15, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                  {latestMetrics[key] == null ? '—' : formatMetricValue(Number(latestMetrics[key]))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

