import { useEffect, useMemo, useRef, useState } from 'react';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { useConfigStore } from '@/stores/useConfigStore';
import { useActiveRepo } from '@/stores/useRepoStore';
import { useConfigField, useNotification, useReranker } from '@/hooks';
import { rerankerTrainingService, type RerankerTrainRunsScope } from '@/services/RerankerTrainingService';
import type {
  CorpusEvalProfile,
  RerankerScoreResponse,
  RerankerTrainMetricEvent,
  RerankerTrainRun,
  RerankerTrainRunMeta,
  RerankerTrainStartRequest,
  TrainingConfig,
} from '@/types/generated';
import { NeuralVisualizer, type TelemetryPoint } from './NeuralVisualizer';
import { RunDiff } from './RunDiff';
import { RunOverview } from './RunOverview';

type LearningBackend = NonNullable<TrainingConfig['learning_reranker_backend']>;

type InspectorTab =
  | 'run-hud'
  | 'live-metrics'
  | 'overview'
  | 'diff'
  | 'config'
  | 'debug-score';

type BottomTab = 'timeline' | 'logs';

const TELEMETRY_RING_LIMIT = 10_000;

function metricLabel(metric: 'mrr' | 'ndcg' | 'map', k: number): string {
  if (metric === 'mrr') return `MRR@${k}`;
  if (metric === 'ndcg') return `nDCG@${k}`;
  return 'MAP';
}

function safeDateLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

function latestMetricsFromEvents(events: RerankerTrainMetricEvent[]): Record<string, number> | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const ev = events[i];
    if (ev.metrics) return ev.metrics;
  }
  return null;
}

function toTelemetryPoint(ev: RerankerTrainMetricEvent): TelemetryPoint | null {
  if (ev.type !== 'telemetry') return null;
  if (ev.proj_x == null || ev.proj_y == null) return null;

  return {
    x: Number(ev.proj_x),
    y: Number(ev.proj_y),
    step: Number(ev.step ?? 0),
    loss: Number(ev.loss ?? 0),
    lr: Number(ev.lr ?? 0),
    gradNorm: Number(ev.grad_norm ?? 0),
    ts: String(ev.ts),
  };
}

function formatMetricValue(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  if (v === 0) return '0.0000';
  if (Math.abs(v) < 1) return v.toFixed(4);
  return v.toFixed(3);
}

function lastEventMeta(events: RerankerTrainMetricEvent[]): { ts?: string; step?: number; epoch?: number; percent?: number } {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const ev = events[i];
    if (ev.step != null || ev.epoch != null || ev.percent != null) {
      return {
        ts: ev.ts,
        step: ev.step == null ? undefined : Number(ev.step),
        epoch: ev.epoch == null ? undefined : Number(ev.epoch),
        percent: ev.percent == null ? undefined : Number(ev.percent),
      };
    }
  }
  return {};
}

export function TrainingStudio() {
  const { success, error: notifyError, info } = useNotification();
  const activeCorpus = useActiveRepo();
  const config = useConfigStore((s) => s.config);
  const loadConfig = useConfigStore((s) => s.loadConfig);

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

  const [scope, setScope] = useState<RerankerTrainRunsScope>('corpus');
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('run-hud');
  const [bottomTab, setBottomTab] = useState<BottomTab>('timeline');

  const [profile, setProfile] = useState<CorpusEvalProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  const [runs, setRuns] = useState<RerankerTrainRunMeta[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);

  const [selectedRunId, setSelectedRunId] = useState('');
  const [selectedRun, setSelectedRun] = useState<RerankerTrainRun | null>(null);

  const [events, setEvents] = useState<RerankerTrainMetricEvent[]>([]);
  const [latestMetrics, setLatestMetrics] = useState<Record<string, number> | null>(null);

  const telemetryRef = useRef<TelemetryPoint[]>([]);
  const telemetryPendingRef = useRef<TelemetryPoint[]>([]);
  const telemetryFlushRafRef = useRef<number | null>(null);
  const [telemetryCount, setTelemetryCount] = useState(0);

  const [promoting, setPromoting] = useState(false);
  const [eventQuery, setEventQuery] = useState('');

  const [primaryMetricOverride, setPrimaryMetricOverride] = useState<string>('');
  const [primaryKOverride, setPrimaryKOverride] = useState<string>('');

  const [logsLoading, setLogsLoading] = useState(false);
  const [logs, setLogs] = useState<any[]>([]);

  const [probeQuery, setProbeQuery] = useState('auth login flow');
  const [probeDocument, setProbeDocument] = useState('auth login token flow good');
  const [probeIncludeLogits, setProbeIncludeLogits] = useState(false);
  const [probeLoading, setProbeLoading] = useState(false);
  const [probeResult, setProbeResult] = useState<RerankerScoreResponse | null>(null);

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
  const [learningBackend, setLearningBackend] = useConfigField<LearningBackend>('training.learning_reranker_backend', 'auto');
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
  const [gradAccumSteps, setGradAccumSteps] = useConfigField<number>('training.learning_reranker_grad_accum_steps', 8);
  const [promoteIfImproves, setPromoteIfImproves] = useConfigField<number>('training.learning_reranker_promote_if_improves', 1);
  const [promoteEpsilon, setPromoteEpsilon] = useConfigField<number>('training.learning_reranker_promote_epsilon', 0.0);
  const [unloadAfterSec, setUnloadAfterSec] = useConfigField<number>('training.learning_reranker_unload_after_sec', 0);

  const topn = config?.reranking?.tribrid_reranker_topn ?? 50;

  const kOptions = useMemo(() => {
    const base = [5, 10, 20];
    const filtered = base.filter((k) => k <= Number(topn));
    return filtered.length ? filtered : [Math.max(1, Math.min(10, Number(topn)))];
  }, [topn]);

  const groupedRuns = useMemo(() => {
    const sorted = [...runs].sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
    if (scope !== 'all') return { [activeCorpus || '']: sorted };
    const groups: Record<string, RerankerTrainRunMeta[]> = {};
    for (const r of sorted) {
      const cid = r.corpus_id || '';
      if (!groups[cid]) groups[cid] = [];
      groups[cid].push(r);
    }
    return groups;
  }, [runs, scope, activeCorpus]);

  const pushTelemetry = (point: TelemetryPoint) => {
    telemetryPendingRef.current.push(point);
    if (telemetryFlushRafRef.current != null) return;

    telemetryFlushRafRef.current = requestAnimationFrame(() => {
      telemetryFlushRafRef.current = null;
      if (!telemetryPendingRef.current.length) return;
      const merged = telemetryRef.current.concat(telemetryPendingRef.current);
      telemetryPendingRef.current = [];
      telemetryRef.current = merged.slice(-TELEMETRY_RING_LIMIT);
      setTelemetryCount(telemetryRef.current.length);
    });
  };

  const resetTelemetry = () => {
    telemetryPendingRef.current = [];
    telemetryRef.current = [];
    setTelemetryCount(0);
  };

  useEffect(() => {
    if (!config) void loadConfig();
  }, [config, loadConfig]);

  useEffect(() => {
    void refreshStats();
  }, [refreshStats]);

  useEffect(() => {
    if (!activeCorpus) {
      setProfile(null);
      setProfileError(null);
      return;
    }

    let cancelled = false;
    setProfileLoading(true);
    setProfileError(null);

    void rerankerTrainingService
      .getProfile(activeCorpus)
      .then((p) => {
        if (cancelled) return;
        setProfile(p);
      })
      .catch((e) => {
        if (cancelled) return;
        setProfile(null);
        setProfileError(e instanceof Error ? e.message : 'Failed to load profile');
      })
      .finally(() => {
        if (cancelled) return;
        setProfileLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeCorpus]);

  useEffect(() => {
    if (!activeCorpus && scope === 'corpus') {
      setRuns([]);
      setRunsError(null);
      return;
    }

    let cancelled = false;
    setRunsLoading(true);
    setRunsError(null);

    void rerankerTrainingService
      .listRuns(activeCorpus || '', scope, 50)
      .then((res) => {
        if (cancelled) return;
        const nextRuns = res.runs || [];
        setRuns(nextRuns);
        if (!selectedRunId && nextRuns.length > 0) setSelectedRunId(nextRuns[0].run_id);
      })
      .catch((e) => {
        if (cancelled) return;
        setRuns([]);
        setRunsError(e instanceof Error ? e.message : 'Failed to load runs');
      })
      .finally(() => {
        if (cancelled) return;
        setRunsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeCorpus, scope, selectedRunId]);

  const closeSseRef = useRef<null | (() => void)>(null);

  useEffect(() => {
    if (!selectedRunId) {
      setSelectedRun(null);
      setEvents([]);
      setLatestMetrics(null);
      resetTelemetry();
      return;
    }

    closeSseRef.current?.();
    closeSseRef.current = null;

    let cancelled = false;
    void Promise.all([
      rerankerTrainingService.getRun(selectedRunId),
      rerankerTrainingService.getMetrics(selectedRunId, 2000),
    ])
      .then(([run, metricsRes]) => {
        if (cancelled) return;
        const evs = metricsRes.events || [];
        setSelectedRun(run);
        setEvents(evs);
        setLatestMetrics(latestMetricsFromEvents(evs));

        const telemetry = evs
          .map(toTelemetryPoint)
          .filter((x): x is TelemetryPoint => x != null)
          .slice(-TELEMETRY_RING_LIMIT);
        telemetryRef.current = telemetry;
        telemetryPendingRef.current = [];
        setTelemetryCount(telemetry.length);
      })
      .catch(() => {
        if (cancelled) return;
        setSelectedRun(null);
        setEvents([]);
        setLatestMetrics(null);
        resetTelemetry();
      });

    closeSseRef.current = rerankerTrainingService.streamRun(
      selectedRunId,
      (ev) => {
        const tel = toTelemetryPoint(ev);
        if (tel) pushTelemetry(tel);

        setEvents((prev) => {
          const next = [...prev, ev].slice(-4000);
          setLatestMetrics(latestMetricsFromEvents(next));
          return next;
        });

        const terminal = ev.status && ['completed', 'failed', 'cancelled'].includes(String(ev.status));
        if (terminal) {
          setSelectedRun((prev) => {
            if (!prev) return prev;
            return {
              ...prev,
              status: ev.status as any,
              completed_at: prev.completed_at || ev.ts,
            };
          });
          setRuns((prev) =>
            prev.map((r) =>
              r.run_id === selectedRunId
                ? {
                    ...r,
                    status: ev.status as any,
                    completed_at: r.completed_at || ev.ts,
                  }
                : r
            )
          );
        }
      },
      {
        onError: (msg) => notifyError(msg),
      }
    );

    return () => {
      cancelled = true;
      closeSseRef.current?.();
      closeSseRef.current = null;
    };
  }, [selectedRunId, notifyError]);

  useEffect(() => {
    if (bottomTab !== 'logs') return;
    setLogsLoading(true);
    void getLogs()
      .then((res) => {
        setLogs(res?.logs || []);
      })
      .catch((e) => {
        notifyError(e instanceof Error ? e.message : 'Failed to load logs');
      })
      .finally(() => {
        setLogsLoading(false);
      });
  }, [bottomTab, getLogs, notifyError]);

  const recommended = useMemo(() => {
    if (!profile) return null;
    const k = Number(profile.recommended_k ?? 10);
    return metricLabel(profile.recommended_metric, k);
  }, [profile]);

  const hud = useMemo(() => {
    const run = selectedRun;
    if (!run) return null;
    const snap: any = run.config_snapshot || {};
    const backend = String(snap?.training?.learning_reranker_backend ?? '');
    const baseModel = String(snap?.training?.learning_reranker_base_model ?? '');
    const activePath = String(snap?.training?.tribrid_reranker_model_path ?? '');

    const started = new Date(run.started_at);
    const done = run.completed_at ? new Date(run.completed_at) : null;
    const now = new Date();
    const durMs =
      Number.isFinite(started.getTime()) && (done ? Number.isFinite(done.getTime()) : true)
        ? (done ? done.getTime() : now.getTime()) - started.getTime()
        : null;

    return {
      backend: backend || '—',
      baseModel: baseModel || '—',
      activePath: activePath || '—',
      durationSec: durMs == null ? null : Math.max(0, durMs / 1000),
      last: lastEventMeta(events),
    };
  }, [selectedRun, events]);

  const filteredEvents = useMemo(() => {
    const q = String(eventQuery || '').trim().toLowerCase();
    if (!q) return events;
    return events.filter((ev) => {
      const msg = String(ev.message || '').toLowerCase();
      return msg.includes(q) || ev.type.includes(q);
    });
  }, [events, eventQuery]);

  const onStartRun = async () => {
    if (!activeCorpus) return;
    try {
      info('Starting training run…');
      const payload: RerankerTrainStartRequest = { corpus_id: activeCorpus };
      if (primaryMetricOverride) payload.primary_metric = primaryMetricOverride as any;
      if (primaryKOverride) payload.primary_k = Number(primaryKOverride);

      const res = await rerankerTrainingService.startRun(payload);
      success(`Run started: ${res.run_id}`);

      const list = await rerankerTrainingService.listRuns(activeCorpus, scope, 50);
      setRuns(list.runs || []);
      setSelectedRunId(res.run_id);
      setInspectorTab('run-hud');
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Failed to start run');
    }
  };

  const onPromote = async () => {
    if (!selectedRunId) return;
    setPromoting(true);
    try {
      const res = await rerankerTrainingService.promoteRun(selectedRunId);
      if (res?.ok) {
        success(`Promoted run: ${selectedRunId}`);
        await loadConfig();
      } else {
        notifyError('Promotion failed');
      }
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Promotion failed');
    } finally {
      setPromoting(false);
    }
  };

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
        include_logits: probeIncludeLogits,
        mode: 'learning',
      });
      setProbeResult(res);
      if (!res.ok) notifyError(res.error || 'Scoring failed');
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Scoring failed');
    } finally {
      setProbeLoading(false);
    }
  };

  const inspectorTabs: Array<{ id: InspectorTab; label: string }> = [
    { id: 'run-hud', label: 'Run HUD' },
    { id: 'live-metrics', label: 'Live Metrics' },
    { id: 'overview', label: 'Run Overview' },
    { id: 'diff', label: 'Run Diff' },
    { id: 'config', label: 'Paths + Config' },
    { id: 'debug-score', label: 'Debug Score Pair' },
  ];

  const disabledLegacy = status.running;

  return (
    <section className="training-studio-root" data-testid="reranker-training-studio">
      <header className="training-studio-header">
        <div>
          <h2 className="studio-title">Learning Reranker Training Studio</h2>
          <p className="studio-subtitle">
            Physics-inspired command center with real backend telemetry streaming.
          </p>
        </div>
        <div className="studio-header-actions">
          <button className="small-button" onClick={() => setScope('corpus')} data-active={scope === 'corpus'}>
            This corpus
          </button>
          <button className="small-button" onClick={() => setScope('all')} data-active={scope === 'all'}>
            All corpora
          </button>
          <button className="small-button" onClick={onStartRun} disabled={!activeCorpus} data-testid="studio-start-run">
            Start Run
          </button>
        </div>
      </header>

      <div className="studio-run-setup">
        <div className="studio-run-setup-item">
          <span className="studio-label">Corpus</span>
          <span className="studio-value studio-mono">{activeCorpus || '—'}</span>
        </div>
        <div className="studio-run-setup-item">
          <span className="studio-label">
            Recommended Metric <TooltipIcon name="RERANKER_TRAIN_RECOMMENDED_METRIC" />
          </span>
          <span className="studio-value">
            {profileLoading
              ? 'Loading…'
              : profileError
              ? profileError
              : recommended || '—'}
          </span>
        </div>
        <div className="studio-run-setup-item">
          <span className="studio-label">Primary override</span>
          <div className="studio-inline-row">
            <select value={primaryMetricOverride} onChange={(e) => setPrimaryMetricOverride(e.target.value)}>
              <option value="">Auto metric</option>
              <option value="mrr">mrr</option>
              <option value="ndcg">ndcg</option>
              <option value="map">map</option>
            </select>
            <select value={primaryKOverride} onChange={(e) => setPrimaryKOverride(e.target.value)}>
              <option value="">Auto k</option>
              {kOptions.map((k) => (
                <option key={k} value={String(k)}>
                  {k}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="training-studio-grid">
        <aside className="studio-left-dock studio-panel">
          <header className="studio-panel-header">
            <h3 className="studio-panel-title">Runs</h3>
            <span className="studio-chip">{runsLoading ? 'Loading…' : `${runs.length}`}</span>
          </header>

          {runsError ? <div className="studio-callout studio-callout-err">{runsError}</div> : null}

          <div className="studio-run-list">
            {Object.entries(groupedRuns).map(([corpusId, items]) => (
              <section key={corpusId || 'unknown'} className="studio-run-group">
                {scope === 'all' ? <div className="studio-run-group-label studio-mono">{corpusId || '—'}</div> : null}
                {items.map((r) => {
                  const isSelected = r.run_id === selectedRunId;
                  return (
                    <button
                      key={r.run_id}
                      className="studio-run-item"
                      data-selected={isSelected}
                      onClick={() => setSelectedRunId(r.run_id)}
                    >
                      <div className="studio-run-item-top">
                        <span className="studio-mono">{r.run_id}</span>
                        <span>{r.status}</span>
                      </div>
                      <div className="studio-run-item-meta">
                        {safeDateLabel(r.started_at)} · {metricLabel(r.primary_metric, Number(r.primary_k))}
                      </div>
                    </button>
                  );
                })}
              </section>
            ))}
            {!runsLoading && runs.length === 0 ? <p className="studio-empty">No runs yet.</p> : null}
          </div>
        </aside>

        <main className="studio-center-stage">
          <NeuralVisualizer pointsRef={telemetryRef} pointCount={telemetryCount} />
        </main>

        <aside className="studio-right-dock studio-panel">
          <div className="studio-tab-row">
            {inspectorTabs.map((tab) => (
              <button
                key={tab.id}
                className="studio-tab-btn"
                data-active={inspectorTab === tab.id}
                onClick={() => setInspectorTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="studio-inspector-body">
            {inspectorTab === 'run-hud' ? (
              <section className="studio-panel studio-compact-panel">
                <header className="studio-panel-header">
                  <h3 className="studio-panel-title">Run HUD</h3>
                  <button
                    className="small-button"
                    onClick={onPromote}
                    disabled={!selectedRunId || selectedRun?.status !== 'completed' || promoting}
                  >
                    {promoting ? 'Promoting…' : 'Promote'}
                  </button>
                </header>
                {selectedRun ? (
                  <div className="studio-keyvals">
                    <div><span>status</span><span className="studio-mono">{selectedRun.status}</span></div>
                    <div><span>backend</span><span className="studio-mono">{hud?.backend || '—'}</span></div>
                    <div><span>base_model</span><span className="studio-mono studio-truncate" title={hud?.baseModel || ''}>{hud?.baseModel || '—'}</span></div>
                    <div><span>active_path</span><span className="studio-mono studio-truncate" title={hud?.activePath || ''}>{hud?.activePath || '—'}</span></div>
                    <div><span>duration</span><span className="studio-mono">{hud?.durationSec == null ? '—' : `${hud.durationSec.toFixed(1)}s`}</span></div>
                    <div><span>step</span><span className="studio-mono">{hud?.last?.step ?? '—'}</span></div>
                  </div>
                ) : (
                  <p className="studio-empty">Select a run.</p>
                )}
              </section>
            ) : null}

            {inspectorTab === 'live-metrics' ? (
              <section className="studio-panel studio-compact-panel">
                <header className="studio-panel-header">
                  <h3 className="studio-panel-title">Live Metrics</h3>
                </header>
                {latestMetrics ? (
                  <div className="studio-metric-grid">
                    {Object.entries(latestMetrics).map(([k, v]) => (
                      <article key={k} className="studio-metric-card">
                        <span className="studio-metric-name">{k}</span>
                        <span className="studio-metric-value studio-mono">{formatMetricValue(Number(v))}</span>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="studio-empty">No metric events yet.</p>
                )}

                <div className="studio-status-block">
                  <div className="studio-status-line" data-testid="reranker-status-run-id">
                    run_id={status.run_id || '—'}
                  </div>
                  <div className="studio-status-line">
                    running={String(status.running)} task={status.task || '—'} progress={status.progress}%
                  </div>
                  {status.result?.output ? (
                    <pre className="studio-pre" data-testid="reranker-status-output">{status.result.output}</pre>
                  ) : null}
                  {status.result?.error ? (
                    <pre className="studio-pre studio-pre-err" data-testid="reranker-status-error">{status.result.error}</pre>
                  ) : null}
                </div>
              </section>
            ) : null}

            {inspectorTab === 'overview' ? <RunOverview run={selectedRun} latestMetrics={latestMetrics} /> : null}
            {inspectorTab === 'diff' ? <RunDiff runs={runs} /> : null}

            {inspectorTab === 'config' ? (
              <section className="studio-panel studio-compact-panel" data-testid="studio-config-panel">
                <header className="studio-panel-header">
                  <h3 className="studio-panel-title">Paths + Mining / Training Config</h3>
                </header>

                <div className="studio-form-grid one">
                  <div className="input-group">
                    <label>Model path <TooltipIcon name="TRIBRID_RERANKER_MODEL_PATH" /></label>
                    <input type="text" value={modelPath} onChange={(e) => setModelPath(e.target.value)} />
                  </div>
                  <div className="input-group">
                    <label>Logs path <TooltipIcon name="TRIBRID_LOG_PATH" /></label>
                    <input type="text" value={logPath} onChange={(e) => setLogPath(e.target.value)} />
                  </div>
                  <div className="input-group">
                    <label>Triplets path <TooltipIcon name="TRIBRID_TRIPLETS_PATH" /></label>
                    <input type="text" value={tripletsPath} onChange={(e) => setTripletsPath(e.target.value)} />
                  </div>
                </div>

                <div className="studio-form-grid two">
                  <div className="input-group">
                    <label>Backend <TooltipIcon name="LEARNING_RERANKER_BACKEND" /></label>
                    <select value={learningBackend} onChange={(e) => setLearningBackend(e.target.value as LearningBackend)}>
                      <option value="auto">auto (platform gated)</option>
                      <option value="transformers">transformers</option>
                      <option value="mlx_qwen3">mlx_qwen3</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>Base model <TooltipIcon name="LEARNING_RERANKER_BASE_MODEL" /></label>
                    <input type="text" value={learningBaseModel} onChange={(e) => setLearningBaseModel(e.target.value)} />
                  </div>
                  <div className="input-group">
                    <label>Triplets mine mode <TooltipIcon name="TRIPLETS_MINE_MODE" /></label>
                    <select value={tripletsMineMode} onChange={(e) => setTripletsMineMode(e.target.value)}>
                      <option value="replace">Replace</option>
                      <option value="append">Append</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>Triplets min count <TooltipIcon name="TRIPLETS_MIN_COUNT" /></label>
                    <input
                      type="number"
                      min={10}
                      max={10000}
                      value={tripletsMinCount}
                      onChange={(e) => setTripletsMinCount(parseInt(e.target.value || '10', 10))}
                    />
                  </div>
                  <div className="input-group">
                    <label>Epochs <TooltipIcon name="RERANKER_TRAIN_EPOCHS" /></label>
                    <input type="number" min={1} max={50} value={epochs} onChange={(e) => setEpochs(parseInt(e.target.value || '1', 10))} />
                  </div>
                  <div className="input-group">
                    <label>Batch <TooltipIcon name="RERANKER_TRAIN_BATCH" /></label>
                    <input type="number" min={1} max={256} value={trainBatch} onChange={(e) => setTrainBatch(parseInt(e.target.value || '1', 10))} />
                  </div>
                  <div className="input-group">
                    <label>Warmup ratio <TooltipIcon name="RERANKER_WARMUP_RATIO" /></label>
                    <input
                      type="number"
                      min={0}
                      max={0.5}
                      step={0.01}
                      value={warmupRatio}
                      onChange={(e) => setWarmupRatio(parseFloat(e.target.value || '0'))}
                    />
                  </div>
                  <div className="input-group">
                    <label>Learning rate <TooltipIcon name="RERANKER_TRAIN_LR" /></label>
                    <input
                      type="number"
                      min={0.000001}
                      max={0.001}
                      step={0.000001}
                      value={trainLr}
                      onChange={(e) => setTrainLr(parseFloat(e.target.value || '0.00002'))}
                    />
                  </div>
                </div>

                <details className="studio-details">
                  <summary>MLX LoRA + promotion (advanced)</summary>
                  <div className="studio-form-grid two">
                    <div className="input-group">
                      <label>LoRA rank <TooltipIcon name="LEARNING_RERANKER_LORA_RANK" /></label>
                      <input type="number" min={1} max={128} value={loraRank} onChange={(e) => setLoraRank(parseInt(e.target.value || '16', 10))} />
                    </div>
                    <div className="input-group">
                      <label>LoRA alpha <TooltipIcon name="LEARNING_RERANKER_LORA_ALPHA" /></label>
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
                      <label>LoRA dropout <TooltipIcon name="LEARNING_RERANKER_LORA_DROPOUT" /></label>
                      <input
                        type="number"
                        min={0}
                        max={0.5}
                        step={0.01}
                        value={loraDropout}
                        onChange={(e) => setLoraDropout(parseFloat(e.target.value || '0.05'))}
                      />
                    </div>
                    <div className="input-group">
                      <label>Target modules <TooltipIcon name="LEARNING_RERANKER_LORA_TARGET_MODULES" /></label>
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
                    <div className="input-group">
                      <label>Negative ratio <TooltipIcon name="LEARNING_RERANKER_NEGATIVE_RATIO" /></label>
                      <input
                        type="number"
                        min={1}
                        max={20}
                        value={negativeRatio}
                        onChange={(e) => setNegativeRatio(parseInt(e.target.value || '5', 10))}
                      />
                    </div>
                    <div className="input-group">
                      <label>Grad accum steps <TooltipIcon name="LEARNING_RERANKER_GRAD_ACCUM_STEPS" /></label>
                      <input
                        type="number"
                        min={1}
                        max={128}
                        value={gradAccumSteps}
                        onChange={(e) => setGradAccumSteps(parseInt(e.target.value || '8', 10))}
                      />
                    </div>
                    <div className="input-group">
                      <label>Auto promote <TooltipIcon name="LEARNING_RERANKER_PROMOTE_IF_IMPROVES" /></label>
                      <select value={promoteIfImproves} onChange={(e) => setPromoteIfImproves(parseInt(e.target.value, 10))}>
                        <option value={1}>Yes</option>
                        <option value={0}>No</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>Promote epsilon <TooltipIcon name="LEARNING_RERANKER_PROMOTE_EPSILON" /></label>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.0001}
                        value={promoteEpsilon}
                        onChange={(e) => setPromoteEpsilon(parseFloat(e.target.value || '0'))}
                      />
                    </div>
                    <div className="input-group">
                      <label>Unload after sec <TooltipIcon name="LEARNING_RERANKER_UNLOAD_AFTER_SEC" /></label>
                      <input
                        type="number"
                        min={0}
                        max={86400}
                        value={unloadAfterSec}
                        onChange={(e) => setUnloadAfterSec(parseInt(e.target.value || '0', 10))}
                      />
                    </div>
                  </div>
                </details>

                <div className="studio-action-row">
                  <button className="small-button" onClick={handleMine} disabled={disabledLegacy} data-testid="reranker-mine">
                    {disabledLegacy && status.task === 'mining' ? 'Mining…' : 'Mine triplets'}
                  </button>
                  <button className="small-button" onClick={handleTrain} disabled={disabledLegacy} data-testid="reranker-train">
                    {disabledLegacy && status.task === 'training' ? 'Training…' : 'Train'}
                  </button>
                  <button className="small-button" onClick={handleEvaluate} disabled={disabledLegacy} data-testid="reranker-evaluate">
                    {disabledLegacy && status.task === 'evaluating' ? 'Evaluating…' : 'Evaluate'}
                  </button>
                  <button className="small-button" onClick={() => void refreshStats()} data-testid="reranker-refresh-counts">
                    Refresh counts
                  </button>
                </div>

                <div className="studio-kpi-grid">
                  <article className="studio-metric-card">
                    <span className="studio-metric-name">Logged queries</span>
                    <span className="studio-metric-value" data-testid="reranker-logs-count">{stats.queryCount}</span>
                    <span className="studio-mini-note studio-mono" title={logPath}>{logPath}</span>
                  </article>
                  <article className="studio-metric-card">
                    <span className="studio-metric-name">Triplets</span>
                    <span className="studio-metric-value" data-testid="reranker-triplets-count">{stats.tripletCount}</span>
                    <span className="studio-mini-note studio-mono" title={tripletsPath}>{tripletsPath}</span>
                  </article>
                  <article className="studio-metric-card">
                    <span className="studio-metric-name">Cost estimate</span>
                    <span className="studio-metric-value">${stats.cost24h.toFixed(4)}</span>
                    <span className="studio-mini-note">avg/query ${stats.costAvg.toFixed(4)}</span>
                  </article>
                </div>
              </section>
            ) : null}

            {inspectorTab === 'debug-score' ? (
              <section className="studio-panel studio-compact-panel" data-testid="studio-debug-score">
                <header className="studio-panel-header">
                  <h3 className="studio-panel-title">Debug Score Pair</h3>
                </header>
                <div className="studio-form-grid one">
                  <div className="input-group">
                    <label>Query</label>
                    <textarea value={probeQuery} onChange={(e) => setProbeQuery(e.target.value)} rows={3} />
                  </div>
                  <div className="input-group">
                    <label>Document</label>
                    <textarea value={probeDocument} onChange={(e) => setProbeDocument(e.target.value)} rows={4} />
                  </div>
                </div>
                <div className="studio-inline-row">
                  <label className="studio-checkbox-inline">
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
                  <span className="studio-mini-note">corpus={activeCorpus || '—'}</span>
                </div>
                {probeResult ? (
                  <pre className="studio-pre" data-testid="reranker-score-result">
                    {JSON.stringify(probeResult, null, 2)}
                  </pre>
                ) : null}
              </section>
            ) : null}
          </div>
        </aside>
      </div>

      <section className="studio-bottom-dock studio-panel">
        <div className="studio-tab-row">
          <button className="studio-tab-btn" data-active={bottomTab === 'timeline'} onClick={() => setBottomTab('timeline')}>
            Event Timeline
          </button>
          <button className="studio-tab-btn" data-active={bottomTab === 'logs'} onClick={() => setBottomTab('logs')}>
            Logs
          </button>
          <div className="studio-tab-spacer" />
          {bottomTab === 'timeline' ? (
            <input
              className="studio-search"
              placeholder="Filter events by type/message"
              value={eventQuery}
              onChange={(e) => setEventQuery(e.target.value)}
            />
          ) : (
            <div className="studio-inline-row">
              <button className="small-button" onClick={() => void downloadLogs()}>
                Download
              </button>
              <button
                className="small-button"
                onClick={() => {
                  void clearLogs().then(() => {
                    setLogs([]);
                    void refreshStats();
                  });
                }}
              >
                Clear
              </button>
            </div>
          )}
        </div>

        <div className="studio-bottom-body">
          {bottomTab === 'timeline' ? (
            <div className="studio-timeline" data-testid="studio-event-timeline">
              {filteredEvents.length === 0 ? (
                <p className="studio-empty">No events.</p>
              ) : (
                filteredEvents
                  .slice()
                  .reverse()
                  .map((ev, idx) => (
                    <article key={`${ev.ts}-${idx}`} className="studio-event-row" data-type={ev.type}>
                      <div className="studio-event-head">
                        <span className="studio-chip">{ev.type}</span>
                        <span className="studio-mono">{safeDateLabel(ev.ts)}</span>
                        {ev.step != null ? <span className="studio-chip">step={ev.step}</span> : null}
                        {ev.percent != null ? <span className="studio-chip">{Number(ev.percent).toFixed(1)}%</span> : null}
                      </div>
                      {ev.message ? <p className="studio-event-message">{ev.message}</p> : null}
                      {ev.type === 'telemetry' ? (
                        <div className="studio-mini-grid studio-mono">
                          <span>x={ev.proj_x ?? 0}</span>
                          <span>y={ev.proj_y ?? 0}</span>
                          <span>loss={ev.loss ?? 0}</span>
                          <span>lr={ev.lr ?? 0}</span>
                          <span>grad={ev.grad_norm ?? 0}</span>
                          <span>samples={ev.sample_count ?? 0}</span>
                        </div>
                      ) : null}
                      {ev.metrics ? (
                        <div className="studio-mini-grid studio-mono">
                          {Object.entries(ev.metrics).map(([k, v]) => (
                            <span key={k}>{k}={formatMetricValue(v)}</span>
                          ))}
                        </div>
                      ) : null}
                    </article>
                  ))
              )}
            </div>
          ) : (
            <div className="studio-log-viewer" data-testid="studio-log-viewer">
              {logsLoading ? (
                <p className="studio-empty">Loading logs…</p>
              ) : logs.length === 0 ? (
                <p className="studio-empty">No logs.</p>
              ) : (
                <pre className="studio-pre">{JSON.stringify(logs, null, 2)}</pre>
              )}
            </div>
          )}
        </div>
      </section>
    </section>
  );
}
