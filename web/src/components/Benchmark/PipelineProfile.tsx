type PipelineProfileResult = {
  model?: string;
  model_id?: string;
  model_name?: string;
  breakdown_ms?: Record<string, number>;
};

type PipelineProfileProps = {
  results: PipelineProfileResult[];
};

function formatMs(ms: number): string {
  if (!Number.isFinite(ms)) return `${ms}ms`;
  if (Math.abs(ms - Math.round(ms)) < 1e-6) return `${Math.round(ms)}ms`;
  return `${ms.toFixed(1)}ms`;
}

function getModelLabel(r: PipelineProfileResult, idx: number): string {
  return r.model ?? r.model_name ?? r.model_id ?? `Model ${idx + 1}`;
}

export function PipelineProfile({ results }: PipelineProfileProps) {
  const withBreakdown = results
    .map((r, idx) => {
      const breakdown = r.breakdown_ms;
      if (!breakdown || Object.keys(breakdown).length === 0) return null;

      const entries = Object.entries(breakdown).sort((a, b) => b[1] - a[1]);
      const label = getModelLabel(r, idx);

      return (
        <div
          key={`${label}-${idx}`}
          style={{
            padding: 12,
            border: '1px solid var(--line)',
            borderRadius: 10,
            background: 'var(--bg-elev1)',
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg)', marginBottom: 8 }}>{label}</div>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 6 }}>
            {entries.map(([stage, ms]) => (
              <li
                key={stage}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 10,
                  fontSize: 12,
                  color: 'var(--fg)',
                  background: 'var(--bg-elev2)',
                  border: '1px solid var(--line)',
                  borderRadius: 8,
                  padding: '6px 10px',
                }}
              >
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--fg-muted)' }}>{stage}</span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{formatMs(ms)}</span>
              </li>
            ))}
          </ul>
        </div>
      );
    })
    .filter((x): x is NonNullable<typeof x> => x !== null);

  if (withBreakdown.length === 0) return null;

  return <div style={{ display: 'grid', gap: 12 }}>{withBreakdown}</div>;
}

