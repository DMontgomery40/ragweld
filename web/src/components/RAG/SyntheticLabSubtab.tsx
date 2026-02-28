import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useNotification } from '@/hooks';
import { useActiveRepo } from '@/stores';
import { configApi } from '@/api/config';
import { ModelPicker } from '@/components/RAG/ModelPicker';
import { syntheticService } from '@/services/SyntheticService';
import type {
  SyntheticArtifactRef,
  SyntheticConfigPatchResponse,
  SyntheticRun,
  SyntheticRunEvent,
  SyntheticRunMeta,
  SyntheticRunStartRequest,
} from '@/types/generated';

type SyntheticArtifactKind = SyntheticArtifactRef['kind'];
type SyntheticProvider = NonNullable<SyntheticRunStartRequest['provider']>;
type SyntheticRecipeKind = NonNullable<SyntheticRunStartRequest['recipe']>;

const PROVIDERS: SyntheticProvider[] = ['internal_ragweld', 'synthetic_data_kit'];
const RECIPES: SyntheticRecipeKind[] = [
  'eval_dataset',
  'semantic_cards',
  'triplets',
  'keywords',
  'autotune_retrieval',
  'full_stack',
];

function labelForKind(kind: SyntheticArtifactKind): string {
  if (kind === 'eval_dataset_json') return 'Eval Dataset';
  if (kind === 'semantic_cards_jsonl') return 'Semantic Summaries';
  if (kind === 'keywords_json') return 'Keywords';
  if (kind === 'triplets_jsonl') return 'Triplets';
  if (kind === 'config_patch_json') return 'Config Patch';
  if (kind === 'quality_eval_json') return 'Quality Eval';
  if (kind === 'report_md') return 'Run Report';
  return kind;
}

function isQualityGatedArtifact(kind: SyntheticArtifactKind): boolean {
  return kind === 'eval_dataset_json' || kind === 'triplets_jsonl';
}

function publishBlockReason(kind: SyntheticArtifactKind, run: SyntheticRun | null): string | null {
  if (!run) return 'Select a run to publish.';
  if (!isQualityGatedArtifact(kind)) return null;

  const passed = run.summary?.quality_gate_passed;
  if (passed === true) return null;
  if (passed === false) {
    const reason = String(run.summary?.quality_failure_reason || '').trim();
    return reason || 'Publish blocked by quality gate.';
  }
  return 'Quality gate has not completed yet.';
}

export function SyntheticLabSubtab() {
  const activeRepo = useActiveRepo();
  const location = useLocation();
  const { success, error: notifyError, info } = useNotification();

  const [provider, setProvider] = useState<SyntheticProvider>('internal_ragweld');
  const [recipe, setRecipe] = useState<SyntheticRecipeKind>('eval_dataset');
  const [generatorModel, setGeneratorModel] = useState('');
  const [judgeModel, setJudgeModel] = useState('');
  const [maxSourceChunks, setMaxSourceChunks] = useState(150);
  const [maxPairs, setMaxPairs] = useState(150);
  const [pairsPerSource, setPairsPerSource] = useState(1);
  const [curateThreshold, setCurateThreshold] = useState(7.0);
  const [starting, setStarting] = useState(false);

  const [runs, setRuns] = useState<SyntheticRunMeta[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [selectedRun, setSelectedRun] = useState<SyntheticRun | null>(null);
  const [events, setEvents] = useState<SyntheticRunEvent[]>([]);
  const [patchPreview, setPatchPreview] = useState<SyntheticConfigPatchResponse | null>(null);
  const [publishing, setPublishing] = useState('');

  const selectedArtifacts = useMemo(() => selectedRun?.artifacts || [], [selectedRun]);

  useEffect(() => {
    const qs = new URLSearchParams(location.search || '');
    const recipeParam = String(qs.get('synthetic_recipe') || '').trim() as SyntheticRecipeKind;
    if (recipeParam && RECIPES.includes(recipeParam)) {
      setRecipe(recipeParam);
    }
  }, [location.search]);

  useEffect(() => {
    const gm = String(localStorage.getItem('synthetic.generator_model') || '').trim();
    const jm = String(localStorage.getItem('synthetic.judge_model') || '').trim();
    if (gm) setGeneratorModel(gm);
    if (jm) setJudgeModel(jm);
  }, []);

  const loadRuns = useCallback(async () => {
    const corpusId = String(activeRepo || '').trim();
    if (!corpusId) {
      setRuns([]);
      setSelectedRun(null);
      return;
    }
    setLoadingRuns(true);
    try {
      const data = await syntheticService.listRuns(corpusId, 50);
      setRuns(data.runs || []);
      if (!selectedRunId && data.runs?.length) {
        setSelectedRunId(data.runs[0].run_id);
      }
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Failed to load synthetic runs');
    } finally {
      setLoadingRuns(false);
    }
  }, [activeRepo, notifyError, selectedRunId]);

  const loadRunDetail = useCallback(
    async (runId: string) => {
      if (!runId) {
        setSelectedRun(null);
        setEvents([]);
        return;
      }
      try {
        const run = await syntheticService.getRun(runId);
        setSelectedRun(run);
      } catch (e) {
        notifyError(e instanceof Error ? e.message : 'Failed to load synthetic run');
      }
    },
    [notifyError]
  );

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    void loadRunDetail(selectedRunId);
    setPatchPreview(null);
    if (!selectedRunId) return;
    setEvents([]);
    const stop = syntheticService.streamRun(
      selectedRunId,
      (ev) => {
        setEvents((prev) => [...prev, ev]);
        if (ev.type === 'complete') {
          void loadRuns();
          void loadRunDetail(selectedRunId);
        }
      },
      {
        onError: () => {
          // no-op: transient stream failures are expected.
        },
      }
    );
    return stop;
  }, [loadRunDetail, loadRuns, selectedRunId]);

  const startRun = useCallback(
    async (forcedRecipe?: SyntheticRecipeKind) => {
      const corpusId = String(activeRepo || '').trim();
      if (!corpusId) {
        notifyError('Select a corpus first.');
        return;
      }
      const gm = String(generatorModel || '').trim();
      const jm = String(judgeModel || '').trim();
      if (!gm || !jm) {
        notifyError('Select both generator and judge models.');
        return;
      }

      setStarting(true);
      try {
        const payload: SyntheticRunStartRequest = {
          corpus_id: corpusId,
          provider,
          recipe: forcedRecipe || recipe,
          max_source_chunks: maxSourceChunks,
          max_pairs: maxPairs,
          pairs_per_source: pairsPerSource,
          curate_enabled: true,
          curate_threshold: curateThreshold,
          include_expected_answer: true,
          include_tags: true,
          seed: 1337,
          generator_model: gm,
          judge_model: jm,
        };
        const run = await syntheticService.startRun(payload);
        localStorage.setItem('synthetic.generator_model', gm);
        localStorage.setItem('synthetic.judge_model', jm);
        info(`Synthetic run started: ${run.run_id}`);
        setSelectedRunId(run.run_id);
        void loadRuns();
      } catch (e) {
        notifyError(e instanceof Error ? e.message : 'Failed to start synthetic run');
      } finally {
        setStarting(false);
      }
    },
    [
      activeRepo,
      curateThreshold,
      generatorModel,
      info,
      judgeModel,
      loadRuns,
      maxPairs,
      maxSourceChunks,
      notifyError,
      pairsPerSource,
      provider,
      recipe,
    ]
  );

  const runPublish = useCallback(
    async (kind: SyntheticArtifactKind) => {
      if (!selectedRunId) return;
      const blockedReason = publishBlockReason(kind, selectedRun);
      if (blockedReason) {
        notifyError(blockedReason);
        return;
      }
      setPublishing(kind);
      try {
        if (kind === 'eval_dataset_json') {
          const resp = await syntheticService.publishEvalDataset(selectedRunId);
          success(resp.message || 'Published eval dataset.');
        } else if (kind === 'semantic_cards_jsonl') {
          const resp = await syntheticService.publishSemanticCards(selectedRunId);
          success(resp.message || 'Published semantic summaries.');
        } else if (kind === 'keywords_json') {
          const resp = await syntheticService.publishKeywords(selectedRunId);
          success(resp.message || 'Published keywords.');
        } else if (kind === 'triplets_jsonl') {
          const resp = await syntheticService.publishTriplets(selectedRunId);
          success(resp.message || 'Published triplets.');
        } else if (kind === 'config_patch_json') {
          const resp = await syntheticService.publishConfigPatch(selectedRunId);
          setPatchPreview(resp);
          info('Config patch preview loaded.');
        }
      } catch (e) {
        notifyError(e instanceof Error ? e.message : 'Publish failed');
      } finally {
        setPublishing('');
      }
    },
    [info, notifyError, selectedRun, selectedRunId, success]
  );

  const applyPatch = useCallback(async () => {
    const corpusId = String(activeRepo || '').trim();
    if (!patchPreview || !corpusId) return;
    try {
      const patch = patchPreview.patch || {};
      for (const [section, updates] of Object.entries(patch)) {
        if (!updates || typeof updates !== 'object') continue;
        await configApi.patchSection(section, updates as Record<string, unknown>, corpusId);
      }
      success('Config patch applied.');
    } catch (e) {
      notifyError(e instanceof Error ? e.message : 'Failed to apply patch');
    }
  }, [activeRepo, notifyError, patchPreview, success]);

  const modelSelectionMissing =
    !String(generatorModel || '').trim() ||
    !String(judgeModel || '').trim();

  const startDisabled =
    starting ||
    !String(activeRepo || '').trim() ||
    modelSelectionMissing;

  return (
    <div className="subtab-panel" style={{ padding: '24px' }} data-testid="synthetic-lab-subtab">
      <div style={{ marginBottom: 18 }}>
        <h3 style={{ fontSize: 18, fontWeight: 600, color: 'var(--fg)', marginBottom: 6 }}>Synthetic Lab</h3>
        <div style={{ fontSize: 13, color: 'var(--fg-muted)' }}>
          Generate synthetic artifacts, evaluate quality gates, and publish to active corpus stores.
        </div>
      </div>

      <section style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 14, marginBottom: 16, background: 'var(--bg-elev1)' }}>
        <div style={{ fontWeight: 600, marginBottom: 10 }}>Recipe Builder</div>
        <div className="input-row">
          <div className="input-group">
            <label>Provider</label>
            <select value={provider} onChange={(e) => setProvider(e.target.value as SyntheticProvider)}>
              {PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div className="input-group">
            <label>Recipe</label>
            <select value={recipe} onChange={(e) => setRecipe(e.target.value as SyntheticRecipeKind)}>
              {RECIPES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="input-row">
          <div style={{ flex: 1 }}>
            <ModelPicker
              componentType="GEN"
              value={generatorModel}
              onChange={setGeneratorModel}
              label="Generator Model"
              allowCustom
            />
          </div>
          <div style={{ flex: 1 }}>
            <ModelPicker
              componentType="GEN"
              value={judgeModel}
              onChange={setJudgeModel}
              label="Judge Model"
              allowCustom
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>Max source chunks</label>
            <input
              type="number"
              min={10}
              max={20000}
              value={maxSourceChunks}
              onChange={(e) => setMaxSourceChunks(parseInt(e.target.value || '150', 10))}
            />
          </div>
          <div className="input-group">
            <label>Max pairs</label>
            <input type="number" min={10} max={50000} value={maxPairs} onChange={(e) => setMaxPairs(parseInt(e.target.value || '150', 10))} />
          </div>
          <div className="input-group">
            <label>Pairs per source</label>
            <input
              type="number"
              min={1}
              max={20}
              value={pairsPerSource}
              onChange={(e) => setPairsPerSource(parseInt(e.target.value || '1', 10))}
            />
          </div>
          <div className="input-group">
            <label>Curate threshold</label>
            <input
              type="number"
              min={0}
              max={10}
              step={0.1}
              value={curateThreshold}
              onChange={(e) => setCurateThreshold(parseFloat(e.target.value || '7'))}
            />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="small-button" disabled={startDisabled} onClick={() => void startRun()}>
            {starting ? 'Starting...' : 'Start Run'}
          </button>
          <button className="small-button" disabled={startDisabled} onClick={() => void startRun('full_stack')}>
            {starting ? 'Starting...' : 'Start Full Stack'}
          </button>
        </div>
        {modelSelectionMissing ? (
          <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginTop: 8 }}>
            Select both generator and judge models to enable start actions.
          </div>
        ) : null}
      </section>

      <section style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 14, marginBottom: 16, background: 'var(--bg-elev1)' }}>
        <div style={{ fontWeight: 600, marginBottom: 10 }}>Runs</div>
        {loadingRuns ? <div style={{ color: 'var(--fg-muted)' }}>Loading runs...</div> : null}
        {!loadingRuns && runs.length === 0 ? <div style={{ color: 'var(--fg-muted)' }}>No synthetic runs yet.</div> : null}
        {runs.length > 0 ? (
          <div style={{ overflowX: 'auto' }}>
            <table className="studio-table" style={{ width: '100%' }}>
              <thead>
                <tr>
                  <th>run_id</th>
                  <th>status</th>
                  <th>recipe</th>
                  <th>items</th>
                  <th>started_at</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr
                    key={r.run_id}
                    style={{ cursor: 'pointer', background: selectedRunId === r.run_id ? 'rgba(var(--accent-rgb), 0.08)' : 'transparent' }}
                    onClick={() => setSelectedRunId(r.run_id)}
                  >
                    <td className="studio-mono">{r.run_id}</td>
                    <td>{r.status}</td>
                    <td>{r.recipe}</td>
                    <td>{r.items_generated ?? 0}</td>
                    <td>{new Date(r.started_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 14, background: 'var(--bg-elev1)' }}>
        <div style={{ fontWeight: 600, marginBottom: 10 }}>Artifacts + Publish</div>
        {!selectedRun ? (
          <div style={{ color: 'var(--fg-muted)' }}>Select a run to inspect artifacts.</div>
        ) : (
          <>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
              <span className="studio-mono">run={selectedRun.run_id}</span>
              <span className="studio-mono">status={selectedRun.status}</span>
            </div>

            <div className="studio-callout" style={{ marginBottom: 10 }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Quality Gate</div>
              <div className="studio-mono">
                threshold={selectedRun.summary?.quality_gate_threshold ?? 0.4} top1={selectedRun.summary?.quality_top1_accuracy ?? 'n/a'} topk={selectedRun.summary?.quality_topk_accuracy ?? 'n/a'} mrr={selectedRun.summary?.quality_mrr ?? 'n/a'}
              </div>
              {selectedRun.summary?.quality_gate_passed === false ? (
                <div style={{ color: 'var(--err)', marginTop: 6 }}>
                  blocked: {selectedRun.summary?.quality_failure_reason || 'quality gate failed'}
                </div>
              ) : selectedRun.summary?.quality_gate_passed === true ? (
                <div style={{ color: 'var(--ok)', marginTop: 6 }}>passed</div>
              ) : (
                <div style={{ color: 'var(--fg-muted)', marginTop: 6 }}>not evaluated</div>
              )}
            </div>

            <div style={{ marginBottom: 10 }}>
              {(selectedArtifacts || []).map((a) => (
                <div key={`${a.kind}:${a.path}`} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                  <span style={{ minWidth: 180 }}>{labelForKind(a.kind)}</span>
                  <span className="studio-mono" title={a.path} style={{ opacity: 0.75, maxWidth: 520, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {a.path}
                  </span>
                  {a.kind !== 'report_md'
                    ? (() => {
                        const blockedReason = publishBlockReason(a.kind, selectedRun);
                        const isBlocked = Boolean(blockedReason);
                        const isPublishing = publishing === a.kind;
                        const blockedByFailure =
                          isQualityGatedArtifact(a.kind) && selectedRun?.summary?.quality_gate_passed === false;
                        return (
                          <>
                            <button
                              className="small-button"
                              title={blockedReason || `Publish ${labelForKind(a.kind)}`}
                              disabled={isPublishing || isBlocked}
                              onClick={() => void runPublish(a.kind)}
                            >
                              {isPublishing ? 'Publishing...' : isBlocked ? 'Blocked' : 'Publish'}
                            </button>
                            {isBlocked && !isPublishing ? (
                              <span style={{ fontSize: 12, color: blockedByFailure ? 'var(--err)' : 'var(--fg-muted)' }}>
                                {blockedReason}
                              </span>
                            ) : null}
                          </>
                        );
                      })()
                    : null}
                </div>
              ))}
            </div>
            {patchPreview ? (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>Config patch preview</div>
                <pre style={{ maxHeight: 280, overflow: 'auto', background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: 8, padding: 10 }}>
                  {JSON.stringify(patchPreview.patch || {}, null, 2)}
                </pre>
                <button className="small-button" onClick={() => void applyPatch()}>
                  Apply Suggested Config Patch
                </button>
              </div>
            ) : null}
            {events.length > 0 ? (
              <details style={{ marginTop: 12 }}>
                <summary>Live events ({events.length})</summary>
                <pre style={{ maxHeight: 220, overflow: 'auto', background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: 8, padding: 10 }}>
                  {events
                    .slice(-60)
                    .map((e) => `${e.ts} ${e.type}${e.message ? ` ${e.message}` : ''}`)
                    .join('\n')}
                </pre>
              </details>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}
