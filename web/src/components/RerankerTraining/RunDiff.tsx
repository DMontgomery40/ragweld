import { useEffect, useMemo, useState } from 'react';
import type { RerankerTrainDiffResponse, RerankerTrainRunMeta } from '@/types/generated';
import { rerankerTrainingService } from '@/services/RerankerTrainingService';

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
  if (!Number.isFinite(v)) return String(v);
  if (v < 10) return `${v.toFixed(2)}s`;
  if (v < 60) return `${v.toFixed(1)}s`;
  return `${v.toFixed(0)}s`;
}

export function RunDiff({ runs }: Props) {
  const sorted = useMemo(() => {
    return [...runs].sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
  }, [runs]);

  const [baselineRunId, setBaselineRunId] = useState<string>('');
  const [currentRunId, setCurrentRunId] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [diff, setDiff] = useState<RerankerTrainDiffResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sorted.length) return;
    if (!currentRunId) setCurrentRunId(sorted[0].run_id);
    if (!baselineRunId && sorted.length > 1) setBaselineRunId(sorted[1].run_id);
  }, [sorted, currentRunId, baselineRunId]);

  useEffect(() => {
    const canDiff = baselineRunId && currentRunId && baselineRunId !== currentRunId;
    if (!canDiff) {
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
    <div
      style={{
        background: 'var(--bg-elev1)',
        border: '1px solid var(--line)',
        borderRadius: 10,
        padding: 14,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 10 }}>Run diff</div>

      {sorted.length < 2 ? (
        <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Need at least two runs to compare.</div>
      ) : (
        <>
          <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
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

          {loading && <div style={{ marginTop: 10, fontSize: 12, color: 'var(--fg-muted)' }}>Computing…</div>}
          {error && (
            <div
              style={{
                marginTop: 10,
                padding: '10px 12px',
                borderRadius: 8,
                border: '1px solid var(--err)',
                background: 'rgba(255, 107, 107, 0.08)',
                color: 'var(--fg)',
                fontSize: 12,
              }}
            >
              {error}
            </div>
          )}

          {diff && diff.compatible === false && (
            <div
              style={{
                marginTop: 10,
                padding: '10px 12px',
                borderRadius: 8,
                border: '1px solid var(--warn)',
                background: 'rgba(var(--warn-rgb), 0.08)',
                color: 'var(--fg)',
                fontSize: 12,
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: 4 }}>Incompatible runs</div>
              <div style={{ color: 'var(--fg-muted)' }}>{diff.reason || 'Primary metric/k differ.'}</div>
            </div>
          )}

          {diff && diff.compatible !== false && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 8 }}>
                Primary: <span style={{ fontFamily: 'var(--font-mono)' }}>{diff.primary_metric}</span>
                {diff.primary_metric !== 'map' && diff.primary_k != null ? (
                  <span style={{ fontFamily: 'var(--font-mono)' }}>@{diff.primary_k}</span>
                ) : null}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
                <div style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 10 }}>
                  <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Δ primary best</div>
                  <div style={{ fontSize: 16, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                    {formatDelta(diff.delta_primary_best)}
                  </div>
                </div>
                <div style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 10 }}>
                  <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Δ time-to-best</div>
                  <div style={{ fontSize: 16, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                    {diff.delta_time_to_best_secs == null
                      ? '—'
                      : `${diff.delta_time_to_best_secs > 0 ? '+' : ''}${formatSeconds(diff.delta_time_to_best_secs)}`}
                  </div>
                </div>
                <div style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 10 }}>
                  <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Δ stability stddev</div>
                  <div style={{ fontSize: 16, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                    {formatDelta(diff.delta_stability_stddev)}
                  </div>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

