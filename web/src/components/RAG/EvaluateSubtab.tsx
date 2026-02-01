// React implementation of EvaluateSubtab - NO legacy JS modules
import { useState, useEffect, useCallback, useRef } from 'react';
import { useAPI, useConfigField } from '@/hooks';
import { EvalDrillDown } from '@/components/Evaluation/EvalDrillDown';
import { LiveTerminal, LiveTerminalHandle } from '@/components/LiveTerminal/LiveTerminal';
import { TerminalService } from '@/services/TerminalService';
import type { EvalDatasetItem, EvalResult, EvalRun, EvalRunMeta, EvalRunsResponse, EvalTestRequest } from '@/types/generated';

// Recommended eval_dataset entries for the TriBridRAG codebase
const RECOMMENDED_EVAL_DATASET: Array<Pick<EvalDatasetItem, 'question' | 'expected_paths'>> = [
  { question: 'Where are chunk summaries API endpoints implemented?', expected_paths: ['server/api/chunk_summaries.py'] },
  { question: 'Where is keyword generation implemented?', expected_paths: ['server/api/keywords.py'] },
  { question: 'Where are eval_dataset CRUD endpoints implemented?', expected_paths: ['server/api/dataset.py'] },
  { question: 'Where are eval run endpoints implemented?', expected_paths: ['server/api/eval.py'] },
  { question: 'Where is config persistence implemented?', expected_paths: ['server/api/config.py', 'server/services/config_store.py'] },
];

/**
 * ---agentspec
 * what: |
 *   React component for evaluation subtab. Manages eval entries, runs test suite, tracks progress, displays results.
 *
 * why: |
 *   Centralizes eval UI state and API calls in single component for cohesion.
 *
 * guardrails:
 *   - DO NOT block UI during evalRunning; use async/await with setEvalRunning gates
 *   - NOTE: testResults keyed by question ID; ensure ID stability across re-renders
 * ---/agentspec
 */
export function EvaluateSubtab() {
  const { api } = useAPI();
  const [corpusId, setCorpusId] = useState<string>(() => {
    return (
      localStorage.getItem('tribrid_active_corpus') ||
      localStorage.getItem('tribrid_active_repo') ||
      'tribrid'
    );
  });
  const [evalDataset, setEvalDataset] = useState<EvalDatasetItem[]>([]);
  const [newEntry, setNewEntry] = useState({ question: '', paths: '', tags: '' });
  const [testResults, setTestResults] = useState<Record<string, EvalResult>>({});
  const [evalRunning, setEvalRunning] = useState(false);
  const [evalProgress, setEvalProgress] = useState({ current: 0, total: 0, status: '' });
  const [evalResults, setEvalResults] = useState<EvalRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evalMulti, setEvalMulti] = useConfigField<number>('retrieval.eval_multi', 1);
  const [evalFinalK, setEvalFinalK] = useConfigField<number>('retrieval.eval_final_k', 5);
  const [sampleSize, setSampleSize] = useState<string>(() => localStorage.getItem('eval_sampleSize') || '');
  const [availableRuns, setAvailableRuns] = useState<EvalRunMeta[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [compareRunId, setCompareRunId] = useState<string | null>(null);
  const [latestRunId, setLatestRunId] = useState<string | null>(null);
  const [showDrillDown, setShowDrillDown] = useState(false);
  const [terminalVisible, setTerminalVisible] = useState(false);
  const terminalRef = useRef<LiveTerminalHandle>(null);

  /**
   * ---agentspec
   * what: |
   *   Retrieves terminal instance from ref or global fallback. Resets terminal state (show, clear) with optional title.
   *
   * why: |
   *   Centralizes terminal access pattern; handles both React ref and global window.terminal_eval_terminal.
   *
   * guardrails:
   *   - DO NOT assume terminal exists; check before calling methods
   *   - NOTE: Fallback to window.terminal_eval_terminal only if ref is null
   * ---/agentspec
   */
  const getTerminal = useCallback(() => {
    return terminalRef.current || (window as any).terminal_eval_terminal;
  }, []);

  /**
   * ---agentspec
   * what: |
   *   Resets VS Code terminal: shows, clears, sets title. Takes optional title string; no return.
   *
   * why: |
   *   Centralizes terminal state reset to avoid repeated null checks across codebase.
   *
   * guardrails:
   *   - DO NOT assume terminal exists; all methods are optional chained
   *   - NOTE: Title defaults to 'RAG Evaluation Logs' if omitted
   * ---/agentspec
   */
  const resetTerminal = useCallback((title = 'RAG Evaluation Logs') => {
    const terminal = getTerminal();
    if (terminal) {
      terminal.show?.();
      terminal.clear?.();
      terminal.setTitle?.(title);
    }
  }, [getTerminal]);

  /**
   * ---agentspec
   * what: |
   *   Appends text lines to terminal and updates progress bar. Takes string or (percent, message) → calls terminal methods.
   *
   * why: |
   *   Wraps terminal ref access with useCallback to prevent unnecessary re-renders and provide stable function identity.
   *
   * guardrails:
   *   - DO NOT call if terminal is undefined; methods are optional chained
   *   - NOTE: Progress updates require terminal.updateProgress support; verify before use
   * ---/agentspec
   */
  const appendTerminalLine = useCallback((line: string) => {
    const terminal = getTerminal();
    terminal?.appendLine?.(line);
  }, [getTerminal]);

  /**
   * ---agentspec
   * what: |
   *   updateTerminalProgress: Updates terminal UI progress bar with percent + optional message. fetchJson: Fetches JSON from API endpoint with default headers, merges custom options.
   *
   * why: |
   *   Encapsulates terminal updates and API calls for reuse across components; consistent header injection.
   *
   * guardrails:
   *   - DO NOT call updateTerminalProgress if terminal is undefined; guard with optional chaining
   *   - NOTE: fetchJson assumes api() helper exists; will fail silently if missing
   *   - ASK USER: Should fetchJson handle non-200 responses or throw?
   * ---/agentspec
   */
  const updateTerminalProgress = useCallback((percent: number, message?: string) => {
    const terminal = getTerminal();
    terminal?.updateProgress?.(percent, message);
  }, [getTerminal]);

  /**
   * ---agentspec
   * what: |
   *   Wraps fetch() with JSON headers and error handling. Takes path + RequestInit options, returns parsed response or throws on non-2xx status.
   *
   * why: |
   *   Centralizes API request logic to avoid repeating headers and error parsing across components.
   *
   * guardrails:
   *   - DO NOT assume res.json() succeeds; caller must handle parse errors
   *   - NOTE: Throws on any non-2xx; no retry logic
   * ---/agentspec
   */
  const fetchJson = useCallback(async (path: string, options: RequestInit = {}) => {
    const res = await fetch(api(path), {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `Request failed (${res.status})`);
    }
    return res.json();
  }, [api]);

  // Keep active corpus scoped across config + API helpers
  useEffect(() => {
    const next = corpusId.trim();
    if (!next) return;
    const prev =
      localStorage.getItem('tribrid_active_corpus') || localStorage.getItem('tribrid_active_repo') || '';
    if (prev !== next) {
      localStorage.setItem('tribrid_active_corpus', next);
      // Legacy key (kept for any older code paths)
      localStorage.setItem('tribrid_active_repo', next);
    }
    try {
      const url = new URL(window.location.href);
      url.searchParams.set('corpus', next);
      url.searchParams.delete('repo');
      window.history.replaceState({}, '', url.toString());
    } catch {
      // ignore
    }
    window.dispatchEvent(new CustomEvent('tribrid-corpus-changed', { detail: { corpus: next, repo: next } }));
    // Legacy event name (kept for any older listeners)
    window.dispatchEvent(new CustomEvent('agro-repo-changed', { detail: { repo: next } }));
  }, [corpusId]);

  useEffect(() => {
    localStorage.setItem('eval_sampleSize', sampleSize);
  }, [sampleSize]);

  // Load available eval runs on mount
  useEffect(() => {
    /**
     * ---agentspec
     * what: |
     *   Fetches eval runs from /eval/runs endpoint. Populates availableRuns state; auto-selects most recent run if none selected.
     *
     * why: |
     *   Centralizes run loading logic with auto-selection to reduce boilerplate in UI initialization.
     *
     * guardrails:
     *   - DO NOT assume data.runs exists; check data.ok first
     *   - NOTE: Auto-select only fires if selectedRunId is falsy; prevents override on re-fetch
     * ---/agentspec
     */
    const loadRuns = async () => {
      try {
        const rid = corpusId.trim();
        if (!rid) return;
        const data: EvalRunsResponse = await fetchJson(`eval/runs?corpus_id=${encodeURIComponent(rid)}`);
        if (data.ok && data.runs) {
          setAvailableRuns(data.runs);
          // Auto-select most recent run if available
          if (data.runs.length > 0 && !selectedRunId) {
            setSelectedRunId(data.runs[0].run_id);
          }
        }
      } catch (err) {
        console.error('Failed to load eval runs:', err);
        const errorMsg = err instanceof Error ? err.message : String(err);
        setError(`Failed to load eval runs: ${errorMsg}`);
        // Also log the full error details for debugging
        console.error('Full error details:', err);
      }
    };
    loadRuns();
  }, [fetchJson, selectedRunId, corpusId]);

  const loadEvalDataset = useCallback(async () => {
    const rid = corpusId.trim();
    if (!rid) return;
    try {
      setLoading(true);
      const entries: EvalDatasetItem[] = await fetchJson(`dataset?corpus_id=${encodeURIComponent(rid)}`);
      setEvalDataset(entries);
      setError(null);
    } catch (err) {
      setError(`Failed to load eval dataset: ${err}`);
      console.error('Failed to load eval dataset:', err);
    } finally {
      setLoading(false);
    }
  }, [corpusId, fetchJson]);

  useEffect(() => {
    void loadEvalDataset();
  }, [loadEvalDataset]);

  /**
   * ---agentspec
   * what: |
   *   Validates non-empty question input, parses comma-separated paths, submits to backend. Returns success/error state.
   *
   * why: |
   *   Client-side validation prevents malformed submissions; path parsing normalizes user input before API call.
   *
   * guardrails:
   *   - DO NOT submit if question.q is empty or whitespace-only
   *   - NOTE: paths are optional; empty array is valid
   *   - ASK USER: What happens on backend failure? (retry, toast, state rollback?)
   * ---/agentspec
   */
  const addEvalDatasetEntry = async () => {
    const rid = corpusId.trim();
    if (!rid) {
      alert('Please enter a corpus ID');
      return;
    }
    if (!newEntry.question.trim()) {
      alert('Please enter a question');
      return;
    }

    const expected_paths = newEntry.paths
      .split(/[\n,]+/)
      .map((p) => p.trim())
      .filter(Boolean);
    const tags = newEntry.tags
      .split(/[,]+/)
      .map((t) => t.trim())
      .filter(Boolean);

    try {
      await fetchJson(`dataset?corpus_id=${encodeURIComponent(rid)}`, {
        method: 'POST',
        body: JSON.stringify({
          question: newEntry.question,
          expected_paths,
          tags,
        } satisfies Partial<EvalDatasetItem>),
      });
      setNewEntry({ question: '', paths: '', tags: '' });
      await loadEvalDataset();
    } catch (err) {
      alert(`Failed to add entry: ${err}`);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Tests eval entry at index against /golden/test endpoint. POSTs question, repo, expected paths; returns JSON result.
   *
   * why: |
   *   Validates agent responses against known-good outputs for regression detection.
   *
   * guardrails:
   *   - DO NOT assume endpoint availability; wrap in try-catch
   *   - NOTE: expect_paths must match actual file structure or test fails silently
   * ---/agentspec
   */
  const testEntry = async (index: number) => {
    const rid = corpusId.trim();
    const entry = evalDataset[index];
    if (!rid || !entry) return;
    try {
      const payload: EvalTestRequest = {
        corpus_id: rid,
        question: entry.question,
        expected_paths: entry.expected_paths,
        use_multi: Boolean(evalMulti),
        final_k: evalFinalK,
      };
      const result: EvalResult = await fetchJson('eval/test', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      const key = entry.entry_id || String(index);
      setTestResults((prev) => ({ ...prev, [key]: result }));
    } catch (err) {
      console.error('Test failed:', err);
      alert(`Test failed: ${err}`);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Deletes a eval entry by index via DELETE request. Confirms user intent, then reloads list.
   *
   * why: |
   *   Confirmation prevents accidental deletions; reload ensures UI stays in sync with backend state.
   *
   * guardrails:
   *   - DO NOT skip confirmation; user must explicitly approve
   *   - NOTE: Silently fails if loadGoldenQuestions() throws; add error recovery
   * ---/agentspec
   */
  const deleteEntry = async (index: number) => {
    const rid = corpusId.trim();
    const entry = evalDataset[index];
    if (!rid || !entry?.entry_id) return;
    if (!confirm('Delete this eval dataset entry?')) return;

    try {
      await fetchJson(
        `dataset/${encodeURIComponent(entry.entry_id)}?corpus_id=${encodeURIComponent(rid)}`,
        { method: 'DELETE' }
      );
      await loadEvalDataset();
    } catch (err) {
      alert(`Failed to delete: ${err}`);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Loads recommended questions from RECOMMENDED_ENTRIES array via POST to 'golden' endpoint. Tracks successful additions; silently skips failures per question.
   *
   * why: |
   *   Batch seeding of eval entries with graceful per-item error handling to avoid total failure on single bad record.
   *
   * guardrails:
   *   - DO NOT throw on individual POST failures; continue loop
   *   - NOTE: Silent skip means failed questions go unlogged; add error tracking if audit needed
   *   - ASK USER: Should failed questions be logged or retried?
   * ---/agentspec
   */
  const loadRecommendedQuestions = async () => {
    try {
      const rid = corpusId.trim();
      if (!rid) {
        alert('Please enter a corpus ID');
        return;
      }
      let added = 0;
      for (const q of RECOMMENDED_EVAL_DATASET) {
        try {
          await fetchJson(`dataset?corpus_id=${encodeURIComponent(rid)}`, {
            method: 'POST',
            body: JSON.stringify(q satisfies Partial<EvalDatasetItem>)
          });
          added++;
        } catch (err) {
          console.warn(`Failed to add entry: ${q.question}`, err);
        }
      }
      await loadEvalDataset();
      alert(`Loaded ${added} recommended eval dataset entries`);
    } catch (err) {
      alert(`Failed to load recommended questions: ${err}`);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Executes evaluation suite against all eval entries. Updates progress state (current, total, status) and sets running flag.
   *
   * why: |
   *   Centralizes test orchestration; guards against empty dataset before batch execution.
   *
   * guardrails:
   *   - DO NOT run if evalEntries.length === 0; alert user instead
   *   - NOTE: setEvalRunning(true) must precede async work to prevent duplicate runs
   * ---/agentspec
   */
  const runAllTests = async () => {
    const rid = corpusId.trim();
    if (!rid) {
      alert('Please enter a corpus ID');
      return;
    }
    if (evalDataset.length === 0) {
      alert('No questions to test');
      return;
    }

    setEvalRunning(true);
    setEvalProgress({ current: 0, total: evalDataset.length, status: 'Starting...' });

    try {
      let top1 = 0, topk = 0;

      for (let i = 0; i < evalDataset.length; i++) {
        const entry = evalDataset[i];
        setEvalProgress(prev => ({ ...prev, current: i + 1, status: `Testing: ${entry.question}` }));

        const payload: EvalTestRequest = {
          corpus_id: rid,
          question: entry.question,
          expected_paths: entry.expected_paths,
          use_multi: Boolean(evalMulti),
          final_k: evalFinalK,
        };

        const result: EvalResult = await fetchJson('eval/test', {
          method: 'POST',
          body: JSON.stringify(payload)
        });

        if (result.top1_hit) top1++;
        if (result.topk_hit) topk++;

        const key = entry.entry_id || String(i);
        setTestResults(prev => ({ ...prev, [key]: result }));
      }

      const msg = `Tests complete: Top-1: ${top1}/${evalDataset.length}, Top-K: ${topk}/${evalDataset.length}`;
      alert(msg);
      setEvalProgress(prev => ({ ...prev, status: msg }));
    } catch (err) {
      alert(`Test run failed: ${err}`);
    } finally {
      setEvalRunning(false);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Initiates full RAG evaluation pipeline. Sets UI state (running, progress, terminal), resets logs, applies sample limit from settings.
   *
   * why: |
   *   Centralizes evaluation startup logic with consistent state management and user feedback.
   *
   * guardrails:
   *   - DO NOT run concurrent evaluations; check evalRunning flag first
   *   - NOTE: sampleLimit parsed from string; validate parseInt result before use
   * ---/agentspec
   */
  const runFullEvaluation = async () => {
    if (evalRunning) return;
    const rid = corpusId.trim();
    if (!rid) {
      alert('Please enter a corpus ID');
      return;
    }

    setEvalRunning(true);
    setEvalProgress({ current: 0, total: 100, status: 'Starting evaluation...' });
    setTerminalVisible(true);
    resetTerminal('RAG Evaluation Logs');

    const sampleLimit = sampleSize ? parseInt(sampleSize, 10) : undefined;
    appendTerminalLine('🧪 Starting full RAG evaluation...');
    appendTerminalLine(
      `Settings: corpus_id=${rid}, use_multi=${Boolean(evalMulti) ? 'true' : 'false'}, final_k=${evalFinalK}, sample_limit=${sampleLimit || 'all'}`
    );

    try {
      // Fast-fail if backend is unreachable (otherwise EventSource just reports "Connection lost").
      try {
        const controller = new AbortController();
        const timeoutMs = 3000;
        const timer = window.setTimeout(() => controller.abort(), timeoutMs);
        try {
          await fetchJson('health', { signal: controller.signal });
        } finally {
          window.clearTimeout(timer);
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        const pretty = msg.includes('aborted') ? 'Backend health check timed out' : msg;
        setEvalRunning(false);
        setEvalProgress((prev) => ({ ...prev, status: 'Backend unreachable' }));
        appendTerminalLine(`\x1b[31mBackend unreachable: ${pretty}\x1b[0m`);
        appendTerminalLine('Tip: run `./start.sh` and confirm http://127.0.0.1:8012/api/health is reachable.');
        return;
      }

      TerminalService.streamEvalRun('eval_terminal', {
        corpus_id: rid,
        use_multi: Boolean(evalMulti),
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
          try {
            const results: EvalRun = await fetchJson(`eval/results?corpus_id=${encodeURIComponent(rid)}`);
            setEvalResults(results);
            if (results.run_id) setLatestRunId(results.run_id);
            // Refresh run list + auto-select latest
            try {
              const runs: EvalRunsResponse = await fetchJson(`eval/runs?corpus_id=${encodeURIComponent(rid)}`);
              if (runs.ok) {
                const list = runs.runs || [];
                setAvailableRuns(list);
                if (list.length > 0) setSelectedRunId(list[0].run_id);
              }
            } catch {
              // ignore
            }
          } catch (err) {
            appendTerminalLine(`\x1b[31mError fetching results: ${err}\x1b[0m`);
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
  };

  /**
   * ---agentspec
   * what: |
   *   Exports evalEntries array as JSON file. Creates blob, generates download link, triggers browser download, cleans up object URL.
   *
   * why: |
   *   Standard browser file export pattern using Blob API and temporary anchor element.
   *
   * guardrails:
   *   - DO NOT call revokeObjectURL before download completes; timing may fail on slow networks
   *   - NOTE: Filename hardcoded; consider parameterizing for reuse
   * ---/agentspec
   */
  const exportDataset = () => {
    const dataStr = JSON.stringify(evalDataset, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'eval_dataset_export.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ padding: '20px' }}>
      {/* Eval dataset manager */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)', marginBottom: '24px' }}>
        <h3>
          <span className="accent-blue">●</span> Eval Dataset Manager
        </h3>
        <p className="small">
          Manage eval_dataset entries for evaluating retrieval quality. Add, test individual entries, or run a full evaluation.
        </p>

        {/* Add New Question Form */}
        <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '6px', padding: '16px', marginBottom: '16px' }}>
          <h4 style={{ fontSize: '13px', color: 'var(--accent)', marginBottom: '12px' }}>Add New Entry</h4>

          <div className="input-group" style={{ marginBottom: '12px' }}>
            <label>Corpus ID</label>
            <input
              type="text"
              value={corpusId}
              onChange={(e) => setCorpusId(e.target.value)}
              placeholder="e.g., tribrid"
            />
          </div>

          <div className="input-group" style={{ marginBottom: '12px' }}>
            <label>Question Text</label>
            <textarea
              value={newEntry.question}
              onChange={(e) => setNewEntry((prev) => ({ ...prev, question: e.target.value }))}
              placeholder="e.g., Where is OAuth token validated?"
              style={{ minHeight: '60px', width: '100%' }}
            />
          </div>

          <div className="input-row" style={{ marginBottom: '12px' }}>
            <div className="input-group">
              <label>Tags (comma-separated)</label>
              <input
                type="text"
                value={newEntry.tags}
                onChange={(e) => setNewEntry((prev) => ({ ...prev, tags: e.target.value }))}
                placeholder="e.g., retrieval, reranker"
              />
            </div>
            <div className="input-group">
              <label>Expected Paths (comma-separated)</label>
              <input
                type="text"
                value={newEntry.paths}
                onChange={(e) => setNewEntry((prev) => ({ ...prev, paths: e.target.value }))}
                placeholder="e.g., server/api/eval.py, server/api/dataset.py"
              />
            </div>
          </div>

          <button
            className="small-button"
            onClick={addEvalDatasetEntry}
            style={{ background: 'var(--accent)', color: 'var(--accent-contrast)', border: 'none', width: '100%' }}
          >
            Add Entry
          </button>
        </div>

        {/* Questions List */}
        <div style={{ background: 'var(--code-bg)', border: '1px solid var(--line)', borderRadius: '6px', padding: '16px', maxHeight: '400px', overflowY: 'auto', marginBottom: '16px' }}>
          {loading ? (
            <div style={{ textAlign: 'center', color: 'var(--fg-muted)' }}>Loading eval dataset...</div>
          ) : error ? (
            <div style={{ color: 'var(--err)' }}>{error}</div>
          ) : evalDataset.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '24px', color: 'var(--fg-muted)' }}>
              No eval dataset entries yet. Add one above!
            </div>
          ) : (
            evalDataset.map((entry, index) => {
              const key = entry.entry_id || String(index);
              const test = testResults[key];
              return (
              <div key={key} style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '4px', padding: '12px', marginBottom: '10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '8px' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, color: 'var(--fg)', marginBottom: '4px', wordBreak: 'break-word' }}>
                      {entry.question}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
                      <span style={{ background: 'var(--bg-elev2)', padding: '2px 6px', borderRadius: '3px', marginRight: '6px' }}>
                        {corpusId.trim() || 'corpus'}
                      </span>
                      {(entry.expected_paths || []).map(p => (
                        <span key={p} style={{ color: 'var(--accent)' }}>{p} </span>
                      ))}
                      {(entry.tags || []).length > 0 && (
                        <span style={{ marginLeft: '8px', color: 'var(--fg-muted)' }}>
                          tags: {(entry.tags || []).join(', ')}
                        </span>
                      )}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '6px', marginLeft: '12px' }}>
                    <button
                      onClick={() => void testEntry(index)}
                      style={{ background: 'var(--bg-elev2)', color: 'var(--link)', border: '1px solid var(--link)', padding: '4px 8px', borderRadius: '3px', fontSize: '11px', cursor: 'pointer' }}
                    >
                      Test
                    </button>
                    <button
                      onClick={() => void deleteEntry(index)}
                      style={{ background: 'var(--bg-elev2)', color: 'var(--err)', border: '1px solid var(--err)', padding: '4px 8px', borderRadius: '3px', fontSize: '11px', cursor: 'pointer' }}
                    >
                      ✗
                    </button>
                  </div>
                </div>
                {test && (
                  <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid var(--line)', fontSize: '12px' }}>
                    <span style={{ color: test.top1_hit ? 'var(--accent)' : 'var(--err)', fontWeight: 600 }}>
                      {test.top1_hit ? '✓' : '✗'} Top-1
                    </span>
                    <span style={{ marginLeft: '12px', color: test.topk_hit ? 'var(--accent)' : 'var(--warn)', fontWeight: 600 }}>
                      {test.topk_hit ? '✓' : '✗'} Top-K
                    </span>
                  </div>
                )}
              </div>
            );
            })
          )}
        </div>

        {/* Action Buttons */}
        <div className="action-buttons" style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button onClick={() => void loadEvalDataset()} style={{ flex: 1 }}>
            Refresh List
          </button>
          <button
            onClick={loadRecommendedQuestions}
            style={{ flex: 1, background: 'var(--bg-elev2)', color: 'var(--link)', border: '1px solid var(--link)' }}
          >
            Load Recommended
          </button>
          <button
            onClick={runAllTests}
            disabled={evalRunning || evalDataset.length === 0}
            style={{ flex: 1, background: 'var(--bg-elev2)', color: 'var(--link)', border: '1px solid var(--link)' }}
          >
            Run All Tests
          </button>
          <button
            onClick={exportDataset}
            style={{ flex: 1, background: 'var(--bg-elev2)', color: 'var(--accent)' }}
          >
            Export JSON
          </button>
        </div>

        {/* Progress indicator for running tests */}
        {evalRunning && evalProgress.total > 0 && (
          <div style={{ marginTop: '16px', padding: '12px', background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '4px' }}>
            <div style={{ marginBottom: '8px', fontSize: '12px', color: 'var(--fg-muted)' }}>
              {evalProgress.status}
            </div>
            <div style={{ background: 'var(--bg)', height: '8px', borderRadius: '4px', overflow: 'hidden' }}>
              <div
                style={{
                  height: '100%',
                  width: `${(evalProgress.current / evalProgress.total) * 100}%`,
                  background: 'var(--link)',
                  transition: 'width 0.3s ease'
                }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Evaluation Runner */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)' }}>
        <h3>
          <span className="accent-purple">●</span> Evaluation Runner
        </h3>
        <p className="small">
          Run full evaluation suite to measure RAG quality. Compare against baseline to detect regressions.
        </p>

        {/* Settings */}
        <div className="input-row" style={{ marginBottom: '16px' }}>
          <div className="input-group">
            <label>Use Multi-Query</label>
            <select
              value={String(Boolean(evalMulti) ? 1 : 0)}
              onChange={(e) => setEvalMulti(e.target.value === '1' ? 1 : 0)}
            >
              <option value="1">Yes</option>
              <option value="0">No</option>
            </select>
          </div>
          <div className="input-group">
            <label>Final K Results</label>
            <input
              type="number"
              value={evalFinalK}
              onChange={(e) => setEvalFinalK(parseInt(e.target.value, 10) || 5)}
              min="1"
              max="20"
            />
          </div>
          <div className="input-group">
            <label>Sample Size</label>
            <select
              value={sampleSize}
              onChange={(e) => setSampleSize(e.target.value)}
            >
              <option value="">Full (All Questions)</option>
              <option value="10">Quick (10 Questions)</option>
              <option value="25">Medium (25 Questions)</option>
              <option value="50">Large (50 Questions)</option>
            </select>
          </div>
        </div>

        {/* Run Button */}
        <button
          className="action-buttons"
          onClick={() => void runFullEvaluation()}
          disabled={evalRunning}
          style={{ width: '100%', background: 'var(--link)', color: 'var(--accent-contrast)', fontSize: '15px', padding: '14px' }}
        >
          🚀 Run Full Evaluation
        </button>

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '8px' }}>
          <button
            onClick={() => {
              setTerminalVisible(!terminalVisible);
              const terminal = getTerminal();
              terminal?.show?.();
            }}
            data-tooltip="EVAL_LOGS_TERMINAL"
            title="Show the sliding terminal with raw eval logs"
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--link)',
              border: '1px solid var(--link)',
              padding: '8px 12px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer'
            }}
          >
            {terminalVisible ? 'Hide Logs' : 'See Logs'}
          </button>
        </div>

        <div
          style={{
            maxHeight: terminalVisible ? '400px' : '0',
            opacity: terminalVisible ? 1 : 0,
            overflow: 'hidden',
            transition: 'max-height 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease',
            marginTop: terminalVisible ? '12px' : '0'
          }}
        >
          <LiveTerminal
            ref={terminalRef}
            id="eval_terminal"
            title="RAG Evaluation Logs"
            initialContent={['Ready for evaluation logs...']}
          />
        </div>

        {/* Results Display */}
        {evalResults && (
          <div style={{ marginTop: '16px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '12px', marginBottom: '16px' }}>
              <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '6px', padding: '12px', textAlign: 'center' }}>
                <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>Top-1 Accuracy</div>
                <div style={{ fontSize: '24px', color: 'var(--accent)', fontWeight: 700 }}>
                  {(((evalResults.top1_accuracy ?? 0) * 100)).toFixed(1)}%
                </div>
              </div>
              <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '6px', padding: '12px', textAlign: 'center' }}>
                <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>Top-K Accuracy</div>
                <div style={{ fontSize: '24px', color: 'var(--accent)', fontWeight: 700 }}>
                  {(((evalResults.topk_accuracy ?? 0) * 100)).toFixed(1)}%
                </div>
              </div>
              <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '6px', padding: '12px', textAlign: 'center' }}>
                <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>MRR</div>
                <div style={{ fontSize: '24px', color: 'var(--warn)', fontWeight: 700 }}>
                  {(evalResults.metrics?.mrr ?? 0).toFixed(4)}
                </div>
              </div>
              <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '6px', padding: '12px', textAlign: 'center' }}>
                <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>Duration</div>
                <div style={{ fontSize: '24px', color: 'var(--link)', fontWeight: 700 }}>
                  {evalResults.duration_secs}s
                </div>
              </div>
            </div>

            {/* Drill-Down Button */}
            {latestRunId && (
              <button
                onClick={() => setShowDrillDown(!showDrillDown)}
                style={{
                  width: '100%',
                  padding: '12px',
                  background: 'var(--bg-elev2)',
                  color: 'var(--link)',
                  border: '1px solid var(--link)',
                  borderRadius: '6px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  marginTop: '12px'
                }}
              >
                {showDrillDown ? '▼ Hide Detailed Results' : '▶ Show Detailed Results (Question-by-Question)'}
              </button>
            )}

            {/* Detailed Drill-Down */}
            {showDrillDown && latestRunId && (
              <div style={{ marginTop: '16px' }}>
                <EvalDrillDown runId={latestRunId} />
              </div>
            )}
          </div>
        )}
      </div>

      {/* ALWAYS VISIBLE: Eval Run Drill-Down Analysis */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        padding: '20px',
        marginTop: '24px'
      }}>
        <h3 style={{
          margin: '0 0 16px 0',
          fontSize: '16px',
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          <span style={{ color: 'var(--accent)' }}>●</span>
          Eval Run Drill-Down Analysis
        </h3>
        <p style={{ fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '16px' }}>
          Deep-dive into any eval run to analyze question-by-question performance, compare expected vs actual results, and identify regressions.
        </p>

        {availableRuns.length === 0 ? (
          <div style={{
            padding: '32px',
            textAlign: 'center',
            color: 'var(--fg-muted)',
            fontSize: '13px'
          }}>
            No eval runs found. Run an evaluation to generate data for analysis.
          </div>
        ) : (
          <>
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: '20px',
              marginBottom: '20px'
            }}>
              <div>
                <label style={{
                  display: 'block',
                  fontSize: '12px',
                  fontWeight: 600,
                  marginBottom: '8px',
                  color: 'var(--fg)'
                }}>
                  📊 PRIMARY RUN (AFTER)
                </label>
                <select
                  value={selectedRunId || ''}
                  onChange={(e) => setSelectedRunId(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--bg-elev2)',
                    color: 'var(--fg)',
                    border: '2px solid var(--accent-green)',
                    borderRadius: '6px',
                    fontSize: '13px',
                    fontFamily: 'inherit',
                    fontWeight: 600
                  }}
                >
                  <option value="">-- Select a run --</option>
                  {availableRuns.map(run => (
                    <option key={run.run_id} value={run.run_id}>
                      {run.run_id} — Top-1: {(run.top1_accuracy * 100).toFixed(1)}% | Top-K: {(run.topk_accuracy * 100).toFixed(1)}%
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{
                  display: 'block',
                  fontSize: '12px',
                  fontWeight: 600,
                  marginBottom: '8px',
                  color: 'var(--fg)'
                }}>
                  🔍 COMPARE WITH (BEFORE) — Optional
                </label>
                <select
                  value={compareRunId || ''}
                  onChange={(e) => setCompareRunId(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--bg-elev2)',
                    color: 'var(--fg)',
                    border: '2px solid var(--err)',
                    borderRadius: '6px',
                    fontSize: '13px',
                    fontFamily: 'inherit',
                    fontWeight: 600
                  }}
                >
                  <option value="">-- No comparison --</option>
                  {availableRuns.filter(r => r.run_id !== selectedRunId).map(run => (
                    <option key={run.run_id} value={run.run_id}>
                      {run.run_id} — Top-1: {(run.top1_accuracy * 100).toFixed(1)}% | Top-K: {(run.topk_accuracy * 100).toFixed(1)}%
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {selectedRunId && (
              <div style={{
                border: '1px solid var(--link)',
                borderRadius: '6px',
                padding: '16px',
                background: 'var(--bg-elev1)'
              }}>
                <EvalDrillDown runId={selectedRunId} compareWithRunId={compareRunId || undefined} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
