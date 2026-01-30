// AGRO - Reranker Comparison Component
// Compare different reranker models side-by-side
// Allows testing reranker performance with custom queries and documents

import { useState } from 'react';
import { useAPI } from '@/hooks';

interface RerankerResult {
  reranker: string;
  scores: Array<{
    document: string;
    score: number;
    rank: number;
  }>;
  duration: number;
}

interface ComparisonResult {
  query: string;
  results: RerankerResult[];
  correlation: number[][];
}

export function Reranker() {
  const { api } = useAPI();
  const [query, setQuery] = useState('');
  const [documents, setDocuments] = useState('');
  const [selectedRerankers, setSelectedRerankers] = useState<string[]>(['cohere']);
  const [comparing, setComparing] = useState(false);
  const [comparisonResult, setComparisonResult] = useState<ComparisonResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const availableRerankers = [
    { id: 'cohere', name: 'Cohere Rerank', description: 'Cohere rerank-english-v2.0' },
    { id: 'voyage', name: 'Voyage AI', description: 'Voyage reranker-lite-1' },
    { id: 'learning-ranker', name: 'Learning Ranker', description: 'Local learning-to-rank model' },
    { id: 'cross-encoder', name: 'Cross-Encoder', description: 'BERT-based cross-encoder' }
  ];

  const toggleReranker = (id: string) => {
    if (selectedRerankers.includes(id)) {
      setSelectedRerankers(selectedRerankers.filter(r => r !== id));
    } else {
      setSelectedRerankers([...selectedRerankers, id]);
    }
  };

  const handleCompare = async () => {
    if (!query.trim() || !documents.trim() || selectedRerankers.length === 0) {
      setError('Please provide a query, documents, and select at least one reranker');
      return;
    }

    setComparing(true);
    setError(null);
    setComparisonResult(null);

    try {
      // Parse documents (expecting JSON array or newline-separated)
      let docArray: string[] = [];
      try {
        docArray = JSON.parse(documents);
      } catch {
        docArray = documents.split('\n').filter(d => d.trim());
      }

      const response = await fetch(api('/reranker/compare'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query.trim(),
          documents: docArray,
          rerankers: selectedRerankers
        })
      });

      if (!response.ok) {
        throw new Error('Reranker comparison failed');
      }

      const data = await response.json();
      setComparisonResult(data);
    } catch (err) {
      console.error('[Reranker] Comparison failed:', err);
      setError(err instanceof Error ? err.message : 'Comparison failed');
    } finally {
      setComparing(false);
    }
  };

  const exportResults = () => {
    if (!comparisonResult) return;

    const exportData = {
      timestamp: new Date().toISOString(),
      ...comparisonResult
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `reranker-comparison-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{
      maxWidth: '1400px',
      margin: '0 auto',
      padding: '24px'
    }}>
      <h2 style={{
        margin: '0 0 24px 0',
        fontSize: '20px',
        fontWeight: '600',
        color: 'var(--fg)'
      }}>
        Reranker Comparison
      </h2>

      {/* Input Section */}
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
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Enter search query..."
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '4px',
              fontSize: '14px'
            }}
            aria-label="Query input"
          />
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{
            display: 'block',
            fontSize: '12px',
            fontWeight: '600',
            color: 'var(--fg-muted)',
            marginBottom: '6px'
          }}>
            Documents (JSON array or newline-separated)
          </label>
          <textarea
            value={documents}
            onChange={(e) => setDocuments(e.target.value)}
            placeholder='["Document 1 text...", "Document 2 text...", "Document 3 text..."]'
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '12px',
              borderRadius: '4px',
              fontSize: '13px',
              fontFamily: 'monospace',
              resize: 'vertical',
              minHeight: '150px'
            }}
            aria-label="Documents input"
          />
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{
            display: 'block',
            fontSize: '12px',
            fontWeight: '600',
            color: 'var(--fg-muted)',
            marginBottom: '8px'
          }}>
            Select Rerankers (Choose 2-4 for comparison)
          </label>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))',
            gap: '12px'
          }}>
            {availableRerankers.map(reranker => (
              <label
                key={reranker.id}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                  padding: '12px',
                  background: selectedRerankers.includes(reranker.id) ? 'var(--bg-elev2)' : 'var(--bg-elev1)',
                  border: `2px solid ${selectedRerankers.includes(reranker.id) ? 'var(--accent)' : 'var(--line)'}`,
                  borderRadius: '6px',
                  cursor: 'pointer',
                  transition: 'all 0.2s'
                }}
              >
                <input
                  type="checkbox"
                  checked={selectedRerankers.includes(reranker.id)}
                  onChange={() => toggleReranker(reranker.id)}
                  style={{
                    width: '18px',
                    height: '18px',
                    cursor: 'pointer',
                    marginTop: '2px'
                  }}
                />
                <div style={{ flex: 1 }}>
                  <div style={{
                    fontSize: '13px',
                    fontWeight: '600',
                    color: 'var(--fg)',
                    marginBottom: '4px'
                  }}>
                    {reranker.name}
                  </div>
                  <div style={{
                    fontSize: '11px',
                    color: 'var(--fg-muted)'
                  }}>
                    {reranker.description}
                  </div>
                </div>
              </label>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <button
            onClick={handleCompare}
            disabled={comparing || !query.trim() || !documents.trim() || selectedRerankers.length === 0}
            style={{
              background: comparing || !query.trim() || !documents.trim() || selectedRerankers.length === 0
                ? 'var(--bg-elev2)'
                : 'var(--accent)',
              color: comparing || !query.trim() || !documents.trim() || selectedRerankers.length === 0
                ? 'var(--fg-muted)'
                : 'var(--accent-contrast)',
              border: 'none',
              padding: '12px 32px',
              borderRadius: '6px',
              fontSize: '14px',
              fontWeight: '600',
              cursor: comparing || !query.trim() || !documents.trim() || selectedRerankers.length === 0
                ? 'not-allowed'
                : 'pointer'
            }}
            aria-label="Compare rerankers"
          >
            {comparing ? 'Comparing...' : 'Compare Rerankers'}
          </button>

          {selectedRerankers.length > 0 && (
            <span style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
              {selectedRerankers.length} reranker{selectedRerankers.length !== 1 ? 's' : ''} selected
            </span>
          )}
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

      {/* Comparison Results */}
      {comparisonResult && (
        <>
          {/* Side-by-Side Results */}
          <div style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            overflow: 'hidden',
            marginBottom: '24px'
          }}>
            <div style={{
              padding: '16px',
              borderBottom: '1px solid var(--line)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <h3 style={{
                margin: 0,
                fontSize: '16px',
                fontWeight: '600',
                color: 'var(--fg)'
              }}>
                Comparison Results
              </h3>
              <button
                onClick={exportResults}
                style={{
                  background: 'var(--accent)',
                  color: 'var(--accent-contrast)',
                  border: 'none',
                  padding: '6px 12px',
                  borderRadius: '4px',
                  fontSize: '12px',
                  fontWeight: '600',
                  cursor: 'pointer'
                }}
                aria-label="Export results"
              >
                Export Results
              </button>
            </div>

            <div style={{
              display: 'grid',
              gridTemplateColumns: `repeat(${comparisonResult.results.length}, 1fr)`,
              gap: '1px',
              background: 'var(--line)'
            }}>
              {comparisonResult.results.map((result, idx) => (
                <div
                  key={idx}
                  style={{
                    background: 'var(--card-bg)',
                    padding: '16px'
                  }}
                >
                  <h4 style={{
                    margin: '0 0 8px 0',
                    fontSize: '14px',
                    fontWeight: '600',
                    color: 'var(--accent)'
                  }}>
                    {availableRerankers.find(r => r.id === result.reranker)?.name || result.reranker}
                  </h4>
                  <div style={{
                    fontSize: '11px',
                    color: 'var(--fg-muted)',
                    marginBottom: '12px'
                  }}>
                    Duration: {result.duration.toFixed(2)}ms
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {result.scores.map((score, scoreIdx) => (
                      <div
                        key={scoreIdx}
                        style={{
                          background: 'var(--bg-elev1)',
                          border: '1px solid var(--line)',
                          borderRadius: '4px',
                          padding: '10px'
                        }}
                      >
                        <div style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          marginBottom: '6px'
                        }}>
                          <span style={{
                            fontSize: '11px',
                            fontWeight: '600',
                            color: 'var(--fg)'
                          }}>
                            Rank #{score.rank}
                          </span>
                          <span style={{
                            fontSize: '12px',
                            fontWeight: '600',
                            color: 'var(--accent)'
                          }}>
                            {score.score.toFixed(4)}
                          </span>
                        </div>
                        <div style={{
                          fontSize: '11px',
                          color: 'var(--fg-muted)',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap'
                        }}>
                          {score.document.substring(0, 100)}...
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Correlation Heatmap */}
          {comparisonResult.correlation && comparisonResult.correlation.length > 1 && (
            <div style={{
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              borderRadius: '6px',
              padding: '20px',
              marginBottom: '24px'
            }}>
              <h3 style={{
                margin: '0 0 16px 0',
                fontSize: '16px',
                fontWeight: '600',
                color: 'var(--fg)'
              }}>
                Correlation Heatmap
              </h3>
              <div style={{
                fontSize: '12px',
                color: 'var(--fg-muted)',
                marginBottom: '16px'
              }}>
                Shows how similar the ranking results are between different rerankers (1.0 = identical, 0.0 = no correlation)
              </div>

              <div style={{ overflow: 'auto' }}>
                <table style={{
                  width: '100%',
                  borderCollapse: 'collapse',
                  fontSize: '13px'
                }}>
                  <thead>
                    <tr>
                      <th style={{ padding: '8px', textAlign: 'left', fontWeight: '600', color: 'var(--fg-muted)' }}>
                        Reranker
                      </th>
                      {comparisonResult.results.map((result, idx) => (
                        <th
                          key={idx}
                          style={{
                            padding: '8px',
                            textAlign: 'center',
                            fontWeight: '600',
                            color: 'var(--fg-muted)',
                            minWidth: '80px'
                          }}
                        >
                          {availableRerankers.find(r => r.id === result.reranker)?.name || result.reranker}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {comparisonResult.results.map((result, rowIdx) => (
                      <tr key={rowIdx}>
                        <td style={{
                          padding: '8px',
                          fontWeight: '600',
                          color: 'var(--fg)',
                          borderTop: '1px solid var(--line)'
                        }}>
                          {availableRerankers.find(r => r.id === result.reranker)?.name || result.reranker}
                        </td>
                        {comparisonResult.correlation[rowIdx].map((correlation, colIdx) => {
                          const intensity = Math.round(correlation * 255);
                          const bgColor = `rgba(var(--accent-rgb, 0, 120, 212), ${correlation})`;
                          return (
                            <td
                              key={colIdx}
                              style={{
                                padding: '12px',
                                textAlign: 'center',
                                fontWeight: '600',
                                color: correlation > 0.5 ? 'white' : 'var(--fg)',
                                background: bgColor,
                                borderTop: '1px solid var(--line)'
                              }}
                            >
                              {correlation.toFixed(3)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {!comparisonResult && !comparing && !error && (
        <div style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '60px 20px',
          textAlign: 'center',
          color: 'var(--fg-muted)'
        }}>
          <div style={{ fontSize: '48px', marginBottom: '16px' }}>🔄</div>
          <div style={{ fontSize: '16px', marginBottom: '8px' }}>No comparison results yet</div>
          <div style={{ fontSize: '13px' }}>Enter a query, documents, select rerankers, and click "Compare Rerankers"</div>
        </div>
      )}
    </div>
  );
}
