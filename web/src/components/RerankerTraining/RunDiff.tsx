import { useEffect, useMemo, useState } from 'react';
import { rerankerTrainingService } from '@/services/RerankerTrainingService';
import type { RerankerTrainDiffResponse, RerankerTrainRunMeta } from '@/types/generated';

type Props = {
  runs: RerankerTrainRunMeta[];
};

function formatDelta(v: number | null | undefined): string {
  if (v == null) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${v.toFixed(4)}`;
}

function formatSeconds(v: number | null | undefined): string {
  if (v == null) return '—';
  if (v < 10) return `${v.toFixed(2)}s`;
  if (v < 60) return `${v.toFixed(1)}s`;
  return `${v.toFixed(0)}s`;
}

export function RunDiff({ runs }: Props) {
  const sorted = useMemo(() => {
    return [...runs].sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
  }, [runs]);

  const [baselineRunId, setBaselineRunId] = useState('');
  const [currentRunId, setCurrentRunId] = useState('');
  const [loading, setLoading] = useState(false);
  const [diff, setDiff] = useState<RerankerTrainDiffResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sorted.length) return;
    if (!currentRunId) setCurrentRunId(sorted[0].run_id);
    if (!baselineRunId && sorted.length > 1) setBaselineRunId(sorted[1].run_id);
  }, [sorted, currentRunId, baselineRunId]);

  useEffect(() => {
    if (!baselineRunId || !currentRunId || baselineRunId === currentRunId) {
      setDiff(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    void rerankerTrainingService
      .diffRuns(baselineRunId, currentRunId)
      .then((res) => {
        if (cancelled) return;
        setDiff(res);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Failed to diff runs');
        setDiff(null);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [baselineRunId, currentRunId]);

  return (
    <section className="studio-panel studio-compact-panel" data-testid="studio-run-diff">
      <header className="studio-panel-header">
        <h3 className="studio-panel-title">Run Diff</h3>
      </header>

      {sorted.length < 2 ? (
        <p className="studio-empty">Need at least two runs to compare.</p>
      ) : (
        <>
          <div className="studio-form-grid two">
            <div className="input-group">
              <label>Baseline</label>
              <select value={baselineRunId} onChange={(e) => setBaselineRunId(e.target.value)}>
                <option value="">Select…</option>
                {sorted.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id}
                  </option>
                ))}
              </select>
            </div>
            <div className="input-group">
              <label>Current</label>
              <select value={currentRunId} onChange={(e) => setCurrentRunId(e.target.value)}>
                <option value="">Select…</option>
                {sorted.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {loading ? <p className="studio-empty">Computing diff…</p> : null}
          {error ? <div className="studio-callout studio-callout-err">{error}</div> : null}

          {diff && diff.compatible === false ? (
            <div className="studio-callout studio-callout-warn">{diff.reason || 'Primary metric/k differ.'}</div>
          ) : null}

          {diff && diff.compatible !== false ? (
            <div className="studio-diff-grid">
              <article className="studio-metric-card">
                <span className="studio-metric-name">Δ primary best</span>
                <span className="studio-metric-value studio-mono">{formatDelta(diff.delta_primary_best)}</span>
              </article>
              <article className="studio-metric-card">
                <span className="studio-metric-name">Δ time-to-best</span>
                <span className="studio-metric-value studio-mono">
                  {diff.delta_time_to_best_secs == null
                    ? '—'
                    : `${diff.delta_time_to_best_secs > 0 ? '+' : ''}${formatSeconds(diff.delta_time_to_best_secs)}`}
                </span>
              </article>
              <article className="studio-metric-card">
                <span className="studio-metric-name">Δ stability stddev</span>
                <span className="studio-metric-value studio-mono">{formatDelta(diff.delta_stability_stddev)}</span>
              </article>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
