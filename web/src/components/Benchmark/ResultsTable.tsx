type BenchmarkResult = {
  model: string;
  response: string;
  latency_ms?: number;
  error?: string;
};

type ResultsTableProps = {
  results: BenchmarkResult[];
};

function formatLatencyMs(ms: number | undefined): string {
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return '—';
  return String(Math.round(ms));
}

export function ResultsTable({ results }: ResultsTableProps) {
  const thStyle = {
    textAlign: 'left' as const,
    padding: '10px 12px',
    borderBottom: '1px solid var(--line)',
    background: 'var(--bg-elev2)',
    color: 'var(--fg)',
    fontSize: '12px',
    fontWeight: 700,
    whiteSpace: 'nowrap' as const,
  };

  const tdStyle = {
    padding: '10px 12px',
    borderBottom: '1px solid var(--line)',
    color: 'var(--fg)',
    fontSize: '12px',
    verticalAlign: 'top' as const,
  };

  const monoCellStyle = {
    ...tdStyle,
    fontFamily: 'var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace)',
    whiteSpace: 'pre-wrap' as const,
    wordBreak: 'break-word' as const,
  };

  return (
    <div
      style={{
        overflowX: 'auto',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        background: 'var(--bg-elev1)',
      }}
    >
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
        }}
        aria-label="Benchmark results"
      >
        <thead>
          <tr>
            <th scope="col" style={thStyle}>
              Model
            </th>
            <th scope="col" style={thStyle}>
              Latency (ms)
            </th>
            <th scope="col" style={thStyle}>
              Response
            </th>
            <th scope="col" style={thStyle}>
              Error
            </th>
          </tr>
        </thead>
        <tbody>
          {results.length === 0 ? (
            <tr>
              <td style={{ ...tdStyle, color: 'var(--fg-muted)' }} colSpan={4}>
                No results yet.
              </td>
            </tr>
          ) : (
            results.map((r, idx) => (
              <tr key={`${r.model}:${idx}`}>
                <td style={monoCellStyle}>{r.model || '—'}</td>
                <td style={tdStyle}>{formatLatencyMs(r.latency_ms)}</td>
                <td style={monoCellStyle}>{r.response || '—'}</td>
                <td
                  style={{
                    ...monoCellStyle,
                    color: r.error ? 'var(--err)' : 'var(--fg-muted)',
                  }}
                >
                  {r.error || '—'}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

