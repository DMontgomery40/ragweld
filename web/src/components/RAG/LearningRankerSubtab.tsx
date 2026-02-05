import { useEffect, useMemo, useState } from 'react';
import { useConfigField, useNotification } from '@/hooks';
import { useReranker } from '@/hooks/useReranker';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { TrainingStudio } from '@/components/RerankerTraining/TrainingStudio';
import { useActiveRepo } from '@/stores/useRepoStore';
import { rerankerTrainingService } from '@/services/RerankerTrainingService';
import type { RerankerScoreResponse, TrainingConfig } from '@/types/generated';

type LearningBackend = NonNullable<TrainingConfig['learning_reranker_backend']>;

export function LearningRankerSubtab() {
  const { success, error: notifyError, info } = useNotification();
  const activeCorpus = useActiveRepo();
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

  // Learning backend (MLX Qwen3 LoRA, or transformers fallback)
  const [learningBackend, setLearningBackend] = useConfigField<LearningBackend>(
    'training.learning_reranker_backend',
    'auto'
  );
  const [learningBaseModel, setLearningBaseModel] = useConfigField<string>(
    'training.learning_reranker_base_model',
    'Qwen/Qwen3-Reranker-0.6B'
  );

  const [loraRank, setLoraRank] = useConfigField<number>('training.learning_reranker_lora_rank', 16);
  const [loraAlpha, setLoraAlpha] = useConfigField<number>('training.learning_reranker_lora_alpha', 32.0);
  const [loraDropout, setLoraDropout] = useConfigField<number>('training.learning_reranker_lora_dropout', 0.05);
  const [loraTargetModules, setLoraTargetModules] = useConfigField<string[]>(
    'training.learning_reranker_lora_target_modules',
    ['q_proj', 'k_proj', 'v_proj', 'o_proj']
  );

  const [negativeRatio, setNegativeRatio] = useConfigField<number>('training.learning_reranker_negative_ratio', 5);
  const [gradAccumSteps, setGradAccumSteps] = useConfigField<number>(
    'training.learning_reranker_grad_accum_steps',
    8
  );
  const [promoteIfImproves, setPromoteIfImproves] = useConfigField<number>(
    'training.learning_reranker_promote_if_improves',
    1
  );
  const [promoteEpsilon, setPromoteEpsilon] = useConfigField<number>('training.learning_reranker_promote_epsilon', 0.0);
  const [unloadAfterSec, setUnloadAfterSec] = useConfigField<number>(
    'training.learning_reranker_unload_after_sec',
    0
  );

  // Logs UI
  const [showLogs, setShowLogs] = useState(false);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logs, setLogs] = useState<any[]>([]);

  // Debug proof: score a single (query, document) pair
  const [probeQuery, setProbeQuery] = useState('auth login flow');
  const [probeDocument, setProbeDocument] = useState('auth login token flow good');
  const [probeIncludeLogits, setProbeIncludeLogits] = useState(false);
  const [probeLoading, setProbeLoading] = useState(false);
  const [probeResult, setProbeResult] = useState<RerankerScoreResponse | null>(null);

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

  const handleProbeScore = async () => {
    if (!activeCorpus) {
      notifyError('No active corpus selected');
      return;
    }
    setProbeLoading(true);
    setProbeResult(null);
    try {
      const res = await rerankerTrainingService.scorePair({
        corpus_id: activeCorpus,
        query: String(probeQuery || ''),
        document: String(probeDocument || ''),
        include_logits: probeIncludeLogits ? 1 : 0,
      });
      setProbeResult(res);
      if (!res.ok) notifyError(res.error || 'Scoring failed');
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Scoring failed');
    } finally {
      setProbeLoading(false);
    }
  };

  return (
    <div className="subtab-panel" style={{ padding: '24px' }}>
      <div style={{ marginBottom: 18 }}>
        <h3 style={{ fontSize: 18, fontWeight: 600, color: 'var(--fg)', marginBottom: 6 }}>
          🧠 Learning reranker
        </h3>
        <div style={{ fontSize: 13, color: 'var(--fg-muted)' }}>
          Mine triplets from logs and train a learning reranker (MLX Qwen3 LoRA when available; otherwise transformers).
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
              Backend <TooltipIcon name="LEARNING_RERANKER_BACKEND" />
            </label>
            <select value={learningBackend} onChange={(e) => setLearningBackend(e.target.value as LearningBackend)}>
              <option value="auto">auto (prefer MLX Qwen3)</option>
              <option value="transformers">transformers (HF)</option>
              <option value="mlx_qwen3">mlx_qwen3 (force)</option>
            </select>
          </div>
          <div className="input-group">
            <label>
              Base model <TooltipIcon name="LEARNING_RERANKER_BASE_MODEL" />
            </label>
            <input type="text" value={learningBaseModel} onChange={(e) => setLearningBaseModel(e.target.value)} />
          </div>
        </div>

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
              min={10}
              max={10000}
              value={tripletsMinCount}
              onChange={(e) => setTripletsMinCount(parseInt(e.target.value || '10', 10))}
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
              max={0.5}
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
              min={0.000001}
              max={0.001}
              step={0.000001}
              value={trainLr}
              onChange={(e) => setTrainLr(parseFloat(e.target.value || '0.00002'))}
            />
          </div>
          <div className="input-group" />
          <div className="input-group" />
        </div>

        <details style={{ marginTop: 10 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 600 }}>MLX LoRA + promotion (advanced)</summary>
          <div style={{ marginTop: 12 }}>
            <div className="input-row">
              <div className="input-group">
                <label>
                  LoRA rank <TooltipIcon name="LEARNING_RERANKER_LORA_RANK" />
                </label>
                <input
                  type="number"
                  min={1}
                  max={128}
                  value={loraRank}
                  onChange={(e) => setLoraRank(parseInt(e.target.value || '16', 10))}
                />
              </div>
              <div className="input-group">
                <label>
                  LoRA alpha <TooltipIcon name="LEARNING_RERANKER_LORA_ALPHA" />
                </label>
                <input
                  type="number"
                  min={0.01}
                  max={512}
                  step={0.5}
                  value={loraAlpha}
                  onChange={(e) => setLoraAlpha(parseFloat(e.target.value || '32'))}
                />
              </div>
              <div className="input-group">
                <label>
                  LoRA dropout <TooltipIcon name="LEARNING_RERANKER_LORA_DROPOUT" />
                </label>
                <input
                  type="number"
                  min={0}
                  max={0.5}
                  step={0.01}
                  value={loraDropout}
                  onChange={(e) => setLoraDropout(parseFloat(e.target.value || '0.05'))}
                />
              </div>
            </div>

            <div className="input-row">
              <div className="input-group">
                <label>
                  Target modules (comma-separated) <TooltipIcon name="LEARNING_RERANKER_LORA_TARGET_MODULES" />
                </label>
                <input
                  type="text"
                  value={(loraTargetModules || []).join(', ')}
                  onChange={(e) =>
                    setLoraTargetModules(
                      String(e.target.value || '')
                        .split(',')
                        .map((v) => v.trim())
                        .filter(Boolean)
                    )
                  }
                />
              </div>
              <div className="input-group" />
              <div className="input-group" />
            </div>

            <div className="input-row">
              <div className="input-group">
                <label>
                  Negative ratio <TooltipIcon name="LEARNING_RERANKER_NEGATIVE_RATIO" />
                </label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={negativeRatio}
                  onChange={(e) => setNegativeRatio(parseInt(e.target.value || '5', 10))}
                />
              </div>
              <div className="input-group">
                <label>
                  Grad accum steps <TooltipIcon name="LEARNING_RERANKER_GRAD_ACCUM_STEPS" />
                </label>
                <input
                  type="number"
                  min={1}
                  max={128}
                  value={gradAccumSteps}
                  onChange={(e) => setGradAccumSteps(parseInt(e.target.value || '8', 10))}
                />
              </div>
              <div className="input-group">
                <label>
                  Unload after sec <TooltipIcon name="LEARNING_RERANKER_UNLOAD_AFTER_SEC" />
                </label>
                <input
                  type="number"
                  min={0}
                  max={86400}
                  value={unloadAfterSec}
                  onChange={(e) => setUnloadAfterSec(parseInt(e.target.value || '0', 10))}
                />
              </div>
            </div>

            <div className="input-row">
              <div className="input-group">
                <label>
                  Auto-promote if improves <TooltipIcon name="LEARNING_RERANKER_PROMOTE_IF_IMPROVES" />
                </label>
                <select
                  value={promoteIfImproves}
                  onChange={(e) => setPromoteIfImproves(parseInt(e.target.value, 10))}
                >
                  <option value={1}>Yes</option>
                  <option value={0}>No</option>
                </select>
              </div>
              <div className="input-group">
                <label>
                  Promote epsilon <TooltipIcon name="LEARNING_RERANKER_PROMOTE_EPSILON" />
                </label>
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.0001}
                  value={promoteEpsilon}
                  onChange={(e) => setPromoteEpsilon(parseFloat(e.target.value || '0'))}
                />
              </div>
              <div className="input-group" />
            </div>
          </div>
        </details>
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
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 14,
          marginBottom: 18,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Debug proof: score a pair</div>
        <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 10 }}>
          Uses <span style={{ fontFamily: 'var(--font-mono)' }}>/api/reranker/score</span> to show a numeric score (and
          optional logits) so you can verify the model is changing after training.
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>Query</label>
            <textarea
              value={probeQuery}
              onChange={(e) => setProbeQuery(e.target.value)}
              rows={2}
              style={{ width: '100%', resize: 'vertical' }}
            />
          </div>
          <div className="input-group">
            <label>Document</label>
            <textarea
              value={probeDocument}
              onChange={(e) => setProbeDocument(e.target.value)}
              rows={2}
              style={{ width: '100%', resize: 'vertical' }}
            />
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, color: 'var(--fg-muted)' }}>
            <input
              type="checkbox"
              checked={probeIncludeLogits}
              onChange={(e) => setProbeIncludeLogits(e.target.checked)}
            />
            include logits
          </label>
          <button className="small-button" onClick={handleProbeScore} disabled={probeLoading || !activeCorpus}>
            {probeLoading ? 'Scoring…' : 'Score'}
          </button>
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
            corpus=<span style={{ fontFamily: 'var(--font-mono)' }}>{activeCorpus || '—'}</span>
          </div>
        </div>

        {probeResult && (
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              fontSize: 11,
              padding: 10,
              borderRadius: 8,
              border: `1px solid ${probeResult.ok ? 'var(--line)' : 'var(--err)'}`,
              background: probeResult.ok ? 'var(--bg-elev2)' : 'rgba(var(--err-rgb), 0.08)',
              color: 'var(--fg)',
              marginTop: 10,
              marginBottom: 0,
            }}
            data-testid="reranker-score-result"
          >
            {JSON.stringify(probeResult, null, 2)}
          </pre>
        )}
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
