import React, { useState, useEffect } from 'react';
import { useAPI } from '@/hooks/useAPI';
import { useErrorHandler } from '@/hooks/useErrorHandler';
import type { TracesLatestResponse } from '@/types/generated';

type TraceViewerProps = {
  className?: string;
};

export const TraceViewer: React.FC<TraceViewerProps> = ({ className = '' }) => {
  const [traceData, setTraceData] = useState<TracesLatestResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRepo, setSelectedRepo] = useState('agro');

  const { api } = useAPI();
  const { handleApiError } = useErrorHandler();

  const loadLatestTrace = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const repoParam = selectedRepo ? `?repo=${encodeURIComponent(selectedRepo)}` : '';
      const response = await fetch(api(`/traces/latest${repoParam}`));
      const data = await response.json();
      setTraceData(data);
    } catch (err) {
      console.error('Failed to load trace:', err);
      const errorMsg = handleApiError(err, 'Load trace');
      setError(errorMsg);
    } finally {
      setIsLoading(false);
    }
  };

  // Auto-load on mount
  useEffect(() => {
    loadLatestTrace();
  }, [selectedRepo]);

  const formatTable = (rows: string[][], headers: string[]) => {
    const cols = headers.length;
    const widths = new Array(cols).fill(0);
    const all = [headers, ...rows];

    all.forEach(r => r.forEach((c, i) => {
      widths[i] = Math.max(widths[i], String(c || '').length);
    }));

    const line = (r: string[]) => r.map((c, i) => String(c || '').padEnd(widths[i])).join('  ');

    return [
      line(headers),
      line(widths.map(w => '-'.repeat(w))),
      ...rows.map(line)
    ].join('\n');
  };

  const renderTraceContent = () => {
    if (isLoading) {
      return (
        <div style={{
          textAlign: 'center',
          padding: '40px',
          color: 'var(--fg-muted)'
        }}>
          Loading trace data...
        </div>
      );
    }

    if (error) {
      return (
        <div style={{
          padding: '20px',
          color: 'var(--err)',
          background: 'color-mix(in oklch, var(--err) 8%, var(--bg))',
          border: '1px solid var(--err)',
          borderRadius: '6px'
        }}>
          Failed to load trace: {error}
        </div>
      );
    }

    if (!traceData || !traceData.trace) {
      return (
        <div style={{
          textAlign: 'center',
          padding: '40px',
          color: 'var(--fg-muted)'
        }}>
          No traces yet. Set Tracing Mode to Local/LangSmith (not Off) and run a query.
        </div>
      );
    }

    const trace = traceData.trace;
    const events = trace.events || [];

    const decideEvent = events.find(ev => ev.kind === 'router.decide');
    const rerankEvent = events.find(ev => ev.kind === 'reranker.rank');
    const gateEvent = events.find(ev => ev.kind === 'gating.outcome');
    const retrieveEvent = events.find(ev => ev.kind === 'retriever.retrieve');

    const parts: JSX.Element[] = [];

    // Header Info
    const headerParts = [
      `Policy: ${decideEvent?.data?.policy || '—'}`,
      `Intent: ${decideEvent?.data?.intent || '—'}`,
      `Final K: ${rerankEvent?.data?.output_topK || '—'}`,
      `Vector: pgvector`
    ];

    parts.push(
      <div key="header" style={{
        fontSize: '12px',
        color: 'var(--fg-muted)',
        marginBottom: '16px',
        padding: '12px',
        background: 'var(--bg-elev2)',
        borderRadius: '4px'
      }}>
        {headerParts.join('  •  ')}
      </div>
    );

    // Pre-rerank candidates
    if (retrieveEvent && Array.isArray(retrieveEvent.data?.candidates)) {
      const candidates = (retrieveEvent.data as any).candidates as any[];
      parts.push(
        <div key="candidates" style={{ marginBottom: '16px' }}>
          <div style={{
            fontSize: '12px',
            fontWeight: 600,
            color: 'var(--fg)',
            marginBottom: '8px'
          }}>
            Pre-rerank candidates ({candidates.length}):
          </div>
          <pre style={{
            background: 'var(--code-bg)',
            border: '1px solid var(--line)',
            borderRadius: '4px',
            padding: '12px',
            fontSize: '11px',
            fontFamily: "'SF Mono', monospace",
            color: 'var(--fg-muted)',
            overflowX: 'auto',
            margin: 0
          }}>
            {formatTable(
              candidates.map(c => [
                (c.path || '').split('/').slice(-2).join('/'),
                String(c.bm25_rank || ''),
                String(c.dense_rank || '')
              ]),
              ['path', 'bm25', 'dense']
            )}
          </pre>
        </div>
      );
    }

    // Rerank results
    if (rerankEvent && Array.isArray(rerankEvent.data?.scores)) {
      const scores = (rerankEvent.data as any).scores as any[];
      parts.push(
        <div key="rerank" style={{ marginBottom: '16px' }}>
          <div style={{
            fontSize: '12px',
            fontWeight: 600,
            color: 'var(--fg)',
            marginBottom: '8px'
          }}>
            Rerank ({scores.length}):
          </div>
          <pre style={{
            background: 'var(--code-bg)',
            border: '1px solid var(--line)',
            borderRadius: '4px',
            padding: '12px',
            fontSize: '11px',
            fontFamily: "'SF Mono', monospace",
            color: 'var(--fg-muted)',
            overflowX: 'auto',
            margin: 0
          }}>
            {formatTable(
              scores.map(s => [
                (s.path || '').split('/').slice(-2).join('/'),
                s.score?.toFixed?.(3) || String(s.score || '')
              ]),
              ['path', 'score']
            )}
          </pre>
        </div>
      );
    }

    // Gating info
    if (gateEvent) {
      const gateData = (gateEvent.data ?? {}) as any;
      parts.push(
        <div key="gate" style={{
          fontSize: '12px',
          color: 'var(--fg)',
          marginBottom: '16px',
          padding: '10px',
          background: 'var(--bg-elev2)',
          borderRadius: '4px',
          borderLeft: '3px solid var(--accent)'
        }}>
          <strong>Gate:</strong>{' '}
          top1&gt;={String(gateData.top1_thresh ?? '—')} avg5&gt;={String(gateData.avg5_thresh ?? '—')}
          {' → '}
          <span style={{ color: 'var(--accent)', fontWeight: 600 }}>
            {String(gateData.outcome ?? '—')}
          </span>
        </div>
      );
    }

    // Events list
    const allEvents = events;
    if (allEvents.length > 0) {
      parts.push(
        <div key="events" style={{ marginBottom: '16px' }}>
          <div style={{
            fontSize: '12px',
            fontWeight: 600,
            color: 'var(--fg)',
            marginBottom: '8px'
          }}>
            Events:
          </div>
          <div style={{
            background: 'var(--code-bg)',
            border: '1px solid var(--line)',
            borderRadius: '4px',
            padding: '12px'
          }}>
            {allEvents.map((ev, idx) => {
              const when = ev.ts
                ? new Date(ev.ts).toLocaleTimeString()
                : new Date().toLocaleTimeString();
              const name = (ev.kind || '').padEnd(18);

              return (
                <div
                  key={idx}
                  style={{
                    fontSize: '11px',
                    fontFamily: "'SF Mono', monospace",
                    color: 'var(--fg-muted)',
                    marginBottom: idx < allEvents.length - 1 ? '4px' : 0
                  }}
                >
                  {when}  {name}  {ev.msg || ''}
                </div>
              );
            })}
          </div>
        </div>
      );
    }

    return <div>{parts}</div>;
  };

  return (
    <div className={`trace-viewer ${className}`}>
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        padding: '16px'
      }}>
        {/* Header with Controls */}
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '16px'
        }}>
          <h3 style={{
            fontSize: '14px',
            fontWeight: 600,
            color: 'var(--fg)',
            textTransform: 'uppercase',
            letterSpacing: '0.5px',
            margin: 0
          }}>
            Latest Trace
          </h3>

          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <select
              value={selectedRepo}
              onChange={(e) => setSelectedRepo(e.target.value)}
              style={{
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '6px 12px',
                borderRadius: '4px',
                fontSize: '12px'
              }}
            >
              <option value="agro">agro</option>
            </select>

            <button
              onClick={loadLatestTrace}
              disabled={isLoading}
              style={{
                background: isLoading ? 'var(--bg-elev2)' : 'var(--accent)',
                color: isLoading ? 'var(--fg-muted)' : 'var(--accent-contrast)',
                border: 'none',
                padding: '6px 12px',
                borderRadius: '4px',
                fontSize: '12px',
                fontWeight: 600,
                cursor: isLoading ? 'not-allowed' : 'pointer',
                opacity: isLoading ? 0.7 : 1
              }}
            >
              {isLoading ? 'Loading...' : 'Refresh'}
            </button>
          </div>
        </div>

        {/* Trace Content */}
        {renderTraceContent()}
      </div>
    </div>
  );
};
