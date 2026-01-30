/**
 * Learning Reranker Subtab Component
 *
 * This component manages the Learning Reranker system, which is a self-improving
 * cross-encoder model that learns from user feedback (thumbs up/down, clicks).
 *
 * IMPORTANT: This component handles CROSS-ENCODER/RERANKER TRAINING AND EVALUATION ONLY.
 * For full RAG pipeline evaluation (retrieval + generation), see EvaluateSubtab.tsx
 *
 * Backend APIs:
 * - /api/config - Get/set reranker configuration
 * - /api/reranker/status - Get current training/mining status
 * - /api/reranker/mine - Mine training triplets from logs
 * - /api/reranker/train - Train the cross-encoder model
 * - /api/reranker/evaluate - Evaluate cross-encoder performance (MRR, Hit@K)
 * - /api/reranker/logs/* - Log management endpoints
 * - /api/reranker/baseline/* - Baseline comparison endpoints
 */

import { useState, useEffect } from 'react';
import { useConfigField, useNotification } from '@/hooks';
import { PromptLink } from '@/components/ui/PromptLink';

/**
 * Reranker status object returned from backend
 */
interface RerankerStatus {
  running: boolean;
  task: string;
  progress: number;
  message: string;
  result: {
    ok: boolean;
    output?: string;
    error?: string;
  } | null;
  live_output: string[];
}

/**
 * Reranker info object from config
 */
interface RerankerInfo {
  enabled: boolean;
  path: string;
  device: string;
  alpha: number;
  topn: number;
  batch: number;
  maxlen: number;
}

/**
 * Training metrics from evaluation
 */
interface EvalMetrics {
  mrr?: number;
  hit1?: number;
  hit3?: number;
  hit5?: number;
}

/**
 * ---agentspec
 * what: |
 *   React component managing learning ranker config UI. Wires 6 state vars (reranker toggle, model path, available models, log/triplets paths, mine mode) to /api/config endpoint.
 *
 * why: |
 *   Centralizes ranker configuration in single subtab; state-to-API binding enables live config updates without page reload.
 *
 * guardrails:
 *   - DO NOT assume availableModels populates automatically; fetch on mount
 *   - NOTE: mineMode values are 'append' or 'replace'; validate before POST
 *   - ASK USER: Confirm /api/config endpoint exists and accepts all 6 fields
 * ---/agentspec
 */
export function LearningRankerSubtab() {
  // Notification hook for toast messages (replaces alert())
  const { success, error: notifyError, info } = useNotification();

  // Configuration state - all inputs wired to agro_config.json via useConfigField
  const [rerankerEnabled, setRerankerEnabled] = useConfigField<string>('AGRO_RERANKER_ENABLED', '0');
  const [modelPath, setModelPath] = useConfigField<string>('AGRO_RERANKER_MODEL_PATH', 'models/cross-encoder-agro');
  const [availableModels, setAvailableModels] = useState<string[]>([]); // UI state only - model list
  const [logPath, setLogPath] = useConfigField<string>('AGRO_LOG_PATH', 'data/logs/queries.jsonl');
  const [tripletsPath, setTripletsPath] = useConfigField<string>('AGRO_TRIPLETS_PATH', 'data/training/triplets.jsonl');
  const [mineMode, setMineMode] = useConfigField<string>('AGRO_RERANKER_MINE_MODE', 'append');
  const [mineReset, setMineReset] = useConfigField<string>('AGRO_RERANKER_MINE_RESET', '0');
  const [blendAlpha, setBlendAlpha] = useConfigField<number>('AGRO_RERANKER_ALPHA', 0.7);
  const [maxSeqLength, setMaxSeqLength] = useConfigField<number>('AGRO_RERANKER_MAXLEN', 512);
  const [batchSize, setBatchSize] = useConfigField<number>('AGRO_RERANKER_BATCH', 16);
  const [rerankerTopN, setRerankerTopN] = useConfigField<number>('AGRO_RERANKER_TOPN', 50);
  const [voyageRerankerModel, setVoyageRerankerModel] = useConfigField<string>('VOYAGE_RERANK_MODEL', 'rerank-2');
  const [reloadOnChange, setReloadOnChange] = useConfigField<string>('AGRO_RERANKER_RELOAD_ON_CHANGE', '0');
  const [trainEpochs, setTrainEpochs] = useConfigField<number>('RERANKER_TRAIN_EPOCHS', 2);
  const [trainBatchSize, setTrainBatchSize] = useConfigField<number>('RERANKER_TRAIN_BATCH', 16);
  const [trainMaxLength, setTrainMaxLength] = useConfigField<number>('RERANKER_TRAIN_MAX_LENGTH', 512);
  const [trainLearningRate, setTrainLearningRate] = useConfigField<number>('RERANKER_TRAIN_LR', 0.00002);
  const [warmupRatio, setWarmupRatio] = useConfigField<number>('RERANKER_WARMUP_RATIO', 0.1);
  const [tripletsMinCount, setTripletsMinCount] = useConfigField<number>('TRIPLETS_MIN_COUNT', 100);
  const [tripletsMineMode, setTripletsMineMode] = useConfigField<string>('TRIPLETS_MINE_MODE', 'replace');

  // Status and display state
  const [rerankerInfo, setRerankerInfo] = useState<RerankerInfo | null>(null);
  const [loggedQueries, setLoggedQueries] = useState<number>(0);
  const [tripletCount, setTripletCount] = useState<number>(0);
  const [status, setStatus] = useState<RerankerStatus | null>(null);
  const [evalMetrics, setEvalMetrics] = useState<EvalMetrics | null>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [showLogs, setShowLogs] = useState<boolean>(false);
  const [cronTime, setCronTime] = useState<string>('02:15');
  const [cronStatus, setCronStatus] = useState<string>('');
  const [testQuery, setTestQuery] = useState<string>('Where is OAuth validated?');
  const [smokeTestResult, setSmokeTestResult] = useState<any>(null);
  const [showSmokeResult, setShowSmokeResult] = useState<boolean>(false);
  const [cost24h, setCost24h] = useState<number>(0);
  const [costAvg, setCostAvg] = useState<number>(0);
  const [noHitQueries, setNoHitQueries] = useState<any[]>([]);
  const [terminalOutput, setTerminalOutput] = useState<string[]>([]);
  // Config loading is handled by useConfigField - no longer needed

  // Load status and data on mount (config is handled by useConfigField)
  useEffect(() => {
    loadAvailableModels();
    loadStatus();
    loadCounts();
    loadCosts();
    loadNoHits();

    // Poll status every 5 seconds during reranker training
    const interval = setInterval(() => {
      loadStatus();
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  // loadConfig function REMOVED - useConfigField handles config loading automatically

  /**
   * Load available reranker models from models directory
   */
  /**
   * ---agentspec
   * what: |
   *   Loads hardcoded cross-encoder model paths from local models/ directory. Returns array of model identifiers for reranking tasks.
   *
   * why: |
   *   Avoids dynamic discovery overhead; pre-validated paths ensure consistent model availability.
   *
   * guardrails:
   *   - DO NOT add models without verifying they exist in models/ directory
   *   - NOTE: Paths are static; runtime model additions require code change
   *   - ASK USER: Should this support dynamic model discovery or config file instead?
   * ---/agentspec
   */
  const loadAvailableModels = async () => {
    // Hardcoded model paths based on models/ directory structure
    const models = [
      'models/cross-encoder-agro',
      'models/cross-encoder-agro.baseline',
      'cross-encoder/ms-marco-MiniLM-L-12-v2',
      'cross-encoder/ms-marco-MiniLM-L-6-v2',
      'BAAI/bge-reranker-base',
      'BAAI/bge-reranker-large'
    ];
    setAvailableModels(models);
  };

  /**
   * Load reranker status from /api/reranker/status
   */
  /**
   * ```
   * ---agentspec
   * what: |
   *   Fetches reranker status from /api/reranker/status endpoint. Updates state with response JSON and terminal output (last 50 lines).
   *
   * why: |
   *   Polls API for live reranker state; slicing terminal output prevents memory bloat from unbounded logs.
   *
   * guardrails:
   *   - DO NOT retry on failure; add error handling
   *   - NOTE: Assumes /api/reranker/status returns {live_output: string[]} shape
   * ---/agentspec
   * ```
   */
  const loadStatus = async () => {
    try {
      const response = await fetch('/api/reranker/status');
      const data = await response.json();
      setStatus(data);

      // Update terminal output
      if (data.live_output && data.live_output.length > 0) {
        setTerminalOutput(data.live_output.slice(-50)); // Last 50 lines
      }

      // Parse eval metrics from result
      if (data.result && data.result.output) {
        parseEvalMetrics(data.result.output);
      }
    } catch (error) {
      console.error('Failed to load status:', error);
    }
  };

  /**
   * Load query and triplet counts
   */
  /**
   * ---agentspec
   * what: |
   *   Fetches query and triplet counts from two endpoints in parallel. Returns Promise resolving to {queries, triplets} objects.
   *
   * why: |
   *   Promise.all parallelizes independent API calls for performance.
   *
   * guardrails:
   *   - DO NOT assume both requests succeed; add .catch() per fetch
   *   - NOTE: Throws if either endpoint returns non-JSON
   * ---/agentspec
   */
  const loadCounts = async () => {
    try {
      const [queriesResp, tripletsResp] = await Promise.all([
        fetch('/api/reranker/logs/count'),
        fetch('/api/reranker/triplets/count')
      ]);

      const queries = await queriesResp.json();
      const triplets = await tripletsResp.json();

      setLoggedQueries(queries.count || 0);
      setTripletCount(triplets.count || 0);
    } catch (error) {
      console.error('Failed to load counts:', error);
    }
  };

  /**
   * Load cost metrics
   */
  /**
   * ---agentspec
   * what: |
   *   Fetches reranker cost metrics from /api/reranker/costs endpoint. Parses JSON response and updates state with 24h total and per-query average.
   *
   * why: |
   *   Centralizes cost data fetching with error handling to keep UI state in sync with backend metrics.
   *
   * guardrails:
   *   - DO NOT retry silently on failure; log errors for debugging
   *   - NOTE: Assumes endpoint returns {total_24h, avg_per_query}; add validation if schema changes
   * ---/agentspec
   */
  const loadCosts = async () => {
    try {
      const response = await fetch('/api/reranker/costs');
      const data = await response.json();
      setCost24h(data.total_24h || 0);
      setCostAvg(data.avg_per_query || 0);
    } catch (error) {
      console.error('Failed to load costs:', error);
    }
  };

  /**
   * Load no-hit queries
   */
  /**
   * ---agentspec
   * what: |
   *   Fetches no-hit queries from /api/reranker/nohits endpoint. Sets noHitQueries state with response array or empty fallback.
   *
   * why: |
   *   Isolates API call logic for reusable data loading with error resilience.
   *
   * guardrails:
   *   - DO NOT retry on failure; logs only
   *   - NOTE: Silently defaults to [] if response.queries missing
   * ---/agentspec
   */
  const loadNoHits = async () => {
    try {
      const response = await fetch('/api/reranker/nohits');
      const data = await response.json();
      setNoHitQueries(data.queries || []);
    } catch (error) {
      console.error('Failed to load no-hits:', error);
    }
  };

  /**
   * Parse evaluation metrics from output text
   */
  /**
   * ---agentspec
   * what: |
   *   Extracts evaluation metrics (MRR@all, Hit@1/3/5) from model output via regex. Returns object with parsed floats or undefined.
   *
   * why: |
   *   Regex parsing decouples metric extraction from eval pipeline; enables reuse across different output formats.
   *
   * guardrails:
   *   - DO NOT assume all metrics present; undefined values expected
   *   - NOTE: Regex fragile to whitespace/format changes; add validation tests
   * ---/agentspec
   */
  const parseEvalMetrics = (output: string) => {
    const mrrMatch = output.match(/MRR@all:\s*([\d.]+)/);
    const hit1Match = output.match(/Hit@1:\s*([\d.]+)/);
    const hit3Match = output.match(/Hit@3:\s*([\d.]+)/);
    const hit5Match = output.match(/Hit@5:\s*([\d.]+)/);

    setEvalMetrics({
      mrr: mrrMatch ? parseFloat(mrrMatch[1]) : undefined,
      hit1: hit1Match ? parseFloat(hit1Match[1]) : undefined,
      hit3: hit3Match ? parseFloat(hit3Match[1]) : undefined,
      hit5: hit5Match ? parseFloat(hit5Match[1]) : undefined
    });
  };

  // Config handler functions REMOVED - useConfigField auto-debounces and saves on change
  // Only action handlers (API calls) remain below

  // Action handlers
  /**
   * ---agentspec
   * what: |
   *   POST to /api/reranker/mine with log_path, triplets_path, mode. Extracts triplets from logs via reranker API.
   *
   * why: |
   *   Centralizes triplet mining logic server-side; client sends paths + mode, receives mined data.
   *
   * guardrails:
   *   - DO NOT assume response success; add .catch() for network/API errors
   *   - NOTE: Requires valid log_path and triplets_path; validate before POST
   * ---/agentspec
   */
  const handleMineTriplets = async () => {
    try {
      const response = await fetch('/api/reranker/mine', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          log_path: logPath,
          triplets_path: tripletsPath,
          mode: mineMode,
          reset: mineReset === '1'
        })
      });
      const data = await response.json();
      if (!data.ok) {
        notifyError(`Mining failed: ${data.error}`);
      } else {
        success('Mining completed successfully');
      }
    } catch (error) {
      console.error('Mining error:', error);
      notifyError('Mining failed');
    }
  };

  /**
   * ---agentspec
   * what: |
   *   POSTs training config (epochs, batch_size, max_length) to /api/reranker/train endpoint. Returns training response.
   *
   * why: |
   *   Centralizes reranker model training trigger with validated hyperparameters.
   *
   * guardrails:
   *   - DO NOT train without user confirmation; long-running operation
   *   - NOTE: Requires backend /api/reranker/train endpoint; fails silently if missing
   *   - ASK USER: Add error handling + progress feedback before production
   * ---/agentspec
   */
  const handleTrainModel = async () => {
    try {
      const response = await fetch('/api/reranker/train', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          epochs: trainEpochs,
          batch_size: trainBatchSize,
          max_length: trainMaxLength,
          triplets_path: tripletsPath,
          output_path: modelPath,
          base_model: 'cross-encoder/ms-marco-MiniLM-L-12-v2'
        })
      });
      const data = await response.json();
      if (!data.ok) {
        notifyError(`Training failed: ${data.error}`);
      } else {
        success('Training started successfully');
      }
    } catch (error) {
      console.error('Training error:', error);
      notifyError('Training failed');
    }
  };

  /**
   * ---agentspec
   * what: |
   *   POSTs empty JSON to /api/reranker/evaluate endpoint. Returns parsed response; checks data.ok flag.
   *
   * why: |
   *   Evaluates reranker model performance via dedicated API route.
   *
   * guardrails:
   *   - DO NOT send empty body; clarify required evaluation params (dataset, metrics, model ID)
   *   - NOTE: data.ok check incomplete; missing error handling for !data.ok case
   *   - ASK USER: What should happen if evaluation fails?
   * ---/agentspec
   */
  const handleEvaluateModel = async () => {
    try {
      const response = await fetch('/api/reranker/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      const data = await response.json();
      if (!data.ok) {
        notifyError(`Evaluation failed: ${data.error}`);
      } else {
        success('Evaluation completed');
      }
    } catch (error) {
      console.error('Evaluation error:', error);
      notifyError('Evaluation failed');
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Fetches reranker logs from /api/reranker/logs endpoint. Sets logs state and displays UI modal.
   *
   * why: |
   *   Centralizes log retrieval with error handling to prevent UI crashes on fetch failure.
   *
   * guardrails:
   *   - DO NOT expose raw error to user; only console.error
   *   - NOTE: Silent failure if endpoint unavailable; consider user feedback
   * ---/agentspec
   */
  const handleViewLogs = async () => {
    try {
      const response = await fetch('/api/reranker/logs');
      const data = await response.json();
      setLogs(data.logs || []);
      setShowLogs(true);
    } catch (error) {
      console.error('Failed to load logs:', error);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Handles log download (opens /api/reranker/logs/download in new tab) and log clearing (confirms, then POSTs to clear endpoint).
   *
   * why: |
   *   Separates UI interactions (download/clear) from API calls for testability and reusability.
   *
   * guardrails:
   *   - DO NOT clear logs without user confirmation; destructive operation
   *   - NOTE: Download uses window.open; clear implementation incomplete (try/catch present but no endpoint call shown)
   * ---/agentspec
   */
  const handleDownloadLogs = () => {
    window.open('/api/reranker/logs/download', '_blank');
  };

  /**
   * ```
   * ---agentspec
   * what: |
   *   Clears all query logs via POST to /api/reranker/logs/clear. Confirms user intent, updates local state on success.
   *
   * why: |
   *   Destructive operation requires confirmation; local state sync prevents stale UI.
   *
   * guardrails:
   *   - DO NOT clear without user confirmation; irreversible
   *   - NOTE: Assumes response.json() contains {ok: boolean}
   *   - ASK USER: Add error handling for failed clears
   * ---/agentspec
   * ```
   */
  const handleClearLogs = async () => {
    if (!confirm('Clear all query logs? This cannot be undone.')) {
      return;
    }
    try {
      const response = await fetch('/api/reranker/logs/clear', { method: 'POST' });
      const data = await response.json();
      if (data.ok) {
        setLogs([]);
        setShowLogs(false);
        loadCounts();
      }
    } catch (error) {
      console.error('Failed to clear logs:', error);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   POST to /api/reranker/baseline/save. Saves current reranker state as baseline. Returns {ok: boolean, error?: string}.
   *
   * why: |
   *   Centralizes baseline persistence logic server-side; client triggers via single endpoint.
   *
   * guardrails:
   *   - DO NOT retry on failure; alert user and let them decide
   *   - NOTE: Assumes /api/reranker/baseline/save exists and handles validation server-side
   * ---/agentspec
   */
  const handleSaveBaseline = async () => {
    try {
      const response = await fetch('/api/reranker/baseline/save', { method: 'POST' });
      const data = await response.json();
      if (data.ok) {
        success('Baseline saved successfully');
      } else {
        notifyError(`Failed to save baseline: ${data.error}`);
      }
    } catch (error) {
      console.error('Failed to save baseline:', error);
      notifyError('Failed to save baseline');
    }
  };

  /**
   * ```
   * ---agentspec
   * what: |
   *   Fetches reranker baseline comparison from /api/reranker/baseline/compare. Returns MRR and Hit@1 metrics with deltas; displays via alert().
   *
   * why: |
   *   Client-side handler for A/B comparison without page reload.
   *
   * guardrails:
   *   - DO NOT rely on alert() for production UX; use modal/toast
   *   - NOTE: Assumes /api endpoint returns {ok, baseline, current, delta} or {ok: false, error}
   *   - ASK USER: Add error retry logic and timeout handling
   * ---/agentspec
   * ```
   */
  const handleCompareBaseline = async () => {
    try {
      const response = await fetch('/api/reranker/baseline/compare');
      const data = await response.json();
      if (data.ok) {
        const deltaSign = data.delta.mrr > 0 ? '+' : '';
        info(`Baseline Comparison: Current MRR ${data.current.mrr} vs Baseline ${data.baseline.mrr} (${deltaSign}${data.delta.mrr})`);
      } else {
        notifyError(`Comparison failed: ${data.error}`);
      }
    } catch (error) {
      console.error('Failed to compare baseline:', error);
      notifyError('Failed to compare baseline');
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Prompts user confirmation, then POSTs to /api/reranker/rollback. Returns success alert or silent abort.
   *
   * why: |
   *   Confirmation gate prevents accidental model downgrades; fetch wraps API call with JSON parsing.
   *
   * guardrails:
   *   - DO NOT rollback without user confirmation; destructive operation
   *   - NOTE: Silent fail if response.ok is false; add error handling
   *   - ASK USER: Should failed rollbacks show error alert?
   * ---/agentspec
   */
  const handleRollback = async () => {
    if (!confirm('Rollback to previous model version? This will replace the current model.')) {
      return;
    }
    try {
      const response = await fetch('/api/reranker/rollback', { method: 'POST' });
      const data = await response.json();
      if (data.ok) {
        success('Model rolled back successfully');
      } else {
        notifyError(`Rollback failed: ${data.error}`);
      }
    } catch (error) {
      console.error('Rollback failed:', error);
      notifyError('Rollback failed');
    }
  };

  /**
   * ---agentspec
   * what: |
   *   POSTs cron setup request to /api/reranker/cron/setup with time payload. Returns JSON response; checks data.ok flag.
   *
   * why: |
   *   Centralizes cron scheduling logic in backend; frontend only sends time parameter.
   *
   * guardrails:
   *   - DO NOT assume data.ok without error handling; add catch for network/parse failures
   *   - NOTE: No timeout or retry logic; add if backend is unreliable
   * ---/agentspec
   */
  const handleSetupCron = async () => {
    try {
      const response = await fetch('/api/reranker/cron/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ time: cronTime })
      });
      const data = await response.json();
      if (data.ok) {
        setCronStatus(`Nightly job scheduled for ${data.time}`);
        success(`Cron job scheduled for ${data.time}`);
      } else {
        notifyError(`Failed to setup cron: ${data.error}`);
      }
    } catch (error) {
      console.error('Failed to setup cron:', error);
      notifyError('Failed to setup cron job');
    }
  };

  /**
   * ---agentspec
   * what: |
   *   POST to /api/reranker/cron/remove. Removes scheduled nightly reranker job. Updates UI status on success or alerts error.
   *
   * why: |
   *   Centralizes cron removal logic in single handler; decouples UI state from API layer.
   *
   * guardrails:
   *   - DO NOT assume response.ok === data.ok; validate both HTTP status and data.ok
   *   - NOTE: Alert blocks UI; consider toast/snackbar for non-blocking feedback
   *   - ASK USER: Should removal require confirmation dialog to prevent accidental deletion?
   * ---/agentspec
   */
  const handleRemoveCron = async () => {
    try {
      const response = await fetch('/api/reranker/cron/remove', { method: 'POST' });
      const data = await response.json();
      if (data.ok) {
        setCronStatus('Nightly job removed');
        success('Cron job removed');
      } else {
        notifyError(`Failed to remove cron: ${data.error}`);
      }
    } catch (error) {
      console.error('Failed to remove cron:', error);
      notifyError('Failed to remove cron job');
    }
  };

  /**
   * ---agentspec
   * what: |
   *   POST to /api/reranker/smoketest with query string. Returns JSON result, sets state.
   *
   * why: |
   *   Validates reranker endpoint health before production use.
   *
   * guardrails:
   *   - DO NOT retry on failure; smoke test should fail fast
   *   - NOTE: Assumes endpoint exists; no fallback if 404
   * ---/agentspec
   */
  const handleSmokeTest = async () => {
    try {
      const response = await fetch('/api/reranker/smoketest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: testQuery })
      });
      const data = await response.json();
      setSmokeTestResult(data);
      setShowSmokeResult(true);
    } catch (error) {
      console.error('Smoke test failed:', error);
      setSmokeTestResult({ ok: false, error: String(error) });
      setShowSmokeResult(true);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Displays cost breakdown alert on button click. Shows 24h total and per-query average in USD.
   *
   * why: |
   *   Simple modal for users to inspect billing metrics without page navigation.
   *
   * guardrails:
   *   - DO NOT persist alert state; dismiss on user action
   *   - NOTE: Requires cost24h and costAvg props pre-calculated
   * ---/agentspec
   */
  const handleViewCostDetails = () => {
    info(`Cost: $${cost24h.toFixed(4)}/24h • $${costAvg.toFixed(6)}/query avg`);
  };

  // Loading check removed - useConfigField handles loading state internally

  return (
    <>
      {/* Header Section */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)', padding: '24px' }}>
        <h2 style={{ color: 'var(--link)' }}>Learning Reranker System</h2>
        <p className="small">
          Self-improving retrieval through user feedback. Trains a cross-encoder that learns from
          thumbs-up/down and clicks to rank better results higher - without touching your chat model.
        </p>
      </div>

      {/* Status Overview */}
      <div className="settings-section">
        <h3>System Status</h3>
        <div className="input-row">
          <div className="input-group">
            <label>Reranker Status</label>
            <div style={{
              padding: '8px',
              background: 'var(--card-bg)',
              borderRadius: '4px',
              fontFamily: "'SF Mono', monospace",
              fontSize: '13px'
            }}>
              {rerankerEnabled === '1' ? 'ENABLED' : 'DISABLED'}
            </div>
          </div>
          <div className="input-group">
            <label>Logged Queries</label>
            <div style={{
              padding: '8px',
              background: 'var(--card-bg)',
              borderRadius: '4px',
              fontFamily: "'SF Mono', monospace",
              fontSize: '13px'
            }}>
              {loggedQueries}
            </div>
          </div>
          <div className="input-group">
            <label>Training Triplets</label>
            <div style={{
              padding: '8px',
              background: 'var(--card-bg)',
              borderRadius: '4px',
              fontFamily: "'SF Mono', monospace",
              fontSize: '13px'
            }}>
              {tripletCount}
            </div>
          </div>
        </div>
      </div>

      {/* Training Workflow */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--accent)' }}>
        <h3>Training Workflow</h3>
        <p className="small">Click buttons below in order. Each step shows progress and results.</p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px', margin: '16px 0' }}>
          {/* Mine Triplets */}
          <div style={{
            background: 'var(--chip-bg)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            padding: '16px'
          }}>
            <h4 style={{ margin: '0 0 8px 0', color: 'var(--link)' }}>1. Mine Triplets</h4>
            <p style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '12px' }}>
              Extract training data from logs
            </p>
            <button
              onClick={handleMineTriplets}
              disabled={status?.running}
              style={{
                width: '100%',
                background: 'var(--link)',
                color: 'var(--fg)',
                border: 'none',
                padding: '8px',
                borderRadius: '4px',
                cursor: status?.running ? 'not-allowed' : 'pointer',
                fontWeight: '600',
                opacity: status?.running ? 0.5 : 1
              }}
            >
              Mine Triplets
            </button>
            {status?.task === 'mining' && (
              <div style={{ marginTop: '8px', fontSize: '11px', color: 'var(--fg-muted)' }}>
                {status.message}
              </div>
            )}
          </div>

          {/* Train Model */}
          <div style={{
            background: 'var(--chip-bg)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            padding: '16px'
          }}>
            <h4 style={{ margin: '0 0 8px 0', color: 'var(--accent)' }}>2. Train Model</h4>
            <p style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '12px' }}>
              Fine-tune cross-encoder (5-15 min)
            </p>
            <button
              onClick={handleTrainModel}
              disabled={status?.running}
              style={{
                width: '100%',
                background: 'var(--accent)',
                color: 'var(--accent-contrast)',
                border: 'none',
                padding: '8px',
                borderRadius: '4px',
                cursor: status?.running ? 'not-allowed' : 'pointer',
                fontWeight: '600',
                opacity: status?.running ? 0.5 : 1
              }}
            >
              Train Model
            </button>
            {status?.task === 'training' && (
              <div style={{ marginTop: '8px', fontSize: '11px', color: 'var(--fg-muted)' }}>
                {status.message} ({status.progress}%)
              </div>
            )}
          </div>

          {/* Evaluate */}
          <div style={{
            background: 'var(--chip-bg)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            padding: '16px'
          }}>
            <h4 style={{ margin: '0 0 8px 0', color: 'var(--warn)' }}>3. Evaluate</h4>
            <p style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '12px' }}>
              Measure MRR and Hit@K metrics
            </p>
            <button
              onClick={handleEvaluateModel}
              disabled={status?.running}
              style={{
                width: '100%',
                background: 'var(--warn)',
                color: 'var(--fg)',
                border: 'none',
                padding: '8px',
                borderRadius: '4px',
                cursor: status?.running ? 'not-allowed' : 'pointer',
                fontWeight: '600',
                opacity: status?.running ? 0.5 : 1
              }}
            >
              Evaluate
            </button>
            {status?.task === 'evaluating' && (
              <div style={{ marginTop: '8px', fontSize: '11px', color: 'var(--fg-muted)' }}>
                {status.message}
              </div>
            )}
          </div>
        </div>

        {/* Current Task Status */}
        <div style={{
          marginTop: '16px',
          padding: '12px',
          background: 'var(--card-bg)',
          borderRadius: '6px',
          borderLeft: '3px solid var(--link)'
        }}>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '4px' }}>
            Current Task:
          </div>
          <div style={{ fontSize: '14px', fontFamily: "'SF Mono', monospace", color: 'var(--fg-muted)' }}>
            {status?.running ? status.message : 'Ready'}
          </div>
        </div>

        {/* Live Terminal Output */}
        {terminalOutput.length > 0 && (
          <div style={{
            marginTop: '16px',
            padding: '12px',
            background: '#1a1a1a',
            borderRadius: '6px',
            maxHeight: '300px',
            overflowY: 'auto',
            fontFamily: "'SF Mono', monospace",
            fontSize: '11px',
            color: '#00ff00'
          }}>
            {terminalOutput.map((line, idx) => (
              <div key={idx}>{line}</div>
            ))}
          </div>
        )}
      </div>

      {/* Settings */}
      <div className="settings-section">
        <h3>Reranker Configuration</h3>
        <div className="input-row">
          <div className="input-group">
            <label>
              Enable Learning Reranker
              <span className="help-icon" data-tooltip="AGRO_RERANKER_ENABLED">?</span>
            </label>
            <select
              name="AGRO_RERANKER_ENABLED"
              value={rerankerEnabled}
              onChange={e => setRerankerEnabled(e.target.value)}
            >
              <option value="0">OFF</option>
              <option value="1">ON</option>
            </select>
          </div>
          <div className="input-group">
            <label>
              Model Path (AGRO_RERANKER_MODEL_PATH)
              <span className="help-icon" data-tooltip="AGRO_RERANKER_MODEL_PATH">?</span>
            </label>
            <select
              name="AGRO_RERANKER_MODEL_PATH"
              value={modelPath}
              onChange={e => setModelPath(e.target.value)}
            >
              {availableModels.map(model => (
                <option key={model} value={model}>{model}</option>
              ))}
            </select>
          </div>
          <div className="input-group">
            <label>
              Telemetry Log Path
              <span className="help-icon" data-tooltip="AGRO_LOG_PATH">?</span>
            </label>
            <input
              type="text"
              name="AGRO_LOG_PATH"
              placeholder="data/logs/queries.jsonl"
              value={logPath}
              onChange={e => setLogPath(e.target.value)}
            />
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <label>
              Triplets Output (AGRO_TRIPLETS_PATH)
              <span className="help-icon" data-tooltip="AGRO_TRIPLETS_PATH">?</span>
            </label>
            <input
              type="text"
              name="AGRO_TRIPLETS_PATH"
              placeholder="data/training/triplets.jsonl"
              value={tripletsPath}
              onChange={e => setTripletsPath(e.target.value)}
            />
          </div>
          <div className="input-group">
            <label>
              Mine Mode (AGRO_RERANKER_MINE_MODE)
              <span className="help-icon" data-tooltip="AGRO_RERANKER_MINE_MODE">?</span>
            </label>
            <select
              name="AGRO_RERANKER_MINE_MODE"
              value={mineMode}
              onChange={e => setMineMode(e.target.value)}
            >
              <option value="append">append</option>
              <option value="replace">replace</option>
            </select>
          </div>
          <div className="input-group">
            <label>
              Reset Before Mine (AGRO_RERANKER_MINE_RESET)
              <span className="help-icon" data-tooltip="AGRO_RERANKER_MINE_RESET">?</span>
            </label>
            <select
              name="AGRO_RERANKER_MINE_RESET"
              value={mineReset}
              onChange={e => setMineReset(e.target.value)}
            >
              <option value="0">No</option>
              <option value="1">Yes</option>
            </select>
          </div>
        </div>

        {/* Current Reranker Info Panel */}
        <div className="input-row" style={{ marginTop: '8px' }}>
          <div
            className="input-group full-width"
            style={{
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              borderRadius: '6px',
              padding: '10px'
            }}
          >
            <div style={{
              fontSize: '11px',
              color: 'var(--fg-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
              marginBottom: '6px'
            }}>
              Current Reranker (Server)
            </div>
            <div className="mono" style={{ fontSize: '12px', lineHeight: '1.6' }}>
              <div>Enabled: <span>{rerankerInfo?.enabled ? 'true' : 'false'}</span></div>
              <div>Model Path: <span>{rerankerInfo?.path || modelPath}</span></div>
              <div>Device: <span>{rerankerInfo?.device || '—'}</span></div>
              <div>
                Alpha: <span>{rerankerInfo?.alpha || blendAlpha}</span> •
                TopN: <span>{rerankerInfo?.topn || rerankerTopN}</span> •
                Batch: <span>{rerankerInfo?.batch || batchSize}</span> •
                MaxLen: <span>{rerankerInfo?.maxlen || maxSeqLength}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Blend Alpha (CE Weight)
              <span className="help-icon" data-tooltip="AGRO_RERANKER_ALPHA">?</span>
            </label>
            <input
              type="number"
              name="AGRO_RERANKER_ALPHA"
              value={blendAlpha}
              min="0.0"
              max="1.0"
              step="0.05"
              onChange={e => setBlendAlpha(parseFloat(e.target.value))}
            />
          </div>
          <div className="input-group">
            <label>
              Max Sequence Length
              <span className="help-icon" data-tooltip="AGRO_RERANKER_MAXLEN">?</span>
            </label>
            <input
              type="number"
              name="AGRO_RERANKER_MAXLEN"
              value={maxSeqLength}
              min="128"
              max="1024"
              step="64"
              onChange={e => setMaxSeqLength(parseInt(e.target.value, 10))}
            />
          </div>
          <div className="input-group">
            <label>
              Batch Size (Inference)
              <span className="help-icon" data-tooltip="AGRO_RERANKER_BATCH">?</span>
            </label>
            <input
              type="number"
              name="AGRO_RERANKER_BATCH"
              value={batchSize}
              min="1"
              max="64"
              step="4"
              onChange={e => setBatchSize(parseInt(e.target.value, 10))}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Reranker Top-N
              <span className="help-icon" data-tooltip="AGRO_RERANKER_TOPN">?</span>
            </label>
            <input
              type="number"
              name="AGRO_RERANKER_TOPN"
              value={rerankerTopN}
              min="10"
              max="200"
              step="5"
              onChange={e => setRerankerTopN(parseInt(e.target.value, 10))}
            />
          </div>
          <div className="input-group">
            <label>
              Voyage Rerank Model
              <span className="help-icon" data-tooltip="VOYAGE_RERANK_MODEL">?</span>
            </label>
            <input
              type="text"
              name="VOYAGE_RERANK_MODEL"
              value={voyageRerankerModel}
              onChange={e => setVoyageRerankerModel(e.target.value)}
            />
          </div>
          <div className="input-group">
            <label>
              Reload on Change
              <span className="help-icon" data-tooltip="AGRO_RERANKER_RELOAD_ON_CHANGE">?</span>
            </label>
            <select
              name="AGRO_RERANKER_RELOAD_ON_CHANGE"
              value={reloadOnChange}
              onChange={e => setReloadOnChange(e.target.value)}
            >
              <option value="0">Disabled</option>
              <option value="1">Enabled</option>
            </select>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Training Epochs
              <span className="help-icon" data-tooltip="RERANKER_TRAIN_EPOCHS">?</span>
            </label>
            <input
              type="number"
              name="RERANKER_TRAIN_EPOCHS"
              value={trainEpochs}
              min="1"
              max="10"
              onChange={e => setTrainEpochs(parseInt(e.target.value, 10))}
            />
          </div>
          <div className="input-group">
            <label>
              Training Batch Size
              <span className="help-icon" data-tooltip="RERANKER_TRAIN_BATCH">?</span>
            </label>
            <input
              type="number"
              name="RERANKER_TRAIN_BATCH"
              value={trainBatchSize}
              min="1"
              max="64"
              step="4"
              onChange={e => setTrainBatchSize(parseInt(e.target.value, 10))}
            />
          </div>
          <div className="input-group">
            <label>
              Training Max Length
              <span className="help-icon" data-tooltip="RERANKER_TRAIN_MAX_LENGTH">?</span>
            </label>
            <input
              type="number"
              name="RERANKER_TRAIN_MAX_LENGTH"
              value={trainMaxLength}
              min="128"
              max="1024"
              step="64"
              onChange={e => setTrainMaxLength(parseInt(e.target.value, 10))}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Training Learning Rate
              <span className="help-icon" data-tooltip="RERANKER_TRAIN_LR">?</span>
            </label>
            <input
              type="number"
              name="RERANKER_TRAIN_LR"
              value={trainLearningRate}
              min="0.000001"
              max="0.001"
              step="0.000001"
              onChange={e => setTrainLearningRate(parseFloat(e.target.value))}
            />
          </div>
          <div className="input-group">
            <label>
              Warmup Ratio
              <span className="help-icon" data-tooltip="RERANKER_WARMUP_RATIO">?</span>
            </label>
            <input
              type="number"
              name="RERANKER_WARMUP_RATIO"
              value={warmupRatio}
              min="0.0"
              max="0.5"
              step="0.05"
              onChange={e => setWarmupRatio(parseFloat(e.target.value))}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Triplets Min Count
              <span className="help-icon" data-tooltip="TRIPLETS_MIN_COUNT">?</span>
            </label>
            <input
              type="number"
              name="TRIPLETS_MIN_COUNT"
              value={tripletsMinCount}
              min="10"
              max="10000"
              step="10"
              onChange={e => setTripletsMinCount(parseInt(e.target.value, 10))}
            />
          </div>
          <div className="input-group">
            <label>
              Triplets Mine Mode
              <span className="help-icon" data-tooltip="TRIPLETS_MINE_MODE">?</span>
            </label>
            <select
              name="TRIPLETS_MINE_MODE"
              value={tripletsMineMode}
              onChange={e => setTripletsMineMode(e.target.value)}
            >
              <option value="replace">Replace</option>
              <option value="append">Append</option>
            </select>
          </div>
        </div>

        {/* Quick links to edit related system prompts */}
        <div className="related-prompts">
          <span className="related-prompts-label">Related Prompts:</span>
          <PromptLink promptKey="eval_analysis">Eval Analysis Prompt</PromptLink>
        </div>
      </div>

      {/* Cross-Encoder Model Performance Evaluation Results */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--warn)' }}>
        <h3>Cross-Encoder Model Performance Evaluation</h3>
        <p className="small" style={{ color: 'var(--fg-muted)', fontSize: '11px', marginBottom: '12px' }}>
          Note: This evaluates ONLY the cross-encoder/reranker model performance (MRR, Hit@K metrics).
          For full RAG pipeline evaluation (retrieval + generation), see the Evaluate subtab.
        </p>
        <div style={{
          background: 'var(--card-bg)',
          borderRadius: '6px',
          padding: '16px',
          minHeight: '120px'
        }}>
          {evalMetrics ? (
            <div style={{ fontFamily: "'SF Mono', monospace", fontSize: '13px' }}>
              <div>MRR@all: <strong>{evalMetrics.mrr?.toFixed(4) || '—'}</strong></div>
              <div>Hit@1: <strong>{evalMetrics.hit1?.toFixed(4) || '—'}</strong></div>
              <div>Hit@3: <strong>{evalMetrics.hit3?.toFixed(4) || '—'}</strong></div>
              <div>Hit@5: <strong>{evalMetrics.hit5?.toFixed(4) || '—'}</strong></div>
            </div>
          ) : (
            <div style={{ color: 'var(--fg-muted)', textAlign: 'center', padding: '20px' }}>
              No evaluation results yet. Click "Evaluate" above.
            </div>
          )}
        </div>

        <div className="input-row" style={{ marginTop: '16px' }}>
          <div className="input-group">
            <button
              onClick={handleSaveBaseline}
              style={{
                background: 'var(--link)',
                color: 'var(--on-link)',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '4px',
                cursor: 'pointer',
                width: '100%',
                fontWeight: '600'
              }}
            >
              Save as Baseline
            </button>
          </div>
          <div className="input-group">
            <button
              onClick={handleCompareBaseline}
              style={{
                background: 'var(--warn)',
                color: 'var(--on-warn)',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: '600',
                width: '100%'
              }}
            >
              Compare vs Baseline
            </button>
          </div>
          <div className="input-group">
            <button
              onClick={handleRollback}
              style={{
                background: 'var(--err)',
                color: 'var(--on-err)',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '4px',
                cursor: 'pointer',
                width: '100%',
                fontWeight: '600'
              }}
            >
              Rollback Model
            </button>
          </div>
        </div>
      </div>

      {/* Log Viewer */}
      <div className="settings-section">
        <h3>Query Logs</h3>
        <div className="input-row">
          <div className="input-group">
            <button
              onClick={handleViewLogs}
              style={{
                background: 'var(--bg-elev1)',
                color: 'var(--fg)',
                border: '1px solid var(--line)',
                padding: '8px 16px',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: '600'
              }}
            >
              View Logs
            </button>
          </div>
          <div className="input-group">
            <button
              onClick={handleDownloadLogs}
              style={{
                background: 'var(--bg-elev1)',
                color: 'var(--fg)',
                border: '1px solid var(--line)',
                padding: '8px 16px',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: '600'
              }}
            >
              Download Logs
            </button>
          </div>
          <div className="input-group">
            <button
              onClick={handleClearLogs}
              style={{
                background: 'var(--err)',
                color: 'var(--on-err)',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: '600'
              }}
            >
              Clear Logs
            </button>
          </div>
        </div>
        {showLogs && (
          <div style={{
            marginTop: '16px',
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            padding: '12px',
            maxHeight: '400px',
            overflowY: 'auto',
            fontFamily: "'SF Mono', monospace",
            fontSize: '11px'
          }}>
            {logs.map((log, idx) => (
              <div key={idx} style={{ marginBottom: '8px', borderBottom: '1px solid var(--line)', paddingBottom: '8px' }}>
                <div><strong>Query:</strong> {log.query_raw}</div>
                <div><strong>Time:</strong> {log.ts}</div>
                <div><strong>Results:</strong> {log.retrieval?.length || 0}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Automation */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--warn)' }}>
        <h3>Automation</h3>
        <p className="small">Set up nightly training to automatically improve the reranker.</p>

        <div className="input-row">
          <div className="input-group">
            <label>Nightly Training Time</label>
            <input
              type="time"
              value={cronTime}
              onChange={(e) => setCronTime(e.target.value)}
            />
          </div>
          <div className="input-group">
            <label>&nbsp;</label>
            <button
              onClick={handleSetupCron}
              style={{
                background: 'var(--link)',
                color: 'var(--on-link)',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '4px',
                cursor: 'pointer',
                width: '100%',
                fontWeight: '600'
              }}
            >
              Setup Nightly Job
            </button>
          </div>
        </div>

        <div style={{ marginTop: '8px' }}>
          <button
            onClick={handleRemoveCron}
            style={{
              background: 'var(--err)',
              color: 'var(--on-err)',
              border: 'none',
              padding: '8px 16px',
              borderRadius: '4px',
              cursor: 'pointer',
              width: '100%',
              fontWeight: '600'
            }}
          >
            Remove Nightly Job
          </button>
        </div>

        {cronStatus && (
          <div style={{
            marginTop: '12px',
            padding: '8px',
            background: 'var(--card-bg)',
            borderRadius: '4px',
            fontSize: '12px',
            color: 'var(--fg-muted)'
          }}>
            {cronStatus}
          </div>
        )}
      </div>

      {/* Smoke Test */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--accent)' }}>
        <h3>Smoke Test</h3>
        <p className="small">Verify end-to-end functionality: query → retrieve → rerank → log → feedback.</p>
        <div className="input-row">
          <div className="input-group">
            <label>Test Query</label>
            <input
              type="text"
              placeholder="Where is OAuth validated?"
              value={testQuery}
              onChange={(e) => setTestQuery(e.target.value)}
            />
          </div>
          <div className="input-group">
            <label>&nbsp;</label>
            <button
              onClick={handleSmokeTest}
              style={{
                background: 'var(--accent)',
                color: 'var(--accent-contrast)',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: '600',
                width: '100%'
              }}
            >
              Run Smoke Test
            </button>
          </div>
        </div>
        {showSmokeResult && smokeTestResult && (
          <div style={{
            marginTop: '16px',
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            padding: '12px',
            fontFamily: "'SF Mono', monospace",
            fontSize: '11px'
          }}>
            {smokeTestResult.ok ? (
              <>
                <div>✓ Smoke test passed</div>
                <div>Results: {smokeTestResult.results_count}</div>
                <div>Reranked: {smokeTestResult.reranked ? 'Yes' : 'No'}</div>
                <div>Event ID: {smokeTestResult.event_id}</div>
              </>
            ) : (
              <div style={{ color: 'var(--err)' }}>✗ Error: {smokeTestResult.error}</div>
            )}
          </div>
        )}
      </div>

      {/* Cost Tracking */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--warn)' }}>
        <h3>Cost Tracking</h3>
        <div className="input-row">
          <div className="input-group">
            <label>Total Cost (Last 24h)</label>
            <div style={{
              padding: '8px',
              background: 'var(--card-bg)',
              borderRadius: '4px',
              fontFamily: "'SF Mono', monospace",
              fontSize: '13px',
              color: 'var(--accent)'
            }}>
              ${cost24h.toFixed(4)}
            </div>
          </div>
          <div className="input-group">
            <label>Avg Cost per Query</label>
            <div style={{
              padding: '8px',
              background: 'var(--card-bg)',
              borderRadius: '4px',
              fontFamily: "'SF Mono', monospace",
              fontSize: '13px',
              color: 'var(--accent)'
            }}>
              ${costAvg.toFixed(6)}
            </div>
          </div>
        </div>
        <button
          onClick={handleViewCostDetails}
          style={{
            background: 'var(--bg-elev1)',
            color: 'var(--fg)',
            border: '1px solid var(--line)',
            padding: '8px 16px',
            borderRadius: '4px',
            cursor: 'pointer',
            width: '100%',
            marginTop: '8px',
            fontWeight: '600'
          }}
        >
          View Cost Breakdown
        </button>
      </div>

      {/* No-Hit Tracking */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--err)' }}>
        <h3>No-Hit Queries</h3>
        <p className="small">
          Queries that returned no relevant results. Consider reindexing or adding these terms to your corpus.
        </p>
        <div style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '12px',
          maxHeight: '200px',
          overflowY: 'auto',
          fontFamily: "'SF Mono', monospace",
          fontSize: '11px'
        }}>
          {noHitQueries.length > 0 ? (
            noHitQueries.map((q, idx) => (
              <div key={idx} style={{ marginBottom: '4px' }}>
                <strong>{q.query}</strong> - {q.ts}
              </div>
            ))
          ) : (
            <div style={{ color: 'var(--fg-muted)', textAlign: 'center', padding: '20px' }}>
              No no-hit queries found
            </div>
          )}
        </div>
      </div>
    </>
  );
}
