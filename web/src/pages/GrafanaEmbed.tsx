import { useMemo } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';

type BarPoint = {
  label: string;
  value: number;
  color: string;
};

const retrievalLatency: BarPoint[] = [
  { label: 'Vector', value: 84, color: '#60a5fa' },
  { label: 'Sparse', value: 132, color: '#f59e0b' },
  { label: 'Graph', value: 227, color: '#a78bfa' },
];

const indexCoverage: BarPoint[] = [
  { label: 'Vector chunks', value: 94, color: '#38bdf8' },
  { label: 'Sparse lexicon', value: 89, color: '#fbbf24' },
  { label: 'Graph entities', value: 76, color: '#22c55e' },
];

function formatRange(from: string | null): string {
  if (!from) return 'Last 1h';
  if (from.startsWith('now-')) return `Last ${from.slice(4)}`;
  return from;
}

export default function GrafanaEmbed() {
  const params = useParams();
  const [searchParams] = useSearchParams();

  const range = formatRange(searchParams.get('from'));
  const refresh = searchParams.get('refresh') || '10s';
  const dashboardSlug = (params.slug || 'tribrid-overview').trim();

  const synthetic = useMemo(() => {
    return {
      mrr: 0.73,
      mrrDelta: -0.04,
      p95LatencyMs: 241,
      errorRatePct: 2.3,
      alertThresholdPct: 3.0,
      corpusCount: 7,
      nodes: 48371,
      edges: 132904,
    };
  }, []);

  const overThreshold = synthetic.errorRatePct >= synthetic.alertThresholdPct;

  return (
    <main
      style={{
        minHeight: '100%',
        background:
          'radial-gradient(1200px 420px at 5% -10%, rgba(59,130,246,0.14), rgba(5,7,12,0)) #05070c',
        color: '#dbe6f5',
        fontFamily: '"Space Grotesk", system-ui, sans-serif',
        padding: '14px 16px 24px',
      }}
    >
      <header
        style={{
          border: '1px solid #1f2937',
          borderRadius: '10px',
          background: 'rgba(10, 14, 23, 0.92)',
          padding: '12px 14px',
          marginBottom: '12px',
        }}
      >
        <div style={{ fontSize: '11px', letterSpacing: '0.08em', color: '#93a4bf', textTransform: 'uppercase' }}>
          Dashboards
        </div>
        <div style={{ marginTop: '4px', fontSize: '18px', fontWeight: 700, color: '#f8fbff' }}>{dashboardSlug}</div>
        <div style={{ marginTop: '6px', fontSize: '12px', color: '#9bb0d1', lineHeight: 1.5 }}>
          Simulated data for hosted demo mode. This mirrors where production MRR, error thresholds, latency, and graph
          indexing health would appear.
        </div>
        <div style={{ marginTop: '10px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '11px', color: '#9bb0d1', border: '1px solid #253349', borderRadius: '999px', padding: '3px 8px' }}>
            {range}
          </span>
          <span style={{ fontSize: '11px', color: '#9bb0d1', border: '1px solid #253349', borderRadius: '999px', padding: '3px 8px' }}>
            Refresh {refresh}
          </span>
          <span style={{ fontSize: '11px', color: '#9bb0d1', border: '1px solid #253349', borderRadius: '999px', padding: '3px 8px' }}>
            Updated {new Date().toLocaleTimeString()}
          </span>
        </div>
      </header>

      <section style={{ display: 'grid', gap: '10px', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <article style={{ border: '1px solid #1f2937', borderRadius: '10px', padding: '12px', background: 'rgba(7, 11, 18, 0.9)' }}>
          <div style={{ fontSize: '11px', color: '#8fa0b8', textTransform: 'uppercase' }}>MRR</div>
          <div style={{ marginTop: '8px', fontSize: '26px', fontWeight: 700, color: '#e8f4ff' }}>{synthetic.mrr.toFixed(2)}</div>
          <div style={{ marginTop: '4px', fontSize: '12px', color: synthetic.mrrDelta < 0 ? '#fca5a5' : '#86efac' }}>
            {synthetic.mrrDelta < 0 ? '' : '+'}
            {(synthetic.mrrDelta * 100).toFixed(1)}% vs previous window
          </div>
        </article>

        <article style={{ border: '1px solid #1f2937', borderRadius: '10px', padding: '12px', background: 'rgba(7, 11, 18, 0.9)' }}>
          <div style={{ fontSize: '11px', color: '#8fa0b8', textTransform: 'uppercase' }}>P95 Retrieval Latency</div>
          <div style={{ marginTop: '8px', fontSize: '26px', fontWeight: 700, color: '#e8f4ff' }}>{synthetic.p95LatencyMs}ms</div>
          <div style={{ marginTop: '4px', fontSize: '12px', color: '#93c5fd' }}>Vector + sparse + graph fusion</div>
        </article>

        <article style={{ border: '1px solid #1f2937', borderRadius: '10px', padding: '12px', background: 'rgba(7, 11, 18, 0.9)' }}>
          <div style={{ fontSize: '11px', color: '#8fa0b8', textTransform: 'uppercase' }}>Error Rate</div>
          <div style={{ marginTop: '8px', fontSize: '26px', fontWeight: 700, color: overThreshold ? '#fecaca' : '#e8f4ff' }}>
            {synthetic.errorRatePct.toFixed(1)}%
          </div>
          <div style={{ marginTop: '4px', fontSize: '12px', color: overThreshold ? '#fca5a5' : '#93c5fd' }}>
            Threshold {synthetic.alertThresholdPct.toFixed(1)}% {overThreshold ? '(alerting)' : '(healthy)'}
          </div>
        </article>

        <article style={{ border: '1px solid #1f2937', borderRadius: '10px', padding: '12px', background: 'rgba(7, 11, 18, 0.9)' }}>
          <div style={{ fontSize: '11px', color: '#8fa0b8', textTransform: 'uppercase' }}>Corpora</div>
          <div style={{ marginTop: '8px', fontSize: '26px', fontWeight: 700, color: '#e8f4ff' }}>{synthetic.corpusCount}</div>
          <div style={{ marginTop: '4px', fontSize: '12px', color: '#93c5fd' }}>
            {synthetic.nodes.toLocaleString()} nodes / {synthetic.edges.toLocaleString()} edges
          </div>
        </article>
      </section>

      <section
        style={{
          display: 'grid',
          gap: '10px',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          marginTop: '10px',
        }}
      >
        <article style={{ border: '1px solid #1f2937', borderRadius: '10px', padding: '12px', background: 'rgba(7, 11, 18, 0.9)' }}>
          <h2 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#f0f7ff' }}>Index Snapshot</h2>
          <p style={{ margin: '6px 0 10px', fontSize: '12px', color: '#9bb0d1', lineHeight: 1.5 }}>
            Coverage of the current synthetic indexing run. This is where partial index failure and drift signals would
            be monitored.
          </p>
          <div style={{ display: 'grid', gap: '10px' }}>
            {indexCoverage.map((point) => (
              <div key={point.label}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#c8d6ea' }}>
                  <span>{point.label}</span>
                  <span>{point.value}%</span>
                </div>
                <div style={{ marginTop: '5px', height: '7px', borderRadius: '999px', background: '#0e1522', overflow: 'hidden' }}>
                  <div style={{ width: `${point.value}%`, height: '100%', background: point.color }} />
                </div>
              </div>
            ))}
          </div>
        </article>

        <article style={{ border: '1px solid #1f2937', borderRadius: '10px', padding: '12px', background: 'rgba(7, 11, 18, 0.9)' }}>
          <h2 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#f0f7ff' }}>Latency by Retrieval Mode</h2>
          <p style={{ margin: '6px 0 10px', fontSize: '12px', color: '#9bb0d1', lineHeight: 1.5 }}>
            Compare vector, sparse, and graph latencies before fusion/reranking bottlenecks.
          </p>
          <div style={{ display: 'grid', gap: '10px' }}>
            {retrievalLatency.map((point) => (
              <div key={point.label}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#c8d6ea' }}>
                  <span>{point.label}</span>
                  <span>{point.value}ms</span>
                </div>
                <div style={{ marginTop: '5px', height: '7px', borderRadius: '999px', background: '#0e1522', overflow: 'hidden' }}>
                  <div style={{ width: `${Math.min(100, (point.value / 260) * 100)}%`, height: '100%', background: point.color }} />
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section
        style={{
          display: 'grid',
          gap: '10px',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          marginTop: '10px',
        }}
      >
        <article style={{ border: '1px solid #1f2937', borderRadius: '10px', padding: '12px', background: 'rgba(7, 11, 18, 0.9)' }}>
          <h2 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#f0f7ff' }}>Alerting Flow</h2>
          <p style={{ margin: '6px 0 10px', fontSize: '12px', color: '#9bb0d1', lineHeight: 1.5 }}>
            If error rate exceeds threshold, this panel maps to Slack webhook and on-call escalation setup.
          </p>
          <div
            style={{
              borderRadius: '8px',
              padding: '10px',
              background: overThreshold ? 'rgba(127,29,29,0.26)' : 'rgba(4,47,46,0.28)',
              border: overThreshold ? '1px solid #ef4444' : '1px solid #0d9488',
              fontSize: '12px',
              color: overThreshold ? '#fecaca' : '#99f6e4',
            }}
          >
            {overThreshold
              ? 'Alert active: webhook dispatch queue exceeded threshold.'
              : 'No active alerts. Synthetic demo pipeline is healthy.'}
          </div>
        </article>

        <article style={{ border: '1px solid #1f2937', borderRadius: '10px', padding: '12px', background: 'rgba(7, 11, 18, 0.9)' }}>
          <h2 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#f0f7ff' }}>Ops Notes</h2>
          <ul style={{ margin: '8px 0 0', paddingLeft: '18px', color: '#b8c8df', fontSize: '12px', lineHeight: 1.6 }}>
            <li>Hosted demo route uses synthetic panels for same-origin embed compatibility.</li>
            <li>Local `/web/grafana` can still point to a real Grafana server.</li>
            <li>Switch back to live Grafana by setting `ui.grafana_base_url` to external URL.</li>
          </ul>
        </article>
      </section>
    </main>
  );
}
