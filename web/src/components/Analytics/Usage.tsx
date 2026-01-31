import { useState, useEffect } from 'react';
import { useAPI } from '@/hooks';

interface UsageData {
  summary: {
    totalQueries: number;
    activeUsers: number;
    activeRepos: number;
    cacheHitRate: number;
  };
  queryVolume: Array<{ date: string; count: number }>;
  topRepos: Array<{ name: string; queries: number }>;
  topUsers: Array<{ name: string; queries: number }>;
  cache: {
    size: number;
    hitRate: number;
    missRate: number;
    evictionRate: number;
  };
}

export function Usage() {
  const { api } = useAPI();
  const [data, setData] = useState<UsageData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch(api('/analytics/usage'));
        if (response.ok) {
          setData(await response.json());
        }
      } catch (error) {
        console.error('Failed to fetch usage data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [api]);

  if (loading || !data) {
    return <div style={{ padding: '24px' }}>Loading usage data...</div>;
  }

  return (
    <div className="usage-container">
      {/* Summary Cards */}
      <div className="summary-section">
        <h3>Usage Summary</h3>
        <div className="summary-grid">
          <div className="summary-card">
            <div className="summary-label">Total Queries</div>
            <div className="summary-value">{data.summary.totalQueries.toLocaleString()}</div>
          </div>
          <div className="summary-card">
            <div className="summary-label">Active Users</div>
            <div className="summary-value">{data.summary.activeUsers}</div>
          </div>
          <div className="summary-card">
            <div className="summary-label">Active Corpora</div>
            <div className="summary-value">{data.summary.activeRepos}</div>
          </div>
          <div className="summary-card">
            <div className="summary-label">Cache Hit Rate</div>
            <div className="summary-value">{(data.summary.cacheHitRate * 100).toFixed(1)}%</div>
          </div>
        </div>
      </div>

      {/* Query Volume Chart */}
      <div className="chart-section">
        <h3>Query Volume (Daily)</h3>
        <div className="chart">
          {data.queryVolume.map((day, idx) => (
            <div key={idx} className="chart-bar-wrapper">
              <div
                className="chart-bar"
                style={{
                  height: `${
                    (day.count / Math.max(...data.queryVolume.map((d) => d.count))) * 100
                  }%`
                }}
                title={`${day.date}: ${day.count} queries`}
              ></div>
              <div className="chart-label">{day.date.split('-').slice(1).join('/')}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Top Repos & Users */}
      <div className="tables-section">
        <div className="table-column">
          <h3>Top Repositories</h3>
          <table>
            <thead>
              <tr>
                <th>Repository</th>
                <th>Queries</th>
              </tr>
            </thead>
            <tbody>
              {data.topRepos.map((repo, idx) => (
                <tr key={idx}>
                  <td>{repo.name}</td>
                  <td>{repo.queries.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="table-column">
          <h3>Top Users</h3>
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Queries</th>
              </tr>
            </thead>
            <tbody>
              {data.topUsers.map((user, idx) => (
                <tr key={idx}>
                  <td>{user.name}</td>
                  <td>{user.queries.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Cache Statistics */}
      <div className="cache-section">
        <h3>Cache Statistics</h3>
        <div className="cache-grid">
          <div className="cache-card">
            <div className="cache-label">Cache Size</div>
            <div className="cache-value">{(data.cache.size / 1024 / 1024).toFixed(2)} MB</div>
          </div>
          <div className="cache-card hit">
            <div className="cache-label">Hit Rate</div>
            <div className="cache-value">{(data.cache.hitRate * 100).toFixed(1)}%</div>
          </div>
          <div className="cache-card miss">
            <div className="cache-label">Miss Rate</div>
            <div className="cache-value">{(data.cache.missRate * 100).toFixed(1)}%</div>
          </div>
          <div className="cache-card eviction">
            <div className="cache-label">Eviction Rate</div>
            <div className="cache-value">{(data.cache.evictionRate * 100).toFixed(1)}%</div>
          </div>
        </div>
      </div>

      <style>{`
        .usage-container {
          padding: 24px;
          display: flex;
          flex-direction: column;
          gap: 24px;
        }

        .summary-section,
        .chart-section,
        .cache-section {
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

        .summary-grid,
        .cache-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 16px;
        }

        .summary-card,
        .cache-card {
          background: var(--bg-elev2);
          border: 1px solid var(--line);
          border-radius: 6px;
          padding: 16px;
          text-align: center;
        }

        .cache-card.hit {
          border-color: var(--ok);
        }

        .cache-card.miss {
          border-color: var(--warn);
        }

        .cache-card.eviction {
          border-color: var(--err);
        }

        .summary-label,
        .cache-label {
          font-size: 12px;
          color: var(--fg-muted);
          margin-bottom: 8px;
        }

        .summary-value,
        .cache-value {
          font-size: 28px;
          font-weight: 700;
          color: var(--fg);
        }

        .chart {
          display: flex;
          align-items: flex-end;
          gap: 4px;
          height: 200px;
        }

        .chart-bar-wrapper {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          height: 100%;
          justify-content: flex-end;
        }

        .chart-bar {
          width: 100%;
          background: var(--accent);
          border-radius: 4px 4px 0 0;
          transition: height 0.3s;
          cursor: pointer;
        }

        .chart-bar:hover {
          opacity: 0.8;
        }

        .chart-label {
          font-size: 10px;
          color: var(--fg-muted);
          margin-top: 8px;
        }

        .tables-section {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
          gap: 24px;
        }

        .table-column {
          background: var(--bg-elev1);
          border: 1px solid var(--line);
          border-radius: 6px;
          padding: 20px;
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
        }

        td {
          padding: 12px;
          border-bottom: 1px solid var(--line);
          font-size: 13px;
          color: var(--fg);
        }

        tr:hover {
          background: var(--bg-elev2);
        }
      `}</style>
    </div>
  );
}
