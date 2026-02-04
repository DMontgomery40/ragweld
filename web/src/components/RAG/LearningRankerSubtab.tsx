import { useEffect, useMemo, useState } from 'react';
import { useConfigField, useNotification } from '@/hooks';
import { useReranker } from '@/hooks/useReranker';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { TrainingStudio } from '@/components/RerankerTraining/TrainingStudio';

export function LearningRankerSubtab() {
  const { success, error: notifyError, info } = useNotification();
  const {
    status,
    stats,
    mineTriplets,
    trainModel,
    evaluateModel,
    getLogs,
    downloadLogs,
    clearLogs,
    refreshStats,
  } = useReranker();

  // Mode is configured in the Reranker subtab
  const [rerankerMode] = useConfigField<string>('reranking.reranker_mode', 'local');

  // Training + logging config (LAW)
  const [modelPath, setModelPath] = useConfigField<string>(
    'training.tribrid_reranker_model_path',
    'models/cross-encoder-tribrid'
  );
  const [logPath, setLogPath] = useConfigField<string>('tracing.tribrid_log_path', 'data/logs/queries.jsonl');
  const [tripletsPath, setTripletsPath] = useConfigField<string>(
    'training.tribrid_triplets_path',
    'data/training/triplets.jsonl'
  );
  const [tripletsMineMode, setTripletsMineMode] = useConfigField<string>('training.triplets_mine_mode', 'replace');
  const [tripletsMinCount, setTripletsMinCount] = useConfigField<number>('training.triplets_min_count', 100);

  const [epochs, setEpochs] = useConfigField<number>('training.reranker_train_epochs', 2);
  const [trainBatch, setTrainBatch] = useConfigField<number>('training.reranker_train_batch', 16);
  const [trainLr, setTrainLr] = useConfigField<number>('training.reranker_train_lr', 0.00002);
  const [warmupRatio, setWarmupRatio] = useConfigField<number>('training.reranker_warmup_ratio', 0.1);

  const [maxLen] = useConfigField<number>('reranking.tribrid_reranker_maxlen', 512);

  // Logs UI
  const [showLogs, setShowLogs] = useState(false);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logs, setLogs] = useState<any[]>([]);

  useEffect(() => {
    void refreshStats();
  }, [refreshStats]);

  const disabled = status.running;

  const modeWarning = useMemo(() => {
    if ((rerankerMode || '').toLowerCase() === 'learning') return null;
    return `Reranker mode is currently "${rerankerMode}". Switch to "learning" in the Reranker subtab to enable training.`;
  }, [rerankerMode]);

  const handleMine = async () => {
    try {
      info('Mining triplets…');
      const res = await mineTriplets();
      if (res?.ok) success('Triplet mining complete');
      else notifyError(res?.error || 'Triplet mining failed');
      await refreshStats();
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Triplet mining failed');
    }
  };

  const handleTrain = async () => {
    try {
      info('Training reranker…');
      const res = await trainModel({ epochs, batch_size: trainBatch, max_length: maxLen });
      if (res?.ok) success(res?.run_id ? `Training started (${res.run_id})` : 'Training started');
      else notifyError(res?.error || 'Training failed');
      await refreshStats();
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Training failed');
    }
  };

  const handleEvaluate = async () => {
    try {
      info('Evaluating reranker…');
      const res = await evaluateModel();
      if (res?.ok) success('Evaluation complete');
      else notifyError(res?.error || 'Evaluation failed');
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Evaluation failed');
    }
  };

  const handleToggleLogs = async () => {
    const next = !showLogs;
    setShowLogs(next);
    if (!next) return;

    setLogsLoading(true);
    try {
      const res = await getLogs();
      setLogs(res?.logs || []);
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Failed to load logs');
    } finally {
      setLogsLoading(false);
    }
  };

  const handleDownloadLogs = async () => {
    try {
      await downloadLogs();
      success('Logs download started');
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Failed to download logs');
    }
  };

  const handleClearLogs = async () => {
    if (!confirm('Clear all learning reranker logs?')) return;
    try {
      await clearLogs();
      success('Logs cleared');
      setLogs([]);
      await refreshStats();
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Failed to clear logs');
    }
  };

  return (
    <div className="subtab-panel" style={{ padding: '24px' }}>
      <div style={{ marginBottom: 18 }}>
        <h3 style={{ fontSize: 18, fontWeight: 600, color: 'var(--fg)', marginBottom: 6 }}>
          🧠 Learning reranker
        </h3>
        <div style={{ fontSize: 13, color: 'var(--fg-muted)' }}>
          Mine triplets from logs and train the TriBrid cross-encoder.
        </div>
      </div>

      {modeWarning && (
        <div
          style={{
            padding: '10px 12px',
            borderRadius: 8,
            border: '1px solid var(--warn)',
            background: 'rgba(var(--warn-rgb), 0.08)',
            color: 'var(--fg)',
            marginBottom: 16,
            fontSize: 13,
          }}
        >
          {modeWarning}
        </div>
      )}

      <TrainingStudio />

      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 14,
          marginBottom: 18,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 10 }}>Paths</div>
        <div className="input-row">
          <div className="input-group">
            <label>
              Model path <TooltipIcon name="TRIBRID_RERANKER_MODEL_PATH" />
            </label>
            <input type="text" value={modelPath} onChange={(e) => setModelPath(e.target.value)} />
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <label>
              Logs path <TooltipIcon name="TRIBRID_LOG_PATH" />
            </label>
            <input type="text" value={logPath} onChange={(e) => setLogPath(e.target.value)} />
          </div>
          <div className="input-group">
            <label>
              Triplets path <TooltipIcon name="TRIBRID_TRIPLETS_PATH" />
            </label>
            <input type="text" value={tripletsPath} onChange={(e) => setTripletsPath(e.target.value)} />
          </div>
        </div>
      </div>

      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 14,
          marginBottom: 18,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 10 }}>Mining + training config</div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Triplets mine mode <TooltipIcon name="TRIPLETS_MINE_MODE" />
            </label>
            <select value={tripletsMineMode} onChange={(e) => setTripletsMineMode(e.target.value)}>
              <option value="replace">Replace</option>
              <option value="append">Append</option>
            </select>
          </div>
          <div className="input-group">
            <label>
              Triplets min count <TooltipIcon name="TRIPLETS_MIN_COUNT" />
            </label>
            <input
              type="number"
              min={0}
              max={100000}
              value={tripletsMinCount}
              onChange={(e) => setTripletsMinCount(parseInt(e.target.value || '0', 10))}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Epochs <TooltipIcon name="RERANKER_TRAIN_EPOCHS" />
            </label>
            <input
              type="number"
              min={1}
              max={50}
              value={epochs}
              onChange={(e) => setEpochs(parseInt(e.target.value || '1', 10))}
            />
          </div>
          <div className="input-group">
            <label>
              Batch <TooltipIcon name="RERANKER_TRAIN_BATCH" />
            </label>
            <input
              type="number"
              min={1}
              max={256}
              value={trainBatch}
              onChange={(e) => setTrainBatch(parseInt(e.target.value || '1', 10))}
            />
          </div>
          <div className="input-group">
            <label>
              Warmup ratio <TooltipIcon name="RERANKER_WARMUP_RATIO" />
            </label>
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={warmupRatio}
              onChange={(e) => setWarmupRatio(parseFloat(e.target.value || '0'))}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Learning rate <TooltipIcon name="RERANKER_TRAIN_LR" />
            </label>
            <input
              type="number"
              min={0}
              step={0.00001}
              value={trainLr}
              onChange={(e) => setTrainLr(parseFloat(e.target.value || '0'))}
            />
          </div>
          <div className="input-group" />
          <div className="input-group" />
        </div>
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        <button className="small-button" onClick={handleMine} disabled={disabled} data-testid="reranker-mine">
          {disabled && status.task === 'mining' ? 'Mining…' : 'Mine triplets'}
        </button>
        <button className="small-button" onClick={handleTrain} disabled={disabled} data-testid="reranker-train">
          {disabled && status.task === 'training' ? 'Training…' : 'Train'}
        </button>
        <button className="small-button" onClick={handleEvaluate} disabled={disabled} data-testid="reranker-evaluate">
          {disabled && status.task === 'evaluating' ? 'Evaluating…' : 'Evaluate'}
        </button>
        <button className="small-button" onClick={() => void refreshStats()} data-testid="reranker-refresh-counts">
          Refresh counts
        </button>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 10,
          marginBottom: 18,
        }}
      >
        <div style={{ background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: 10, padding: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Logged queries</div>
          <div style={{ fontSize: 18, fontWeight: 700 }} data-testid="reranker-logs-count">
            {stats.queryCount}
          </div>
          <div style={{ fontSize: 11, color: 'var(--fg-muted)' }}>{logPath}</div>
        </div>
        <div style={{ background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: 10, padding: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Triplets</div>
          <div style={{ fontSize: 18, fontWeight: 700 }} data-testid="reranker-triplets-count">
            {stats.tripletCount}
          </div>
          <div style={{ fontSize: 11, color: 'var(--fg-muted)' }}>{tripletsPath}</div>
        </div>
        <div style={{ background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: 10, padding: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Costs (placeholder)</div>
          <div style={{ fontSize: 13, color: 'var(--fg-muted)' }}>
            24h: ${stats.cost24h.toFixed(4)} · avg/query: ${stats.costAvg.toFixed(4)}
          </div>
        </div>
      </div>

      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 14,
          marginBottom: 18,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Status</div>
        <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 8 }}>
          running={String(status.running)} task={status.task || '—'} progress={status.progress}%
        </div>
        {status.run_id && (
          <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 8 }} data-testid="reranker-status-run-id">
            run_id={status.run_id}
          </div>
        )}
        {status.message && (
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              fontSize: 12,
              padding: 10,
              borderRadius: 8,
              border: '1px solid var(--line)',
              background: 'var(--bg-elev2)',
              color: 'var(--fg)',
              margin: 0,
            }}
          >
            {status.message}
          </pre>
        )}
        {status.result?.error && (
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              fontSize: 12,
              padding: 10,
              borderRadius: 8,
              border: '1px solid var(--err)',
              background: 'rgba(var(--err-rgb), 0.08)',
              color: 'var(--fg)',
              marginTop: 10,
              marginBottom: 0,
            }}
            data-testid="reranker-status-error"
          >
            {status.result.error}
          </pre>
        )}
        {status.result?.output && (
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              fontSize: 12,
              padding: 10,
              borderRadius: 8,
              border: '1px solid var(--line)',
              background: 'var(--bg-elev2)',
              color: 'var(--fg)',
              marginTop: 10,
              marginBottom: 0,
            }}
            data-testid="reranker-status-output"
          >
            {status.result.output}
          </pre>
        )}
        {status.result?.metrics && (
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              fontSize: 11,
              padding: 10,
              borderRadius: 8,
              border: '1px solid var(--line)',
              background: 'var(--bg-elev2)',
              color: 'var(--fg)',
              marginTop: 10,
              marginBottom: 0,
            }}
            data-testid="reranker-status-metrics"
          >
            {JSON.stringify(status.result.metrics, null, 2)}
          </pre>
        )}
      </div>

      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 14,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div style={{ fontWeight: 600 }}>Logs</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="small-button" onClick={handleToggleLogs}>
              {showLogs ? 'Hide' : 'View'}
            </button>
            <button className="small-button" onClick={handleDownloadLogs}>
              Download
            </button>
            <button className="small-button" onClick={handleClearLogs}>
              Clear
            </button>
          </div>
        </div>

        {showLogs && (
          <div>
            {logsLoading ? (
              <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Loading…</div>
            ) : logs.length === 0 ? (
              <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>No logs.</div>
            ) : (
              <pre
                style={{
                  whiteSpace: 'pre-wrap',
                  fontSize: 11,
                  padding: 10,
                  borderRadius: 8,
                  border: '1px solid var(--line)',
                  background: 'var(--bg-elev2)',
                  color: 'var(--fg)',
                  margin: 0,
                  maxHeight: 360,
                  overflow: 'auto',
                }}
              >
                {JSON.stringify(logs, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
