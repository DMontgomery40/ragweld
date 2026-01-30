import { useState, useEffect } from 'react';
import { useAPI } from '@/hooks';

interface CostData {
  breakdown: {
    embeddings: number;
    llm: number;
    reranker: number;
    storage: number;
  };
  daily: Array<{ date: string; cost: number }>;
  detailed: Array<{
    date: string;
    component: string;
    requests: number;
    cost: number;
  }>;
  projectedMonthly: number;
  budgetAlert: boolean;
}

export function Cost() {
  const { api } = useAPI();
  const [period, setPeriod] = useState<'today' | 'week' | 'month' | 'custom'>('today');
  const [costData, setCostData] = useState<CostData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchCostData = async () => {
      setLoading(true);
      try {
        const response = await fetch(api(`/analytics/cost?period=${period}`));
        if (response.ok) {
          const data = await response.json();
          setCostData(data);
        }
      } catch (error) {
        console.error('Failed to fetch cost data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchCostData();
  }, [api, period]);

  const exportCSV = () => {
    if (!costData) return;

    const csv = [
      ['Date', 'Component', 'Requests', 'Cost'],
      ...costData.detailed.map((row) => [
        row.date,
        row.component,
        row.requests.toString(),
        row.cost.toFixed(4)
      ])
    ]
      .map((row) => row.join(','))
      .join('\n');

    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `cost-report-${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  if (loading || !costData) {
    return (
      <div style={{ padding: '24px', textAlign: 'center' }}>
        <div style={{ fontSize: '14px', color: 'var(--fg-muted)' }}>Loading cost data...</div>
      </div>
    );
  }

  const totalCost = Object.values(costData.breakdown).reduce((sum, val) => sum + val, 0);

  return (
    <div className="cost-container">
      {/* Period Selector */}
      <div className="period-selector">
        <button
          className={`period-btn ${period === 'today' ? 'active' : ''}`}
          onClick={() => setPeriod('today')}
        >
          Today
        </button>
        <button
          className={`period-btn ${period === 'week' ? 'active' : ''}`}
          onClick={() => setPeriod('week')}
        >
          Week
        </button>
        <button
          className={`period-btn ${period === 'month' ? 'active' : ''}`}
          onClick={() => setPeriod('month')}
        >
          Month
        </button>
        <button
          className={`period-btn ${period === 'custom' ? 'active' : ''}`}
          onClick={() => setPeriod('custom')}
        >
          Custom
        </button>
        <button className="export-btn" onClick={exportCSV}>
          Export CSV
        </button>
      </div>

      {/* Budget Alert */}
      {costData.budgetAlert && (
        <div className="budget-alert">
          ⚠️ Warning: Monthly spending is approaching or exceeding your budget threshold
        </div>
      )}

      {/* Cost Breakdown Pie Chart (simulated) */}
      <div className="breakdown-section">
        <h3>Cost Breakdown</h3>
        <div className="breakdown-grid">
          <div className="breakdown-card">
            <div className="breakdown-label">Embeddings</div>
            <div className="breakdown-value">${costData.breakdown.embeddings.toFixed(2)}</div>
            <div className="breakdown-percent">
              {((costData.breakdown.embeddings / totalCost) * 100).toFixed(1)}%
            </div>
          </div>
          <div className="breakdown-card">
            <div className="breakdown-label">LLM</div>
            <div className="breakdown-value">${costData.breakdown.llm.toFixed(2)}</div>
            <div className="breakdown-percent">
              {((costData.breakdown.llm / totalCost) * 100).toFixed(1)}%
            </div>
          </div>
          <div className="breakdown-card">
            <div className="breakdown-label">Reranker</div>
            <div className="breakdown-value">${costData.breakdown.reranker.toFixed(2)}</div>
            <div className="breakdown-percent">
              {((costData.breakdown.reranker / totalCost) * 100).toFixed(1)}%
            </div>
          </div>
          <div className="breakdown-card">
            <div className="breakdown-label">Storage</div>
            <div className="breakdown-value">${costData.breakdown.storage.toFixed(2)}</div>
            <div className="breakdown-percent">
              {((costData.breakdown.storage / totalCost) * 100).toFixed(1)}%
            </div>
          </div>
        </div>
      </div>

      {/* Cost Table */}
      <div className="table-section">
        <h3>Detailed Cost Breakdown</h3>
        <div className="table-wrapper">
          <table className="cost-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Component</th>
                <th>Requests</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {costData.detailed.map((row, idx) => (
                <tr key={idx}>
                  <td>{row.date}</td>
                  <td>{row.component}</td>
                  <td>{row.requests.toLocaleString()}</td>
                  <td>${row.cost.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Daily Trend */}
      <div className="trend-section">
        <h3>Daily Cost Trend</h3>
        <div className="trend-chart">
          {costData.daily.map((day, idx) => (
            <div key={idx} className="trend-bar-wrapper">
              <div
                className="trend-bar"
                style={{
                  height: `${(day.cost / Math.max(...costData.daily.map((d) => d.cost))) * 100}%`
                }}
                title={`${day.date}: $${day.cost.toFixed(2)}`}
              ></div>
              <div className="trend-label">{day.date.split('-').slice(1).join('/')}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Projected Monthly Cost */}
      <div className="projection-section">
        <h3>Projected Monthly Cost</h3>
        <div className="projection-value">${costData.projectedMonthly.toFixed(2)}</div>
        <div className="projection-note">Based on current usage patterns</div>
      </div>

      <style jsx>{`
        .cost-container {
          padding: 24px;
          display: flex;
          flex-direction: column;
          gap: 24px;
        }

        .period-selector {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }

        .period-btn,
        .export-btn {
          padding: 8px 16px;
          border-radius: 6px;
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s;
          background: var(--bg-elev1);
          border: 1px solid var(--line);
          color: var(--fg);
        }

        .period-btn.active {
          background: var(--accent);
          color: #000;
          border-color: var(--accent);
        }

        .export-btn {
          margin-left: auto;
          background: var(--accent);
          color: #000;
        }

        .export-btn:hover,
        .period-btn:hover {
          opacity: 0.9;
        }

        .budget-alert {
          padding: 12px;
          background: rgba(239, 68, 68, 0.1);
          border: 1px solid rgba(239, 68, 68, 0.3);
          border-radius: 6px;
          color: var(--err);
          font-size: 13px;
        }

        .breakdown-section,
        .table-section,
        .trend-section,
        .projection-section {
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

        .breakdown-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 16px;
        }

        .breakdown-card {
          background: var(--bg-elev2);
          border: 1px solid var(--line);
          border-radius: 6px;
          padding: 16px;
          text-align: center;
        }

        .breakdown-label {
          font-size: 12px;
          color: var(--fg-muted);
          margin-bottom: 8px;
        }

        .breakdown-value {
          font-size: 24px;
          font-weight: 700;
          color: var(--fg);
          margin-bottom: 4px;
        }

        .breakdown-percent {
          font-size: 14px;
          color: var(--accent);
        }

        .table-wrapper {
          overflow-x: auto;
        }

        .cost-table {
          width: 100%;
          border-collapse: collapse;
        }

        .cost-table th {
          text-align: left;
          padding: 12px;
          background: var(--bg-elev2);
          border-bottom: 2px solid var(--line);
          font-size: 12px;
          font-weight: 600;
          color: var(--fg-muted);
          text-transform: uppercase;
        }

        .cost-table td {
          padding: 12px;
          border-bottom: 1px solid var(--line);
          font-size: 13px;
          color: var(--fg);
        }

        .cost-table tr:hover {
          background: var(--bg-elev2);
        }

        .trend-chart {
          display: flex;
          align-items: flex-end;
          gap: 8px;
          height: 200px;
        }

        .trend-bar-wrapper {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          height: 100%;
          justify-content: flex-end;
        }

        .trend-bar {
          width: 100%;
          background: var(--accent);
          border-radius: 4px 4px 0 0;
          transition: height 0.3s;
          cursor: pointer;
        }

        .trend-bar:hover {
          opacity: 0.8;
        }

        .trend-label {
          font-size: 10px;
          color: var(--fg-muted);
          margin-top: 8px;
          writing-mode: horizontal-tb;
        }

        .projection-value {
          font-size: 48px;
          font-weight: 700;
          color: var(--fg);
          text-align: center;
          margin-bottom: 8px;
        }

        .projection-note {
          font-size: 13px;
          color: var(--fg-muted);
          text-align: center;
        }
      `}</style>
    </div>
  );
}
