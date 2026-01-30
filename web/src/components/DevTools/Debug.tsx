// AGRO - Debug Component
// Query debugger with detailed trace output
// Reference: /assets/dev tools - debug subtag 1.png, /assets/dev tools - degub subtag 2.png

import { useState } from 'react';
import { useAPI } from '@/hooks';

interface DebugResult {
  routing: any;
  denseResults: any[];
  sparseResults: any[];
  fusionScores: any[];
  rerankerScores: any[];
  finalResults: any[];
  timing: {
    routing: number;
    dense: number;
    sparse: number;
    fusion: number;
    reranking: number;
    total: number;
  };
}

export function Debug() {
  const { api } = useAPI();
  const [query, setQuery] = useState('');
  const [repository, setRepository] = useState('agro');
  const [repositories, setRepositories] = useState(['agro', 'test-repo']);
  const [debugging, setDebugging] = useState(false);
  const [result, setResult] = useState<DebugResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleDebug = async () => {
    if (!query.trim()) return;

    setDebugging(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch(api('/debug/query'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query.trim(),
          repo: repository
        })
      });

      if (!response.ok) {
        throw new Error('Debug request failed');
      }

      const data = await response.json();
      setResult(data);
    } catch (err) {
      console.error('[Debug] Failed to debug query:', err);
      setError(err instanceof Error ? err.message : 'Debug failed');
    } finally {
      setDebugging(false);
    }
  };

  const exportDebugInfo = () => {
    if (!result) return;

    const exportData = {
      query,
      repository,
      timestamp: new Date().toISOString(),
      result
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `debug-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const renderTimingWaterfall = () => {
    if (!result?.timing) return null;

    const { timing } = result;
    const maxTime = timing.total;

    const steps = [
      { label: 'Routing', time: timing.routing, color: 'var(--accent)' },
      { label: 'Dense Search', time: timing.dense, color: 'var(--success)' },
      { label: 'Sparse Search', time: timing.sparse, color: 'var(--warn)' },
      { label: 'Fusion', time: timing.fusion, color: 'var(--info)' },
      { label: 'Reranking', time: timing.reranking, color: 'var(--err)' }
    ];

    return (
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '16px',
        marginTop: '16px'
      }}>
        <h4 style={{
          margin: '0 0 16px 0',
          fontSize: '14px',
          fontWeight: '600',
          color: 'var(--fg)'
        }}>
          Timing Breakdown
        </h4>

        <div style={{ marginBottom: '16px', fontSize: '13px' }}>
          <strong>Total:</strong> {timing.total.toFixed(2)}ms
        </div>

        {steps.map((step, idx) => (
          <div key={idx} style={{ marginBottom: '12px' }}>
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginBottom: '4px',
              fontSize: '12px'
            }}>
              <span style={{ color: 'var(--fg)' }}>{step.label}</span>
              <span style={{ color: 'var(--fg-muted)' }}>{step.time.toFixed(2)}ms</span>
            </div>
            <div style={{
              height: '8px',
              background: 'var(--bg-elev1)',
              borderRadius: '4px',
              overflow: 'hidden'
            }}>
              <div style={{
                height: '100%',
                width: `${(step.time / maxTime) * 100}%`,
                background: step.color,
                transition: 'width 0.3s ease'
              }} />
            </div>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div style={{
      maxWidth: '1200px',
      margin: '0 auto',
      padding: '24px'
    }}>
      <h2 style={{
        margin: '0 0 24px 0',
        fontSize: '20px',
        fontWeight: '600',
        color: 'var(--fg)'
      }}>
        Query Debugger
      </h2>

      {/* Debug Input */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '20px',
        marginBottom: '24px'
      }}>
        <div style={{ marginBottom: '16px' }}>
          <label style={{
            display: 'block',
            fontSize: '12px',
            fontWeight: '600',
            color: 'var(--fg-muted)',
            marginBottom: '6px'
          }}>
            Query
          </label>
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Enter a query to debug..."
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '12px',
              borderRadius: '4px',
              fontSize: '14px',
              fontFamily: 'inherit',
              resize: 'vertical',
              minHeight: '80px'
            }}
            aria-label="Debug query input"
          />
        </div>

        <div style={{
          display: 'flex',
          gap: '12px',
          alignItems: 'center'
        }}>
          <div style={{ flex: 1 }}>
            <label style={{
              display: 'block',
              fontSize: '12px',
              fontWeight: '600',
              color: 'var(--fg-muted)',
              marginBottom: '6px'
            }}>
              Repository
            </label>
            <select
              value={repository}
              onChange={(e) => setRepository(e.target.value)}
              style={{
                width: '100%',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '13px'
              }}
              aria-label="Repository selector"
            >
              {repositories.map(repo => (
                <option key={repo} value={repo}>{repo}</option>
              ))}
            </select>
          </div>

          <button
            onClick={handleDebug}
            disabled={!query.trim() || debugging}
            style={{
              background: query.trim() && !debugging ? 'var(--accent)' : 'var(--bg-elev2)',
              color: query.trim() && !debugging ? 'var(--accent-contrast)' : 'var(--fg-muted)',
              border: 'none',
              padding: '10px 24px',
              borderRadius: '6px',
              fontSize: '14px',
              fontWeight: '600',
              cursor: query.trim() && !debugging ? 'pointer' : 'not-allowed',
              marginTop: '22px'
            }}
            aria-label="Debug query"
          >
            {debugging ? 'Debugging...' : 'Debug Query'}
          </button>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div style={{
          background: 'var(--err)',
          color: 'white',
          padding: '16px',
          borderRadius: '6px',
          marginBottom: '24px',
          fontSize: '14px'
        }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Debug Results */}
      {result && (
        <>
          {/* Timing Waterfall */}
          {renderTimingWaterfall()}

          {/* Routing Decision */}
          <div style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            padding: '16px',
            marginTop: '16px'
          }}>
            <h4 style={{
              margin: '0 0 12px 0',
              fontSize: '14px',
              fontWeight: '600',
              color: 'var(--fg)'
            }}>
              Routing Decision
            </h4>
            <pre style={{
              background: 'var(--code-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              padding: '12px',
              fontSize: '12px',
              fontFamily: 'monospace',
              color: 'var(--fg)',
              overflow: 'auto',
              maxHeight: '200px'
            }}>
              {JSON.stringify(result.routing, null, 2)}
            </pre>
          </div>

          {/* Dense Search Results */}
          <div style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            padding: '16px',
            marginTop: '16px'
          }}>
            <h4 style={{
              margin: '0 0 12px 0',
              fontSize: '14px',
              fontWeight: '600',
              color: 'var(--fg)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              Dense Search Results
              <span style={{
                background: 'var(--success)',
                color: 'white',
                padding: '2px 8px',
                borderRadius: '12px',
                fontSize: '11px',
                fontWeight: '600'
              }}>
                {result.denseResults?.length || 0}
              </span>
            </h4>
            <pre style={{
              background: 'var(--code-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              padding: '12px',
              fontSize: '12px',
              fontFamily: 'monospace',
              color: 'var(--fg)',
              overflow: 'auto',
              maxHeight: '300px'
            }}>
              {JSON.stringify(result.denseResults, null, 2)}
            </pre>
          </div>

          {/* Sparse Search Results */}
          <div style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            padding: '16px',
            marginTop: '16px'
          }}>
            <h4 style={{
              margin: '0 0 12px 0',
              fontSize: '14px',
              fontWeight: '600',
              color: 'var(--fg)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              Sparse Search Results
              <span style={{
                background: 'var(--warn)',
                color: 'white',
                padding: '2px 8px',
                borderRadius: '12px',
                fontSize: '11px',
                fontWeight: '600'
              }}>
                {result.sparseResults?.length || 0}
              </span>
            </h4>
            <pre style={{
              background: 'var(--code-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              padding: '12px',
              fontSize: '12px',
              fontFamily: 'monospace',
              color: 'var(--fg)',
              overflow: 'auto',
              maxHeight: '300px'
            }}>
              {JSON.stringify(result.sparseResults, null, 2)}
            </pre>
          </div>

          {/* Hybrid Fusion Scores */}
          <div style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            padding: '16px',
            marginTop: '16px'
          }}>
            <h4 style={{
              margin: '0 0 12px 0',
              fontSize: '14px',
              fontWeight: '600',
              color: 'var(--fg)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              Hybrid Fusion Scores
              <span style={{
                background: 'var(--info)',
                color: 'white',
                padding: '2px 8px',
                borderRadius: '12px',
                fontSize: '11px',
                fontWeight: '600'
              }}>
                {result.fusionScores?.length || 0}
              </span>
            </h4>
            <pre style={{
              background: 'var(--code-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              padding: '12px',
              fontSize: '12px',
              fontFamily: 'monospace',
              color: 'var(--fg)',
              overflow: 'auto',
              maxHeight: '300px'
            }}>
              {JSON.stringify(result.fusionScores, null, 2)}
            </pre>
          </div>

          {/* Reranker Scores */}
          <div style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            padding: '16px',
            marginTop: '16px'
          }}>
            <h4 style={{
              margin: '0 0 12px 0',
              fontSize: '14px',
              fontWeight: '600',
              color: 'var(--fg)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              Reranker Scores
              <span style={{
                background: 'var(--err)',
                color: 'white',
                padding: '2px 8px',
                borderRadius: '12px',
                fontSize: '11px',
                fontWeight: '600'
              }}>
                {result.rerankerScores?.length || 0}
              </span>
            </h4>
            <pre style={{
              background: 'var(--code-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              padding: '12px',
              fontSize: '12px',
              fontFamily: 'monospace',
              color: 'var(--fg)',
              overflow: 'auto',
              maxHeight: '300px'
            }}>
              {JSON.stringify(result.rerankerScores, null, 2)}
            </pre>
          </div>

          {/* Final Results */}
          <div style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            padding: '16px',
            marginTop: '16px'
          }}>
            <h4 style={{
              margin: '0 0 12px 0',
              fontSize: '14px',
              fontWeight: '600',
              color: 'var(--fg)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              Final Results
              <span style={{
                background: 'var(--accent)',
                color: 'white',
                padding: '2px 8px',
                borderRadius: '12px',
                fontSize: '11px',
                fontWeight: '600'
              }}>
                {result.finalResults?.length || 0}
              </span>
            </h4>
            <pre style={{
              background: 'var(--code-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              padding: '12px',
              fontSize: '12px',
              fontFamily: 'monospace',
              color: 'var(--fg)',
              overflow: 'auto',
              maxHeight: '400px'
            }}>
              {JSON.stringify(result.finalResults, null, 2)}
            </pre>
          </div>

          {/* Export Button */}
          <div style={{
            display: 'flex',
            justifyContent: 'flex-end',
            marginTop: '16px'
          }}>
            <button
              onClick={exportDebugInfo}
              style={{
                background: 'var(--accent)',
                color: 'var(--accent-contrast)',
                border: 'none',
                padding: '10px 20px',
                borderRadius: '6px',
                fontSize: '14px',
                fontWeight: '600',
                cursor: 'pointer'
              }}
              aria-label="Export debug info"
            >
              Export Debug Info
            </button>
          </div>
        </>
      )}
    </div>
  );
}
