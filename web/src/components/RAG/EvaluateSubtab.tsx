// React implementation of EvaluateSubtab - NO legacy JS modules
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useAPI } from '@/hooks';
import { EvalDrillDown } from '@/components/Evaluation/EvalDrillDown';
import { LiveTerminal, LiveTerminalHandle } from '@/components/LiveTerminal/LiveTerminal';
import { TerminalService } from '@/services/TerminalService';
// Recommended golden questions for AGRO codebase
const RECOMMENDED_GOLDEN = [
  { q: 'Where is hybrid retrieval implemented?', repo: 'agro', expect_paths: ['retrieval/hybrid_search.py'] },
  { q: 'Where is keyword generation handled server-side?', repo: 'agro', expect_paths: ['server/app.py','keywords/generate'] },
  { q: 'Where is the metadata enrichment logic for code/keywords?', repo: 'agro', expect_paths: ['metadata_enricher.py'] },
  { q: 'Where is the indexing pipeline (BM25 and dense) implemented?', repo: 'agro', expect_paths: ['indexer/index_repo.py'] },
  { q: 'Where is comprehensive index status computed?', repo: 'agro', expect_paths: ['server/app.py','server/index_stats.py','index/status'] },
  { q: 'Where are semantic cards built or listed?', repo: 'agro', expect_paths: ['server/app.py','api/cards','indexer/build_cards.py'] },
  { q: 'Where are golden questions API routes defined?', repo: 'agro', expect_paths: ['server/app.py','api/golden'] },
  { q: 'Where is the endpoint to test a single golden question?', repo: 'agro', expect_paths: ['server/app.py','api/golden/test'] },
  { q: 'Where are GUI assets mounted and served?', repo: 'agro', expect_paths: ['server/app.py','/gui','gui/index.html'] },
  { q: 'Where is repository configuration (repos.json) loaded?', repo: 'agro', expect_paths: ['config_loader.py'] },
  { q: 'Where are MCP stdio tools implemented (rag_answer, rag_search)?', repo: 'agro', expect_paths: ['server/mcp/server.py'] },
  { q: 'Where can I list or fetch latest LangGraph traces?', repo: 'agro', expect_paths: ['server/app.py','api/traces'] }
];

interface GoldenQuestion {
  q: string;
  repo: string;
  expect_paths: string[];
}

interface TestResult {
  top1_hit: boolean;
  topk_hit: boolean;
  all_results?: Array<{
    file_path: string;
    start_line: number;
    rerank_score: number;
  }>;
}

interface EvalResults {
  top1_accuracy: number;
  topk_accuracy: number;
  mrr?: number;
  duration_secs: number;
  results?: Array<{
    question: string;
    repo: string;
    expect_paths: string[];
    top1_hit: boolean;
    topk_hit: boolean;
    top_paths: string[];
    reciprocal_rank?: number;
  }>;
}

/**
 * ---agentspec
 * what: |
 *   React component for evaluation subtab. Manages golden questions, runs test suite, tracks progress, displays results.
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
  const [goldenQuestions, setGoldenQuestions] = useState<GoldenQuestion[]>([]);
  const [newQuestion, setNewQuestion] = useState({ q: '', repo: 'agro', paths: '' });
  const [testResults, setTestResults] = useState<{ [key: number]: TestResult }>({});
  const [evalRunning, setEvalRunning] = useState(false);
  const [evalProgress, setEvalProgress] = useState({ current: 0, total: 0, status: '' });
  const [evalResults, setEvalResults] = useState<EvalResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evalSettings, setEvalSettings] = useState({
    useMulti: true,
    finalK: 5,
    sampleSize: '',
    goldenPath: 'data/golden.json',
    baselinePath: 'data/evals/eval_baseline.json'
  });
  const [availableRuns, setAvailableRuns] = useState<Array<{run_id: string, top1_accuracy: number, topk_accuracy: number, mrr?: number}>>([]);
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

  // Load config and golden questions on mount
  useEffect(() => {
    loadConfig();
    loadGoldenQuestions();
  }, []);

  // Load eval settings from backend config
  /**
   * ---agentspec
   * what: |
   *   Fetches config from /api/config endpoint. Extracts env vars, sets goldenPath to GOLDEN_PATH or defaults to 'data/golden.json'.
   *
   * why: |
   *   Centralizes config loading at app startup; avoids hardcoding paths.
   *
   * guardrails:
   *   - DO NOT assume /api/config always returns env object; add fallback
   *   - NOTE: No error handling; fetch failures will silently fail
   * ---/agentspec
   */
  const loadConfig = async () => {
    try {
      const response = await fetch('/api/config');
      const data = await response.json();
      const env = data.env || {};

      setEvalSettings(prev => ({
        ...prev,
        goldenPath: env.GOLDEN_PATH || 'data/golden.json',
        baselinePath: env.BASELINE_PATH || 'data/evals/eval_baseline.json',
        // Load user preferences from localStorage
        useMulti: localStorage.getItem('eval_useMulti') === 'false' ? false : true,
        finalK: parseInt(localStorage.getItem('eval_finalK') || '5', 10),
        sampleSize: localStorage.getItem('eval_sampleSize') || ''
      }));
    } catch (error) {
      console.error('Failed to load eval config:', error);
    }
  };

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
        const data = await fetchJson('eval/runs');
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
  }, [fetchJson, selectedRunId]);

  /**
   * ---agentspec
   * what: |
   *   Fetches golden questions from 'golden' endpoint. Sets state: questions array, loading flag, error message.
   *
   * why: |
   *   Centralizes async data load with error handling and loading state for UI feedback.
   *
   * guardrails:
   *   - DO NOT retry on failure; let caller handle retry logic
   *   - NOTE: Clears error only on success; preserves error state on fetch failure
   * ---/agentspec
   */
  const loadGoldenQuestions = async () => {
    try {
      setLoading(true);
      const response = await fetchJson('golden');
      setGoldenQuestions(response.questions || []);
      setError(null);
    } catch (err) {
      setError(`Failed to load golden questions: ${err}`);
      console.error('Failed to load golden questions:', err);
    } finally {
      setLoading(false);
    }
  };

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
  const addGoldenQuestion = async () => {
    if (!newQuestion.q.trim()) {
      alert('Please enter a question');
      return;
    }

    /**
     * ---agentspec
     * what: |
     *   Parses comma-separated paths from newQuestion.paths, trims whitespace, filters empty strings. POSTs to 'golden' endpoint with query, repo, and expect_paths array.
     *
     * why: |
     *   Normalizes user input (paths) before API submission to ensure clean, validated array format.
     *
     * guardrails:
     *   - DO NOT assume fetchJson succeeds; add error handling for network/API failures
     *   - NOTE: Empty strings filtered; silent skip may hide malformed input
     * ---/agentspec
     */
    const expect_paths = newQuestion.paths.split(',').map(p => p.trim()).filter(p => p);

    try {
      await fetchJson('golden', {
        method: 'POST',
        body: JSON.stringify({
          q: newQuestion.q,
          repo: newQuestion.repo,
          expect_paths
        })
      });
      setNewQuestion({ q: '', repo: 'agro', paths: '' });
      await loadGoldenQuestions();
    } catch (err) {
      alert(`Failed to add question: ${err}`);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Tests golden question at index against /golden/test endpoint. POSTs question, repo, expected paths; returns JSON result.
   *
   * why: |
   *   Validates agent responses against known-good outputs for regression detection.
   *
   * guardrails:
   *   - DO NOT assume endpoint availability; wrap in try-catch
   *   - NOTE: expect_paths must match actual file structure or test fails silently
   * ---/agentspec
   */
  const testQuestion = async (index: number) => {
    const q = goldenQuestions[index];
    try {
      const result = await fetchJson('golden/test', {
        method: 'POST',
        body: JSON.stringify({
          q: q.q,
          repo: q.repo,
          expect_paths: q.expect_paths,
          final_k: 5,
          use_multi: true
        })
      });
      setTestResults(prev => ({ ...prev, [index]: result }));
    } catch (err) {
      console.error('Test failed:', err);
      alert(`Test failed: ${err}`);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Deletes a golden question by index via DELETE request. Confirms user intent, then reloads list.
   *
   * why: |
   *   Confirmation prevents accidental deletions; reload ensures UI stays in sync with backend state.
   *
   * guardrails:
   *   - DO NOT skip confirmation; user must explicitly approve
   *   - NOTE: Silently fails if loadGoldenQuestions() throws; add error recovery
   * ---/agentspec
   */
  const deleteQuestion = async (index: number) => {
    if (!confirm('Delete this question?')) return;

    try {
      await fetchJson(`golden/${index}`, { method: 'DELETE' });
      await loadGoldenQuestions();
    } catch (err) {
      alert(`Failed to delete: ${err}`);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Loads recommended questions from RECOMMENDED_GOLDEN array via POST to 'golden' endpoint. Tracks successful additions; silently skips failures per question.
   *
   * why: |
   *   Batch seeding of golden questions with graceful per-item error handling to avoid total failure on single bad record.
   *
   * guardrails:
   *   - DO NOT throw on individual POST failures; continue loop
   *   - NOTE: Silent skip means failed questions go unlogged; add error tracking if audit needed
   *   - ASK USER: Should failed questions be logged or retried?
   * ---/agentspec
   */
  const loadRecommendedQuestions = async () => {
    try {
      let added = 0;
      for (const q of RECOMMENDED_GOLDEN) {
        try {
          await fetchJson('golden', {
            method: 'POST',
            body: JSON.stringify(q)
          });
          added++;
        } catch (err) {
          console.warn(`Failed to add question: ${q.q}`, err);
        }
      }
      await loadGoldenQuestions();
      alert(`Loaded ${added} recommended questions`);
    } catch (err) {
      alert(`Failed to load recommended questions: ${err}`);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Executes evaluation suite against all golden questions. Updates progress state (current, total, status) and sets running flag.
   *
   * why: |
   *   Centralizes test orchestration; guards against empty dataset before batch execution.
   *
   * guardrails:
   *   - DO NOT run if goldenQuestions.length === 0; alert user instead
   *   - NOTE: setEvalRunning(true) must precede async work to prevent duplicate runs
   * ---/agentspec
   */
  const runAllTests = async () => {
    if (goldenQuestions.length === 0) {
      alert('No questions to test');
      return;
    }

    setEvalRunning(true);
    setEvalProgress({ current: 0, total: goldenQuestions.length, status: 'Starting...' });

    try {
      let top1 = 0, topk = 0;

      for (let i = 0; i < goldenQuestions.length; i++) {
        const q = goldenQuestions[i];
        setEvalProgress(prev => ({ ...prev, current: i + 1, status: `Testing: ${q.q}` }));

        const result = await fetchJson('golden/test', {
          method: 'POST',
          body: JSON.stringify({
            q: q.q,
            repo: q.repo,
            expect_paths: q.expect_paths || [],
            final_k: 5,
            use_multi: true
          })
        });

        if (result.top1_hit) top1++;
        if (result.topk_hit) topk++;

        setTestResults(prev => ({ ...prev, [i]: result }));
      }

      const msg = `Tests complete: Top-1: ${top1}/${goldenQuestions.length}, Top-K: ${topk}/${goldenQuestions.length}`;
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

    setEvalRunning(true);
    setEvalProgress({ current: 0, total: 100, status: 'Starting evaluation...' });
    setTerminalVisible(true);
    resetTerminal('RAG Evaluation Logs');

    const sampleLimit = evalSettings.sampleSize ? parseInt(evalSettings.sampleSize, 10) : undefined;
    appendTerminalLine('🧪 Starting full RAG evaluation...');
    appendTerminalLine(`Settings: use_multi=${evalSettings.useMulti ? 'true' : 'false'}, final_k=${evalSettings.finalK}, sample_limit=${sampleLimit || 'all'}`);

    try {
      TerminalService.streamEvalRun('eval_terminal', {
        use_multi: evalSettings.useMulti,
        final_k: evalSettings.finalK,
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
            const results = await fetchJson('eval/results');
            setEvalResults(results);
            if (results.run_id) {
              setLatestRunId(results.run_id);
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
   *   Exports goldenQuestions array as JSON file. Creates blob, generates download link, triggers browser download, cleans up object URL.
   *
   * why: |
   *   Standard browser file export pattern using Blob API and temporary anchor element.
   *
   * guardrails:
   *   - DO NOT call revokeObjectURL before download completes; timing may fail on slow networks
   *   - NOTE: Filename hardcoded; consider parameterizing for reuse
   * ---/agentspec
   */
  const exportQuestions = () => {
    const dataStr = JSON.stringify(goldenQuestions, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'golden_questions_export.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ padding: '20px' }}>
      {/* Golden Questions Manager */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)', marginBottom: '24px' }}>
        <h3>
          <span className="accent-blue">●</span> Golden Questions Manager
        </h3>
        <p className="small">
          Manage test questions for evaluating retrieval quality. Add, edit, test individual questions, or run full evaluation suite.
        </p>

        {/* Add New Question Form */}
        <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '6px', padding: '16px', marginBottom: '16px' }}>
          <h4 style={{ fontSize: '13px', color: 'var(--accent)', marginBottom: '12px' }}>Add New Question</h4>

          <div className="input-group" style={{ marginBottom: '12px' }}>
            <label>Question Text</label>
            <textarea
              value={newQuestion.q}
              onChange={e => setNewQuestion(prev => ({ ...prev, q: e.target.value }))}
              placeholder="e.g., Where is OAuth token validated?"
              style={{ minHeight: '60px', width: '100%' }}
            />
          </div>

          <div className="input-row" style={{ marginBottom: '12px' }}>
            <div className="input-group">
              <label>Repository</label>
              <select
                value={newQuestion.repo}
                onChange={e => setNewQuestion(prev => ({ ...prev, repo: e.target.value }))}
              >
                <option value="agro">agro</option>
              </select>
            </div>
            <div className="input-group">
              <label>Expected Paths (comma-separated)</label>
              <input
                type="text"
                value={newQuestion.paths}
                onChange={e => setNewQuestion(prev => ({ ...prev, paths: e.target.value }))}
                placeholder="auth, oauth, token"
              />
            </div>
          </div>

          <button
            className="small-button"
            onClick={addGoldenQuestion}
            style={{ background: 'var(--accent)', color: 'var(--accent-contrast)', border: 'none', width: '100%' }}
          >
            Add Question
          </button>
        </div>

        {/* Questions List */}
        <div style={{ background: 'var(--code-bg)', border: '1px solid var(--line)', borderRadius: '6px', padding: '16px', maxHeight: '400px', overflowY: 'auto', marginBottom: '16px' }}>
          {loading ? (
            <div style={{ textAlign: 'center', color: 'var(--fg-muted)' }}>Loading questions...</div>
          ) : error ? (
            <div style={{ color: 'var(--err)' }}>{error}</div>
          ) : goldenQuestions.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '24px', color: 'var(--fg-muted)' }}>
              No golden questions yet. Add one above!
            </div>
          ) : (
            goldenQuestions.map((q, index) => (
              <div key={index} style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '4px', padding: '12px', marginBottom: '10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '8px' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, color: 'var(--fg)', marginBottom: '4px', wordBreak: 'break-word' }}>
                      {q.q}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
                      <span style={{ background: 'var(--bg-elev2)', padding: '2px 6px', borderRadius: '3px', marginRight: '6px' }}>
                        {q.repo}
                      </span>
                      {(q.expect_paths || []).map(p => (
                        <span key={p} style={{ color: 'var(--accent)' }}>{p} </span>
                      ))}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '6px', marginLeft: '12px' }}>
                    <button
                      onClick={() => testQuestion(index)}
                      style={{ background: 'var(--bg-elev2)', color: 'var(--link)', border: '1px solid var(--link)', padding: '4px 8px', borderRadius: '3px', fontSize: '11px', cursor: 'pointer' }}
                    >
                      Test
                    </button>
                    <button
                      onClick={() => deleteQuestion(index)}
                      style={{ background: 'var(--bg-elev2)', color: 'var(--err)', border: '1px solid var(--err)', padding: '4px 8px', borderRadius: '3px', fontSize: '11px', cursor: 'pointer' }}
                    >
                      ✗
                    </button>
                  </div>
                </div>
                {testResults[index] && (
                  <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid var(--line)', fontSize: '12px' }}>
                    <span style={{ color: testResults[index].top1_hit ? 'var(--accent)' : 'var(--err)', fontWeight: 600 }}>
                      {testResults[index].top1_hit ? '✓' : '✗'} Top-1
                    </span>
                    <span style={{ marginLeft: '12px', color: testResults[index].topk_hit ? 'var(--accent)' : 'var(--warn)', fontWeight: 600 }}>
                      {testResults[index].topk_hit ? '✓' : '✗'} Top-K
                    </span>
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        {/* Action Buttons */}
        <div className="action-buttons" style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button onClick={loadGoldenQuestions} style={{ flex: 1 }}>
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
            disabled={evalRunning || goldenQuestions.length === 0}
            style={{ flex: 1, background: 'var(--bg-elev2)', color: 'var(--link)', border: '1px solid var(--link)' }}
          >
            Run All Tests
          </button>
          <button
            onClick={exportQuestions}
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
              value={evalSettings.useMulti ? '1' : '0'}
              onChange={e => {
                const newValue = e.target.value === '1';
                setEvalSettings(prev => ({ ...prev, useMulti: newValue }));
                localStorage.setItem('eval_useMulti', String(newValue));
              }}
            >
              <option value="1">Yes</option>
              <option value="0">No</option>
            </select>
          </div>
          <div className="input-group">
            <label>Final K Results</label>
            <input
              type="number"
              value={evalSettings.finalK}
              onChange={e => {
                const newValue = parseInt(e.target.value) || 5;
                setEvalSettings(prev => ({ ...prev, finalK: newValue }));
                localStorage.setItem('eval_finalK', String(newValue));
              }}
              min="1"
              max="20"
            />
          </div>
          <div className="input-group">
            <label>Sample Size</label>
            <select
              value={evalSettings.sampleSize}
              onChange={e => {
                const newValue = e.target.value;
                setEvalSettings(prev => ({ ...prev, sampleSize: newValue }));
                localStorage.setItem('eval_sampleSize', newValue);
              }}
            >
              <option value="">Full (All Questions)</option>
              <option value="10">Quick (10 Questions)</option>
              <option value="25">Medium (25 Questions)</option>
              <option value="50">Large (50 Questions)</option>
            </select>
          </div>
        </div>

        {/* Run Button - navigates to Eval Analysis tab with autorun */}
        <button
          className="action-buttons"
          onClick={() => {
            // Navigate to Eval Analysis tab with autorun param
            window.location.hash = '#/eval-analysis?autorun=true';
          }}
          disabled={evalRunning}
          style={{ width: '100%', background: 'var(--link)', color: 'var(--accent-contrast)', fontSize: '15px', padding: '14px' }}
        >
          🚀 Run Full Evaluation
        </button>
        <p style={{ fontSize: '11px', color: 'var(--fg-muted)', textAlign: 'center', marginTop: '8px' }}>
          Opens Eval Analysis tab with live terminal
        </p>

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
                  {(evalResults.top1_accuracy * 100).toFixed(1)}%
                </div>
              </div>
              <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '6px', padding: '12px', textAlign: 'center' }}>
                <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>Top-K Accuracy</div>
                <div style={{ fontSize: '24px', color: 'var(--accent)', fontWeight: 700 }}>
                  {(evalResults.topk_accuracy * 100).toFixed(1)}%
                </div>
              </div>
              <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '6px', padding: '12px', textAlign: 'center' }}>
                <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>MRR</div>
                <div style={{ fontSize: '24px', color: 'var(--warn)', fontWeight: 700 }}>
                  {(evalResults.mrr ?? 0).toFixed(4)}
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
