import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactElement } from 'react';
import { DockviewReact, type DockviewApi, type DockviewReadyEvent, type IDockviewPanelProps } from 'dockview';
import { Group, Panel, Separator } from 'react-resizable-panels';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useNavigate } from 'react-router-dom';
import 'dockview/dist/styles/dockview.css';

import { apiClient, api } from '@/api/client';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { useConfigStore } from '@/stores/useConfigStore';
import { useActiveRepo } from '@/stores/useRepoStore';
import { useConfigField, useNotification } from '@/hooks';
import { agentTrainingService, type AgentTrainRunsScope } from '@/services/AgentTrainingService';
import type {
  AgentTrainMetricEvent,
  AgentTrainRun,
  AgentTrainRunMeta,
  AgentTrainStartRequest,
  ChatRequest,
  ChatResponse,
} from '@/types/generated';

import { NeuralVisualizer, type TelemetryPoint } from '@/components/RerankerTraining/NeuralVisualizer';
import { GradientDescentViz } from '@/components/RerankerTraining/GradientDescentViz';
import { StudioLogTerminal } from '@/components/RerankerTraining/StudioLogTerminal';
import { RunDiff } from './RunDiff';
import { RunOverview } from './RunOverview';

type InspectorTab = 'run-hud' | 'live-metrics' | 'overview' | 'diff' | 'config' | 'debug-prompt';
type BottomTab = 'timeline' | 'logs' | 'gradient';
type LayoutPreset = 'balanced' | 'focus_viz' | 'focus_logs' | 'focus_inspector';
type SyntheticRecipeKind = 'eval_dataset' | 'full_stack';

type StudioDockRenderers = {
  runs: () => ReactElement;
  visualizer: () => ReactElement;
  inspector: () => ReactElement;
  activity: () => ReactElement;
};

const StudioDockRendererContext = createContext<StudioDockRenderers | null>(null);

function useStudioDockRenderers(): StudioDockRenderers {
  const ctx = useContext(StudioDockRendererContext);
  if (!ctx) throw new Error('StudioDockRendererContext missing');
  return ctx;
}

function DockRunsPanel(_: IDockviewPanelProps) {
  return useStudioDockRenderers().runs();
}

function DockVisualizerPanel(_: IDockviewPanelProps) {
  return useStudioDockRenderers().visualizer();
}

function DockInspectorPanel(_: IDockviewPanelProps) {
  return useStudioDockRenderers().inspector();
}

function DockActivityPanel(_: IDockviewPanelProps) {
  return useStudioDockRenderers().activity();
}

const DOCK_COMPONENTS: Record<string, (props: IDockviewPanelProps) => ReactElement> = {
  'studio-runs': DockRunsPanel,
  'studio-visualizer': DockVisualizerPanel,
  'studio-inspector': DockInspectorPanel,
  'studio-activity': DockActivityPanel,
};

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function safeDateLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

function latestMetricsFromEvents(events: AgentTrainMetricEvent[]): Record<string, number> | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const ev = events[i];
    if (ev.metrics) return ev.metrics;
  }
  return null;
}

function toTelemetryPoint(ev: AgentTrainMetricEvent): TelemetryPoint | null {
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

function metricEventKey(ev: AgentTrainMetricEvent): string {
  return JSON.stringify({
    type: ev.type,
    ts: ev.ts,
    status: ev.status ?? null,
    step: ev.step ?? null,
    epoch: ev.epoch ?? null,
    percent: ev.percent ?? null,
    message: ev.message ?? null,
    loss: ev.loss ?? null,
    lr: ev.lr ?? null,
    grad_norm: ev.grad_norm ?? null,
    param_norm: ev.param_norm ?? null,
    update_norm: ev.update_norm ?? null,
    proj_x: ev.proj_x ?? null,
    proj_y: ev.proj_y ?? null,
    metrics: ev.metrics ?? null,
  });
}

function formatMetricValue(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  if (v === 0) return '0.0000';
  if (Math.abs(v) < 1) return v.toFixed(4);
  return v.toFixed(3);
}

function lastEventMeta(events: AgentTrainMetricEvent[]): { ts?: string; step?: number; epoch?: number; percent?: number } {
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

type RunStatus = NonNullable<AgentTrainRun['status']>;

function normalizeRunStatus(status: AgentTrainRun['status'] | null | undefined): RunStatus | 'unknown' {
  if (status === 'queued' || status === 'running' || status === 'completed' || status === 'failed' || status === 'cancelled') {
    return status;
  }
  return 'unknown';
}

function formatHudProgress(status: RunStatus | 'unknown', percent: number | undefined): string {
  const pct = Number.isFinite(percent) ? clamp(Number(percent), 0, 100) : null;
  if (status === 'failed') return pct == null ? 'failed' : `${pct}% (failed)`;
  if (status === 'cancelled') return pct == null ? 'cancelled' : `${pct}% (cancelled)`;
  if (status === 'completed') return pct == null ? '100%' : `${pct}%`;
  return pct == null ? '—' : `${pct}%`;
}

function lastTerminalMessage(events: AgentTrainMetricEvent[]): string | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const ev = events[i];
    const msg = String(ev.message || '').trim();
    if (!msg) continue;
    if (ev.type === 'error') return msg;
    if (ev.status === 'failed' || ev.status === 'cancelled') return msg;
  }
  return null;
}

function presetLabel(preset: LayoutPreset): string {
  if (preset === 'focus_viz') return 'Focus Viz';
  if (preset === 'focus_logs') return 'Focus Logs';
  if (preset === 'focus_inspector') return 'Focus Inspector';
  return 'Balanced';
}

function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function TrainingStudio() {
  const { success, error: notifyError, info } = useNotification();
  const activeCorpus = useActiveRepo();
  const navigate = useNavigate();
  const config = useConfigStore((s) => s.config);
  const loadConfig = useConfigStore((s) => s.loadConfig);

  const [scope, setScope] = useState<AgentTrainRunsScope>('corpus');
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('run-hud');
  const [bottomTab, setBottomTab] = useState<BottomTab>('timeline');

  const [runs, setRuns] = useState<AgentTrainRunMeta[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);

  const [selectedRunId, setSelectedRunId] = useState('');
  const [selectedRun, setSelectedRun] = useState<AgentTrainRun | null>(null);

  const [events, setEvents] = useState<AgentTrainMetricEvent[]>([]);
  const [latestMetrics, setLatestMetrics] = useState<Record<string, number> | null>(null);

  const telemetryRef = useRef<TelemetryPoint[]>([]);
  const telemetryPendingRef = useRef<TelemetryPoint[]>([]);
  const telemetryFlushRafRef = useRef<number | null>(null);
  const seenEventKeysRef = useRef<Set<string>>(new Set());
  const [telemetryCount, setTelemetryCount] = useState(0);

  const [promoting, setPromoting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [eventQuery, setEventQuery] = useState('');
  const [syntheticRecipe, setSyntheticRecipe] = useState<SyntheticRecipeKind>('eval_dataset');

  const [logClearIso, setLogClearIso] = useState<string | null>(null);

  // Shared training knobs (same config fields as Learning Reranker Studio).
  const [epochs, setEpochs] = useConfigField<number>('training.reranker_train_epochs', 2);
  const [trainBatch, setTrainBatch] = useConfigField<number>('training.reranker_train_batch', 16);
  const [trainLr, setTrainLr] = useConfigField<number>('training.reranker_train_lr', 0.00002);
  const [warmupRatio, setWarmupRatio] = useConfigField<number>('training.reranker_warmup_ratio', 0.1);
  const [maxLen, setMaxLen] = useConfigField<number>('reranking.tribrid_reranker_maxlen', 512);

  // Ragweld agent config (editable in inspector config tab).
  const [ragweldBackend, setRagweldBackend] = useConfigField<string>('training.ragweld_agent_backend', 'mlx_qwen3');
  const [ragweldBaseModel, setRagweldBaseModel] = useConfigField<string>(
    'training.ragweld_agent_base_model',
    'mlx-community/Qwen3-1.7B-4bit'
  );
  const [ragweldModelPath, setRagweldModelPath] = useConfigField<string>(
    'training.ragweld_agent_model_path',
    'models/learning-agent-epstein-files-1'
  );
  const [ragweldDatasetPath, setRagweldDatasetPath] = useConfigField<string>('training.ragweld_agent_train_dataset_path', '');
  const [loraRank, setLoraRank] = useConfigField<number>('training.ragweld_agent_lora_rank', 16);
  const [loraAlpha, setLoraAlpha] = useConfigField<number>('training.ragweld_agent_lora_alpha', 32.0);
  const [loraDropout, setLoraDropout] = useConfigField<number>('training.ragweld_agent_lora_dropout', 0.05);
  const [loraTargetModules, setLoraTargetModules] = useConfigField<string[]>(
    'training.ragweld_agent_lora_target_modules',
    ['q_proj', 'k_proj', 'v_proj', 'o_proj']
  );
  const [gradAccumSteps, setGradAccumSteps] = useConfigField<number>('training.ragweld_agent_grad_accum_steps', 8);
  const [telemetryIntervalSteps, setTelemetryIntervalSteps] = useConfigField<number>(
    'training.ragweld_agent_telemetry_interval_steps',
    2
  );
  const [promoteIfImproves, setPromoteIfImproves] = useConfigField<number>('training.ragweld_agent_promote_if_improves', 1);
  const [promoteEpsilon, setPromoteEpsilon] = useConfigField<number>('training.ragweld_agent_promote_epsilon', 0.0);

  // Studio layout prefs (reuse the existing Learning Reranker Studio UI keys so the layout feels identical).
  const [layoutEngine, setLayoutEngine] = useConfigField<'dockview' | 'panels'>('ui.learning_reranker_layout_engine', 'dockview');
  const [defaultPreset, setDefaultPreset] = useConfigField<LayoutPreset>('ui.learning_reranker_default_preset', 'balanced');
  const [showSetupRow, setShowSetupRow] = useConfigField<number>('ui.learning_reranker_show_setup_row', 0);
  const [logsRenderer, setLogsRenderer] = useConfigField<'json' | 'xterm'>('ui.learning_reranker_logs_renderer', 'xterm');
  const [dockviewLayoutJson, setDockviewLayoutJson] = useConfigField<string>('ui.learning_reranker_dockview_layout_json', '');

  const [studioLeftPct, setStudioLeftPct] = useConfigField<number>('ui.learning_reranker_studio_left_panel_pct', 20);
  const [studioRightPct, setStudioRightPct] = useConfigField<number>('ui.learning_reranker_studio_right_panel_pct', 30);
  const [studioBottomPct, setStudioBottomPct] = useConfigField<number>('ui.learning_reranker_studio_bottom_panel_pct', 28);
  const [visualizerRenderer, setVisualizerRenderer] = useConfigField<'auto' | 'webgpu' | 'webgl2' | 'canvas2d'>(
    'ui.learning_reranker_visualizer_renderer',
    'auto'
  );
  const [visualizerQuality, setVisualizerQuality] = useConfigField<'balanced' | 'cinematic' | 'ultra'>(
    'ui.learning_reranker_visualizer_quality',
    'cinematic'
  );
  const [visualizerColorMode, setVisualizerColorMode] = useConfigField<'absolute' | 'delta'>(
    'ui.learning_reranker_visualizer_color_mode',
    'absolute'
  );
  const [visualizerMaxPoints, setVisualizerMaxPoints] = useConfigField<number>('ui.learning_reranker_visualizer_max_points', 10000);
  const [visualizerTargetFps, setVisualizerTargetFps] = useConfigField<number>('ui.learning_reranker_visualizer_target_fps', 60);
  const [visualizerTailSeconds, setVisualizerTailSeconds] = useConfigField<number>('ui.learning_reranker_visualizer_tail_seconds', 8);
  const [visualizerMotionIntensity, setVisualizerMotionIntensity] = useConfigField<number>(
    'ui.learning_reranker_visualizer_motion_intensity',
    1
  );
  const [visualizerShowVectorField, setVisualizerShowVectorField] = useConfigField<number>(
    'ui.learning_reranker_visualizer_show_vector_field',
    1
  );
  const [visualizerReduceMotion, setVisualizerReduceMotion] = useConfigField<number>(
    'ui.learning_reranker_visualizer_reduce_motion',
    0
  );

  const ringLimit = clamp(Number(visualizerMaxPoints || 10000), 1000, 50000);

  const sortedRuns = useMemo(() => {
    const sorted = [...runs].sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
    if (scope === 'corpus') return sorted.filter((r) => r.corpus_id === activeCorpus);
    return sorted;
  }, [runs, scope, activeCorpus]);

  const pushTelemetry = (point: TelemetryPoint) => {
    telemetryPendingRef.current.push(point);
    if (telemetryFlushRafRef.current != null) return;

    telemetryFlushRafRef.current = requestAnimationFrame(() => {
      telemetryFlushRafRef.current = null;
      if (!telemetryPendingRef.current.length) return;
      const merged = telemetryRef.current.concat(telemetryPendingRef.current);
      telemetryPendingRef.current = [];
      telemetryRef.current = merged.slice(-ringLimit);
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
    if (!activeCorpus && scope === 'corpus') {
      setRuns([]);
      setRunsError(null);
      return;
    }

    let cancelled = false;
    setRunsLoading(true);
    setRunsError(null);

    void agentTrainingService
      .listRuns(activeCorpus || '', scope, 200)
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
      seenEventKeysRef.current.clear();
      resetTelemetry();
      return;
    }

    closeSseRef.current?.();
    closeSseRef.current = null;

    let cancelled = false;
    void Promise.all([agentTrainingService.getRun(selectedRunId), agentTrainingService.getMetrics(selectedRunId, 2000)])
      .then(([run, metricsRes]) => {
        if (cancelled) return;
        const rawEvents = metricsRes.events || [];
        const seen = new Set<string>();
        const evs: AgentTrainMetricEvent[] = [];
        for (const ev of rawEvents) {
          const key = metricEventKey(ev);
          if (seen.has(key)) continue;
          seen.add(key);
          evs.push(ev);
        }
        setSelectedRun(run);
        setEvents(evs);
        seenEventKeysRef.current = seen;
        setLatestMetrics(latestMetricsFromEvents(evs));

        const telemetry = evs
          .map(toTelemetryPoint)
          .filter((x): x is TelemetryPoint => x != null)
          .slice(-ringLimit);
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

    closeSseRef.current = agentTrainingService.streamRun(
      selectedRunId,
      (ev) => {
        const key = metricEventKey(ev);
        if (seenEventKeysRef.current.has(key)) return;
        seenEventKeysRef.current.add(key);

        const tel = toTelemetryPoint(ev);
        if (tel) pushTelemetry(tel);

        setEvents((prev) => {
          const next = [...prev, ev].slice(-5000);
          if (next.length >= 5000) {
            seenEventKeysRef.current = new Set(next.map(metricEventKey));
          }
          setLatestMetrics(latestMetricsFromEvents(next));
          return next;
        });

        const terminal = ev.status && ['completed', 'failed', 'cancelled'].includes(String(ev.status));
        if (terminal) {
          setSelectedRun((prev) => {
            if (!prev) return prev;
            return { ...prev, status: ev.status as any, completed_at: prev.completed_at || ev.ts };
          });
          setRuns((prev) =>
            prev.map((r) => (r.run_id === selectedRunId ? { ...r, status: ev.status as any, completed_at: r.completed_at || ev.ts } : r))
          );
        }
      },
      { onError: (msg) => notifyError(msg) }
    );

    return () => {
      cancelled = true;
      closeSseRef.current?.();
      closeSseRef.current = null;
    };
  }, [selectedRunId, notifyError, ringLimit]);

  const hud = useMemo(() => {
    const run = selectedRun;
    if (!run) return null;

    const snap: any = run.config_snapshot || {};
    const backend = String(snap?.training?.ragweld_agent_backend ?? '');
    const baseModel = String(snap?.training?.ragweld_agent_base_model ?? '');
    const activePath = String(snap?.training?.ragweld_agent_model_path ?? '');

    const started = new Date(run.started_at);
    const done = run.completed_at ? new Date(run.completed_at) : null;
    const now = new Date();
    const durMs =
      Number.isFinite(started.getTime()) && (done ? Number.isFinite(done.getTime()) : true)
        ? (done ? done.getTime() : now.getTime()) - started.getTime()
        : null;

    const status = normalizeRunStatus(run.status);
    const last = lastEventMeta(events);
    const progressLabel = formatHudProgress(status, last.percent);

    return {
      status,
      backend: backend || '—',
      baseModel: baseModel || '—',
      activePath: activePath || '—',
      durationSec: durMs == null ? null : Math.max(0, durMs / 1000),
      last,
      progressLabel,
      terminalMessage: status === 'failed' || status === 'cancelled' ? lastTerminalMessage(events) : null,
    };
  }, [selectedRun, events]);

  const filteredEvents = useMemo(() => {
    const q = String(eventQuery || '').trim().toLowerCase();
    if (!q) return events;
    return events.filter((ev) => {
      const msg = String(ev.message || '').toLowerCase();
      return msg.includes(q) || String(ev.type || '').toLowerCase().includes(q);
    });
  }, [events, eventQuery]);

  const runsScrollRef = useRef<HTMLDivElement | null>(null);
  const runsRailRef = useRef<HTMLDivElement | null>(null);
  const eventsScrollRef = useRef<HTMLDivElement | null>(null);
  const eventsRailRef = useRef<HTMLDivElement | null>(null);

  const runsVirtualizer = useVirtualizer({
    count: sortedRuns.length,
    getScrollElement: () => runsScrollRef.current,
    estimateSize: () => 96,
    overscan: 6,
  });

  const eventsVirtualizer = useVirtualizer({
    count: filteredEvents.length,
    getScrollElement: () => eventsScrollRef.current,
    estimateSize: () => 132,
    overscan: 8,
  });

  const runVirtualItems = runsVirtualizer.getVirtualItems();
  const eventVirtualItems = eventsVirtualizer.getVirtualItems();

  useEffect(() => {
    const rail = runsRailRef.current;
    if (!rail) return;
    rail.style.height = `${runsVirtualizer.getTotalSize()}px`;
    const rows = rail.querySelectorAll<HTMLElement>('[data-role="runs-vrow"]');
    rows.forEach((row) => {
      const start = Number(row.dataset.start || 0);
      row.style.transform = `translateY(${start}px)`;
    });
  }, [runVirtualItems, sortedRuns.length, runsVirtualizer]);

  useEffect(() => {
    const rail = eventsRailRef.current;
    if (!rail) return;
    rail.style.height = `${eventsVirtualizer.getTotalSize()}px`;
    const rows = rail.querySelectorAll<HTMLElement>('[data-role="events-vrow"]');
    rows.forEach((row) => {
      const start = Number(row.dataset.start || 0);
      row.style.transform = `translateY(${start}px)`;
    });
  }, [eventVirtualItems, filteredEvents.length, eventsVirtualizer]);

  const onStartRun = async () => {
    if (!activeCorpus) return;
    try {
      info('Starting agent training run…');
      const payload: AgentTrainStartRequest = { corpus_id: activeCorpus };
      const res = await agentTrainingService.startRun(payload);
      success(`Run started: ${res.run_id}`);

      const list = await agentTrainingService.listRuns(activeCorpus, scope, 200);
      setRuns(list.runs || []);
      setSelectedRunId(res.run_id);
      setInspectorTab('run-hud');
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Failed to start run');
    }
  };

  const openSyntheticLab = useCallback(() => {
    const qs = new URLSearchParams();
    qs.set('subtab', 'synthetic');
    qs.set('synthetic_context', 'learning-agent');
    qs.set('synthetic_recipe', syntheticRecipe);
    qs.set('synthetic_autorun', '0');
    navigate({ pathname: '/rag', search: `?${qs.toString()}` });
  }, [navigate, syntheticRecipe]);

  const onCancel = async () => {
    if (!selectedRunId) return;
    setCancelling(true);
    try {
      const res = await agentTrainingService.cancelRun(selectedRunId);
      if (res?.ok) success(`Cancellation requested: ${selectedRunId}`);
      else notifyError('Cancel failed');
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Cancel failed');
    } finally {
      setCancelling(false);
    }
  };

  const onPromote = async () => {
    if (!selectedRunId) return;
    setPromoting(true);
    try {
      const res = await agentTrainingService.promoteRun(selectedRunId);
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

  const onDownloadLogs = () => {
    const lines = (events || []).map((ev) => JSON.stringify(ev)).join('\n');
    downloadText(`agent-train-${selectedRunId || 'run'}.metrics.jsonl`, lines);
  };

  const onClearLogs = () => {
    setLogClearIso(new Date().toISOString());
  };

  const logEvents = useMemo(() => {
    const cleared = logClearIso ? new Date(logClearIso).getTime() : null;
    return (events || []).filter((ev) => {
      if (cleared != null) {
        const t = new Date(String(ev.ts || '')).getTime();
        if (Number.isFinite(t) && t < cleared) return false;
      }
      return ev.type === 'log' || ev.type === 'error' || ev.type === 'state' || ev.type === 'complete';
    });
  }, [events, logClearIso]);

  // Debug prompt: run a single /api/chat call using ragweld:<base_model>.
  const [debugPrompt, setDebugPrompt] = useState('');
  const [debugRunning, setDebugRunning] = useState(false);
  const [debugOutput, setDebugOutput] = useState('');
  const [debugError, setDebugError] = useState<string | null>(null);

  const onRunDebugPrompt = async () => {
    if (!activeCorpus) {
      notifyError('No active corpus selected');
      return;
    }
    const prompt = String(debugPrompt || '').trim();
    if (!prompt) return;

    setDebugRunning(true);
    setDebugOutput('');
    setDebugError(null);

    try {
      const modelOverride = `ragweld:${String(ragweldBaseModel || '').trim()}`;
      const payload: ChatRequest = {
        message: prompt,
        sources: { corpus_ids: [activeCorpus] },
        stream: false,
        images: [],
        model_override: modelOverride,
        include_vector: true,
        include_sparse: true,
        include_graph: true,
      };
      const { data } = await apiClient.post<ChatResponse>(api('/chat'), payload, { headers: { 'Cache-Control': 'no-store' } });
      const text = String(data?.message?.content || '').trim();
      setDebugOutput(text || '(empty)');
    } catch (e) {
      setDebugError(e instanceof Error ? e.message : 'Failed to run debug prompt');
      setDebugOutput('');
    } finally {
      setDebugRunning(false);
    }
  };

  const onTopLayout = (layout: Record<string, number>) => {
    const nextLeft = clamp(Math.round(Number(layout.left ?? studioLeftPct)), 15, 35);
    const nextRight = clamp(Math.round(Number(layout.right ?? studioRightPct)), 20, 45);
    if (Math.abs(nextLeft - Number(studioLeftPct)) >= 1) setStudioLeftPct(nextLeft);
    if (Math.abs(nextRight - Number(studioRightPct)) >= 1) setStudioRightPct(nextRight);
  };

  const onVerticalLayout = (layout: Record<string, number>) => {
    const nextBottom = clamp(Math.round(Number(layout.bottom ?? studioBottomPct)), 18, 45);
    if (Math.abs(nextBottom - Number(studioBottomPct)) >= 1) setStudioBottomPct(nextBottom);
  };

  const dockApiRef = useRef<DockviewApi | null>(null);
  const dockLayoutDisposableRef = useRef<{ dispose: () => void } | null>(null);
  const pendingPresetRef = useRef<LayoutPreset | null>(null);

  const seedDockviewLayout = useCallback(
    (apiInst: DockviewApi, preset: LayoutPreset) => {
      apiInst.clear();

      const width = Math.max(apiInst.width || 0, 640);
      const height = Math.max(apiInst.height || 0, 480);

      const leftPctRaw =
        preset === 'focus_viz'
          ? 14
          : preset === 'focus_logs'
            ? 14
            : preset === 'focus_inspector'
              ? 16
              : Number(studioLeftPct);
      const rightPctRaw =
        preset === 'focus_inspector'
          ? 36
          : preset === 'focus_viz'
            ? 24
            : preset === 'focus_logs'
              ? 24
              : Number(studioRightPct);
      const bottomPctRaw =
        preset === 'focus_logs'
          ? 38
          : preset === 'focus_viz'
            ? 24
            : preset === 'focus_inspector'
              ? 24
              : Number(studioBottomPct);

      const leftPct = clamp(leftPctRaw, 12, 26);
      const rightPct = clamp(rightPctRaw, 20, 38);
      const bottomPct = clamp(bottomPctRaw, 22, 44);

      const leftRatioRaw = leftPct / 100;
      const rightRatioRaw = rightPct / 100;
      const centerMinRatio = width < 900 ? 0.44 : 0.36;
      const maxSideRatio = Math.max(0.2, 1 - centerMinRatio);
      const sideTotalRatio = leftRatioRaw + rightRatioRaw;
      const sideScale = sideTotalRatio > maxSideRatio ? maxSideRatio / sideTotalRatio : 1;

      let leftPx = Math.max(180, Math.floor(width * leftRatioRaw * sideScale));
      let rightPx = Math.max(220, Math.floor(width * rightRatioRaw * sideScale));

      const centerMinPx = Math.max(320, Math.floor(width * centerMinRatio));
      let centerWidthPx = width - leftPx - rightPx;
      if (centerWidthPx < centerMinPx) {
        const deficit = centerMinPx - centerWidthPx;
        const trimLeft = Math.floor(deficit * 0.45);
        const trimRight = deficit - trimLeft;
        leftPx = Math.max(160, leftPx - trimLeft);
        rightPx = Math.max(200, rightPx - trimRight);
        centerWidthPx = Math.max(centerMinPx, width - leftPx - rightPx);
      }

      const bottomPx = clamp(Math.floor((height * bottomPct) / 100), 170, Math.floor(height * 0.58));

      // Build center hero first, then split full-width activity below it, then add side docks.
      const vizPanel = apiInst.addPanel({
        id: 'studio-visualizer',
        component: 'studio-visualizer',
        title: 'Visualizer',
        initialWidth: centerWidthPx,
        minimumWidth: 380,
      });

      const activityPanel = apiInst.addPanel({
        id: 'studio-activity',
        component: 'studio-activity',
        title: 'Timeline + Logs',
        position: { referencePanel: vizPanel, direction: 'below' },
        initialHeight: bottomPx,
        minimumHeight: 180,
      });

      apiInst.addPanel({
        id: 'studio-runs',
        component: 'studio-runs',
        title: 'Runs',
        position: { referencePanel: vizPanel, direction: 'left' },
        initialWidth: leftPx,
        minimumWidth: 220,
      });

      const inspectorPanel = apiInst.addPanel({
        id: 'studio-inspector',
        component: 'studio-inspector',
        title: 'Inspector',
        position: { referencePanel: vizPanel, direction: 'right' },
        initialWidth: rightPx,
        minimumWidth: 280,
      });

      if (preset === 'focus_logs') {
        setBottomTab('logs');
        activityPanel.api.maximize();
      } else if (preset === 'focus_inspector') {
        inspectorPanel.api.maximize();
      } else if (preset === 'focus_viz') {
        vizPanel.api.maximize();
      }
    },
    [setBottomTab, studioBottomPct, studioLeftPct, studioRightPct]
  );

  const persistDockLayout = useCallback(
    (apiInst: DockviewApi) => {
      try {
        const serialized = JSON.stringify(apiInst.toJSON());
        if (serialized === String(dockviewLayoutJson || '')) return;
        setDockviewLayoutJson(serialized);
      } catch {
        // no-op
      }
    },
    [dockviewLayoutJson, setDockviewLayoutJson]
  );

  const onDockReady = useCallback(
    (event: DockviewReadyEvent) => {
      const apiInst = event.api;
      dockApiRef.current = apiInst;

      dockLayoutDisposableRef.current?.dispose();

      let restored = false;
      const raw = String(dockviewLayoutJson || '').trim();
      if (raw) {
        try {
          apiInst.fromJSON(JSON.parse(raw));
          restored = true;
        } catch {
          restored = false;
        }
      }

      if (restored) {
        const required = ['studio-runs', 'studio-visualizer', 'studio-inspector', 'studio-activity'];
        const hasAllPanels = required.every((id) => apiInst.getPanel(id));
        if (!hasAllPanels) restored = false;
      }

      const pendingPreset = pendingPresetRef.current;
      if (pendingPreset) {
        seedDockviewLayout(apiInst, pendingPreset);
        pendingPresetRef.current = null;
      } else if (!restored) {
        seedDockviewLayout(apiInst, defaultPreset);
      }

      const disposable = apiInst.onDidLayoutChange(() => {
        persistDockLayout(apiInst);
      });
      dockLayoutDisposableRef.current = disposable as any;
    },
    [defaultPreset, dockviewLayoutJson, persistDockLayout, seedDockviewLayout]
  );

  useEffect(() => {
    return () => {
      dockLayoutDisposableRef.current?.dispose();
      dockLayoutDisposableRef.current = null;
    };
  }, []);

  const togglePaneMaximize = useCallback((panelId: string) => {
    const apiInst = dockApiRef.current;
    const panel = apiInst?.getPanel(panelId);
    if (!panel) return;
    if (panel.api.isMaximized()) {
      panel.api.exitMaximized();
    } else {
      panel.api.maximize();
    }
  }, []);

  const popoutPane = useCallback(
    async (panelId: string) => {
      const apiInst = dockApiRef.current;
      const panel = apiInst?.getPanel(panelId);
      if (!apiInst || !panel) {
        notifyError('Pane unavailable for popout');
        return;
      }
      const ok = await apiInst.addPopoutGroup(panel);
      if (!ok) notifyError('Popout failed to open');
    },
    [notifyError]
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || !e.shiftKey) return;
      if (e.key === '1') {
        e.preventDefault();
        togglePaneMaximize('studio-visualizer');
      }
      if (e.key === '2') {
        e.preventDefault();
        setBottomTab('logs');
        togglePaneMaximize('studio-activity');
      }
      if (e.key === '3') {
        e.preventDefault();
        togglePaneMaximize('studio-inspector');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [togglePaneMaximize]);

  const applyLayoutPreset = useCallback(
    (preset: LayoutPreset) => {
      setDefaultPreset(preset);

      if (layoutEngine === 'dockview') {
        const apiInst = dockApiRef.current;
        if (!apiInst) {
          pendingPresetRef.current = preset;
          return;
        }
        seedDockviewLayout(apiInst, preset);
        persistDockLayout(apiInst);
        return;
      }

      if (preset === 'focus_viz') {
        setStudioLeftPct(16);
        setStudioRightPct(22);
        setStudioBottomPct(20);
        return;
      }
      if (preset === 'focus_logs') {
        setStudioLeftPct(16);
        setStudioRightPct(24);
        setStudioBottomPct(42);
        setBottomTab('logs');
        return;
      }
      if (preset === 'focus_inspector') {
        setStudioLeftPct(15);
        setStudioRightPct(42);
        setStudioBottomPct(24);
        return;
      }

      setStudioLeftPct(20);
      setStudioRightPct(30);
      setStudioBottomPct(28);
    },
    [
      layoutEngine,
      persistDockLayout,
      seedDockviewLayout,
      setBottomTab,
      setDefaultPreset,
      setStudioBottomPct,
      setStudioLeftPct,
      setStudioRightPct,
    ]
  );

  const inspectorTabs: Array<{ id: InspectorTab; label: string }> = [
    { id: 'run-hud', label: 'Run HUD' },
    { id: 'live-metrics', label: 'Live Metrics' },
    { id: 'overview', label: 'Run Overview' },
    { id: 'diff', label: 'Run Diff' },
    { id: 'config', label: 'Config' },
    { id: 'debug-prompt', label: 'Debug Prompt' },
  ];

  const renderRunsPanel = useCallback(() => {
    return (
      <section className="studio-panel studio-left-dock">
        <header className="studio-panel-header">
          <h3 className="studio-panel-title">Runs</h3>
          <span className="studio-chip">{runsLoading ? 'Loading…' : `${sortedRuns.length}`}</span>
        </header>
        {runsError ? <div className="studio-callout studio-callout-err">{runsError}</div> : null}

        <div className="studio-run-list studio-virtual-scroll" ref={runsScrollRef} data-testid="studio-runs-list">
          {!runsLoading && sortedRuns.length === 0 ? <p className="studio-empty">No runs yet.</p> : null}
          <div className="studio-virtual-rail" ref={runsRailRef}>
            {runVirtualItems.map((virtualRow) => {
              const run = sortedRuns[virtualRow.index];
              if (!run) return null;
              const isSelected = run.run_id === selectedRunId;
              const best = run.primary_metric_best;
              const final = run.primary_metric_final;

              return (
                <div
                  key={`${run.run_id}-${virtualRow.index}`}
                  className="studio-virtual-item studio-run-virtual-item"
                  data-role="runs-vrow"
                  data-start={Math.floor(virtualRow.start)}
                >
                  <button className="studio-run-item" data-selected={isSelected} onClick={() => setSelectedRunId(run.run_id)}>
                    <div className="studio-run-item-top">
                      <span className="studio-mono">{run.run_id}</span>
                      <span className="studio-run-status-pill studio-mono" data-status={run.status}>
                        {run.status}
                      </span>
                    </div>
                    <div className="studio-run-item-meta">
                      {safeDateLabel(run.started_at)} · eval_loss best={best == null ? '—' : formatMetricValue(Number(best))} final=
                      {final == null ? '—' : formatMetricValue(Number(final))}
                    </div>
                    {scope === 'all' ? <div className="studio-run-item-meta studio-mono">{run.corpus_id || '—'}</div> : null}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      </section>
    );
  }, [runVirtualItems, runsError, runsLoading, scope, selectedRunId, sortedRuns]);

  const renderVisualizerPanel = useCallback(() => {
    const progressLosses = events
      .filter((ev) => ev.type === 'progress' && ev.metrics && typeof ev.metrics.train_loss === 'number')
      .map((ev) => ({ step: Number(ev.step ?? 0), loss: Number(ev.metrics!.train_loss) }))
      .filter((p) => Number.isFinite(p.loss) && Number.isFinite(p.step));

    let best: { step: number; loss: number } | null = null;
    for (const p of progressLosses) {
      if (!best || p.loss < best.loss) best = p;
    }
    const last = progressLosses.length ? progressLosses[progressLosses.length - 1] : null;

    return (
      <section className="studio-center-stage">
        <NeuralVisualizer
          pointsRef={telemetryRef}
          pointCount={telemetryCount}
          rendererPreference={visualizerRenderer}
          quality={visualizerQuality}
          intensityMode={visualizerColorMode}
          bestTrainLoss={best?.loss ?? null}
          bestTrainLossStep={best?.step ?? null}
          lastTrainLoss={last?.loss ?? null}
          lastTrainLossStep={last?.step ?? null}
          targetFps={Number(visualizerTargetFps)}
          tailSeconds={Number(visualizerTailSeconds)}
          motionIntensity={Number(visualizerMotionIntensity)}
          reduceMotion={Number(visualizerReduceMotion) === 1}
          showVectorField={Number(visualizerShowVectorField) === 1}
        />
      </section>
    );
  }, [
    events,
    telemetryCount,
    visualizerMotionIntensity,
    visualizerColorMode,
    visualizerQuality,
    visualizerReduceMotion,
    visualizerRenderer,
    visualizerShowVectorField,
    visualizerTailSeconds,
    visualizerTargetFps,
  ]);

  const renderInspectorPanel = useCallback(() => {
    const promoteDisabled = !selectedRunId || selectedRun?.status !== 'completed' || promoting;
    const cancelDisabled = !selectedRunId || (selectedRun?.status && ['completed', 'failed', 'cancelled'].includes(String(selectedRun.status))) || cancelling;

    return (
      <section className="studio-panel studio-right-dock">
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
          <span className="studio-tab-spacer"></span>
          <button className="small-button" onClick={onCancel} disabled={cancelDisabled}>
            {cancelling ? 'Cancelling…' : 'Cancel'}
          </button>
          <button className="small-button" onClick={onPromote} disabled={promoteDisabled}>
            {promoting ? 'Promoting…' : 'Promote'}
          </button>
        </div>

        <div className="studio-inspector-body">
          {inspectorTab === 'run-hud' ? (
            <section className="studio-panel studio-compact-panel">
              <header className="studio-panel-header">
                <h3 className="studio-panel-title">Run HUD</h3>
              </header>
              {selectedRun ? (
                <div className="studio-keyvals">
                  <div>
                    <span>status</span>
                    <span className="studio-run-status-pill studio-mono" data-status={hud?.status || 'unknown'}>
                      {hud?.status || 'unknown'}
                    </span>
                  </div>
                  <div>
                    <span>backend</span>
                    <span className="studio-mono">{hud?.backend || '—'}</span>
                  </div>
                  <div>
                    <span>base_model</span>
                    <span className="studio-mono studio-truncate" title={hud?.baseModel || ''}>
                      {hud?.baseModel || '—'}
                    </span>
                  </div>
                  <div>
                    <span>active_path</span>
                    <span className="studio-mono studio-truncate" title={hud?.activePath || ''}>
                      {hud?.activePath || '—'}
                    </span>
                  </div>
                  <div>
                    <span>duration</span>
                    <span className="studio-mono">{hud?.durationSec == null ? '—' : `${hud.durationSec.toFixed(1)}s`}</span>
                  </div>
                  <div>
                    <span>step</span>
                    <span className="studio-mono">{hud?.last?.step ?? '—'}</span>
                  </div>
                  <div>
                    <span>epoch</span>
                    <span className="studio-mono">{hud?.last?.epoch ?? '—'}</span>
                  </div>
                  <div>
                    <span>progress</span>
                    <span className="studio-mono">{hud?.progressLabel || '—'}</span>
                  </div>
                  {hud?.terminalMessage ? (
                    <div>
                      <span>{hud.status === 'cancelled' ? 'cancel_reason' : 'failure_reason'}</span>
                      <span className="studio-mono studio-truncate" title={hud.terminalMessage}>
                        {hud.terminalMessage}
                      </span>
                    </div>
                  ) : null}
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
            </section>
          ) : null}

          {inspectorTab === 'overview' ? <RunOverview run={selectedRun} latestMetrics={latestMetrics} /> : null}
          {inspectorTab === 'diff' ? <RunDiff runs={runs} /> : null}

          {inspectorTab === 'config' ? (
            <section className="studio-panel studio-compact-panel" data-testid="studio-config-panel">
              <header className="studio-panel-header">
                <h3 className="studio-panel-title">Agent Config + Training Hyperparams</h3>
              </header>

              <div className="studio-form-grid two">
                <div className="input-group">
                  <label>
                    Backend <TooltipIcon name="RAGWELD_AGENT_BACKEND" />
                  </label>
                  <select value={ragweldBackend} onChange={(e) => setRagweldBackend(e.target.value)}>
                    <option value="mlx_qwen3">mlx_qwen3</option>
                  </select>
                </div>
                <div className="input-group">
                  <label>
                    Base model <TooltipIcon name="RAGWELD_AGENT_BASE_MODEL" />
                  </label>
                  <input type="text" value={ragweldBaseModel} onChange={(e) => setRagweldBaseModel(e.target.value)} />
                </div>
              </div>

              <div className="studio-form-grid one">
                <div className="input-group">
                  <label>
                    Active adapter dir <TooltipIcon name="RAGWELD_AGENT_MODEL_PATH" />
                  </label>
                  <input type="text" value={ragweldModelPath} onChange={(e) => setRagweldModelPath(e.target.value)} />
                </div>
                <div className="input-group">
                  <label>
                    Training dataset path <TooltipIcon name="RAGWELD_AGENT_TRAIN_DATASET_PATH" />
                  </label>
                  <input type="text" value={ragweldDatasetPath} onChange={(e) => setRagweldDatasetPath(e.target.value)} />
                </div>
                <div className="studio-callout">
                  <div style={{ fontWeight: 700, marginBottom: 8 }}>Synthetic Dataset Builder</div>
                  <div className="studio-form-grid two">
                    <div className="input-group">
                      <label>Recipe</label>
                      <select value={syntheticRecipe} onChange={(e) => setSyntheticRecipe(e.target.value as SyntheticRecipeKind)}>
                        <option value="eval_dataset">Eval dataset (trainable)</option>
                        <option value="full_stack">Eval dataset + extras</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>Execution</label>
                      <input type="text" value="Run from Synthetic Lab (model selection required)" readOnly />
                    </div>
                  </div>
                  <button className="small-button" onClick={openSyntheticLab} disabled={!activeCorpus}>
                    Open Synthetic Lab
                  </button>
                </div>
              </div>

              <details className="studio-details">
                <summary>MLX LoRA + promotion (advanced)</summary>
                <div className="studio-form-grid two">
                  <div className="input-group">
                    <label>
                      LoRA rank <TooltipIcon name="RAGWELD_AGENT_LORA_RANK" />
                    </label>
                    <input type="number" min={1} max={128} value={loraRank} onChange={(e) => setLoraRank(parseInt(e.target.value || '16', 10))} />
                  </div>
                  <div className="input-group">
                    <label>
                      LoRA alpha <TooltipIcon name="RAGWELD_AGENT_LORA_ALPHA" />
                    </label>
                    <input type="number" min={1} max={512} step={1} value={loraAlpha} onChange={(e) => setLoraAlpha(parseFloat(e.target.value || '32'))} />
                  </div>
                  <div className="input-group">
                    <label>
                      LoRA dropout <TooltipIcon name="RAGWELD_AGENT_LORA_DROPOUT" />
                    </label>
                    <input type="number" min={0} max={0.5} step={0.01} value={loraDropout} onChange={(e) => setLoraDropout(parseFloat(e.target.value || '0.05'))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Grad accum steps <TooltipIcon name="RAGWELD_AGENT_GRAD_ACCUM_STEPS" />
                    </label>
                    <input type="number" min={1} max={128} value={gradAccumSteps} onChange={(e) => setGradAccumSteps(parseInt(e.target.value || '1', 10))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Telemetry interval <TooltipIcon name="RAGWELD_AGENT_TELEMETRY_INTERVAL_STEPS" />
                    </label>
                    <input type="number" min={1} max={20} value={telemetryIntervalSteps} onChange={(e) => setTelemetryIntervalSteps(parseInt(e.target.value || '2', 10))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Promote if improves <TooltipIcon name="RAGWELD_AGENT_PROMOTE_IF_IMPROVES" />
                    </label>
                    <select value={String(promoteIfImproves)} onChange={(e) => setPromoteIfImproves(parseInt(e.target.value, 10))}>
                      <option value="1">Yes</option>
                      <option value="0">No</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      Promote epsilon <TooltipIcon name="RAGWELD_AGENT_PROMOTE_EPSILON" />
                    </label>
                    <input type="number" min={0} max={10} step={0.0001} value={promoteEpsilon} onChange={(e) => setPromoteEpsilon(parseFloat(e.target.value || '0'))} />
                  </div>
                  <div className="input-group">
                    <label>
                      LoRA target modules <TooltipIcon name="RAGWELD_AGENT_LORA_TARGET_MODULES" />
                    </label>
                    <input
                      type="text"
                      value={(Array.isArray(loraTargetModules) ? loraTargetModules : []).join(', ')}
                      onChange={(e) => {
                        const list = e.target.value
                          .split(',')
                          .map((x) => x.trim())
                          .filter(Boolean);
                        setLoraTargetModules(list.length ? list : ['q_proj']);
                      }}
                    />
                  </div>
                </div>
              </details>

              <details className="studio-details">
                <summary>Shared hyperparams (epochs/batch/lr/warmup/max_length)</summary>
                <div className="studio-form-grid two">
                  <div className="input-group">
                    <label>
                      Epochs <TooltipIcon name="RERANKER_TRAIN_EPOCHS" />
                    </label>
                    <input type="number" min={1} max={20} value={epochs} onChange={(e) => setEpochs(parseInt(e.target.value || '1', 10))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Batch <TooltipIcon name="RERANKER_TRAIN_BATCH" />
                    </label>
                    <input type="number" min={1} max={128} value={trainBatch} onChange={(e) => setTrainBatch(parseInt(e.target.value || '1', 10))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Warmup ratio <TooltipIcon name="RERANKER_WARMUP_RATIO" />
                    </label>
                    <input type="number" min={0} max={0.5} step={0.01} value={warmupRatio} onChange={(e) => setWarmupRatio(parseFloat(e.target.value || '0'))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Learning rate <TooltipIcon name="RERANKER_TRAIN_LR" />
                    </label>
                    <input type="number" min={0.000001} max={0.001} step={0.000001} value={trainLr} onChange={(e) => setTrainLr(parseFloat(e.target.value || '0.00002'))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Max length <TooltipIcon name="TRIBRID_RERANKER_MAXLEN" />
                    </label>
                    <input type="number" min={128} max={2048} value={maxLen} onChange={(e) => setMaxLen(parseInt(e.target.value || '512', 10))} />
                  </div>
                </div>
              </details>

              <details className="studio-details">
                <summary>Studio layout + visualizer</summary>
                <div className="studio-form-grid two">
                  <div className="input-group">
                    <label>
                      Layout engine <TooltipIcon name="LEARNING_RERANKER_LAYOUT_ENGINE" />
                    </label>
                    <select value={layoutEngine} onChange={(e) => setLayoutEngine(e.target.value as 'dockview' | 'panels')}>
                      <option value="dockview">dockview</option>
                      <option value="panels">panels</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      Default preset <TooltipIcon name="LEARNING_RERANKER_DEFAULT_PRESET" />
                    </label>
                    <select value={defaultPreset} onChange={(e) => setDefaultPreset(e.target.value as LayoutPreset)}>
                      <option value="balanced">balanced</option>
                      <option value="focus_viz">focus_viz</option>
                      <option value="focus_logs">focus_logs</option>
                      <option value="focus_inspector">focus_inspector</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      Show setup row <TooltipIcon name="LEARNING_RERANKER_SHOW_SETUP_ROW" />
                    </label>
                    <select value={String(showSetupRow)} onChange={(e) => setShowSetupRow(parseInt(e.target.value, 10))}>
                      <option value="0">No</option>
                      <option value="1">Yes</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      Logs renderer <TooltipIcon name="LEARNING_RERANKER_LOGS_RENDERER" />
                    </label>
                    <select value={logsRenderer} onChange={(e) => setLogsRenderer(e.target.value as 'json' | 'xterm')}>
                      <option value="xterm">xterm</option>
                      <option value="json">json</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      Left panel % <TooltipIcon name="LEARNING_RERANKER_STUDIO_LEFT_PANEL_PCT" />
                    </label>
                    <input type="number" min={15} max={35} value={studioLeftPct} onChange={(e) => setStudioLeftPct(parseInt(e.target.value || '20', 10))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Right panel % <TooltipIcon name="LEARNING_RERANKER_STUDIO_RIGHT_PANEL_PCT" />
                    </label>
                    <input type="number" min={20} max={45} value={studioRightPct} onChange={(e) => setStudioRightPct(parseInt(e.target.value || '30', 10))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Bottom panel % <TooltipIcon name="LEARNING_RERANKER_STUDIO_BOTTOM_PANEL_PCT" />
                    </label>
                    <input type="number" min={18} max={45} value={studioBottomPct} onChange={(e) => setStudioBottomPct(parseInt(e.target.value || '28', 10))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Renderer <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_RENDERER" />
                    </label>
                    <select value={visualizerRenderer} onChange={(e) => setVisualizerRenderer(e.target.value as any)}>
                      <option value="auto">auto</option>
                      <option value="webgpu">webgpu</option>
                      <option value="webgl2">webgl2</option>
                      <option value="canvas2d">canvas2d</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      Quality <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_QUALITY" />
                    </label>
                    <select value={visualizerQuality} onChange={(e) => setVisualizerQuality(e.target.value as any)}>
                      <option value="balanced">balanced</option>
                      <option value="cinematic">cinematic</option>
                      <option value="ultra">ultra</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      Color mode <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_COLOR_MODE" />
                    </label>
                    <select value={visualizerColorMode} onChange={(e) => setVisualizerColorMode(e.target.value as any)}>
                      <option value="absolute">absolute</option>
                      <option value="delta">delta</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      Max points <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_MAX_POINTS" />
                    </label>
                    <input type="number" min={1000} max={50000} value={visualizerMaxPoints} onChange={(e) => setVisualizerMaxPoints(parseInt(e.target.value || '10000', 10))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Target FPS <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_TARGET_FPS" />
                    </label>
                    <input type="number" min={30} max={144} value={visualizerTargetFps} onChange={(e) => setVisualizerTargetFps(parseInt(e.target.value || '60', 10))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Tail sec <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_TAIL_SECONDS" />
                    </label>
                    <input type="number" min={1} max={30} step={0.5} value={visualizerTailSeconds} onChange={(e) => setVisualizerTailSeconds(parseFloat(e.target.value || '8'))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Motion intensity <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_MOTION_INTENSITY" />
                    </label>
                    <input type="number" min={0} max={2} step={0.05} value={visualizerMotionIntensity} onChange={(e) => setVisualizerMotionIntensity(parseFloat(e.target.value || '1'))} />
                  </div>
                  <div className="input-group">
                    <label>
                      Show vector field <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_SHOW_VECTOR_FIELD" />
                    </label>
                    <select value={String(visualizerShowVectorField)} onChange={(e) => setVisualizerShowVectorField(parseInt(e.target.value, 10))}>
                      <option value="1">Yes</option>
                      <option value="0">No</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      Reduce motion <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_REDUCE_MOTION" />
                    </label>
                    <select value={String(visualizerReduceMotion)} onChange={(e) => setVisualizerReduceMotion(parseInt(e.target.value, 10))}>
                      <option value="0">No</option>
                      <option value="1">Yes</option>
                    </select>
                  </div>
                </div>
              </details>
            </section>
          ) : null}

          {inspectorTab === 'debug-prompt' ? (
            <section className="studio-panel studio-compact-panel" data-testid="studio-debug-prompt-panel">
              <header className="studio-panel-header">
                <h3 className="studio-panel-title">Debug Prompt</h3>
                <button className="small-button" onClick={onRunDebugPrompt} disabled={debugRunning || !debugPrompt.trim() || !activeCorpus}>
                  {debugRunning ? 'Running…' : 'Run'}
                </button>
              </header>

              <div className="studio-form-grid one">
                <div className="input-group">
                  <label>Prompt</label>
                  <textarea value={debugPrompt} onChange={(e) => setDebugPrompt(e.target.value)} rows={4} placeholder="Ask the agent something…" />
                </div>
                <div className="studio-status-line studio-mono">
                  model_override={String(`ragweld:${String(ragweldBaseModel || '').trim()}`)}
                </div>
                {debugError ? <div className="studio-callout studio-callout-err">{debugError}</div> : null}
                <pre className="studio-pre studio-pre-full" data-testid="studio-debug-prompt-output">
                  {debugOutput || '—'}
                </pre>
              </div>
            </section>
          ) : null}
        </div>
      </section>
    );
  }, [
    activeCorpus,
    cancelling,
    debugError,
    debugOutput,
    debugPrompt,
    debugRunning,
    defaultPreset,
    epochs,
    gradAccumSteps,
    hud?.activePath,
    hud?.backend,
    hud?.baseModel,
    hud?.durationSec,
    hud?.last?.epoch,
    hud?.last?.percent,
    hud?.last?.step,
    inspectorTab,
    inspectorTabs,
    latestMetrics,
    layoutEngine,
    logsRenderer,
    loraAlpha,
    loraDropout,
    loraRank,
    loraTargetModules,
    maxLen,
    onCancel,
    onPromote,
    onRunDebugPrompt,
    promoteEpsilon,
    promoteIfImproves,
    promoting,
    ragweldBackend,
    ragweldBaseModel,
    ragweldDatasetPath,
    ragweldModelPath,
    selectedRun,
    selectedRunId,
    setBottomTab,
    setDebugPrompt,
    setDefaultPreset,
    setEpochs,
    setGradAccumSteps,
    setInspectorTab,
    setLayoutEngine,
    setLogsRenderer,
    setLoraAlpha,
    setLoraDropout,
    setLoraRank,
    setLoraTargetModules,
    setMaxLen,
    setPromoteEpsilon,
    setPromoteIfImproves,
    setRagweldBackend,
    setRagweldBaseModel,
    setRagweldDatasetPath,
    setRagweldModelPath,
    setShowSetupRow,
    setStudioBottomPct,
    setStudioLeftPct,
    setStudioRightPct,
    setTelemetryIntervalSteps,
    setTrainBatch,
    setTrainLr,
    setVisualizerColorMode,
    setVisualizerMaxPoints,
    setVisualizerMotionIntensity,
    setVisualizerQuality,
    setVisualizerReduceMotion,
    setVisualizerRenderer,
    setVisualizerShowVectorField,
    setVisualizerTailSeconds,
    setVisualizerTargetFps,
    setWarmupRatio,
    showSetupRow,
    studioBottomPct,
    studioLeftPct,
    studioRightPct,
    telemetryIntervalSteps,
    trainBatch,
    trainLr,
    visualizerColorMode,
    visualizerMaxPoints,
    visualizerMotionIntensity,
    visualizerQuality,
    visualizerReduceMotion,
    visualizerRenderer,
    visualizerShowVectorField,
    visualizerTailSeconds,
    visualizerTargetFps,
    warmupRatio,
  ]);

  const renderLogsBody = useCallback(() => {
    if (logsRenderer === 'xterm') {
      return <StudioLogTerminal logs={logEvents} loading={false} onDownload={onDownloadLogs} onClear={onClearLogs} />;
    }
    return (
      <div className="studio-log-viewer" data-testid="studio-log-viewer">
        {logEvents.length === 0 ? <p className="studio-empty">No logs.</p> : <pre className="studio-pre">{JSON.stringify(logEvents, null, 2)}</pre>}
      </div>
    );
  }, [logEvents, logsRenderer]);

  const renderActivityPanel = useCallback(() => {
    return (
      <section className="studio-panel studio-bottom-dock">
        <div className="studio-tab-row">
          <button className="studio-tab-btn" data-active={bottomTab === 'timeline'} onClick={() => setBottomTab('timeline')}>
            Event Timeline
          </button>
          <button className="studio-tab-btn" data-active={bottomTab === 'logs'} onClick={() => setBottomTab('logs')}>
            Logs
          </button>
          <button className="studio-tab-btn" data-active={bottomTab === 'gradient'} onClick={() => setBottomTab('gradient')}>
            Gradient Descent
          </button>
          {bottomTab === 'timeline' ? (
            <input className="studio-search" placeholder="Filter events by type/message" value={eventQuery} onChange={(e) => setEventQuery(e.target.value)} />
          ) : (
            <span className="studio-tab-spacer"></span>
          )}
          <button className="small-button" onClick={onDownloadLogs}>
            Download
          </button>
          <button className="small-button" onClick={onClearLogs}>
            Clear
          </button>
        </div>

        <div className="studio-bottom-body">
          {bottomTab === 'timeline' ? (
            <div className="studio-timeline studio-virtual-scroll" ref={eventsScrollRef} data-testid="studio-event-timeline">
              {filteredEvents.length === 0 ? <p className="studio-empty">No events yet.</p> : null}
              <div className="studio-virtual-rail" ref={eventsRailRef}>
                {eventVirtualItems.map((virtualRow) => {
                  const ev = filteredEvents[virtualRow.index];
                  if (!ev) return null;

                  return (
                    <div
                      key={`${ev.ts}-${virtualRow.index}`}
                      className="studio-virtual-item studio-event-virtual-item"
                      data-role="events-vrow"
                      data-start={Math.floor(virtualRow.start)}
                    >
                      <article className="studio-event-row" data-type={ev.type}>
                        <header className="studio-event-head">
                          <span className="studio-chip">{ev.type}</span>
                          <span className="studio-chip">{safeDateLabel(String(ev.ts))}</span>
                          {ev.step != null ? <span className="studio-chip">step={ev.step}</span> : null}
                          {ev.epoch != null ? <span className="studio-chip">epoch={ev.epoch}</span> : null}
                          {ev.percent != null ? <span className="studio-chip">{ev.percent}%</span> : null}
                        </header>
                        {ev.message ? <p className="studio-event-message">{ev.message}</p> : null}
                        {ev.metrics ? (
                          <div className="studio-mini-grid">
                            {Object.entries(ev.metrics).map(([k, v]) => (
                              <span key={k} className="studio-mono">
                                {k}={formatMetricValue(Number(v))}
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </article>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : bottomTab === 'gradient' ? (
            <div className="studio-gradient-viz" data-testid="studio-gradient-descent-viz">
              <GradientDescentViz events={events} />
            </div>
          ) : (
            renderLogsBody()
          )}
        </div>
      </section>
    );
  }, [bottomTab, eventQuery, eventVirtualItems, events, filteredEvents, renderLogsBody, setBottomTab]);

  const dockRenderers = useMemo<StudioDockRenderers>(
    () => ({
      runs: renderRunsPanel,
      visualizer: renderVisualizerPanel,
      inspector: renderInspectorPanel,
      activity: renderActivityPanel,
    }),
    [renderActivityPanel, renderInspectorPanel, renderRunsPanel, renderVisualizerPanel]
  );

  const renderLegacyPanels = useCallback(() => {
    return (
      <Group orientation="vertical" className="studio-panel-group" onLayoutChanged={onVerticalLayout}>
        <Panel id="top" defaultSize={`${100 - Number(studioBottomPct)}%`} minSize="55%">
          <Group orientation="horizontal" className="studio-panel-group" onLayoutChanged={onTopLayout}>
            <Panel id="left" defaultSize={`${Number(studioLeftPct)}%`} minSize="15%" maxSize="35%" className="studio-left-dock">
              {renderRunsPanel()}
            </Panel>

            <Separator className="studio-resize-handle" />

            <Panel id="center" minSize="25%" className="studio-center-stage">
              {renderVisualizerPanel()}
            </Panel>

            <Separator className="studio-resize-handle" />

            <Panel id="right" defaultSize={`${Number(studioRightPct)}%`} minSize="20%" maxSize="45%" className="studio-right-dock">
              {renderInspectorPanel()}
            </Panel>
          </Group>
        </Panel>

        <Separator className="studio-resize-handle horizontal" />

        <Panel id="bottom" defaultSize={`${Number(studioBottomPct)}%`} minSize="18%" maxSize="45%" className="studio-bottom-dock">
          {renderActivityPanel()}
        </Panel>
      </Group>
    );
  }, [
    onTopLayout,
    onVerticalLayout,
    renderActivityPanel,
    renderInspectorPanel,
    renderRunsPanel,
    renderVisualizerPanel,
    studioBottomPct,
    studioLeftPct,
    studioRightPct,
  ]);

  return (
    <section className="training-studio-root" data-testid="learning-agent-training-studio">
      <header className="training-studio-header">
        <div>
          <h2 className="studio-title">Learning Agent Studio</h2>
          <p className="studio-subtitle">
            Train MLX LoRA adapters for <span className="studio-mono">{String(ragweldBaseModel || '').trim() || 'ragweld'}</span> and promote
            them to <span className="studio-mono">{String(ragweldModelPath || '').trim() || 'training.ragweld_agent_model_path'}</span>.
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

      <div className="studio-command-bar">
        <div className="studio-command-group">
          <button className="small-button" onClick={onCancel} disabled={!selectedRunId || cancelling}>
            {cancelling ? 'Cancelling…' : 'Cancel'}
          </button>
          <button className="small-button" onClick={onPromote} disabled={!selectedRunId || selectedRun?.status !== 'completed' || promoting}>
            {promoting ? 'Promoting…' : 'Promote'}
          </button>
          <button className="small-button" onClick={onDownloadLogs} disabled={!events.length}>
            Export metrics.jsonl
          </button>
          <button className="small-button" onClick={() => resetTelemetry()} disabled={!telemetryCount}>
            Reset telemetry
          </button>
        </div>

        <div className="studio-command-group">
          <button className="small-button" onClick={() => applyLayoutPreset('balanced')}>
            Balanced
          </button>
          <button className="small-button" onClick={() => applyLayoutPreset('focus_viz')}>
            Focus Viz
          </button>
          <button className="small-button" onClick={() => applyLayoutPreset('focus_logs')}>
            Focus Logs
          </button>
          <button className="small-button" onClick={() => applyLayoutPreset('balanced')}>
            Reset View
          </button>
          <button className="small-button" onClick={() => setShowSetupRow(showSetupRow === 1 ? 0 : 1)}>
            {showSetupRow === 1 ? 'Hide Setup' : 'Show Setup'}
          </button>
          <button className="small-button" onClick={() => void popoutPane('studio-visualizer')}>
            Pop Out Viz
          </button>
          <button
            className="small-button"
            onClick={() => {
              setBottomTab('logs');
              void popoutPane('studio-activity');
            }}
          >
            Pop Out Logs
          </button>
        </div>
      </div>

      <div className="studio-hint-row">
        <span className="studio-help-anchor">Preset: {presetLabel(defaultPreset)}</span>
        <span className="studio-help-anchor">Engine: {layoutEngine}</span>
        <span className="studio-help-anchor">Shortcuts: Ctrl/Cmd+Shift+1/2/3 (viz/logs/inspector)</span>
      </div>

      {showSetupRow === 1 ? (
        <div className="studio-run-setup">
          <div className="studio-run-setup-item">
            <span className="studio-label">Corpus</span>
            <span className="studio-value studio-mono">{activeCorpus || '—'}</span>
          </div>
          <div className="studio-run-setup-item">
            <span className="studio-label">Backend</span>
            <span className="studio-value studio-mono">{String(ragweldBackend || '').trim() || '—'}</span>
          </div>
          <div className="studio-run-setup-item">
            <span className="studio-label">Base model</span>
            <span className="studio-value studio-mono studio-truncate" title={String(ragweldBaseModel || '')}>
              {String(ragweldBaseModel || '').trim() || '—'}
            </span>
          </div>
          <div className="studio-run-setup-item">
            <span className="studio-label">Dataset</span>
            <span className="studio-value studio-mono studio-truncate" title={String(ragweldDatasetPath || '')}>
              {String(ragweldDatasetPath || '').trim() || '(uses evaluation.eval_dataset_path)'}
            </span>
          </div>
        </div>
      ) : null}

      <div className="studio-workspace" data-layout-engine={layoutEngine}>
        {layoutEngine === 'dockview' ? (
          <StudioDockRendererContext.Provider value={dockRenderers}>
            <DockviewReact
              className="studio-dockview dockview-theme-abyss"
              components={DOCK_COMPONENTS}
              onReady={onDockReady}
              disableFloatingGroups={false}
              popoutUrl="/web/"
            />
          </StudioDockRendererContext.Provider>
        ) : (
          renderLegacyPanels()
        )}
      </div>
    </section>
  );
}
