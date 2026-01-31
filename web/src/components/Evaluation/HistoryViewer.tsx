import React, { useState } from 'react';
import { useEvalHistory, EvalHistoryEntry } from '@/hooks/useEvalHistory';
import { useUIHelpers } from '@/hooks/useUIHelpers';

interface HistoryViewerProps {
  className?: string;
}

export const HistoryViewer: React.FC<HistoryViewerProps> = ({ className = '' }) => {
  const {
    runs,
    selectedRun,
    selectedRunIndex,
    clearHistory,
    deleteRun,
    selectRun,
    getDeltaVsPrevious,
    exportHistory
  } = useEvalHistory();

  const { showToast } = useUIHelpers();
  const [_expandedIndex, _setExpandedIndex] = useState<number | null>(null);

  const handleClearHistory = () => {
    if (confirm('Clear all evaluation history? This cannot be undone.')) {
      clearHistory();
      showToast('History cleared', 'success');
    }
  };

  const handleDeleteRun = (index: number) => {
    if (confirm('Delete this evaluation run?')) {
      deleteRun(index);
      showToast('Run deleted', 'success');
    }
  };

  const handleExport = () => {
    exportHistory();
    showToast('History exported', 'success');
  };

  const getConfigDisplay = (entry: EvalHistoryEntry) => {
    if (entry.reranker_mode === 'local') {
      return {
        display: 'BM25 + Local CE',
        color: 'var(--accent)',
        bg: 'rgba(var(--accent-rgb), 0.1)'
      };
    } else if (entry.reranker_mode === 'cloud') {
      return {
        display: `BM25 + ${entry.reranker_cloud_provider || 'Cloud'} CE`,
        color: 'var(--link)',
        bg: 'rgba(var(--link-rgb), 0.1)'
      };
    } else if (entry.reranker_mode === 'learning') {
      return {
        display: 'BM25 + AGRO Learning CE',
        color: 'var(--success)',
        bg: 'rgba(var(--success-rgb), 0.1)'
      };
    }
    // none or missing
    return {
      display: 'BM25 Only',
      color: 'var(--fg-muted)',
      bg: 'rgba(var(--fg-muted-rgb), 0.1)'
    };
  };

  const getTop5Color = (pct: number) => {
    if (pct >= 95) return 'var(--accent-green)';
    if (pct >= 90) return 'var(--accent)';
    if (pct >= 80) return 'var(--link)';
    if (pct < 70) return 'var(--warn)';
    return 'var(--fg)';
  };

  return (
    <div className={`history-viewer ${className}`}>
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        padding: '16px'
      }}>
        {/* Header */}
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
            Evaluation History ({runs.length})
          </h3>

          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={handleExport}
              disabled={runs.length === 0}
              style={{
                background: 'var(--bg-elev2)',
                color: 'var(--fg)',
                border: '1px solid var(--line)',
                padding: '6px 12px',
                borderRadius: '4px',
                fontSize: '12px',
                fontWeight: 600,
                cursor: runs.length === 0 ? 'not-allowed' : 'pointer',
                opacity: runs.length === 0 ? 0.7 : 1
              }}
            >
              Export
            </button>

            <button
              onClick={handleClearHistory}
              disabled={runs.length === 0}
              style={{
                background: 'var(--bg-elev2)',
                color: 'var(--err)',
                border: '1px solid var(--err)',
                padding: '6px 12px',
                borderRadius: '4px',
                fontSize: '12px',
                fontWeight: 600,
                cursor: runs.length === 0 ? 'not-allowed' : 'pointer',
                opacity: runs.length === 0 ? 0.7 : 1
              }}
            >
              Clear All
            </button>
          </div>
        </div>

        {/* History Table */}
        {runs.length === 0 ? (
          <div style={{
            textAlign: 'center',
            padding: '40px 24px',
            color: 'var(--fg-muted)'
          }}>
            No evaluation history yet. Run evaluations to see comparisons.
          </div>
        ) : (
          <div style={{
            overflowX: 'auto'
          }}>
            <table style={{
              width: '100%',
              borderCollapse: 'collapse'
            }}>
              <thead>
                <tr style={{
                  borderBottom: '2px solid var(--line)'
                }}>
                  <th style={{
                    padding: '10px',
                    textAlign: 'left',
                    fontSize: '11px',
                    fontWeight: 600,
                    color: 'var(--fg-muted)',
                    textTransform: 'uppercase'
                  }}>
                    Timestamp
                  </th>
                  <th style={{
                    padding: '10px',
                    textAlign: 'left',
                    fontSize: '11px',
                    fontWeight: 600,
                    color: 'var(--fg-muted)',
                    textTransform: 'uppercase'
                  }}>
                    Config
                  </th>
                  <th style={{
                    padding: '10px',
                    textAlign: 'center',
                    fontSize: '11px',
                    fontWeight: 600,
                    color: 'var(--fg-muted)',
                    textTransform: 'uppercase'
                  }}>
                    Top-1
                  </th>
                  <th style={{
                    padding: '10px',
                    textAlign: 'center',
                    fontSize: '11px',
                    fontWeight: 600,
                    color: 'var(--fg-muted)',
                    textTransform: 'uppercase'
                  }}>
                    Top-K
                  </th>
                  <th style={{
                    padding: '10px',
                    textAlign: 'center',
                    fontSize: '11px',
                    fontWeight: 600,
                    color: 'var(--fg-muted)',
                    textTransform: 'uppercase'
                  }}>
                    Duration
                  </th>
                  <th style={{
                    padding: '10px',
                    textAlign: 'center',
                    fontSize: '11px',
                    fontWeight: 600,
                    color: 'var(--fg-muted)',
                    textTransform: 'uppercase'
                  }}>
                    Delta
                  </th>
                  <th style={{
                    padding: '10px',
                    textAlign: 'right',
                    fontSize: '11px',
                    fontWeight: 600,
                    color: 'var(--fg-muted)',
                    textTransform: 'uppercase'
                  }}>
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {runs.map((entry, index) => {
                  const timestamp = new Date(entry.timestamp);
                  const dateStr = timestamp.toLocaleDateString();
                  const timeStr = timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

                  const top1Pct = ((entry.top1 / entry.total) * 100).toFixed(1);
                  const top5Pct = ((entry.topk / entry.total) * 100).toFixed(1);

                  const config = getConfigDisplay(entry);
                  const top5Color = getTop5Color(parseFloat(top5Pct));

                  const deltaInfo = getDeltaVsPrevious(index);
                  let deltaDisplay = '—';
                  let deltaColor = 'var(--fg-muted)';

                  if (deltaInfo) {
                    deltaDisplay = `${deltaInfo.delta >= 0 ? '+' : ''}${deltaInfo.delta.toFixed(1)}%`;
                    deltaColor = deltaInfo.improved ? 'var(--accent-green)' : 'var(--warn)';
                  }

                  return (
                    <tr
                      key={index}
                      style={{
                        borderBottom: '1px solid var(--line)',
                        background: selectedRunIndex === index ? 'var(--bg-elev2)' : 'transparent',
                        cursor: 'pointer'
                      }}
                      onClick={() => selectRun(selectedRunIndex === index ? null : index)}
                    >
                      <td style={{
                        padding: '10px',
                        fontFamily: 'monospace',
                        fontSize: '11px',
                        color: 'var(--fg-muted)'
                      }}>
                        {dateStr}<br />
                        <span style={{ color: 'var(--fg-muted)', opacity: 0.7 }}>{timeStr}</span>
                      </td>
                      <td style={{ padding: '10px' }}>
                        <span style={{
                          display: 'inline-block',
                          padding: '4px 8px',
                          borderRadius: '4px',
                          background: config.bg,
                          color: config.color,
                          fontWeight: 600,
                          fontSize: '11px'
                        }}>
                          {config.display}
                        </span>
                      </td>
                      <td style={{
                        padding: '10px',
                        textAlign: 'center',
                        fontFamily: 'monospace',
                        fontWeight: 600
                      }}>
                        <div style={{ color: 'var(--fg)' }}>{entry.top1}/{entry.total}</div>
                        <div style={{ fontSize: '10px', color: 'var(--fg-muted)' }}>{top1Pct}%</div>
                      </td>
                      <td style={{
                        padding: '10px',
                        textAlign: 'center',
                        fontFamily: 'monospace',
                        fontWeight: 700
                      }}>
                        <div style={{ color: top5Color, fontSize: '14px' }}>
                          {entry.topk}/{entry.total}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--fg-muted)' }}>{top5Pct}%</div>
                      </td>
                      <td style={{
                        padding: '10px',
                        textAlign: 'center',
                        fontFamily: 'monospace',
                        color: 'var(--fg-muted)'
                      }}>
                        {entry.secs.toFixed(0)}s
                      </td>
                      <td style={{
                        padding: '10px',
                        textAlign: 'center',
                        fontFamily: 'monospace',
                        fontWeight: 600,
                        color: deltaColor
                      }}>
                        {deltaDisplay}
                      </td>
                      <td style={{ padding: '10px', textAlign: 'right' }}>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteRun(index);
                          }}
                          style={{
                            background: 'transparent',
                            color: 'var(--err)',
                            border: '1px solid var(--err)',
                            padding: '4px 8px',
                            borderRadius: '3px',
                            fontSize: '11px',
                            cursor: 'pointer'
                          }}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Selected Run Details */}
        {selectedRun && (
          <div style={{
            marginTop: '20px',
            background: 'var(--bg-elev2)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            padding: '16px'
          }}>
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '12px'
            }}>
              <h4 style={{
                fontSize: '13px',
                fontWeight: 600,
                color: 'var(--fg)',
                margin: 0
              }}>
                Run Details
              </h4>
              <button
                onClick={() => selectRun(null)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--fg-muted)',
                  fontSize: '16px',
                  cursor: 'pointer',
                  padding: '0 8px'
                }}
              >
                ✕
              </button>
            </div>

            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, 1fr)',
              gap: '12px',
              fontSize: '12px'
            }}>
              <div>
                <div style={{ color: 'var(--fg-muted)', marginBottom: '4px' }}>Timestamp</div>
                <div style={{ color: 'var(--fg)', fontFamily: 'monospace' }}>
                  {new Date(selectedRun.timestamp).toLocaleString()}
                </div>
              </div>

              <div>
                <div style={{ color: 'var(--fg-muted)', marginBottom: '4px' }}>Configuration</div>
                <div style={{ color: 'var(--fg)', fontWeight: 600 }}>
                  {selectedRun.config}
                </div>
              </div>

              <div>
                <div style={{ color: 'var(--fg-muted)', marginBottom: '4px' }}>Reranker Mode</div>
                <div style={{ color: 'var(--fg)' }}>
                  {selectedRun.reranker_mode || 'none'}
                </div>
              </div>

              <div>
                <div style={{ color: 'var(--fg-muted)', marginBottom: '4px' }}>Final K</div>
                <div style={{ color: 'var(--fg)' }}>
                  {selectedRun.final_k}
                </div>
              </div>

              <div>
                <div style={{ color: 'var(--fg-muted)', marginBottom: '4px' }}>Multi-Stage</div>
                <div style={{ color: 'var(--fg)' }}>
                  {selectedRun.use_multi ? 'Yes' : 'No'}
                </div>
              </div>

              <div>
                <div style={{ color: 'var(--fg-muted)', marginBottom: '4px' }}>Total Questions</div>
                <div style={{ color: 'var(--fg)', fontWeight: 600 }}>
                  {selectedRun.total}
                </div>
              </div>

              <div>
                <div style={{ color: 'var(--fg-muted)', marginBottom: '4px' }}>Top-1 Accuracy</div>
                <div style={{ color: 'var(--accent)', fontWeight: 700, fontSize: '16px' }}>
                  {((selectedRun.top1 / selectedRun.total) * 100).toFixed(1)}%
                </div>
              </div>

              <div>
                <div style={{ color: 'var(--fg-muted)', marginBottom: '4px' }}>Top-K Accuracy</div>
                <div style={{ color: 'var(--link)', fontWeight: 700, fontSize: '16px' }}>
                  {((selectedRun.topk / selectedRun.total) * 100).toFixed(1)}%
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
