type SplitScreenResult = {
  model: string;
  response: string;
  latency_ms?: number;
  error?: string;
};

type SplitScreenProps = {
  results: SplitScreenResult[];
};

function cx(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(' ');
}

function formatLatencyMs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 10_000) return `${(ms / 1000).toFixed(2)}s`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function SplitScreen({ results }: SplitScreenProps) {
  const hasThreeOrMore = results.length >= 3;
  const hasFourOrMore = results.length >= 4;
  const single = results.length === 1;

  return (
    <div
      className={cx(
        'grid gap-3',
        'grid-cols-2',
        hasThreeOrMore && 'lg:grid-cols-3',
        hasFourOrMore && 'xl:grid-cols-4'
      )}
      style={{ width: '100%' }}
      data-testid="benchmark-splitscreen"
    >
      {results.map((r, idx) => {
        const errorText = String(r.error || '').trim();
        const responseText = String(r.response || '');
        const hasLatency = typeof r.latency_ms === 'number' && Number.isFinite(r.latency_ms);

        return (
          <section
            key={`${r.model}-${idx}`}
            className={cx(single && 'col-span-2')}
            style={{
              background: 'var(--bg-elev1)',
              border: '1px solid var(--line)',
              borderRadius: '12px',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
              minHeight: 280,
            }}
            aria-label={`Benchmark result for ${r.model}`}
          >
            <header
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                justifyContent: 'space-between',
                gap: 12,
                padding: '12px 14px',
                borderBottom: '1px solid var(--line)',
                background: 'var(--bg-elev2)',
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    color: 'var(--fg)',
                    lineHeight: 1.2,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                  title={r.model}
                >
                  {r.model}
                </div>
                <div style={{ marginTop: 4, fontSize: 12, color: 'var(--fg-muted)' }}>
                  {hasLatency ? `Latency: ${formatLatencyMs(r.latency_ms as number)}` : 'Latency: —'}
                </div>
              </div>

              <div
                style={{
                  flex: '0 0 auto',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '4px 10px',
                  borderRadius: 999,
                  fontSize: 11,
                  fontWeight: 700,
                  border: `1px solid ${errorText ? 'var(--err)' : 'var(--ok)'}`,
                  background: errorText ? 'rgba(255, 107, 107, 0.10)' : 'rgba(0, 255, 136, 0.10)',
                  color: errorText ? 'var(--err)' : 'var(--ok)',
                }}
                aria-label={errorText ? 'Error' : 'Success'}
              >
                <span aria-hidden="true">{errorText ? '✕' : '✓'}</span>
                <span>{errorText ? 'Error' : 'OK'}</span>
              </div>
            </header>

            <div style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 10, flex: 1, minHeight: 0 }}>
              {errorText ? (
                <div
                  style={{
                    background: 'rgba(255, 107, 107, 0.10)',
                    border: '1px solid rgba(255, 107, 107, 0.35)',
                    borderRadius: 10,
                    padding: '10px 12px',
                    color: 'var(--err)',
                    fontSize: 12,
                    lineHeight: 1.4,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                  title={errorText}
                >
                  {errorText}
                </div>
              ) : null}

              <pre
                style={{
                  margin: 0,
                  padding: '12px 12px',
                  background: 'rgba(0, 0, 0, 0.18)',
                  border: '1px solid var(--line)',
                  borderRadius: 10,
                  color: 'var(--fg)',
                  fontSize: 12,
                  lineHeight: 1.45,
                  fontFamily: 'var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace)',
                  whiteSpace: 'pre-wrap',
                  overflow: 'auto',
                  flex: 1,
                  minHeight: 0,
                }}
                aria-label="Model response"
              >
                {responseText || (errorText ? '' : '—')}
              </pre>
            </div>
          </section>
        );
      })}
    </div>
  );
}

