import { useEffect, useMemo, useRef, useState } from 'react';
import { useNotification } from '@/hooks';
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
    if (ev.type === 'metrics' && ev.metrics) return ev.metrics;
  }
  return null;
}

export function TrainingStudio() {
  const { success, error: notifyError, info } = useNotification();
  const activeCorpus = useActiveRepo();

  const config = useConfigStore((s) => s.config);
  const loadConfig = useConfigStore((s) => s.loadConfig);

  const topn = config?.reranking?.tribrid_reranker_topn ?? 10;

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
            <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 4 }}>Recommended metric</div>
            {profileLoading ? (
              <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Loading…</div>
            ) : profileError ? (
              <div style={{ fontSize: 12, color: 'var(--err)' }}>{profileError}</div>
            ) : recommended ? (
              <div style={{ fontSize: 13 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{recommended}</span>{' '}
                {profile?.rationale ? (
                  <span
                    title={profile.rationale}
                    style={{ marginLeft: 8, fontSize: 12, color: 'var(--fg-muted)', cursor: 'help', textDecoration: 'underline' }}
                  >
                    Why?
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
                  <label>Primary metric override</label>
                  <select value={primaryMetricOverride} onChange={(e) => setPrimaryMetricOverride(e.target.value)}>
                    <option value="">Auto (use profile)</option>
                    <option value="mrr">mrr</option>
                    <option value="ndcg">ndcg</option>
                    <option value="map">map</option>
                  </select>
                </div>
                <div className="input-group">
                  <label>Primary k override</label>
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
          <RunOverview run={selectedRun} latestMetrics={latestMetrics} />
          <RunDiff runs={runs} />
        </div>
      </div>
    </div>
  );
}

