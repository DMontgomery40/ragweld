import { useState, useEffect } from 'react';
import { useAPI } from '@/hooks';

interface PerformanceData {
  latency: {
    avg: number;
    p50: number;
    p95: number;
    p99: number;
    histogram: Array<{ bucket: string; count: number }>;
  };
  throughput: {
    qps: number;
    qpm: number;
    peak: number;
  };
  success: {
    successRate: number;
    errorRate: number;
    timeoutRate: number;
  };
  slowQueries: Array<{
    id: string;
    query: string;
    latency: number;
    timestamp: string;
  }>;
}

export function Performance() {
  const { api } = useAPI();
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch(api('/analytics/performance'));
        if (response.ok) {
          setData(await response.json());
        }
      } catch (error) {
        console.error('Failed to fetch performance data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [api]);

  if (loading || !data) {
    return <div style={{ padding: '24px' }}>Loading performance data...</div>;
  }

  return (
    <div className="performance-container">
      {/* Latency Metrics */}
      <div className="metrics-section">
        <h3>Latency Metrics</h3>
        <div className="metrics-grid">
          <div className="metric-card">
            <div className="metric-label">Average</div>
            <div className="metric-value">{data.latency.avg.toFixed(2)}ms</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">P50</div>
            <div className="metric-value">{data.latency.p50.toFixed(2)}ms</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">P95</div>
            <div className="metric-value">{data.latency.p95.toFixed(2)}ms</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">P99</div>
            <div className="metric-value">{data.latency.p99.toFixed(2)}ms</div>
          </div>
        </div>
      </div>

      {/* Throughput */}
      <div className="metrics-section">
        <h3>Throughput</h3>
        <div className="metrics-grid">
          <div className="metric-card">
            <div className="metric-label">Queries/Second</div>
            <div className="metric-value">{data.throughput.qps.toFixed(2)}</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Queries/Minute</div>
            <div className="metric-value">{data.throughput.qpm.toFixed(0)}</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Peak Throughput</div>
            <div className="metric-value">{data.throughput.peak.toFixed(2)} QPS</div>
          </div>
        </div>
      </div>

      {/* Success Rate */}
      <div className="metrics-section">
        <h3>Success Rate</h3>
        <div className="metrics-grid">
          <div className="metric-card success">
            <div className="metric-label">Success Rate</div>
            <div className="metric-value">{(data.success.successRate * 100).toFixed(2)}%</div>
          </div>
          <div className="metric-card error">
            <div className="metric-label">Error Rate</div>
            <div className="metric-value">{(data.success.errorRate * 100).toFixed(2)}%</div>
          </div>
          <div className="metric-card timeout">
            <div className="metric-label">Timeout Rate</div>
            <div className="metric-value">{(data.success.timeoutRate * 100).toFixed(2)}%</div>
          </div>
        </div>
      </div>

      {/* Latency Histogram */}
      <div className="histogram-section">
        <h3>Latency Distribution</h3>
        <div className="histogram">
          {data.latency.histogram.map((bucket, idx) => (
            <div key={idx} className="histogram-bar-wrapper">
              <div
                className="histogram-bar"
                style={{
                  height: `${
                    (bucket.count / Math.max(...data.latency.histogram.map((b) => b.count))) * 100
                  }%`
                }}
                title={`${bucket.bucket}: ${bucket.count} queries`}
              ></div>
              <div className="histogram-label">{bucket.bucket}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Slow Queries */}
      <div className="slow-queries-section">
        <h3>Top Slowest Queries</h3>
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Query</th>
                <th>Latency</th>
                <th>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {data.slowQueries.map((q) => (
                <tr key={q.id}>
                  <td className="query-text">{q.query}</td>
                  <td>{q.latency.toFixed(2)}ms</td>
                  <td>{new Date(q.timestamp).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <style jsx>{`
        .performance-container {
          padding: 24px;
          display: flex;
          flex-direction: column;
          gap: 24px;
        }

        .metrics-section,
        .histogram-section,
        .slow-queries-section {
          background: var(--bg-elev1);
          border: 1px solid var(--line);
          border-radius: 6px;
          padding: 20px;
        }

        h3 {
          font-size: 16px;
          font-weight: 600;
          color: var(--fg);
          margin: 0 0 16px 0;
        }

        .metrics-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 16px;
        }

        .metric-card {
          background: var(--bg-elev2);
          border: 1px solid var(--line);
          border-radius: 6px;
          padding: 16px;
          text-align: center;
        }

        .metric-card.success {
          border-color: var(--ok);
        }

        .metric-card.error {
          border-color: var(--err);
        }

        .metric-card.timeout {
          border-color: var(--warn);
        }

        .metric-label {
          font-size: 12px;
          color: var(--fg-muted);
          margin-bottom: 8px;
        }

        .metric-value {
          font-size: 24px;
          font-weight: 700;
          color: var(--fg);
        }

        .histogram {
          display: flex;
          align-items: flex-end;
          gap: 4px;
          height: 200px;
        }

        .histogram-bar-wrapper {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          height: 100%;
          justify-content: flex-end;
        }

        .histogram-bar {
          width: 100%;
          background: var(--accent);
          border-radius: 4px 4px 0 0;
          transition: all 0.2s;
          cursor: pointer;
        }

        .histogram-bar:hover {
          opacity: 0.8;
        }

        .histogram-label {
          font-size: 10px;
          color: var(--fg-muted);
          margin-top: 8px;
          transform: rotate(-45deg);
          transform-origin: center;
        }

        .table-wrapper {
          overflow-x: auto;
        }

        table {
          width: 100%;
          border-collapse: collapse;
        }

        th {
          text-align: left;
          padding: 12px;
          background: var(--bg-elev2);
          border-bottom: 2px solid var(--line);
          font-size: 12px;
          font-weight: 600;
          color: var(--fg-muted);
          text-transform: uppercase;
        }

        td {
          padding: 12px;
          border-bottom: 1px solid var(--line);
          font-size: 13px;
          color: var(--fg);
        }

        .query-text {
          max-width: 400px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        tr:hover {
          background: var(--bg-elev2);
        }
      `}</style>
    </div>
  );
}
