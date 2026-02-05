import { useEffect, useMemo, useRef, useState } from 'react';
import { useNotification } from '@/hooks';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { useConfigStore } from '@/stores/useConfigStore';
import { useActiveRepo } from '@/stores/useRepoStore';
import { rerankerTrainingService, type RerankerTrainRunsScope } from '@/services/RerankerTrainingService';
import type {
  CorpusEvalProfile,
  RerankerTrainMetricEvent,
  RerankerTrainRun,
  RerankerTrainRunMeta,
  RerankerTrainStartRequest,
} from '@/types/generated';
import { GradientDescentViz } from './GradientDescentViz';
import { RunDiff } from './RunDiff';
import { RunOverview } from './RunOverview';

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
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i];
    if (ev.metrics) return ev.metrics;
  }
  return null;
}

function formatMetricValue(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  if (v === 0) return '0.0000';
  if (Math.abs(v) < 1) return v.toFixed(4);
  return v.toFixed(3);
}

function lastEventMeta(events: RerankerTrainMetricEvent[]): { ts?: string; step?: number; epoch?: number; percent?: number } {
  for (let i = events.length - 1; i >= 0; i--) {
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

  const topn = config?.reranking?.tribrid_reranker_topn ?? 50;

  const [scope, setScope] = useState<RerankerTrainRunsScope>('corpus');

  const [profile, setProfile] = useState<CorpusEvalProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  const [runs, setRuns] = useState<RerankerTrainRunMeta[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);

  const [selectedRunId, setSelectedRunId] = useState<string>('');
  const [selectedRun, setSelectedRun] = useState<RerankerTrainRun | null>(null);
  const [events, setEvents] = useState<RerankerTrainMetricEvent[]>([]);
  const [latestMetrics, setLatestMetrics] = useState<Record<string, number> | null>(null);
  const [promoting, setPromoting] = useState(false);
  const [eventQuery, setEventQuery] = useState('');

  const [primaryMetricOverride, setPrimaryMetricOverride] = useState<string>(''); // '' = auto
  const [primaryKOverride, setPrimaryKOverride] = useState<string>(''); // '' = auto

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

  // Ensure config is loaded (needed to clamp k options)
  useEffect(() => {
    if (!config) void loadConfig();
  }, [config, loadConfig]);

  // Load profile for active corpus
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

  // Load runs
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

  // Selected run details + SSE
  const closeSseRef = useRef<null | (() => void)>(null);
  useEffect(() => {
    if (!selectedRunId) {
      setSelectedRun(null);
      setEvents([]);
      setLatestMetrics(null);
      return;
    }

    closeSseRef.current?.();
    closeSseRef.current = null;

    let cancelled = false;
    void Promise.all([
      rerankerTrainingService.getRun(selectedRunId),
      rerankerTrainingService.getMetrics(selectedRunId, 500),
    ])
      .then(([run, metricsRes]) => {
        if (cancelled) return;
        const evs = metricsRes.events || [];
        setSelectedRun(run);
        setEvents(evs);
        setLatestMetrics(latestMetricsFromEvents(evs));
      })
      .catch(() => {
        if (cancelled) return;
        setSelectedRun(null);
        setEvents([]);
        setLatestMetrics(null);
      });

    // Stream updates (best-effort)
    closeSseRef.current = rerankerTrainingService.streamRun(
      selectedRunId,
      (ev) => {
        setEvents((prev) => {
          const next = [...prev, ev].slice(-2000);
          setLatestMetrics(latestMetricsFromEvents(next));
          return next;
        });

        // Keep run status in sync without requiring a manual refresh/reload.
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
        onError: (msg) => {
          notifyError(msg);
        },
      }
    );

    return () => {
      cancelled = true;
      closeSseRef.current?.();
      closeSseRef.current = null;
    };
  }, [selectedRunId, notifyError]);

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
    const modelPath = String(snap?.training?.tribrid_reranker_model_path ?? '');

    const started = new Date(run.started_at);
    const done = run.completed_at ? new Date(run.completed_at) : null;
    const now = new Date();
    const durMs =
      Number.isFinite(started.getTime()) && (done ? Number.isFinite(done.getTime()) : true)
        ? (done ? done.getTime() : now.getTime()) - started.getTime()
        : null;
    const durSec = durMs == null ? null : Math.max(0, durMs / 1000);

    const last = lastEventMeta(events);
    return {
      backend: backend || '—',
      baseModel: baseModel || '—',
      modelPath: modelPath || '—',
      durationSec: durSec,
      last,
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

  const onStart = async () => {
    if (!activeCorpus) return;
    try {
      info('Starting training run…');

      const payload: RerankerTrainStartRequest = { corpus_id: activeCorpus };
      if (primaryMetricOverride) payload.primary_metric = primaryMetricOverride as any;
      if (primaryKOverride) payload.primary_k = Number(primaryKOverride);

      const res = await rerankerTrainingService.startRun(payload);
      success(`Run started: ${res.run_id}`);

      // Refresh list + select new run
      const list = await rerankerTrainingService.listRuns(activeCorpus, scope, 50);
      setRuns(list.runs || []);
      setSelectedRunId(res.run_id);
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

  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
        <div>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Training Studio</div>
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
            North Star metric is chosen once at run start and persisted.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Scope</div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              className="small-button"
              onClick={() => setScope('corpus')}
              style={{
                background: scope === 'corpus' ? 'var(--accent)' : 'var(--bg-elev2)',
                color: scope === 'corpus' ? 'var(--accent-contrast)' : 'var(--fg)',
              }}
            >
              This corpus
            </button>
            <button
              className="small-button"
              onClick={() => setScope('all')}
              style={{
                background: scope === 'all' ? 'var(--accent)' : 'var(--bg-elev2)',
                color: scope === 'all' ? 'var(--accent-contrast)' : 'var(--fg)',
              }}
            >
              All
            </button>
          </div>
        </div>
      </div>

      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 14,
          marginTop: 12,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 4 }}>Active corpus</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>{activeCorpus || '—'}</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 4 }}>
              Recommended metric <TooltipIcon name="RERANKER_TRAIN_RECOMMENDED_METRIC" />
            </div>
            {profileLoading ? (
              <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Loading…</div>
            ) : profileError ? (
              <div style={{ fontSize: 12, color: 'var(--err)' }}>{profileError}</div>
            ) : recommended ? (
              <div style={{ fontSize: 13 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{recommended}</span>{' '}
                {profile?.rationale ? (
                  <span style={{ marginLeft: 8, fontSize: 12, color: 'var(--fg-muted)' }}>
                    <span title={profile.rationale} style={{ cursor: 'help', textDecoration: 'underline' }}>
                      Why
                    </span>
                    <TooltipIcon name="RERANKER_TRAIN_RECOMMENDED_METRIC" />
                  </span>
                ) : null}
              </div>
            ) : (
              <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>—</div>
            )}
          </div>
        </div>

        <div style={{ marginTop: 12 }}>
          <details>
            <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Advanced</summary>
            <div style={{ marginTop: 12 }}>
              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div className="input-group">
                  <label>
                    Primary metric override <TooltipIcon name="RERANKER_TRAIN_PRIMARY_METRIC_OVERRIDE" />
                  </label>
                  <select value={primaryMetricOverride} onChange={(e) => setPrimaryMetricOverride(e.target.value)}>
                    <option value="">Auto (use profile)</option>
                    <option value="mrr">mrr</option>
                    <option value="ndcg">ndcg</option>
                    <option value="map">map</option>
                  </select>
                </div>
                <div className="input-group">
                  <label>
                    Primary k override <TooltipIcon name="RERANKER_TRAIN_PRIMARY_K_OVERRIDE" />
                  </label>
                  <select value={primaryKOverride} onChange={(e) => setPrimaryKOverride(e.target.value)}>
                    <option value="">Auto (use profile)</option>
                    {kOptions.map((k) => (
                      <option key={k} value={String(k)}>
                        {k}
                      </option>
                    ))}
                  </select>
                  <div style={{ marginTop: 6, fontSize: 12, color: 'var(--fg-muted)' }}>
                    Options are clamped to ≤ <span style={{ fontFamily: 'var(--font-mono)' }}>{String(topn)}</span>.
                  </div>
                </div>
              </div>

              <div style={{ marginTop: 12, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <button className="small-button" onClick={onStart} disabled={!activeCorpus}>
                  Start run
                </button>
              </div>
            </div>
          </details>
        </div>
      </div>

      <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'minmax(280px, 420px) 1fr', gap: 12 }}>
        <div
          style={{
            background: 'var(--bg-elev1)',
            border: '1px solid var(--line)',
            borderRadius: 10,
            padding: 14,
            maxHeight: 520,
            overflow: 'auto',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10 }}>
            <div style={{ fontWeight: 600 }}>Runs</div>
            <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>{runsLoading ? 'Loading…' : `${runs.length}`}</div>
          </div>
          {runsError && <div style={{ marginTop: 8, fontSize: 12, color: 'var(--err)' }}>{runsError}</div>}

          {!runsLoading && runs.length === 0 ? (
            <div style={{ marginTop: 10, fontSize: 12, color: 'var(--fg-muted)' }}>No runs yet.</div>
          ) : (
            <div style={{ marginTop: 10 }}>
              {Object.entries(groupedRuns).map(([corpusId, items]) => (
                <div key={corpusId || 'unknown'} style={{ marginBottom: 12 }}>
                  {scope === 'all' ? (
                    <div style={{ marginBottom: 6, fontSize: 12, color: 'var(--fg-muted)' }}>
                      <span
                        style={{
                          display: 'inline-block',
                          padding: '2px 8px',
                          borderRadius: 999,
                          border: '1px solid var(--line)',
                          background: 'var(--bg-elev2)',
                          fontFamily: 'var(--font-mono)',
                        }}
                      >
                        {corpusId || '—'}
                      </span>
                    </div>
                  ) : null}

                  <div style={{ display: 'grid', gap: 8 }}>
                    {items.map((r) => {
                      const isSelected = r.run_id === selectedRunId;
                      const label = metricLabel(r.primary_metric, Number(r.primary_k));
                      return (
                        <button
                          key={r.run_id}
                          onClick={() => setSelectedRunId(r.run_id)}
                          style={{
                            textAlign: 'left',
                            borderRadius: 10,
                            border: isSelected ? '2px solid var(--accent)' : '1px solid var(--line)',
                            background: isSelected ? 'rgba(var(--accent-rgb), 0.08)' : 'var(--bg-elev2)',
                            color: 'var(--fg)',
                            padding: 10,
                            cursor: 'pointer',
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{r.run_id}</div>
                            {scope === 'all' ? (
                              <div style={{ fontSize: 11, color: 'var(--fg-muted)' }}>{r.corpus_id}</div>
                            ) : null}
                          </div>
                          <div style={{ marginTop: 4, fontSize: 12, color: 'var(--fg-muted)' }}>
                            {safeDateLabel(r.started_at)} · {r.status} ·{' '}
                            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--fg)' }}>{label}</span>
                          </div>
                          <div style={{ marginTop: 4, fontSize: 12, color: 'var(--fg-muted)' }}>
                            best={r.primary_metric_best ?? '—'} · final={r.primary_metric_final ?? '—'}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ display: 'grid', gap: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
            Events buffered: <span style={{ fontFamily: 'var(--font-mono)' }}>{events.length}</span>
          </div>

          <div
            style={{
              background: 'var(--bg-elev1)',
              border: '1px solid var(--line)',
              borderRadius: 10,
              padding: 14,
            }}
          >
            <GradientDescentViz events={events} />
          </div>

          <div
            style={{
              background: 'var(--bg-elev1)',
              border: '1px solid var(--line)',
              borderRadius: 10,
              padding: 14,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>Run HUD</div>
                <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
                  {selectedRun ? (
                    <>
                      status=<span style={{ fontFamily: 'var(--font-mono)' }}>{selectedRun.status}</span>
                      {hud?.last?.step != null ? (
                        <>
                          {' '}
                          · step=<span style={{ fontFamily: 'var(--font-mono)' }}>{hud.last.step}</span>
                        </>
                      ) : null}
                      {hud?.last?.epoch != null ? (
                        <>
                          {' '}
                          · epoch=<span style={{ fontFamily: 'var(--font-mono)' }}>{hud.last.epoch}</span>
                        </>
                      ) : null}
                      {hud?.last?.percent != null ? (
                        <>
                          {' '}
                          · <span style={{ fontFamily: 'var(--font-mono)' }}>{hud.last.percent.toFixed(1)}%</span>
                        </>
                      ) : null}
                    </>
                  ) : (
                    'Select a run to see details.'
                  )}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button
                  className="small-button"
                  onClick={onPromote}
                  disabled={!selectedRunId || selectedRun?.status !== 'completed' || promoting}
                >
                  {promoting ? 'Promoting…' : 'Promote'}
                </button>
              </div>
            </div>

            {selectedRun ? (
              <div
                style={{
                  marginTop: 10,
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                  gap: 10,
                }}
              >
                <div
                  style={{
                    border: '1px solid var(--line)',
                    borderRadius: 10,
                    padding: 10,
                    background: 'var(--bg-elev2)',
                  }}
                >
                  <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Backend</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{hud?.backend ?? '—'}</div>
                </div>
                <div
                  style={{
                    border: '1px solid var(--line)',
                    borderRadius: 10,
                    padding: 10,
                    background: 'var(--bg-elev2)',
                  }}
                >
                  <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Base model</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{hud?.baseModel ?? '—'}</div>
                </div>
                <div
                  style={{
                    border: '1px solid var(--line)',
                    borderRadius: 10,
                    padding: 10,
                    background: 'var(--bg-elev2)',
                  }}
                >
                  <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Active artifact path</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{hud?.modelPath ?? '—'}</div>
                </div>
                <div
                  style={{
                    border: '1px solid var(--line)',
                    borderRadius: 10,
                    padding: 10,
                    background: 'var(--bg-elev2)',
                  }}
                >
                  <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Wall clock</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                    {hud?.durationSec == null ? '—' : `${hud.durationSec.toFixed(hud.durationSec < 10 ? 2 : 1)}s`}
                  </div>
                </div>
              </div>
            ) : null}
          </div>

          <div
            style={{
              background: 'var(--bg-elev1)',
              border: '1px solid var(--line)',
              borderRadius: 10,
              padding: 14,
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 8 }}>Live metrics (latest)</div>
            {!latestMetrics ? (
              <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>No metrics yet.</div>
            ) : (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                  gap: 10,
                }}
              >
                {[
                  'train_loss',
                  'eval_loss',
                  'lr',
                  'grad_norm',
                  'update_norm',
                  'tokens_per_sec',
                  'examples_per_sec',
                  'batch_time_ms',
                  'step_time_ms',
                  'mem_rss_mb',
                  'mlx_mem_mb',
                  'logit_margin_mean',
                  'nan_count',
                ].map((key) => (
                  <div
                    key={key}
                    style={{
                      border: '1px solid var(--line)',
                      borderRadius: 10,
                      padding: 10,
                      background: 'var(--bg-elev2)',
                    }}
                  >
                    <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>{key}</div>
                    <div style={{ fontSize: 15, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                      {latestMetrics[key] == null ? '—' : formatMetricValue(Number(latestMetrics[key]))}
                    </div>
                  </div>
                ))}
              </div>
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
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline' }}>
              <div style={{ fontWeight: 600 }}>Event timeline</div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="text"
                  value={eventQuery}
                  onChange={(e) => setEventQuery(e.target.value)}
                  placeholder="Filter…"
                  style={{
                    width: 180,
                    padding: '6px 8px',
                    borderRadius: 8,
                    border: '1px solid var(--line)',
                    background: 'var(--bg-elev2)',
                    color: 'var(--fg)',
                    fontSize: 12,
                  }}
                />
                <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
                  {filteredEvents.length}/{events.length}
                </div>
              </div>
            </div>
            <div style={{ marginTop: 10, maxHeight: 260, overflow: 'auto' }}>
              {filteredEvents.length === 0 ? (
                <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>No events.</div>
              ) : (
                <div style={{ display: 'grid', gap: 8 }}>
                  {filteredEvents
                    .slice(-400)
                    .reverse()
                    .map((ev, idx) => (
                      <div
                        key={`${ev.ts}-${idx}`}
                        style={{
                          border: '1px solid var(--line)',
                          borderRadius: 10,
                          padding: 10,
                          background: 'var(--bg-elev2)',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
                          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-muted)' }}>
                            {safeDateLabel(ev.ts)} · {ev.type}
                          </div>
                          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-muted)' }}>
                            {ev.step != null ? `step=${ev.step}` : ''} {ev.epoch != null ? `epoch=${ev.epoch}` : ''}
                          </div>
                        </div>
                        {ev.message ? (
                          <div style={{ marginTop: 6, fontSize: 12, color: 'var(--fg)' }}>{ev.message}</div>
                        ) : null}
                      </div>
                    ))}
                </div>
              )}
            </div>
          </div>

          <RunOverview run={selectedRun} latestMetrics={latestMetrics} />
          <RunDiff runs={runs} />
        </div>
      </div>
    </div>
  );
}
