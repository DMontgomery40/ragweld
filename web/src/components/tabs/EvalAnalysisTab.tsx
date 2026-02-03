// TriBridRAG - Eval Analysis Tab
// Top-level tab for evaluation drill-down and AI analysis
// This is the keystone feature - comparing eval runs with LLM insights

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useSubtab } from '@/hooks';
import { EvalDrillDown } from '@/components/Evaluation/EvalDrillDown';
import { EvalDatasetSubtab } from '@/components/Evaluation/EvalDatasetSubtab';
import { SystemPromptsSubtab } from '@/components/Evaluation/SystemPromptsSubtab';
import { TraceViewer } from '@/components/Evaluation/TraceViewer';
import { LiveTerminal, LiveTerminalHandle } from '@/components/LiveTerminal/LiveTerminal';
import { TerminalService } from '@/services/TerminalService';
import { evalApi } from '@/api';
import { CollapsibleSection } from '@/components/ui/CollapsibleSection';
import { useConfigStore } from '@/stores/useConfigStore';
import { useActiveRepo, useRepoStore, useRepoInitialized, useRepoLoading, useRepos } from '@/stores';
import type { EvalRunMeta } from '@/types/generated';

type EvalSubtab = 'analysis' | 'dataset' | 'prompts' | 'trace';

export const EvalAnalysisTab: React.FC = () => {
  const { activeSubtab, setSubtab } = useSubtab<EvalSubtab>({ routePath: '/eval', defaultSubtab: 'analysis' });
  const [runs, setRuns] = useState<EvalRunMeta[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [compareRunId, setCompareRunId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Eval runner state
  const [evalRunning, setEvalRunning] = useState(false);
  const [evalProgress, setEvalProgress] = useState({ current: 0, total: 100, status: '' });
  const [terminalVisible, setTerminalVisible] = useState(false);
  const [sampleSize, setSampleSize] = useState<string>('');
  const terminalRef = useRef<LiveTerminalHandle>(null);

  // Eval settings from Pydantic config (Zustandic - syncs with backend)
  const config = useConfigStore((s) => s.config);
  const loadConfig = useConfigStore((s) => s.loadConfig);
  const patchSectionDebounced = useConfigStore((s) => s.patchSectionDebounced);
  const activeRepo = useActiveRepo();
  const repos = useRepos();
  const reposInitialized = useRepoInitialized();
  const reposLoading = useRepoLoading();
  const { loadRepos, setActiveRepo } = useRepoStore();

  // Reset run selection when corpus changes
  useEffect(() => {
    setRuns([]);
    setSelectedRunId(null);
    setCompareRunId(null);
  }, [activeRepo]);

  // Derive eval settings from config store - these mirror retrieval settings
  const evalUseMulti = (config?.retrieval?.eval_multi ?? 1) !== 0; // 0 = disabled, 1 = enabled
  const evalFinalK = config?.retrieval?.eval_final_k ?? 5;
  const evalMultiM = config?.evaluation?.eval_multi_m ?? 10;

  // Load config on mount
  useEffect(() => {
    if (!config) loadConfig();
  }, [config, loadConfig]);

  // Ensure corpora are loaded so activeRepo is valid
  useEffect(() => {
    if (!reposInitialized && !reposLoading) {
      loadRepos();
    }
  }, [loadRepos, reposInitialized, reposLoading]);

  // Terminal helpers
  const getTerminal = useCallback(() => {
    return terminalRef.current || (window as any).terminal_eval_analysis;
  }, []);

  const resetTerminal = useCallback((title = 'RAG Evaluation Logs') => {
    const terminal = getTerminal();
    if (terminal) {
      terminal.show?.();
      terminal.clear?.();
      terminal.setTitle?.(title);
    }
  }, [getTerminal]);

  const appendTerminalLine = useCallback((line: string) => {
    const terminal = getTerminal();
    terminal?.appendLine?.(line);
  }, [getTerminal]);

  const updateTerminalProgress = useCallback((percent: number, message?: string) => {
    const terminal = getTerminal();
    terminal?.updateProgress?.(percent, message);
  }, [getTerminal]);

  // Run full evaluation
  const runFullEvaluation = useCallback(async () => {
    console.log('[EvalAnalysisTab] runFullEvaluation called, evalRunning:', evalRunning);
    if (evalRunning) return;

    console.log('[EvalAnalysisTab] Starting eval run...');
    setEvalRunning(true);
    setEvalProgress({ current: 0, total: 100, status: 'Starting evaluation...' });
    setTerminalVisible(true);
    resetTerminal('RAG Evaluation Logs');

    const sampleLimit = sampleSize ? parseInt(sampleSize, 10) : undefined;
    const corpusId = String(activeRepo || '').trim();
    if (!corpusId) {
      setEvalRunning(false);
      setEvalProgress({ current: 0, total: 100, status: 'Select a corpus first' });
      appendTerminalLine('\x1b[31mMissing corpus selection. Choose a corpus and try again.\x1b[0m');
      return;
    }
    appendTerminalLine('🧪 Starting full RAG evaluation...');
    appendTerminalLine(
      `Settings: corpus_id=${corpusId}, use_multi=${evalUseMulti ? 'true' : 'false'}, final_k=${evalFinalK}, sample_limit=${sampleLimit || 'all'}`
    );

    console.log('[EvalAnalysisTab] Calling TerminalService.streamEvalRun with settings:', {
      use_multi: evalUseMulti,
      final_k: evalFinalK,
      sample_limit: sampleLimit,
    });
    try {
      TerminalService.streamEvalRun('eval_analysis_terminal', {
        corpus_id: corpusId,
        use_multi: evalUseMulti,
        final_k: evalFinalK,
        sample_limit: sampleLimit,
        onLine: (line) => {
          appendTerminalLine(line);
        },
        onProgress: (percent, message) => {
          setEvalProgress({
            current: percent,
            total: 100,
            status: message || 'Running evaluation...'
          });
          updateTerminalProgress(percent, message);
        },
        onError: (message) => {
          setEvalRunning(false);
          setEvalProgress((prev) => ({ ...prev, status: message || 'Error' }));
          appendTerminalLine(`\x1b[31mError: ${message}\x1b[0m`);
        },
        onComplete: async () => {
          console.log('[EvalAnalysisTab] onComplete fired - refreshing runs list');
          try {
            // Refresh runs list to get new eval
            const data = await evalApi.listRuns(corpusId);
            console.log('[EvalAnalysisTab] Got runs response:', data);
            const sortedRuns = (data.runs || []).sort((a: EvalRunMeta, b: EvalRunMeta) =>
              b.run_id.localeCompare(a.run_id)
            );
              console.log('[EvalAnalysisTab] Setting runs:', sortedRuns.length, 'first:', sortedRuns[0]?.run_id);
              setRuns(sortedRuns);
              // Auto-select the newest run
              if (sortedRuns.length > 0) {
                console.log('[EvalAnalysisTab] Auto-selecting newest run:', sortedRuns[0].run_id);
                setSelectedRunId(sortedRuns[0].run_id);
                if (sortedRuns.length > 1) {
                  setCompareRunId(sortedRuns[1].run_id);
                }
              }
            appendTerminalLine('\x1b[32m✓ Evaluation complete!\x1b[0m');
          } catch (err) {
            appendTerminalLine(`\x1b[31mError refreshing results: ${err}\x1b[0m`);
          } finally {
            setEvalRunning(false);
            setEvalProgress({ current: 100, total: 100, status: 'Complete' });
            updateTerminalProgress(100, 'Complete');
          }
        }
      });
    } catch (err) {
      setEvalRunning(false);
      setEvalProgress((prev) => ({ ...prev, status: 'Failed to start' }));
      appendTerminalLine(`\x1b[31mFailed to start evaluation: ${err}\x1b[0m`);
    }
  }, [activeRepo, appendTerminalLine, evalFinalK, evalRunning, evalUseMulti, resetTerminal, sampleSize, updateTerminalProgress]);

  // Check URL params for auto-run trigger (from RAG > Evaluate subtab)
  useEffect(() => {
    const hash = window.location.hash;
    if (hash.includes('autorun=true')) {
      // Remove the param from URL to prevent re-running on refresh
      const newHash = hash.replace(/[?&]autorun=true/, '').replace(/\?$/, '');
      window.history.replaceState(null, '', newHash || '#/eval-analysis');
      // Trigger the eval run after a brief delay to let component mount
      setTimeout(() => {
        runFullEvaluation();
      }, 500);
    }
  }, [runFullEvaluation]);

  // Fetch available eval runs
  useEffect(() => {
    const fetchRuns = async () => {
      try {
        setLoading(true);
        const corpusId = String(activeRepo || '').trim();
        if (!corpusId) {
          setRuns([]);
          setError(null);
          return;
        }
        const data = await evalApi.listRuns(corpusId);

        // Sort by timestamp descending (newest first)
        const sortedRuns = (data.runs || []).sort((a: EvalRunMeta, b: EvalRunMeta) =>
          b.run_id.localeCompare(a.run_id)
        );

        setRuns(sortedRuns);

        // Auto-select the most recent run
        if (sortedRuns.length > 0 && !selectedRunId) {
          setSelectedRunId(sortedRuns[0].run_id);
          // If there's a second run, auto-select it for comparison
          if (sortedRuns.length > 1) {
            setCompareRunId(sortedRuns[1].run_id);
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchRuns();
  }, [activeRepo]);

  // Format run label for dropdown
  const formatRunLabel = (run: EvalRunMeta) => {
    const date = run.run_id.replace(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/, '$1-$2-$3 $4:$5');
    const accuracy = (run.topk_accuracy * 100).toFixed(1);
    return `${date} — ${accuracy}% (${run.total} questions)`;
  };

  // Helper components for analysis subtab states
  const AnalysisLoadingState = () => (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100%',
      color: 'var(--fg-muted)'
    }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{
          width: '40px',
          height: '40px',
          border: '3px solid var(--line)',
          borderTopColor: 'var(--accent)',
          borderRadius: '50%',
          animation: 'spin 1s linear infinite',
          margin: '0 auto 16px'
        }} />
        Loading evaluation runs...
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    </div>
  );

  const AnalysisErrorState = () => (
    <div style={{
      padding: '24px',
      textAlign: 'center',
      color: 'var(--err)'
    }}>
      <div style={{ fontSize: '24px', marginBottom: '12px' }}>⚠️</div>
      <div>Error loading evaluation runs: {error}</div>
      <button
        onClick={() => window.location.reload()}
        style={{
          marginTop: '16px',
          padding: '8px 16px',
          background: 'var(--accent)',
          color: '#000',
          border: 'none',
          borderRadius: '6px',
          cursor: 'pointer'
        }}
      >
        Retry
      </button>
    </div>
  );

  const AnalysisEmptyState = () => (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100%',
      padding: '48px',
      textAlign: 'center'
    }}>
      <div style={{ fontSize: '48px', marginBottom: '16px' }}>📊</div>
      <h2 style={{ color: 'var(--fg)', marginBottom: '8px' }}>No Evaluation Runs Yet</h2>
      <p style={{ color: 'var(--fg-muted)', maxWidth: '400px', marginBottom: '24px' }}>
        Run your first evaluation to see detailed analysis and comparisons here.
      </p>
      <button
        onClick={runFullEvaluation}
        disabled={evalRunning}
        style={{
          padding: '12px 24px',
          background: evalRunning ? 'var(--bg-elev2)' : 'var(--accent)',
          color: evalRunning ? 'var(--fg-muted)' : '#000',
          border: 'none',
          borderRadius: '8px',
          fontSize: '14px',
          fontWeight: 600,
          cursor: evalRunning ? 'not-allowed' : 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}
      >
        <span>🧪</span>
        {evalRunning ? 'Running...' : 'Run First Evaluation'}
      </button>
    </div>
  );

  // Determine if header should be shown (only for analysis subtab with runs)
  const showHeader = activeSubtab === 'analysis' && !loading && !error && runs.length > 0;

  const clamp = (n: number, min: number, max: number): number => Math.min(max, Math.max(min, n));

  const renderRunSettings = () => (
    <CollapsibleSection
      title="Run Settings"
      description="Choose corpus and key evaluation parameters. Most values persist per corpus."
      defaultExpanded={false}
      storageKey="eval_run_settings"
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '14px' }}>
        <div>
          <label
            htmlFor="eval-run-settings-corpus"
            style={{ display: 'block', fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '6px' }}
          >
            Corpus
          </label>
          <select
            id="eval-run-settings-corpus"
            value={String(activeRepo || '')}
            disabled={reposLoading}
            onChange={(e) => void setActiveRepo(e.target.value)}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '8px',
              fontSize: '13px',
              cursor: reposLoading ? 'not-allowed' : 'pointer',
              opacity: reposLoading ? 0.7 : 1,
            }}
          >
            {repos.map((r) => (
              <option key={r.corpus_id} value={r.corpus_id}>
                {r.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label
            htmlFor="eval-run-settings-sample-size"
            style={{ display: 'block', fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '6px' }}
          >
            Sample Size (run only)
          </label>
          <select
            id="eval-run-settings-sample-size"
            value={sampleSize}
            onChange={(e) => setSampleSize(e.target.value)}
            disabled={evalRunning}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '8px',
              fontSize: '13px',
              cursor: evalRunning ? 'not-allowed' : 'pointer',
              opacity: evalRunning ? 0.7 : 1,
            }}
          >
            <option value="">All questions</option>
            <option value="10">10 questions</option>
            <option value="25">25 questions</option>
            <option value="50">50 questions</option>
          </select>
        </div>

        <div>
          <label
            htmlFor="eval-run-settings-final-k"
            style={{ display: 'block', fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '6px' }}
          >
            Final K (eval)
          </label>
          <input
            id="eval-run-settings-final-k"
            type="number"
            min={1}
            max={50}
            step={1}
            value={Number(evalFinalK)}
            disabled={evalRunning}
            onChange={(e) => {
              const next = clamp(parseInt(e.target.value || '0', 10) || 1, 1, 50);
              patchSectionDebounced('retrieval', { eval_final_k: next });
            }}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '8px',
              fontSize: '13px',
            }}
          />
        </div>

        <div>
          <label
            htmlFor="eval-run-settings-eval-multi"
            style={{ display: 'block', fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '6px' }}
          >
            Multi Q (eval)
          </label>
          <select
            id="eval-run-settings-eval-multi"
            value={String(config?.retrieval?.eval_multi ?? 1)}
            disabled={evalRunning}
            onChange={(e) => {
              const next = e.target.value === '0' ? 0 : 1;
              patchSectionDebounced('retrieval', { eval_multi: next });
            }}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '8px',
              fontSize: '13px',
              cursor: evalRunning ? 'not-allowed' : 'pointer',
              opacity: evalRunning ? 0.7 : 1,
            }}
          >
            <option value="1">Enabled</option>
            <option value="0">Disabled</option>
          </select>
        </div>

        <div>
          <label
            htmlFor="eval-run-settings-eval-multi-m"
            style={{ display: 'block', fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '6px' }}
          >
            Multi Q M (variants)
          </label>
          <input
            id="eval-run-settings-eval-multi-m"
            type="number"
            min={1}
            max={20}
            step={1}
            value={Number(evalMultiM)}
            disabled={evalRunning}
            onChange={(e) => {
              const next = clamp(parseInt(e.target.value || '0', 10) || 1, 1, 20);
              patchSectionDebounced('evaluation', { eval_multi_m: next });
            }}
            style={{
              width: '100%',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '10px 12px',
              borderRadius: '8px',
              fontSize: '13px',
            }}
          />
        </div>
      </div>

      <div style={{ marginTop: '14px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '14px' }}>
        <div style={{ borderTop: '1px solid var(--line)', paddingTop: '14px' }}>
          <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--fg)', marginBottom: '10px' }}>Fusion</div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '10px' }}>
            <div>
              <label
                htmlFor="eval-run-settings-fusion-method"
                style={{ display: 'block', fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '6px' }}
              >
                Method
              </label>
              <select
                id="eval-run-settings-fusion-method"
                value={String(config?.fusion?.method ?? 'rrf')}
                disabled={evalRunning}
                onChange={(e) => patchSectionDebounced('fusion', { method: e.target.value })}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '10px 12px',
                  borderRadius: '8px',
                  fontSize: '13px',
                }}
              >
                <option value="rrf">RRF</option>
                <option value="weighted">Weighted</option>
              </select>
            </div>

            <div>
              <label
                htmlFor="eval-run-settings-fusion-rrf-k"
                style={{ display: 'block', fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '6px' }}
              >
                RRF k
              </label>
              <input
                id="eval-run-settings-fusion-rrf-k"
                type="number"
                min={1}
                max={200}
                step={1}
                value={Number(config?.fusion?.rrf_k ?? 60)}
                disabled={evalRunning}
                onChange={(e) => {
                  const next = clamp(parseInt(e.target.value || '0', 10) || 1, 1, 200);
                  patchSectionDebounced('fusion', { rrf_k: next });
                }}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '10px 12px',
                  borderRadius: '8px',
                  fontSize: '13px',
                }}
              />
            </div>
          </div>
        </div>

        <div style={{ borderTop: '1px solid var(--line)', paddingTop: '14px' }}>
          <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--fg)', marginBottom: '10px' }}>Fusion Weights</div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px' }}>
            <div>
              <label
                htmlFor="eval-run-settings-fusion-vector-weight"
                style={{ display: 'block', fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '6px' }}
              >
                Vector
              </label>
              <input
                id="eval-run-settings-fusion-vector-weight"
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={Number(config?.fusion?.vector_weight ?? 0.4)}
                disabled={evalRunning}
                onChange={(e) => {
                  const next = clamp(parseFloat(e.target.value || '0') || 0, 0, 1);
                  patchSectionDebounced('fusion', { vector_weight: next });
                }}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '10px 12px',
                  borderRadius: '8px',
                  fontSize: '13px',
                }}
              />
            </div>

            <div>
              <label
                htmlFor="eval-run-settings-fusion-sparse-weight"
                style={{ display: 'block', fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '6px' }}
              >
                Sparse
              </label>
              <input
                id="eval-run-settings-fusion-sparse-weight"
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={Number(config?.fusion?.sparse_weight ?? 0.3)}
                disabled={evalRunning}
                onChange={(e) => {
                  const next = clamp(parseFloat(e.target.value || '0') || 0, 0, 1);
                  patchSectionDebounced('fusion', { sparse_weight: next });
                }}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '10px 12px',
                  borderRadius: '8px',
                  fontSize: '13px',
                }}
              />
            </div>

            <div>
              <label
                htmlFor="eval-run-settings-fusion-graph-weight"
                style={{ display: 'block', fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '6px' }}
              >
                Graph
              </label>
              <input
                id="eval-run-settings-fusion-graph-weight"
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={Number(config?.fusion?.graph_weight ?? 0.3)}
                disabled={evalRunning}
                onChange={(e) => {
                  const next = clamp(parseFloat(e.target.value || '0') || 0, 0, 1);
                  patchSectionDebounced('fusion', { graph_weight: next });
                }}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '10px 12px',
                  borderRadius: '8px',
                  fontSize: '13px',
                }}
              />
            </div>
          </div>
        </div>

        <div style={{ borderTop: '1px solid var(--line)', paddingTop: '14px' }}>
          <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--fg)', marginBottom: '10px' }}>Retrieval Legs</div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--fg)' }}>
                <input
                  type="checkbox"
                  checked={Boolean(config?.vector_search?.enabled ?? true)}
                  disabled={evalRunning}
                  onChange={(e) => patchSectionDebounced('vector_search', { enabled: e.target.checked })}
                />
                Vector
              </label>
              <input
                id="eval-run-settings-vector-topk"
                type="number"
                min={10}
                max={200}
                step={1}
                value={Number(config?.vector_search?.top_k ?? 50)}
                disabled={evalRunning || !(config?.vector_search?.enabled ?? true)}
                onChange={(e) => {
                  const next = clamp(parseInt(e.target.value || '0', 10) || 10, 10, 200);
                  patchSectionDebounced('vector_search', { top_k: next });
                }}
                style={{
                  width: '120px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '8px 10px',
                  borderRadius: '8px',
                  fontSize: '13px',
                }}
              />
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--fg)' }}>
                <input
                  type="checkbox"
                  checked={Boolean(config?.sparse_search?.enabled ?? true)}
                  disabled={evalRunning}
                  onChange={(e) => patchSectionDebounced('sparse_search', { enabled: e.target.checked })}
                />
                Sparse
              </label>
              <input
                id="eval-run-settings-sparse-topk"
                type="number"
                min={10}
                max={200}
                step={1}
                value={Number(config?.sparse_search?.top_k ?? 50)}
                disabled={evalRunning || !(config?.sparse_search?.enabled ?? true)}
                onChange={(e) => {
                  const next = clamp(parseInt(e.target.value || '0', 10) || 10, 10, 200);
                  patchSectionDebounced('sparse_search', { top_k: next });
                }}
                style={{
                  width: '120px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '8px 10px',
                  borderRadius: '8px',
                  fontSize: '13px',
                }}
              />
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--fg)' }}>
                <input
                  type="checkbox"
                  checked={Boolean(config?.graph_search?.enabled ?? true)}
                  disabled={evalRunning}
                  onChange={(e) => patchSectionDebounced('graph_search', { enabled: e.target.checked })}
                />
                Graph
              </label>
              <input
                id="eval-run-settings-graph-topk"
                type="number"
                min={5}
                max={100}
                step={1}
                value={Number(config?.graph_search?.top_k ?? 30)}
                disabled={evalRunning || !(config?.graph_search?.enabled ?? true)}
                onChange={(e) => {
                  const next = clamp(parseInt(e.target.value || '0', 10) || 5, 5, 100);
                  patchSectionDebounced('graph_search', { top_k: next });
                }}
                style={{
                  width: '120px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '8px 10px',
                  borderRadius: '8px',
                  fontSize: '13px',
                }}
              />
            </div>
          </div>
        </div>
      </div>
    </CollapsibleSection>
  );

  return (
    <div style={{
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden'
    }}>
      {/* Subtab Navigation - ALWAYS AT TOP */}
      <div style={{
        display: 'flex',
        gap: '2px',
        padding: '0 24px',
        borderBottom: '1px solid var(--line)',
        background: 'var(--bg-elev1)'
      }}>
        <button
          onClick={() => setSubtab('analysis')}
          data-tooltip="EVAL_ANALYSIS_SUBTAB"
          style={{
            padding: '12px 20px',
            background: activeSubtab === 'analysis' ? 'var(--bg)' : 'transparent',
            color: activeSubtab === 'analysis' ? 'var(--accent)' : 'var(--fg-muted)',
            border: 'none',
            borderBottom: activeSubtab === 'analysis' ? '2px solid var(--accent)' : '2px solid transparent',
            fontSize: '13px',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            transition: 'all 0.2s ease'
          }}
        >
          <span style={{ fontSize: '14px' }}>&#x1F4CA;</span>
          Eval Analysis
        </button>
        <button
          onClick={() => setSubtab('dataset')}
          style={{
            padding: '12px 20px',
            background: activeSubtab === 'dataset' ? 'var(--bg)' : 'transparent',
            color: activeSubtab === 'dataset' ? 'var(--accent)' : 'var(--fg-muted)',
            border: 'none',
            borderBottom: activeSubtab === 'dataset' ? '2px solid var(--accent)' : '2px solid transparent',
            fontSize: '13px',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            transition: 'all 0.2s ease'
          }}
        >
          <span style={{ fontSize: '14px' }}>&#x1F4DD;</span>
          Eval Dataset
        </button>
        <button
          onClick={() => setSubtab('prompts')}
          data-tooltip="SYSTEM_PROMPTS_SUBTAB"
          style={{
            padding: '12px 20px',
            background: activeSubtab === 'prompts' ? 'var(--bg)' : 'transparent',
            color: activeSubtab === 'prompts' ? 'var(--accent)' : 'var(--fg-muted)',
            border: 'none',
            borderBottom: activeSubtab === 'prompts' ? '2px solid var(--accent)' : '2px solid transparent',
            fontSize: '13px',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            transition: 'all 0.2s ease'
          }}
        >
          <span style={{ fontSize: '14px' }}>&#x1F4DD;</span>
          System Prompts
        </button>
        <button
          onClick={() => setSubtab('trace')}
          data-tooltip="TRACE_VIEWER_SUBTAB"
          style={{
            padding: '12px 20px',
            background: activeSubtab === 'trace' ? 'var(--bg)' : 'transparent',
            color: activeSubtab === 'trace' ? 'var(--accent)' : 'var(--fg-muted)',
            border: 'none',
            borderBottom: activeSubtab === 'trace' ? '2px solid var(--accent)' : '2px solid transparent',
            fontSize: '13px',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            transition: 'all 0.2s ease'
          }}
        >
          <span style={{ fontSize: '14px' }}>&#x1F50E;</span>
          Trace Viewer
        </button>
      </div>

      {/* Header with Run Selectors - only show for analysis subtab when runs exist */}
      {showHeader && (
      <div style={{
        padding: '20px 24px',
        borderBottom: '1px solid var(--line)',
        background: 'linear-gradient(135deg, var(--bg) 0%, var(--bg-elev1) 100%)'
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '16px'
        }}>
          <div>
            <h2 style={{
              fontSize: '22px',
              fontWeight: 700,
              color: 'var(--fg)',
              margin: 0,
              display: 'flex',
              alignItems: 'center',
              gap: '10px'
            }}>
              <span style={{ fontSize: '26px' }}>🔬</span>
              Eval Analysis
            </h2>
            <p style={{
              fontSize: '13px',
              color: 'var(--fg-muted)',
              margin: '4px 0 0'
            }}>
              Deep-dive into evaluation runs with AI-powered insights and recommendations
            </p>
          </div>
          
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontSize: '12px',
            color: 'var(--fg-muted)'
          }}>
            <span>{runs.length} runs available</span>
          </div>
        </div>

        {/* Run Selectors */}
        <div style={{
          display: 'flex',
          gap: '24px',
          alignItems: 'flex-end',
          flexWrap: 'wrap'
        }}>
          {/* Primary Run Selector */}
          <div style={{ flex: '1', minWidth: '280px' }}>
            <label 
              style={{ 
                display: 'block', 
                fontSize: '11px', 
                fontWeight: 600, 
                color: 'var(--accent)',
                textTransform: 'uppercase',
                marginBottom: '6px',
                letterSpacing: '0.5px'
              }}
            >
              Primary Run (AFTER)
              <span className="help-icon" data-tooltip="EVAL_PRIMARY_RUN" style={{ marginLeft: '4px', cursor: 'help' }}>?</span>
            </label>
            <select
              value={selectedRunId || ''}
              onChange={(e) => setSelectedRunId(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 12px',
                background: 'var(--input-bg)',
                color: 'var(--fg)',
                border: '2px solid var(--accent)',
                borderRadius: '8px',
                fontSize: '13px',
                fontWeight: 500,
                cursor: 'pointer'
              }}
            >
              {runs.map(run => (
                <option key={run.run_id} value={run.run_id}>
                  {formatRunLabel(run)}
                </option>
              ))}
            </select>
          </div>

          {/* Comparison Run Selector */}
          <div style={{ flex: '1', minWidth: '280px' }}>
            <label 
              style={{ 
                display: 'block', 
                fontSize: '11px', 
                fontWeight: 600, 
                color: 'var(--link)',
                textTransform: 'uppercase',
                marginBottom: '6px',
                letterSpacing: '0.5px'
              }}
            >
              Compare With (BEFORE)
              <span className="help-icon" data-tooltip="EVAL_COMPARE_RUN" style={{ marginLeft: '4px', cursor: 'help' }}>?</span>
            </label>
            <select
              value={compareRunId || ''}
              onChange={(e) => setCompareRunId(e.target.value || null)}
              style={{
                width: '100%',
                padding: '10px 12px',
                background: 'var(--input-bg)',
                color: 'var(--fg)',
                border: '2px solid var(--link)',
                borderRadius: '8px',
                fontSize: '13px',
                fontWeight: 500,
                cursor: 'pointer'
              }}
            >
              <option value="">— No comparison (single run view) —</option>
              {runs.filter(r => r.run_id !== selectedRunId).map(run => (
                <option key={run.run_id} value={run.run_id}>
                  {formatRunLabel(run)}
                </option>
              ))}
            </select>
          </div>

          {/* Quick Actions */}
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={() => {
                // Swap primary and compare
                const temp = selectedRunId;
                setSelectedRunId(compareRunId);
                setCompareRunId(temp);
              }}
              disabled={!compareRunId}
              style={{
                padding: '10px 14px',
                background: 'var(--bg-elev2)',
                color: 'var(--fg)',
                border: '1px solid var(--line)',
                borderRadius: '8px',
                fontSize: '13px',
                cursor: compareRunId ? 'pointer' : 'not-allowed',
                opacity: compareRunId ? 1 : 0.5,
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
              title="Swap primary and comparison runs"
            >
              ↕️ Swap
            </button>
            <button
              onClick={runFullEvaluation}
              disabled={evalRunning}
              data-tooltip="RUN_EVAL_ANALYSIS"
              style={{
                padding: '10px 18px',
                background: evalRunning ? 'var(--bg-elev2)' : 'var(--accent)',
                color: evalRunning ? 'var(--fg-muted)' : '#000',
                border: 'none',
                borderRadius: '8px',
                fontSize: '13px',
                fontWeight: 600,
                cursor: evalRunning ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
              title="Run a new evaluation and see live logs"
            >
              {evalRunning ? (
                <>
                  <span style={{
                    display: 'inline-block',
                    width: '14px',
                    height: '14px',
                    border: '2px solid var(--fg-muted)',
                    borderTopColor: 'var(--accent)',
                    borderRadius: '50%',
                    animation: 'spin 1s linear infinite'
                  }} />
                  Running...
                </>
              ) : (
                <>
                  <span>🚀</span>
                  Run Eval
                </>
              )}
            </button>
            {terminalVisible && (
              <button
                onClick={() => setTerminalVisible(false)}
                style={{
                  padding: '10px 14px',
                  background: 'var(--bg-elev2)',
                  color: 'var(--fg-muted)',
                  border: '1px solid var(--line)',
                  borderRadius: '8px',
                  fontSize: '13px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}
                title="Hide terminal logs"
              >
                ✕ Hide Logs
              </button>
            )}
          </div>
        </div>

        {renderRunSettings()}

        {/* Live Terminal Dropdown - slides down with cubic-bezier animation */}
        <div
          style={{
            maxHeight: terminalVisible ? '400px' : '0',
            opacity: terminalVisible ? 1 : 0,
            overflow: 'hidden',
            transition: 'max-height 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease',
            marginTop: terminalVisible ? '16px' : '0',
            paddingLeft: '24px',
            paddingRight: '24px'
          }}
        >
          <LiveTerminal
            ref={terminalRef}
            id="eval_analysis_terminal"
            title="RAG Evaluation Logs"
            initialContent={['Ready for evaluation...']}
          />
        </div>

        {/* Progress bar when running */}
        {evalRunning && (
          <div style={{
            padding: '12px 24px',
            background: 'var(--bg-elev1)',
            borderTop: '1px solid var(--line)'
          }}>
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '8px',
              fontSize: '12px'
            }}>
              <span style={{ color: 'var(--fg)' }}>{evalProgress.status}</span>
              <span style={{ color: 'var(--accent)', fontWeight: 600 }}>{evalProgress.current}%</span>
            </div>
            <div style={{
              height: '6px',
              background: 'var(--bg)',
              borderRadius: '3px',
              overflow: 'hidden'
            }}>
              <div
                style={{
                  height: '100%',
                  width: `${evalProgress.current}%`,
                  background: 'linear-gradient(90deg, var(--accent), var(--link))',
                  borderRadius: '3px',
                  transition: 'width 0.3s ease'
                }}
              />
            </div>
          </div>
        )}
      </div>
      )}

      {/* Content Area */}
      <div style={{
        flex: 1,
        overflow: 'auto'
      }}>
        {activeSubtab === 'analysis' ? (
          // Analysis subtab: handle loading/error/empty/data states
          loading ? (
            <AnalysisLoadingState />
          ) : error ? (
            <AnalysisErrorState />
          ) : runs.length === 0 ? (
            <div style={{ padding: '24px' }}>
              {renderRunSettings()}
              <AnalysisEmptyState />
            </div>
          ) : selectedRunId ? (
            <EvalDrillDown
              key={`${selectedRunId}-${compareRunId || 'none'}`}
              runId={selectedRunId}
              compareWithRunId={compareRunId || undefined}
            />
          ) : (
            <div style={{
              padding: '48px',
              textAlign: 'center',
              color: 'var(--fg-muted)'
            }}>
              Select an evaluation run to view details
            </div>
          )
        ) : activeSubtab === 'dataset' ? (
          <div style={{ padding: '24px' }}>
            <EvalDatasetSubtab />
          </div>
        ) : activeSubtab === 'prompts' ? (
          // System Prompts subtab - always accessible
          <SystemPromptsSubtab />
        ) : (
          <div style={{ padding: '24px' }}>
            <TraceViewer />
          </div>
        )}
      </div>
    </div>
  );
};

export default EvalAnalysisTab;
