import React, { useState } from 'react';
import { useEvaluation } from '@/hooks/useEvaluation';
import { useUIHelpers } from '@/hooks/useUIHelpers';
import type { EvalResult, EvalComparisonResult } from '@/types/generated';

interface EvaluationRunnerProps {
  className?: string;
}

export const EvaluationRunner: React.FC<EvaluationRunnerProps> = ({ className = '' }) => {
  const {
    isRunning,
    currentRun,
    results,
    progress,
    progressText,
    runEval,
    exportResults,
    clearState,
    listRuns,
    compareRuns,
  } = useEvaluation();

  const { showToast } = useUIHelpers();

  const [useMulti, setUseMulti] = useState(true);
  const [finalK, setFinalK] = useState(5);
  const [comparison, setComparison] = useState<EvalComparisonResult | null>(null);
  const [showComparison, setShowComparison] = useState(false);

  const handleRunEval = async () => {
    // Note: use_multi and final_k are controlled by server config, not passed as options
    await runEval();
  };

  const handleCompare = async () => {
    // Get the two most recent runs and compare them
    const runs = await listRuns();
    if (runs.length < 2) {
      showToast('Need at least 2 runs to compare', 'error');
      return;
    }
    const result = await compareRuns(runs[1].run_id, runs[0].run_id);
    if (result) {
      setComparison(result);
      setShowComparison(true);
    }
  };

  const handleExport = async () => {
    const exported = await exportResults('json');
    // Create a blob and download
    const blob = new Blob([exported], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `eval-results-${currentRun?.run_id ?? 'export'}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Results exported', 'success');
  };

  // Calculate pass/fail counts from results array
  const failures = results.filter((r: EvalResult) => !r.topk_hit);
  const passes = results.filter((r: EvalResult) => r.topk_hit);

  return (
    <div className={`evaluation-runner ${className}`}>
      {/* Settings Panel */}
      <div className="eval-settings" style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        padding: '16px',
        marginBottom: '20px'
      }}>
        <h3 style={{
          fontSize: '14px',
          fontWeight: 600,
          color: 'var(--fg)',
          marginBottom: '16px',
          textTransform: 'uppercase',
          letterSpacing: '0.5px'
        }}>
          Evaluation Configuration
        </h3>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
          <div>
            <label htmlFor="eval-use-multi" style={{
              fontSize: '12px',
              color: 'var(--fg-muted)',
              display: 'block',
              marginBottom: '6px'
            }}>
              Use Multi-Stage Retrieval
            </label>
            <select
              id="eval-use-multi"
              value={useMulti ? '1' : '0'}
              onChange={(e) => setUseMulti(e.target.value === '1')}
              disabled={isRunning}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px',
                borderRadius: '4px',
                fontSize: '13px'
              }}
            >
              <option value="1">Yes (BM25 + Dense)</option>
              <option value="0">No (BM25 only)</option>
            </select>
          </div>

          <div>
            <label htmlFor="eval-final-k" style={{
              fontSize: '12px',
              color: 'var(--fg-muted)',
              display: 'block',
              marginBottom: '6px'
            }}>
              Final K (Top Results)
            </label>
            <input
              type="number"
              id="eval-final-k"
              value={finalK}
              onChange={(e) => setFinalK(parseInt(e.target.value) || 5)}
              disabled={isRunning}
              min={1}
              max={20}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px',
                borderRadius: '4px',
                fontSize: '13px'
              }}
            />
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button
            onClick={handleRunEval}
            disabled={isRunning}
            style={{
              flex: 1,
              minWidth: '150px',
              background: isRunning ? 'var(--bg-elev2)' : 'var(--accent)',
              color: isRunning ? 'var(--fg-muted)' : 'var(--accent-contrast)',
              border: 'none',
              padding: '10px 16px',
              borderRadius: '4px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: isRunning ? 'not-allowed' : 'pointer',
              opacity: isRunning ? 0.7 : 1
            }}
          >
            {isRunning ? progressText || 'Running...' : 'Run Full Evaluation'}
          </button>

          {currentRun && !isRunning && (
            <>
              <button
                onClick={handleCompare}
                style={{
                  background: 'var(--warn)',
                  color: 'var(--bg)',
                  border: 'none',
                  padding: '10px 16px',
                  borderRadius: '4px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                Compare with Previous
              </button>

              <button
                onClick={handleExport}
                style={{
                  background: 'var(--bg-elev2)',
                  color: 'var(--fg)',
                  border: '1px solid var(--line)',
                  padding: '10px 16px',
                  borderRadius: '4px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                Export Results
              </button>

              <button
                onClick={clearState}
                style={{
                  background: 'transparent',
                  color: 'var(--fg-muted)',
                  border: '1px solid var(--line)',
                  padding: '10px 16px',
                  borderRadius: '4px',
                  fontSize: '13px',
                  cursor: 'pointer'
                }}
              >
                Clear
              </button>
            </>
          )}
        </div>
      </div>

      {/* Progress Bar */}
      {isRunning && (
        <div className="eval-progress" style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '16px',
          marginBottom: '20px'
        }}>
          <div style={{ fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
            {progressText || 'Running evaluation...'}
          </div>
          <div style={{
            width: '100%',
            height: '8px',
            background: 'var(--bg-elev2)',
            borderRadius: '4px',
            overflow: 'hidden'
          }}>
            <div style={{
              width: `${progress}%`,
              height: '100%',
              background: 'linear-gradient(90deg, var(--accent), var(--link))',
              transition: 'width 0.3s ease'
            }} />
          </div>
        </div>
      )}

      {/* Results Display */}
      {currentRun && !isRunning && (
        <div className="eval-results" style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '16px',
          marginBottom: '20px'
        }}>
          <h3 style={{
            fontSize: '14px',
            fontWeight: 600,
            color: 'var(--fg)',
            marginBottom: '16px',
            textTransform: 'uppercase',
            letterSpacing: '0.5px'
          }}>
            Evaluation Results
          </h3>

          {/* Overall Metrics */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '20px' }}>
            <div style={{
              background: 'var(--bg-elev2)',
              border: '1px solid var(--line)',
              borderRadius: '6px',
              padding: '12px',
              textAlign: 'center'
            }}>
              <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px', textTransform: 'uppercase' }}>
                Top-1 Accuracy
              </div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--accent)' }}>
                {((currentRun.top1_accuracy ?? 0) * 100).toFixed(1)}%
              </div>
            </div>

            <div style={{
              background: 'var(--bg-elev2)',
              border: '1px solid var(--line)',
              borderRadius: '6px',
              padding: '12px',
              textAlign: 'center'
            }}>
              <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px', textTransform: 'uppercase' }}>
                Top-K Accuracy
              </div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--link)' }}>
                {((currentRun.topk_accuracy ?? 0) * 100).toFixed(1)}%
              </div>
            </div>

            <div style={{
              background: 'var(--bg-elev2)',
              border: '1px solid var(--line)',
              borderRadius: '6px',
              padding: '12px',
              textAlign: 'center'
            }}>
              <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px', textTransform: 'uppercase' }}>
                Duration
              </div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--fg)' }}>
                {currentRun.duration_secs?.toFixed(1)}s
              </div>
            </div>
          </div>

          {/* Summary */}
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '16px' }}>
            <span style={{ color: 'var(--ok)', marginRight: '16px' }}>✓ {passes.length} passed</span>
            <span style={{ color: 'var(--err)' }}>✗ {failures.length} failed</span>
          </div>

          {/* Failures Section */}
          {failures.length > 0 && (
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--err)', marginBottom: '8px' }}>
                FAILURES
              </div>
              {failures.map((result: EvalResult, idx: number) => (
                <ResultCard key={idx} result={result} isFailure={true} />
              ))}
            </div>
          )}

          {/* Passes Section (Collapsed) */}
          {passes.length > 0 && (
            <details style={{ marginTop: '12px' }}>
              <summary style={{
                fontSize: '12px',
                fontWeight: 600,
                color: 'var(--accent)',
                marginBottom: '8px',
                cursor: 'pointer',
                userSelect: 'none'
              }}>
                PASSES ({passes.length})
              </summary>
              <div style={{ marginTop: '8px' }}>
                {passes.map((result: EvalResult, idx: number) => (
                  <ResultCard key={idx} result={result} isFailure={false} />
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      {/* Comparison Display */}
      {showComparison && comparison && (
        <div className="eval-comparison" style={{
          background: 'var(--code-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '16px',
          marginBottom: '20px'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h4 style={{
              fontSize: '14px',
              color: 'var(--link)',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
              margin: 0
            }}>
              Run Comparison
            </h4>
            <button
              onClick={() => setShowComparison(false)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--fg-muted)',
                fontSize: '18px',
                cursor: 'pointer',
                padding: '0 8px'
              }}
            >
              ✕
            </button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
            <ComparisonCard
              title="MRR Change"
              baseline={comparison.baseline_metrics.mrr}
              current={comparison.current_metrics.mrr}
              delta={comparison.delta_mrr}
            />
            <ComparisonCard
              title="Recall@10 Change"
              baseline={comparison.baseline_metrics.recall_at_10}
              current={comparison.current_metrics.recall_at_10}
              delta={comparison.delta_recall_at_10}
            />
          </div>

          {comparison.degraded_entries && comparison.degraded_entries.length > 0 && (
            <div style={{
              background: 'color-mix(in oklch, var(--err) 8%, var(--bg))',
              border: '1px solid var(--err)',
              borderRadius: '4px',
              padding: '12px',
              marginBottom: '12px'
            }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--err)', marginBottom: '8px' }}>
                ⚠ DEGRADED ENTRIES ({comparison.degraded_entries.length})
              </div>
              {comparison.degraded_entries.map((entryId: string, idx: number) => (
                <div key={idx} style={{ fontSize: '11px', color: 'var(--err)', opacity: 0.85, marginBottom: '4px' }}>
                  {entryId}
                </div>
              ))}
            </div>
          )}

          {comparison.improved_entries && comparison.improved_entries.length > 0 && (
            <div style={{
              background: 'color-mix(in oklch, var(--ok) 8%, var(--bg))',
              border: '1px solid var(--ok)',
              borderRadius: '4px',
              padding: '12px'
            }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--ok)', marginBottom: '8px' }}>
                ✓ IMPROVED ENTRIES ({comparison.improved_entries.length})
              </div>
              {comparison.improved_entries.map((entryId: string, idx: number) => (
                <div key={idx} style={{ fontSize: '11px', color: 'var(--ok)', opacity: 0.85, marginBottom: '4px' }}>
                  {entryId}
                </div>
              ))}
            </div>
          )}

          {(!comparison.degraded_entries || comparison.degraded_entries.length === 0) && (
            <div style={{
              background: 'color-mix(in oklch, var(--ok) 8%, var(--bg))',
              border: '1px solid var(--ok)',
              borderRadius: '4px',
              padding: '12px',
              textAlign: 'center',
              color: 'var(--ok)',
              fontWeight: 600
            }}>
              ✓ No degraded entries detected
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// Helper component for individual result cards
const ResultCard: React.FC<{ result: EvalResult; isFailure: boolean }> = ({ result, isFailure }) => {
  const top1Color = result.top1_hit ? 'var(--ok)' : 'var(--err)';
  const topkColor = result.topk_hit ? 'var(--ok)' : 'var(--warn)';

  return (
    <div style={{
      background: 'var(--card-bg)',
      borderLeft: `3px solid ${isFailure ? 'var(--err)' : 'var(--ok)'}`,
      padding: '10px',
      marginBottom: '8px',
      borderRadius: '4px'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '6px' }}>
        <div style={{ flex: 1, fontSize: '12px', color: 'var(--fg)', fontWeight: 500 }}>
          {result.question}
        </div>
        <div style={{ fontSize: '11px', marginLeft: '12px' }}>
          <span style={{
            background: 'var(--bg-elev2)',
            padding: '2px 6px',
            borderRadius: '3px'
          }}>
            {result.entry_id}
          </span>
        </div>
      </div>
      <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>
        <strong>Expected:</strong> {result.expected_paths.join(', ')}
      </div>
      <div style={{ fontSize: '11px' }}>
        <span style={{ color: top1Color, fontWeight: 600 }}>
          {result.top1_hit ? '✓' : '✗'} Top-1
        </span>
        <span style={{ marginLeft: '12px', color: topkColor, fontWeight: 600 }}>
          {result.topk_hit ? '✓' : '✗'} Top-K
        </span>
      </div>
      {result.top_paths && result.top_paths.length > 0 && (
        <div style={{
          marginTop: '6px',
          fontSize: '10px',
          fontFamily: "'SF Mono', monospace",
          color: 'var(--fg-muted)'
        }}>
          {result.top_paths.slice(0, 3).map((path: string, i: number) => {
            const match = result.expected_paths.some((exp: string) => path.includes(exp));
            const color = match ? 'var(--ok)' : 'var(--fg-muted)';
            return (
              <div key={i} style={{ color }}>
                {i + 1}. {path}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

// Helper component for comparison cards
const ComparisonCard: React.FC<{
  title: string;
  baseline: number;
  current: number;
  delta: number;
}> = ({ title, baseline, current, delta }) => {
  const deltaColor = delta >= 0 ? 'var(--ok)' : 'var(--err)';
  const icon = delta >= 0 ? '✓' : '✗';

  return (
    <div style={{
      background: 'var(--card-bg)',
      border: '1px solid var(--line)',
      borderRadius: '4px',
      padding: '12px'
    }}>
      <div style={{
        fontSize: '11px',
        color: 'var(--fg-muted)',
        textTransform: 'uppercase',
        letterSpacing: '0.5px',
        marginBottom: '4px'
      }}>
        {title}
      </div>
      <div style={{ fontSize: '14px', color: 'var(--fg-muted)', marginBottom: '4px' }}>
        Baseline: {(baseline * 100).toFixed(1)}%
      </div>
      <div style={{ fontSize: '14px', color: 'var(--fg)', marginBottom: '4px' }}>
        Current: {(current * 100).toFixed(1)}%
      </div>
      <div style={{ fontSize: '16px', color: deltaColor, fontWeight: 700 }}>
        {icon} {delta >= 0 ? '+' : ''}{(delta * 100).toFixed(1)}%
      </div>
    </div>
  );
};
