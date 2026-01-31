import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useConfigStore } from '@/stores/useConfigStore';
import type { EvalResult, EvalRun } from '@/types/generated';

interface EvalDrillDownProps {
  runId: string;
  compareWithRunId?: string;
}

// Collapsible component for long values (especially prompts)
const CollapsibleValue: React.FC<{ value: string; maxLen?: number }> = ({ value, maxLen = 80 }) => {
  const [expanded, setExpanded] = useState(false);
  const isLong = value.length > maxLen;

  if (!isLong) {
    return <span style={{ wordBreak: 'break-word' }}>{value}</span>;
  }

  return (
    <span>
      <span style={{ wordBreak: 'break-word' }}>
        {expanded ? value : `${value.slice(0, maxLen)}...`}
      </span>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          marginLeft: '6px',
          padding: '2px 6px',
          fontSize: '10px',
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          borderRadius: '4px',
          cursor: 'pointer',
          verticalAlign: 'middle'
        }}
        title={expanded ? 'Collapse' : `Expand (${value.length} chars)`}
      >
        {expanded ? 'Collapse' : 'Expand'}
      </button>
    </span>
  );
};

// Helper to format config values with proper wrapping
const formatConfigValue = (value: any, key?: string): React.ReactNode => {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span style={{ color: 'var(--fg-muted)' }}>[]</span>;
    if (value.length <= 3) {
      return (
        <span style={{ wordBreak: 'break-word', maxWidth: '200px', display: 'inline-block' }}>
          {JSON.stringify(value)}
        </span>
      );
    }
    // For long arrays, show truncated with count
    return (
      <span title={JSON.stringify(value)} style={{ cursor: 'help' }}>
        [{value.slice(0, 2).map(v => JSON.stringify(v)).join(', ')}...]
        <span style={{ color: 'var(--fg-muted)', fontSize: '10px', marginLeft: '4px' }}>
          ({value.length} items)
        </span>
      </span>
    );
  }
  if (typeof value === 'boolean') {
    return value ? '✓' : '✗';
  }
  // Handle long strings - especially prompts
  if (typeof value === 'string' && value.length > 50) {
    // For prompt keys, use collapsible with smaller threshold
    const isPrompt = key?.toLowerCase().includes('prompt');
    return <CollapsibleValue value={value} maxLen={isPrompt ? 60 : 80} />;
  }
  return JSON.stringify(value);
};

export const EvalDrillDown: React.FC<EvalDrillDownProps> = ({ runId, compareWithRunId }) => {
  const [evalRun, setEvalRun] = useState<EvalRun | null>(null);
  const [compareRun, setCompareRun] = useState<EvalRun | null>(null);
  const [selectedQuestion, setSelectedQuestion] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // UI state
  const [configExpanded, setConfigExpanded] = useState(false);

  // LLM Analysis state
  const [llmAnalysis, setLlmAnalysis] = useState<string | null>(null);
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmError, setLlmError] = useState<string | null>(null);
  const [modelUsed, setModelUsed] = useState<string | null>(null);

  // Zustand - config key categories for grouping (from Pydantic backend)
  const { evalKeyCategories, loadEvalKeyCategories } = useConfigStore();

  // Load eval key categories on mount
  useEffect(() => {
    loadEvalKeyCategories();
  }, [loadEvalKeyCategories]);

  // Function to fetch LLM analysis
  const fetchLLMAnalysis = useCallback(async (
    currentRun: EvalRun, 
    compRun: EvalRun, 
    configDiffs: any[], 
    topkRegressions: EvalResult[], 
    topkImprovements: EvalResult[],
    top1RegressionsCount: number,
    top1ImprovementsCount: number
  ) => {
    setLlmLoading(true);
    setLlmError(null);
    setLlmAnalysis(null);
    
    try {
      const response = await fetch('/api/eval/analyze_comparison', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_run: {
            run_id: currentRun.run_id,
            top1_accuracy: currentRun.top1_accuracy,
            topk_accuracy: currentRun.topk_accuracy,
            total: currentRun.total,
            duration_secs: currentRun.duration_secs
          },
          compare_run: {
            run_id: compRun.run_id,
            top1_accuracy: compRun.top1_accuracy,
            topk_accuracy: compRun.topk_accuracy,
            total: compRun.total,
            duration_secs: compRun.duration_secs
          },
          config_diffs: configDiffs,
          // Top-K question-level changes (shown in results table)
          topk_regressions: topkRegressions.map(r => ({ question: r.question })),
          topk_improvements: topkImprovements.map(r => ({ question: r.question })),
          // Top-1 counts (for sanity checking)
          top1_regressions_count: top1RegressionsCount,
          top1_improvements_count: top1ImprovementsCount
        })
      });
      
      const data = await response.json();
      if (data.ok) {
        setLlmAnalysis(data.analysis);
        setModelUsed(data.model_used);
      } else {
        setLlmError(data.error || 'Failed to generate analysis');
      }
    } catch (err) {
      setLlmError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLlmLoading(false);
    }
  }, []);

  useEffect(() => {
    const fetchRuns = async () => {
      try {
        setLoading(true);
        // Reset ALL LLM analysis state when runs change
        setLlmAnalysis(null);
        setLlmError(null);
        setLlmLoading(false);
        setModelUsed(null);
        
        const response = await fetch(`/api/eval/results/${runId}`);
        if (!response.ok) throw new Error('Failed to fetch run data');
        const data: EvalRun = await response.json();
        console.log('[EvalDrillDown] Fetched data:', data);
        console.log('[EvalDrillDown] Question 0 expected_paths:', data.results?.[0]?.expected_paths);
        setEvalRun(data);

        if (compareWithRunId) {
          const compareResponse = await fetch(`/api/eval/results/${compareWithRunId}`);
          if (compareResponse.ok) {
            const compareData: EvalRun = await compareResponse.json();
            setCompareRun(compareData);
          }
        } else {
          setCompareRun(null);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchRuns();
  }, [runId, compareWithRunId]);

  // ==========================================================================
  // useMemo hooks MUST be called before any early returns (React hooks rules)
  // These are safe to call with null evalRun - they just return empty objects
  // ==========================================================================

  // Group config by category using Zustand-backed categories from Pydantic backend
  const groupedConfig = useMemo(() => {
    if (!evalRun?.config) return {};

    const groups: Record<string, Array<[string, any]>> = {};

    Object.entries(evalRun.config).forEach(([key, value]) => {
      // Get category from Zustand (backed by Pydantic), fallback to 'Other'
      const category = evalKeyCategories?.[key.toUpperCase()] || 'Other';
      if (!groups[category]) groups[category] = [];
      groups[category].push([key, value]);
    });

    return groups;
  }, [evalKeyCategories, evalRun?.config]);

  // Category order for display (derived from Zustand data)
  const categoryOrder = useMemo(() => {
    // Preferred display order
    const preferredOrder = [
      'BM25 Search', 'Embedding', 'Retrieval', 'Reranking', 'Chunking',
      'Scoring', 'Layer Bonuses', 'Keywords', 'Query Expansion', 'Other'
    ];

    // Get unique categories from groupedConfig
    const presentCategories = new Set(Object.keys(groupedConfig));

    // Return in preferred order, then any remaining
    return [
      ...preferredOrder.filter(cat => presentCategories.has(cat)),
      ...Array.from(presentCategories).filter(cat => !preferredOrder.includes(cat))
    ];
  }, [groupedConfig]);

  // ==========================================================================
  // Early returns for loading/error states (AFTER all hooks)
  // ==========================================================================

  if (loading) {
    return (
      <div style={{ padding: '24px', textAlign: 'center', color: 'var(--fg-muted)' }}>
        Loading evaluation details...
      </div>
    );
  }

  if (error || !evalRun) {
    return (
      <div style={{ padding: '24px', textAlign: 'center', color: 'var(--err)' }}>
        Error: {error || 'No data found'}
      </div>
    );
  }

  // Normalize config by merging snapshot with runtime fields so diffs always reflect actual run params
  const normalizeConfig = (run: EvalRun | null) => {
    if (!run) return {};
    const cfg = { ...(run.config || {}) };
    if (run.use_multi !== undefined) {
      cfg['use_multi'] = run.use_multi;
      cfg['eval_multi'] = run.use_multi ? 1 : 0;
    }
    if (run.final_k !== undefined) {
      cfg['final_k'] = run.final_k;
      cfg['eval_final_k'] = run.final_k;
    }
    return cfg;
  };

  const getConfigDiff = () => {
    if (!compareRun) return [];

    // Handle case where one or both runs don't have config
    const currentConfig = normalizeConfig(evalRun);
    const previousConfig = normalizeConfig(compareRun);

    const allKeys = new Set([...Object.keys(currentConfig), ...Object.keys(previousConfig)]);
    const diffs: Array<{ key: string; current: any; previous: any; changed: boolean; isEmbedding?: boolean }> = [];

    // Keys that indicate embedding configuration
    const embeddingKeys = ['EMBEDDING_TYPE', 'EMBEDDING_DIM', 'EMBEDDING_MODEL', 'EMBEDDING_TYPE_AT_INDEX', 'EMBED_TYPE'];

    allKeys.forEach(key => {
      const current = currentConfig[key];
      const previous = previousConfig[key];
      const changed = JSON.stringify(current) !== JSON.stringify(previous);
      if (changed) {
        const isEmbedding = embeddingKeys.some(ek => key.toUpperCase().includes(ek));
        diffs.push({ key, current, previous, changed, isEmbedding });
      }
    });

    // Sort to put embedding diffs first (critical)
    diffs.sort((a, b) => {
      if (a.isEmbedding && !b.isEmbedding) return -1;
      if (!a.isEmbedding && b.isEmbedding) return 1;
      return 0;
    });

    return diffs;
  };

  // Check if there's an embedding difference in the config diffs
  const hasEmbeddingDiff = (diffs: ReturnType<typeof getConfigDiff>) => {
    if (!diffs) return false;
    return diffs.some(d => d.isEmbedding);
  };

  const getRegressionStatus = (questionIdx: number) => {
    if (!compareRun || !compareRun.results?.[questionIdx]) return null;

    const currentHit = evalRun.results?.[questionIdx]?.topk_hit;
    const previousHit = compareRun.results?.[questionIdx]?.topk_hit;

    if (!currentHit && previousHit) return 'regression';
    if (currentHit && !previousHit) return 'improvement';
    return 'unchanged';
  };

  const configDiffs = getConfigDiff();
  const results = evalRun.results || [];
  const regressions = results.filter((_, idx) => getRegressionStatus(idx) === 'regression').length;
  const improvements = results.filter((_, idx) => getRegressionStatus(idx) === 'improvement').length;

  // Count total keys (groupedConfig is defined above early returns via useMemo)
  const retrievalKeyCount = Object.values(groupedConfig).reduce(
    (sum, params) => sum + (params?.length || 0), 0
  );

  return (
    <div className="eval-drill-down" style={{ padding: '24px' }}>
      {/* Summary Cards */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
        gap: '16px',
        marginBottom: '24px'
      }}>
        <div style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '16px'
        }}>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
            Top-1 Accuracy
          </div>
          <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--accent)' }}>
            {((evalRun?.top1_accuracy ?? 0) * 100).toFixed(1)}%
          </div>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
            {evalRun?.top1_hits ?? 0} / {evalRun?.total ?? 0} questions
          </div>
        </div>

        <div style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '16px'
        }}>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
            Top-K Accuracy
          </div>
          <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--link)' }}>
            {((evalRun?.topk_accuracy ?? 0) * 100).toFixed(1)}%
          </div>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
            {evalRun?.topk_hits ?? 0} / {evalRun?.total ?? 0} questions
          </div>
        </div>

        <div style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '16px'
        }}>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
            MRR
          </div>
          <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--warn)' }}>
            {evalRun?.metrics?.mrr !== undefined ? evalRun.metrics.mrr.toFixed(4) : 'N/A'}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
            Mean Reciprocal Rank
          </div>
        </div>

        <div style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '16px'
        }}>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
            Avg Duration
          </div>
          <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--fg)' }}>
            {(() => {
              const total = evalRun?.total ?? 0;
              const totalDuration = evalRun?.duration_secs ?? 0;
              const avgDuration = total > 0 ? totalDuration / total : 0;
              return avgDuration.toFixed(2);
            })()}s
          </div>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
            Total: {(evalRun?.duration_secs ?? 0).toFixed(1)}s ({((evalRun?.duration_secs ?? 0) / 60).toFixed(1)}m)
          </div>
        </div>

        {compareRun && (
          <>
            <div style={{
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              borderRadius: '8px',
              padding: '16px'
            }}>
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
                Regressions
              </div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--err)' }}>
                {regressions}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
                Questions that got worse
              </div>
            </div>

            <div style={{
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              borderRadius: '8px',
              padding: '16px'
            }}>
              <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
                Improvements
              </div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--accent-green)' }}>
                {improvements}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
                Questions that got better
              </div>
            </div>
          </>
        )}
      </div>

      {/* Run Configuration - Collapsible */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        marginBottom: '24px'
      }}>
        <button
          onClick={() => setConfigExpanded(!configExpanded)}
          style={{
            width: '100%',
            padding: '16px',
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '8px'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '16px' }}>⚙️</span>
            <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--fg)' }}>
              Run Configuration — {evalRun.run_id}
            </span>
            <span style={{
              fontSize: '11px',
              color: '#000',
              fontWeight: 600,
              background: 'var(--accent)',
              padding: '2px 8px',
              borderRadius: '10px'
            }}>
              {retrievalKeyCount} retrieval keys
            </span>
          </div>
          <span style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
            {configExpanded ? '▼ Collapse' : '▶ Expand'}
          </span>
        </button>

        {Object.keys(evalRun.config || {}).length === 0 ? (
          <div style={{ padding: '0 16px 16px' }}>
            <div style={{ color: 'var(--fg-muted)', fontSize: '12px', fontStyle: 'italic', marginBottom: '8px' }}>
              No config parameters captured for this run
            </div>
            <div style={{ fontSize: '10px', color: 'var(--fg-muted)', fontFamily: 'monospace', background: 'var(--bg-elev2)', padding: '8px', borderRadius: '4px' }}>
              DEBUG: config = {JSON.stringify(evalRun.config)}
            </div>
          </div>
        ) : configExpanded && (
          <div style={{ padding: '0 16px 16px' }}>
            {/* Categories and key mappings from Zustand (backed by Pydantic) */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
              {categoryOrder
                .filter(category => groupedConfig[category]?.length > 0)
                .map(category => {
                  const params = groupedConfig[category];
                  return (
                    <div key={category} style={{
                      background: 'var(--bg-elev2)',
                      borderRadius: '6px',
                      padding: '10px'
                    }}>
                      <div style={{
                        fontSize: '10px',
                        fontWeight: 600,
                        color: 'var(--accent)',
                        textTransform: 'uppercase',
                        marginBottom: '8px',
                        letterSpacing: '0.5px'
                      }}>
                        {category} ({params.length})
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {params.map(([key, value]) => (
                          <div key={key} style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'flex-start',
                            gap: '6px',
                            fontSize: '11px',
                            padding: '3px 6px',
                            background: 'var(--card-bg)',
                            borderRadius: '3px',
                            minWidth: 0
                          }}>
                            <span style={{
                              color: 'var(--fg)',
                              fontFamily: 'monospace',
                              flexShrink: 0,
                              fontSize: '10px'
                            }}>{key}</span>
                            <span style={{
                              color: 'var(--link)',
                              fontWeight: 600,
                              fontFamily: 'monospace',
                              textAlign: 'right',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              maxWidth: '140px',
                              fontSize: '10px'
                            }}>
                              {formatConfigValue(value, key)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>
        )}
      </div>

      {/* 🔥 CONFIG DIFF - THE MOST IMPORTANT SECTION 🔥 */}
      {compareRun && (
        <div style={{
          background: 'linear-gradient(135deg, rgba(var(--accent-rgb), 0.05), rgba(var(--link-rgb), 0.05))',
          border: '3px solid var(--accent)',
          borderRadius: '12px',
          padding: '24px',
          marginBottom: '32px',
          boxShadow: '0 8px 16px rgba(0,0,0,0.2)'
        }}>
          <h2 style={{
            fontSize: '18px',
            fontWeight: 700,
            color: 'var(--accent)',
            marginBottom: '8px',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            flexWrap: 'wrap'
          }}>
            <span style={{ fontSize: '24px' }}>🔍</span>
            CONFIGURATION CHANGES — ONLY WHAT'S DIFFERENT
            <span style={{
              fontSize: '14px',
              fontWeight: 600,
              background: 'var(--accent)',
              color: '#000',
              padding: '4px 12px',
              borderRadius: '12px'
            }}>
              {configDiffs.length} params changed
            </span>
            {/* Embedding difference badge - highlighted prominently */}
            {hasEmbeddingDiff(configDiffs) && (
              <span 
                data-tooltip="EMBEDDING_MISMATCH"
                style={{
                  fontSize: '12px',
                  fontWeight: 700,
                  background: 'linear-gradient(135deg, var(--warn), var(--err))',
                  color: '#000',
                  padding: '6px 14px',
                  borderRadius: '12px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  boxShadow: '0 2px 8px rgba(255,170,0,0.3)'
                }}
              >
                <span>⚠️</span>
                EMBEDDING DIFFERS
              </span>
            )}
          </h2>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '20px' }}>
            Comparing: <span style={{ fontFamily: 'monospace', color: 'var(--err)' }}>{compareRun?.run_id || 'baseline'}</span>
            {' → '}
            <span style={{ fontFamily: 'monospace', color: 'var(--accent-green)' }}>{evalRun.run_id}</span>
            {' • '}
            Performance change:
            <span style={{
              color: (evalRun.topk_accuracy ?? 0) > (compareRun?.topk_accuracy ?? 0) ? 'var(--accent-green)' : 'var(--err)',
              fontWeight: 600,
              marginLeft: '8px'
            }}>
              {(((evalRun.topk_accuracy ?? 0) - (compareRun?.topk_accuracy ?? 0)) * 100).toFixed(1)}%
            </span>
            {configDiffs.length === 0 && (
              <span style={{ marginLeft: '12px', color: 'var(--fg-muted)', fontStyle: 'italic' }}>
                No config deltas captured; AI analysis is still available.
              </span>
            )}
          </div>

          <div style={{ display: 'grid', gap: '12px', fontSize: '13px' }}>
            {configDiffs.map(({ key, current, previous }) => {
              // Determine if this param change correlates with improvement or regression
              const perfImproved = (evalRun.topk_accuracy ?? 0) > (compareRun?.topk_accuracy ?? 0);

              // Check if both values are arrays
              const isArray = Array.isArray(current) && Array.isArray(previous);

              if (isArray) {
                // Array diff logic
                const currentSet = new Set(current);
                const previousSet = new Set(previous);
                const onlyInCurrent = current.filter((item: any) => !previousSet.has(item));
                const onlyInPrevious = previous.filter((item: any) => !currentSet.has(item));
                const hasDiffs = onlyInCurrent.length > 0 || onlyInPrevious.length > 0;

                if (!hasDiffs) return null; // Skip if no actual changes

                return (
                  <details key={key} style={{
                    padding: '12px 16px',
                    background: 'var(--card-bg)',
                    border: '2px solid var(--line)',
                    borderRadius: '8px',
                  }}>
                    <summary style={{
                      fontWeight: 700,
                      color: 'var(--accent)',
                      fontFamily: 'monospace',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '12px'
                    }}>
                      {key}
                      <span style={{ fontSize: '11px', fontWeight: 400, color: 'var(--fg-muted)' }}>
                        ({onlyInCurrent.length} different in AFTER, {onlyInPrevious.length} different in BEFORE)
                      </span>
                    </summary>
                    <div style={{ marginTop: '12px', display: 'grid', gap: '8px', fontSize: '12px' }}>
                      {onlyInCurrent.length > 0 && (
                        <div>
                          <div style={{ fontWeight: 600, color: 'var(--accent-green)', marginBottom: '4px' }}>
                            ✓ In AFTER only:
                          </div>
                          <div style={{ paddingLeft: '16px', fontFamily: 'monospace', color: 'var(--fg-muted)' }}>
                            {onlyInCurrent.map((item: any, idx: number) => (
                              <div key={idx}>{JSON.stringify(item)}</div>
                            ))}
                          </div>
                        </div>
                      )}
                      {onlyInPrevious.length > 0 && (
                        <div>
                          <div style={{ fontWeight: 600, color: 'var(--err)', marginBottom: '4px' }}>
                            ✗ In BEFORE only:
                          </div>
                          <div style={{ paddingLeft: '16px', fontFamily: 'monospace', color: 'var(--fg-muted)' }}>
                            {onlyInPrevious.map((item: any, idx: number) => (
                              <div key={idx}>{JSON.stringify(item)}</div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </details>
                );
              }

              // Non-array params - compact layout with truncation
              const formatValue = (val: any) => {
                if (val === undefined) return '(not set)';
                if (val === null) return 'null';
                const str = JSON.stringify(val);
                if (str && str.length > 20) return str.slice(0, 17) + '...';
                return str || '(empty)';
              };

              // Check if this is an embedding-related key
              const embeddingKeyPattern = /EMBED|embedding/i;
              const isEmbeddingKey = embeddingKeyPattern.test(key);
              
              return (
                <div key={key} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  padding: '10px 16px',
                  background: isEmbeddingKey 
                    ? 'linear-gradient(135deg, rgba(255, 170, 0, 0.15), rgba(255, 107, 107, 0.1))' 
                    : 'var(--card-bg)',
                  border: isEmbeddingKey 
                    ? '2px solid var(--warn)' 
                    : '1px solid var(--line)',
                  borderRadius: '8px',
                  flexWrap: 'wrap',
                  position: 'relative'
                }}>
                  <div style={{ 
                    fontWeight: 600, 
                    color: 'var(--accent)', 
                    fontFamily: 'monospace',
                    minWidth: '160px',
                    fontSize: '13px'
                  }}>
                    {key}
                  </div>
                  <div style={{ 
                    display: 'flex', 
                    gap: '8px', 
                    fontFamily: 'monospace', 
                    alignItems: 'center',
                    fontSize: '12px'
                  }}>
                    <div 
                      title={JSON.stringify(previous)}
                      style={{
                        padding: '4px 10px',
                        background: 'var(--bg-elev2)',
                        border: '1px solid var(--fg-muted)',
                        borderRadius: '4px',
                        color: 'var(--fg-muted)',
                        fontWeight: 500,
                        maxWidth: '150px',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                      }}
                    >
                      {formatValue(previous)}
                    </div>
                    <span style={{ color: 'var(--accent)', fontSize: '14px' }}>→</span>
                    <div 
                      title={JSON.stringify(current)}
                      style={{
                        padding: '4px 10px',
                        background: perfImproved 
                          ? 'rgba(var(--accent-green-rgb), 0.15)' 
                          : 'rgba(var(--err-rgb), 0.15)',
                        border: `1px solid ${perfImproved ? 'var(--accent-green)' : 'var(--err)'}`,
                        borderRadius: '4px',
                        color: perfImproved ? 'var(--accent-green)' : 'var(--err)',
                        fontWeight: 600,
                        maxWidth: '150px',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                      }}
                    >
                      {formatValue(current)}
                    </div>
                  </div>
                </div>
              );
            })}
            {configDiffs.length === 0 && (
              <div style={{
                padding: '12px 16px',
                background: 'var(--card-bg)',
                border: '1px dashed var(--line)',
                borderRadius: '8px',
                color: 'var(--fg-muted)',
                fontSize: '12px'
              }}>
                No configuration differences detected between runs. If you expected changes, verify that eval config keys are captured via Pydantic and rerun.
              </div>
            )}
          </div>

          {/* Regression/Improvement Correlation Summary */}
          <div style={{
            marginTop: '20px',
            padding: '16px',
            background: 'var(--bg-elev2)',
            borderRadius: '8px',
            border: '1px solid var(--line)'
          }}>
            <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--fg)', marginBottom: '12px' }}>
              📊 Impact Analysis:
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', fontSize: '12px' }}>
              <div>
                <span style={{ color: 'var(--err)', fontWeight: 600 }}>{regressions} regressions</span>
                <span style={{ color: 'var(--fg-muted)' }}> (questions that got worse)</span>
              </div>
              <div>
                <span style={{ color: 'var(--accent-green)', fontWeight: 600 }}>{improvements} improvements</span>
                <span style={{ color: 'var(--fg-muted)' }}> (questions that got better)</span>
              </div>
            </div>
          </div>

          {/* 🤖 LLM Analysis Section */}
          <div style={{
            marginTop: '24px',
            padding: '20px',
            background: 'linear-gradient(135deg, rgba(var(--link-rgb), 0.08), rgba(var(--accent-rgb), 0.04))',
            borderRadius: '12px',
            border: '2px solid var(--link)'
          }}>
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '16px'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '20px' }}>🤖</span>
                <h4 style={{
                  margin: 0,
                  fontSize: '15px',
                  fontWeight: 700,
                  color: 'var(--link)'
                }}>
                  AI Analysis & Recommendations
                </h4>
                {modelUsed && (
                  <span style={{
                    fontSize: '10px',
                    padding: '3px 8px',
                    background: 'var(--bg-elev2)',
                    borderRadius: '10px',
                    color: 'var(--fg-muted)'
                  }}>
                    {modelUsed}
                  </span>
                )}
              </div>
              
              {!llmAnalysis && !llmLoading && (
                <button
                  onClick={() => {
                    if (evalRun && compareRun) {
                      const evalResults = evalRun.results || [];
                      const compareResults = compareRun.results || [];
                      // Calculate Top-K changes (what we show in the table)
                      const topkRegressions = evalResults.filter((_, idx) => {
                        const currentHit = evalResults[idx]?.topk_hit;
                        const previousHit = compareResults[idx]?.topk_hit;
                        return !currentHit && previousHit;
                      });
                      const topkImprovements = evalResults.filter((_, idx) => {
                        const currentHit = evalResults[idx]?.topk_hit;
                        const previousHit = compareResults[idx]?.topk_hit;
                        return currentHit && !previousHit;
                      });
                      // Calculate Top-1 changes (for complete picture)
                      const top1Regressions = evalResults.filter((_, idx) => {
                        const currentHit = evalResults[idx]?.top1_hit;
                        const previousHit = compareResults[idx]?.top1_hit;
                        return !currentHit && previousHit;
                      });
                      const top1Improvements = evalResults.filter((_, idx) => {
                        const currentHit = evalResults[idx]?.top1_hit;
                        const previousHit = compareResults[idx]?.top1_hit;
                        return currentHit && !previousHit;
                      });
                      // Send both metrics for accurate analysis
                      fetchLLMAnalysis(
                        evalRun,
                        compareRun,
                        configDiffs || [],
                        topkRegressions,
                        topkImprovements,
                        top1Regressions.length,
                        top1Improvements.length
                      );
                    }
                  }}
                  style={{
                    background: 'var(--link)',
                    color: 'white',
                    border: 'none',
                    padding: '10px 20px',
                    borderRadius: '8px',
                    fontSize: '13px',
                    fontWeight: 600,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}
                >
                  <span>✨</span>
                  Generate AI Analysis
                </button>
              )}
              
              {llmAnalysis && (
                <button
                  onClick={() => {
                    setLlmAnalysis(null);
                    setLlmError(null);
                  }}
                  style={{
                    background: 'transparent',
                    color: 'var(--fg-muted)',
                    border: '1px solid var(--line)',
                    padding: '6px 12px',
                    borderRadius: '6px',
                    fontSize: '11px',
                    cursor: 'pointer'
                  }}
                >
                  Clear
                </button>
              )}
            </div>

            {llmLoading && (
              <div style={{
                textAlign: 'center',
                padding: '32px',
                color: 'var(--fg-muted)'
              }}>
                <div style={{ fontSize: '24px', marginBottom: '12px' }}>⏳</div>
                <div>Analyzing comparison with AI...</div>
                <div style={{ fontSize: '11px', marginTop: '8px', opacity: 0.7 }}>
                  This may take a few seconds
                </div>
              </div>
            )}

            {llmError && (
              <div style={{
                background: 'rgba(var(--err-rgb), 0.1)',
                border: '1px solid var(--err)',
                borderRadius: '8px',
                padding: '16px',
                color: 'var(--err)',
                fontSize: '13px'
              }}>
                <strong>Error:</strong> {llmError}
              </div>
            )}

            {llmAnalysis && (
              <div style={{
                background: 'var(--card-bg)',
                borderRadius: '8px',
                padding: '20px',
                fontSize: '13px',
                lineHeight: 1.7,
                color: 'var(--fg)'
              }}>
                {/* Render markdown-like content */}
                {llmAnalysis.split('\n').map((line, idx) => {
                  // Headers
                  if (line.startsWith('## ')) {
                    return (
                      <h3 key={idx} style={{
                        fontSize: '15px',
                        fontWeight: 700,
                        color: 'var(--accent)',
                        marginTop: idx > 0 ? '20px' : 0,
                        marginBottom: '12px',
                        borderBottom: '1px solid var(--line)',
                        paddingBottom: '8px'
                      }}>
                        {line.replace('## ', '')}
                      </h3>
                    );
                  }
                  if (line.startsWith('### ')) {
                    return (
                      <h4 key={idx} style={{
                        fontSize: '14px',
                        fontWeight: 600,
                        color: 'var(--link)',
                        marginTop: '16px',
                        marginBottom: '8px'
                      }}>
                        {line.replace('### ', '')}
                      </h4>
                    );
                  }
                  // Bold text
                  if (line.startsWith('**') && line.endsWith('**')) {
                    return (
                      <div key={idx} style={{
                        fontWeight: 700,
                        color: 'var(--fg)',
                        marginTop: '12px',
                        marginBottom: '4px'
                      }}>
                        {line.replace(/\*\*/g, '')}
                      </div>
                    );
                  }
                  // List items
                  if (line.match(/^[\d]+\.\s/) || line.startsWith('- ')) {
                    return (
                      <div key={idx} style={{
                        paddingLeft: '20px',
                        marginBottom: '6px',
                        position: 'relative'
                      }}>
                        <span style={{
                          position: 'absolute',
                          left: 0,
                          color: 'var(--accent)'
                        }}>
                          {line.startsWith('- ') ? '•' : line.match(/^[\d]+/)?.[0] + '.'}
                        </span>
                        {line.replace(/^[\d]+\.\s/, '').replace(/^-\s/, '')}
                      </div>
                    );
                  }
                  // Empty lines
                  if (line.trim() === '') {
                    return <div key={idx} style={{ height: '8px' }} />;
                  }
                  // Regular paragraph
                  return (
                    <p key={idx} style={{ margin: '8px 0' }}>
                      {line}
                    </p>
                  );
                })}
              </div>
            )}

            {!llmAnalysis && !llmLoading && !llmError && (
              <div style={{
                textAlign: 'center',
                padding: '24px',
                color: 'var(--fg-muted)',
                fontSize: '13px'
              }}>
                Click "Generate AI Analysis" to get insights about this comparison,
                including root cause analysis and actionable recommendations.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Question Results Table */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        overflow: 'hidden'
      }}>
        <div style={{
          padding: '16px',
          borderBottom: '1px solid var(--line)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <h3 style={{
            fontSize: '14px',
            fontWeight: 600,
            color: 'var(--fg)',
            margin: 0
          }}>
            Question Results
          </h3>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
            Click any question to see details
          </div>
        </div>

        <div style={{ maxHeight: '600px', overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead style={{ position: 'sticky', top: 0, background: 'var(--bg-elev2)', zIndex: 1 }}>
              <tr>
                <th style={{ padding: '10px', textAlign: 'left', fontSize: '11px', fontWeight: 600, color: 'var(--fg-muted)', textTransform: 'uppercase' }}>
                  #
                </th>
                <th style={{ padding: '10px', textAlign: 'left', fontSize: '11px', fontWeight: 600, color: 'var(--fg-muted)', textTransform: 'uppercase' }}>
                  Question
                </th>
                <th style={{ padding: '10px', textAlign: 'center', fontSize: '11px', fontWeight: 600, color: 'var(--fg-muted)', textTransform: 'uppercase' }}>
                  Top-1
                </th>
                <th style={{ padding: '10px', textAlign: 'center', fontSize: '11px', fontWeight: 600, color: 'var(--fg-muted)', textTransform: 'uppercase' }}>
                  Top-K
                </th>
                <th style={{ padding: '10px', textAlign: 'center', fontSize: '11px', fontWeight: 600, color: 'var(--fg-muted)', textTransform: 'uppercase' }}>
                  Duration
                </th>
                {compareRun && (
                  <th style={{ padding: '10px', textAlign: 'center', fontSize: '11px', fontWeight: 600, color: 'var(--fg-muted)', textTransform: 'uppercase' }}>
                    Status
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {results.map((result, idx) => {
                const status = getRegressionStatus(idx);
                const isExpanded = selectedQuestion === idx;

                return (
                  <React.Fragment key={idx}>
                    <tr
                      onClick={() => setSelectedQuestion(isExpanded ? null : idx)}
                      style={{
                        borderBottom: '1px solid var(--line)',
                        background: isExpanded ? 'var(--bg-elev2)' : 'transparent',
                        cursor: 'pointer'
                      }}
                    >
                      <td style={{ padding: '10px', fontFamily: 'monospace', fontSize: '12px', color: 'var(--fg-muted)' }}>
                        {idx + 1}
                      </td>
                      <td style={{ padding: '10px', fontSize: '12px', color: 'var(--fg)', maxWidth: '400px' }}>
                        {result.question}
                      </td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>
                        <span style={{
                          display: 'inline-block',
                          width: '20px',
                          height: '20px',
                          borderRadius: '50%',
                          background: result.top1_hit ? 'var(--accent-green)' : 'var(--err)',
                          color: 'white',
                          fontSize: '11px',
                          fontWeight: 600,
                          lineHeight: '20px'
                        }}>
                          {result.top1_hit ? '✓' : '✗'}
                        </span>
                      </td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>
                        <span style={{
                          display: 'inline-block',
                          width: '20px',
                          height: '20px',
                          borderRadius: '50%',
                          background: result.topk_hit ? 'var(--accent-green)' : 'var(--err)',
                          color: 'white',
                          fontSize: '11px',
                          fontWeight: 600,
                          lineHeight: '20px'
                        }}>
                          {result.topk_hit ? '✓' : '✗'}
                        </span>
                      </td>
                      <td style={{ padding: '10px', textAlign: 'center', fontFamily: 'monospace', fontSize: '11px', color: 'var(--fg-muted)' }}>
                        <div>{(result?.duration_secs ?? 0).toFixed(2)}s</div>
                        <div style={{ fontSize: '9px', color: 'var(--fg-muted)' }}>
                          ({((result?.duration_secs ?? 0) * 1000).toFixed(0)}ms)
                        </div>
                      </td>
                      {compareRun && (
                        <td style={{ padding: '10px', textAlign: 'center' }}>
                          {status === 'regression' && (
                            <span style={{ color: 'var(--err)', fontWeight: 600, fontSize: '11px' }}>⬇ WORSE</span>
                          )}
                          {status === 'improvement' && (
                            <span style={{ color: 'var(--accent-green)', fontWeight: 600, fontSize: '11px' }}>⬆ BETTER</span>
                          )}
                          {status === 'unchanged' && (
                            <span style={{ color: 'var(--fg-muted)', fontSize: '11px' }}>—</span>
                          )}
                        </td>
                      )}
                    </tr>

                    {/* Expanded Detail */}
                    {isExpanded && (
                      <tr>
                        <td colSpan={compareRun ? 6 : 5} style={{ padding: '16px', background: 'var(--bg-elev1)' }}>
                          <div style={{ display: 'grid', gap: '16px', fontSize: '12px' }}>
                            {/* Expected Paths */}
                            <div>
                              <div style={{ fontWeight: 600, color: 'var(--accent)', marginBottom: '8px' }}>
                                ✓ Expected Paths:
                                <span style={{ fontSize: '10px', color: 'var(--fg-muted)', marginLeft: '8px' }}>
                                  (type: {typeof result.expected_paths}, array: {Array.isArray(result.expected_paths) ? 'yes' : 'no'}, count: {result.expected_paths?.length ?? 0})
                                </span>
                              </div>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                {result.expected_paths && Array.isArray(result.expected_paths) && result.expected_paths.length > 0 ? (
                                  result.expected_paths.map((path, i) => (
                                    <div key={i} style={{
                                      fontFamily: 'monospace',
                                      padding: '6px 10px',
                                      background: 'var(--card-bg)',
                                      borderRadius: '4px',
                                      color: 'var(--fg)'
                                    }}>
                                      {path}
                                    </div>
                                  ))
                                ) : (
                                  <div style={{ color: 'var(--fg-muted)' }}>No expected paths specified</div>
                                )}
                              </div>
                            </div>

                            {/* Returned Paths */}
                            <div>
                              <div style={{ fontWeight: 600, color: 'var(--link)', marginBottom: '8px' }}>
                                → Returned Paths:
                              </div>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                {result.top_paths && result.top_paths.length > 0 ? (
                                  result.top_paths.map((path, i) => {
                                    const isExpected = result.expected_paths?.some(exp => path.includes(exp));
                                    return (
                                      <div key={i} style={{
                                        fontFamily: 'monospace',
                                        padding: '6px 10px',
                                        background: isExpected ? 'rgba(var(--accent-green-rgb), 0.1)' : 'var(--card-bg)',
                                        borderRadius: '4px',
                                        borderLeft: isExpected ? '3px solid var(--accent-green)' : 'none',
                                        color: 'var(--fg)',
                                        display: 'flex',
                                        justifyContent: 'space-between'
                                      }}>
                                        <span>{path}</span>
                                        {isExpected && (
                                          <span style={{ color: 'var(--accent-green)', fontWeight: 600 }}>✓ MATCH</span>
                                        )}
                                      </div>
                                    );
                                  })
                                ) : (
                                  <div style={{ color: 'var(--err)' }}>No results returned</div>
                                )}
                              </div>
                            </div>

                            {/* Scores if available */}
                            {result.docs && result.docs.length > 0 && (
                              <div>
                                <div style={{ fontWeight: 600, color: 'var(--fg)', marginBottom: '8px' }}>
                                  Document Scores:
                                  {(() => {
                                    const scores = result.docs.map(d => d?.score ?? 0);
                                    const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
                                    const min = Math.min(...scores);
                                    const max = Math.max(...scores);
                                    return (
                                      <span style={{ fontSize: '10px', color: 'var(--fg-muted)', marginLeft: '8px', fontWeight: 'normal' }}>
                                        (avg: {avg.toFixed(4)}, min: {min.toFixed(4)}, max: {max.toFixed(4)})
                                      </span>
                                    );
                                  })()}
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                  {result.docs.map((doc, i) => (
                                    <div key={i} style={{
                                      display: 'flex',
                                      justifyContent: 'space-between',
                                      fontFamily: 'monospace',
                                      padding: '6px 10px',
                                      background: 'var(--card-bg)',
                                      borderRadius: '4px'
                                    }}>
                                      <span style={{ color: 'var(--fg)' }}>{doc.file_path}</span>
                                      <span style={{ color: 'var(--accent)', fontWeight: 600 }}>
                                        {(doc?.score ?? 0).toFixed(4)}
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
