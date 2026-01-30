import { useState, useEffect } from 'react';
import { useAPI } from '@/hooks';

interface Trace {
  id: string;
  timestamp: string;
  duration: number;
  status: 'success' | 'error';
  query: string;
  spans: Array<{
    name: string;
    duration: number;
    startOffset: number;
    tags: Record<string, string>;
  }>;
  error?: string;
}

export function Tracing() {
  const { api } = useAPI();
  const [traces, setTraces] = useState<Trace[]>([]);
  const [selectedTrace, setSelectedTrace] = useState<Trace | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchTraces = async () => {
      try {
        const response = await fetch(api('/analytics/traces'));
        if (response.ok) {
          setTraces(await response.json());
        }
      } catch (error) {
        console.error('Failed to fetch traces:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchTraces();
  }, [api]);

  const filteredTraces = traces.filter(
    (t) =>
      !searchQuery ||
      t.id.includes(searchQuery) ||
      t.query.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const exportTrace = (trace: Trace) => {
    const json = JSON.stringify(trace, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trace-${trace.id}.json`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  if (loading) {
    return <div style={{ padding: '24px' }}>Loading traces...</div>;
  }

  return (
    <div className="tracing-container">
      {/* Search */}
      <div className="search-section">
        <input
          type="search"
          placeholder="Search traces by ID or query..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {/* Trace List */}
      <div className="traces-section">
        <h3>Traces ({filteredTraces.length})</h3>
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Trace ID</th>
                <th>Timestamp</th>
                <th>Duration</th>
                <th>Status</th>
                <th>Query</th>
              </tr>
            </thead>
            <tbody>
              {filteredTraces.map((trace) => (
                <tr
                  key={trace.id}
                  onClick={() => setSelectedTrace(trace)}
                  className={selectedTrace?.id === trace.id ? 'selected' : ''}
                >
                  <td className="trace-id">{trace.id}</td>
                  <td>{new Date(trace.timestamp).toLocaleString()}</td>
                  <td>{trace.duration.toFixed(2)}ms</td>
                  <td>
                    <span className={`status-badge ${trace.status}`}>{trace.status}</span>
                  </td>
                  <td className="query-preview">{trace.query}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Trace Detail */}
      {selectedTrace && (
        <div className="detail-section">
          <div className="detail-header">
            <h3>Trace Details: {selectedTrace.id}</h3>
            <button className="export-btn" onClick={() => exportTrace(selectedTrace)}>
              Export
            </button>
          </div>

          {/* Waterfall */}
          <div className="waterfall">
            <h4>Span Waterfall</h4>
            {selectedTrace.spans.map((span, idx) => (
              <div key={idx} className="span-row">
                <div className="span-name">{span.name}</div>
                <div className="span-timeline">
                  <div
                    className="span-bar"
                    style={{
                      marginLeft: `${(span.startOffset / selectedTrace.duration) * 100}%`,
                      width: `${(span.duration / selectedTrace.duration) * 100}%`
                    }}
                    title={`${span.duration.toFixed(2)}ms`}
                  ></div>
                </div>
                <div className="span-duration">{span.duration.toFixed(2)}ms</div>
              </div>
            ))}
          </div>

          {/* Span Details */}
          <div className="spans-detail">
            <h4>Span Details</h4>
            {selectedTrace.spans.map((span, idx) => (
              <div key={idx} className="span-detail-card">
                <div className="span-detail-name">{span.name}</div>
                <div className="span-detail-meta">
                  Duration: {span.duration.toFixed(2)}ms | Start: {span.startOffset.toFixed(2)}ms
                </div>
                {Object.keys(span.tags).length > 0 && (
                  <div className="span-tags">
                    {Object.entries(span.tags).map(([key, value]) => (
                      <div key={key} className="tag">
                        <span className="tag-key">{key}:</span>
                        <span className="tag-value">{value}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Error Details */}
          {selectedTrace.error && (
            <div className="error-section">
              <h4>Error Details</h4>
              <div className="error-message">{selectedTrace.error}</div>
            </div>
          )}
        </div>
      )}

      <style jsx>{`
        .tracing-container {
          padding: 24px;
          display: flex;
          flex-direction: column;
          gap: 24px;
        }

        .search-section input {
          width: 100%;
          padding: 12px;
          background: var(--input-bg);
          border: 1px solid var(--line);
          border-radius: 6px;
          color: var(--fg);
          font-size: 13px;
        }

        .traces-section,
        .detail-section {
          background: var(--bg-elev1);
          border: 1px solid var(--line);
          border-radius: 6px;
          padding: 20px;
        }

        h3,
        h4 {
          font-size: 16px;
          font-weight: 600;
          color: var(--fg);
          margin: 0 0 16px 0;
        }

        h4 {
          font-size: 14px;
          margin-top: 20px;
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
        }

        td {
          padding: 12px;
          border-bottom: 1px solid var(--line);
          font-size: 13px;
          color: var(--fg);
        }

        tr {
          cursor: pointer;
          transition: background 0.2s;
        }

        tr:hover,
        tr.selected {
          background: var(--bg-elev2);
        }

        .trace-id {
          font-family: monospace;
          font-size: 12px;
        }

        .query-preview {
          max-width: 300px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .status-badge {
          padding: 4px 8px;
          border-radius: 4px;
          font-size: 11px;
          font-weight: 600;
          text-transform: uppercase;
        }

        .status-badge.success {
          background: rgba(34, 197, 94, 0.2);
          color: var(--ok);
        }

        .status-badge.error {
          background: rgba(239, 68, 68, 0.2);
          color: var(--err);
        }

        .detail-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .export-btn {
          padding: 8px 16px;
          background: var(--accent);
          color: #000;
          border: none;
          border-radius: 6px;
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
        }

        .export-btn:hover {
          opacity: 0.9;
        }

        .waterfall {
          margin-bottom: 24px;
        }

        .span-row {
          display: grid;
          grid-template-columns: 200px 1fr 100px;
          gap: 12px;
          align-items: center;
          margin-bottom: 8px;
        }

        .span-name {
          font-size: 12px;
          color: var(--fg);
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .span-timeline {
          position: relative;
          height: 24px;
          background: var(--bg-elev2);
          border-radius: 4px;
        }

        .span-bar {
          position: absolute;
          height: 100%;
          background: var(--accent);
          border-radius: 4px;
          transition: all 0.2s;
          cursor: pointer;
        }

        .span-bar:hover {
          opacity: 0.8;
        }

        .span-duration {
          font-size: 12px;
          color: var(--fg-muted);
          text-align: right;
        }

        .spans-detail {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .span-detail-card {
          background: var(--bg-elev2);
          border: 1px solid var(--line);
          border-radius: 4px;
          padding: 12px;
        }

        .span-detail-name {
          font-size: 14px;
          font-weight: 600;
          color: var(--fg);
          margin-bottom: 4px;
        }

        .span-detail-meta {
          font-size: 12px;
          color: var(--fg-muted);
          margin-bottom: 8px;
        }

        .span-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .tag {
          background: var(--bg-elev3);
          padding: 4px 8px;
          border-radius: 4px;
          font-size: 11px;
        }

        .tag-key {
          color: var(--fg-muted);
          margin-right: 4px;
        }

        .tag-value {
          color: var(--fg);
          font-family: monospace;
        }

        .error-section {
          margin-top: 20px;
          padding: 16px;
          background: rgba(239, 68, 68, 0.1);
          border: 1px solid var(--err);
          border-radius: 6px;
        }

        .error-message {
          font-size: 13px;
          color: var(--err);
          font-family: monospace;
          white-space: pre-wrap;
        }
      `}</style>
    </div>
  );
}
