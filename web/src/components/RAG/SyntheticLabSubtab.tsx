import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useNotification } from '@/hooks';
import { api, apiClient, withCorpusScope } from '@/api/client';
import { LineageMeta } from '@/components/ui/LineageMeta';
import { NumberField } from '@/components/ui/NumberField';
import { useActiveRepo } from '@/stores';
import { configApi } from '@/api/config';
import { describeSyntheticFailure, syntheticService } from '@/services/SyntheticService';
import type {
  ChatModelInfo,
  ChatModelsResponse,
  SyntheticArtifactRef,
  SyntheticConfigPatchResponse,
  SyntheticRun,
  SyntheticRunEvent,
  SyntheticRunMeta,
  SyntheticUnreadableRun,
  SyntheticRunStartRequest,
} from '@/types/generated';
import { chatModelDetail, chatModelName, groupChatModels } from '@/components/Chat/modelLabel';

type SyntheticArtifactKind = SyntheticArtifactRef['kind'];
type SyntheticProvider = NonNullable<SyntheticRunStartRequest['provider']>;
type SyntheticRecipeKind = NonNullable<SyntheticRunStartRequest['recipe']>;

const PROVIDERS: SyntheticProvider[] = ['grounded_qa'];
const RECIPES: SyntheticRecipeKind[] = [
  'eval_dataset',
  'semantic_cards',
  'triplets',
  'keywords',
  'autotune_retrieval',
  'full_stack',
];

function toModelValue(model: ChatModelInfo): string {
  return String(model.override || model.id || '').trim();
}


function SyntheticModelPicker({
  label,
  value,
  onChange,
  models,
  loading,
  error,
}: {
  label: string;
  value: string;
  onChange: (model: string) => void;
  models: ChatModelInfo[];
  loading: boolean;
  error: string | null;
}) {
  const groupedModels = useMemo(
    () =>
      groupChatModels(models.filter((model) => model.source === 'litellm' && Boolean(toModelValue(model)))).map(
        ({ group, models: items }) => ({ source: group, label: `${group} (${items.length})`, items })
      ),
    [models]
  );

  return (
    <div className="setting-row">
      <label>{label}</label>
      {loading ? (
        <span style={{ color: 'var(--fg-muted)', fontSize: '13px' }}>Loading runnable models...</span>
      ) : error ? (
        <span style={{ color: 'var(--err)', fontSize: '13px' }}>{error}</span>
      ) : (
        <select value={value} onChange={(e) => onChange(e.target.value)} disabled={groupedModels.length === 0}>
          <option value="">Select a model</option>
          {groupedModels.map((group) => (
            <optgroup key={group.source} label={group.label}>
              {group.items.map((model) => {
                const optionValue = toModelValue(model);
                return (
                  <option key={optionValue} value={optionValue} title={chatModelDetail(model)}>
                    {chatModelName(model)}
                  </option>
                );
              })}
            </optgroup>
          ))}
        </select>
      )}
    </div>
  );
}

// A judge score is a 0–10 mean; the raw value carries 15 decimals, which reads as a
// debug leak. Two decimals is the reported precision everywhere it is shown.
function fmtScore(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : 'n/a';
}

async function copyText(value: string, onOk: () => void, onErr: () => void): Promise<void> {
  try {
    await navigator.clipboard.writeText(value);
    onOk();
  } catch {
    onErr();
  }
}

function recipeLabel(recipe: SyntheticRecipeKind): string {
  if (recipe === 'eval_dataset') return 'Eval Dataset';
  if (recipe === 'semantic_cards') return 'Semantic Summaries';
  if (recipe === 'triplets') return 'Triplets';
  if (recipe === 'keywords') return 'Keywords';
  if (recipe === 'autotune_retrieval') return 'Autotune Retrieval';
  if (recipe === 'full_stack') return 'Full Stack';
  return recipe;
}

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

// Mirror of the server gate (`_promotion_block_reason` in server/api/synthetic.py):
// a run is promotable only when it completed. A gated recipe that fails its gate is
// marked failed upstream, so a completed run's gate is passed (True) or absent (None,
// for recipes without a gate) — both promotable; an un-attached run has no target.
function promotionBlockReason(run: SyntheticRun | null): string | null {
  if (!run) return 'Select a run to promote.';
  if (run.status !== 'completed') {
    return `This run is ${run.status}; only a completed run can be promoted. A run that produced nothing and was never evaluated cannot be an alias target.`;
  }
  if (run.summary?.quality_gate_passed === false) {
    const reason = String(run.summary?.quality_failure_reason || '').trim();
    return `Quality gate did not pass; promotion blocked. ${reason}`.trim();
  }
  if (!String(run.bundle_id || '').trim()) {
    return 'This run is not attached to a lineage bundle, so there is nothing to promote.';
  }
  return null;
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
  const { success, error: notifyError, info, notifications, removeNotification } = useNotification();

  const [provider, setProvider] = useState<SyntheticProvider>('grounded_qa');
  const [recipe, setRecipe] = useState<SyntheticRecipeKind>('eval_dataset');
  const [generatorModel, setGeneratorModel] = useState('');
  const [judgeModel, setJudgeModel] = useState('');
  const [maxSourceChunks, setMaxSourceChunks] = useState(150);
  const [maxPairs, setMaxPairs] = useState(150);
  const [pairsPerSource, setPairsPerSource] = useState(1);
  const [curateThreshold, setCurateThreshold] = useState(7.0);
  const [starting, setStarting] = useState(false);
  const [availableModels, setAvailableModels] = useState<ChatModelInfo[]>([]);
  const [loadingAvailableModels, setLoadingAvailableModels] = useState(false);
  const [availableModelsError, setAvailableModelsError] = useState<string | null>(null);

  const [runs, setRuns] = useState<SyntheticRunMeta[]>([]);
  const [unreadableRuns, setUnreadableRuns] = useState<SyntheticUnreadableRun[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [selectedRun, setSelectedRun] = useState<SyntheticRun | null>(null);
  const [events, setEvents] = useState<SyntheticRunEvent[]>([]);
  const [patchPreview, setPatchPreview] = useState<SyntheticConfigPatchResponse | null>(null);
  const [publishing, setPublishing] = useState('');

  const selectedArtifacts = useMemo(() => selectedRun?.artifacts || [], [selectedRun]);

  // Arriving with a preset applied and no sign of it is how an operator ends up starting the
  // most expensive recipe there is without having chosen it.
  const [presetNotice, setPresetNotice] = useState('');

  useEffect(() => {
    const qs = new URLSearchParams(location.search || '');
    const recipeParam = String(qs.get('synthetic_recipe') || '').trim() as SyntheticRecipeKind;
    if (recipeParam && RECIPES.includes(recipeParam)) {
      setRecipe(recipeParam);
      const from = String(qs.get('synthetic_context') || '').trim();
      setPresetNotice(
        `Recipe preset to "${recipeLabel(recipeParam)}"${from ? ` from ${from}` : ''}. Nothing has run — review it and start when you are ready.`
      );
    } else {
      setPresetNotice('');
    }
  }, [location.search]);

  useEffect(() => {
    const gm = String(localStorage.getItem('synthetic.generator_model') || '').trim();
    const jm = String(localStorage.getItem('synthetic.judge_model') || '').trim();
    if (gm) setGeneratorModel(gm);
    if (jm) setJudgeModel(jm);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const corpusId = String(activeRepo || '').trim();

    setLoadingAvailableModels(true);
    setAvailableModelsError(null);

    apiClient
      .get<ChatModelsResponse>(withCorpusScope(api('/chat/models'), corpusId || undefined))
      .then(({ data }) => {
        if (cancelled) return;
        const models = Array.isArray(data?.models)
          ? data.models.filter(
              (model) =>
                Array.isArray(model.components) &&
                model.components.includes('GEN') &&
                model.source === 'litellm'
            )
          : [];
        setAvailableModels(models);
      })
      .catch((err) => {
        if (cancelled) return;
        setAvailableModels([]);
        setAvailableModelsError(err instanceof Error ? err.message : 'Failed to load runnable models');
      })
      .finally(() => {
        if (!cancelled) setLoadingAvailableModels(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeRepo]);

  const availableModelValues = useMemo(() => {
    return new Set(availableModels.map((model) => toModelValue(model)).filter(Boolean));
  }, [availableModels]);

  useEffect(() => {
    if (loadingAvailableModels) return;

    const gm = String(generatorModel || '').trim();
    const jm = String(judgeModel || '').trim();
    const generatorStillAvailable = !gm || availableModelValues.has(gm);
    const judgeStillAvailable = !jm || availableModelValues.has(jm);

    if (!generatorStillAvailable) {
      setGeneratorModel('');
      localStorage.removeItem('synthetic.generator_model');
    }
    if (!judgeStillAvailable) {
      setJudgeModel('');
      localStorage.removeItem('synthetic.judge_model');
    }
  }, [availableModelValues, generatorModel, judgeModel, loadingAvailableModels]);

  const loadRuns = useCallback(async () => {
    const corpusId = String(activeRepo || '').trim();
    if (!corpusId) {
      setRuns([]);
      setUnreadableRuns([]);
      setSelectedRun(null);
      return;
    }
    setLoadingRuns(true);
    try {
      const data = await syntheticService.listRuns(corpusId, 50);
      setRuns(data.runs || []);
      setUnreadableRuns(data.unreadable || []);
      if (!selectedRunId && data.runs?.length) {
        setSelectedRunId(data.runs[0].run_id);
      }
    } catch (e) {
      notifyError(describeSyntheticFailure(e, 'Failed to load synthetic runs'));
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
        notifyError(describeSyntheticFailure(e, 'Failed to load synthetic run'));
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
    setArtifactPreview(null);
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
      if (!availableModelValues.has(gm) || !availableModelValues.has(jm)) {
        notifyError('Selected generator and judge models must be currently available.');
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
        notifyError(describeSyntheticFailure(e, 'Failed to start synthetic run'));
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
      availableModelValues,
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
        notifyError(describeSyntheticFailure(e, 'Publish failed'));
      } finally {
        setPublishing('');
      }
    },
    [info, notifyError, selectedRun, selectedRunId, success]
  );

  // Promotion goes through the gated synthetic endpoint, not the generic lineage
  // alias store: the server refuses a failed or un-evaluated run with a typed 409.
  const promoteRun = useCallback(
    async (alias: string) => {
      if (!selectedRunId) return;
      try {
        await apiClient.post(api(`/synthetic/run/${encodeURIComponent(selectedRunId)}/promote/${encodeURIComponent(alias)}`));
      } catch (e) {
        throw new Error(describeSyntheticFailure(e, `Failed to promote ${alias}`));
      }
    },
    [selectedRunId]
  );

  const [retrying, setRetrying] = useState(false);
  // A failed run is not a dead end: re-launch with the same recipe, models, and
  // parameters the run stored, so the operator does not rebuild the request by hand.
  const retryRun = useCallback(async () => {
    if (!selectedRun) return;
    setRetrying(true);
    try {
      const run = await syntheticService.startRun(selectedRun.request);
      info(`Retry started: ${run.run_id}`);
      setSelectedRunId(run.run_id);
      void loadRuns();
    } catch (e) {
      notifyError(describeSyntheticFailure(e, 'Failed to retry run'));
    } finally {
      setRetrying(false);
    }
  }, [selectedRun, info, loadRuns, notifyError]);

  const [artifactPreview, setArtifactPreview] = useState<{ kind: SyntheticArtifactKind; rows: Record<string, unknown>[] } | null>(null);
  const [previewing, setPreviewing] = useState('');
  // View an artifact through the read-only preview endpoint (bounded rows), so a
  // bare server path becomes something the operator can actually inspect in place.
  const previewArtifact = useCallback(
    async (kind: SyntheticArtifactKind) => {
      if (!selectedRunId) return;
      setPreviewing(kind);
      try {
        const { data } = await apiClient.get<{ rows?: Record<string, unknown>[] }>(
          api(`/synthetic/run/${encodeURIComponent(selectedRunId)}/artifact/preview?kind=${encodeURIComponent(kind)}&limit=20`)
        );
        setArtifactPreview({ kind, rows: Array.isArray(data?.rows) ? data.rows : [] });
      } catch (e) {
        notifyError(describeSyntheticFailure(e, 'Failed to preview artifact'));
      } finally {
        setPreviewing('');
      }
    },
    [selectedRunId, notifyError]
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
      notifyError(describeSyntheticFailure(e, 'Failed to apply patch'));
    }
  }, [activeRepo, notifyError, patchPreview, success]);

  const generatorModelSelected = String(generatorModel || '').trim();
  const judgeModelSelected = String(judgeModel || '').trim();
  const modelSelectionMissing = !generatorModelSelected || !judgeModelSelected;
  const selectionUnavailable =
    Boolean(generatorModelSelected) && !availableModelValues.has(generatorModelSelected) ||
    Boolean(judgeModelSelected) && !availableModelValues.has(judgeModelSelected);

  const startDisabled =
    starting ||
    !String(activeRepo || '').trim() ||
    loadingAvailableModels ||
    availableModels.length === 0 ||
    modelSelectionMissing ||
    selectionUnavailable;

  return (
    <div className="subtab-panel" style={{ padding: '24px' }} data-testid="synthetic-lab-subtab">
      <div className="notification-container" data-testid="synthetic-lab-notifications">
        {notifications.map((notification) => (
          <div key={notification.id} className={`notification notification-${notification.type}`} role="status">
            <span>{notification.message}</span>
            <button onClick={() => removeNotification(notification.id)} aria-label="Dismiss notification">×</button>
          </div>
        ))}
      </div>
      {presetNotice ? (
        <div
          data-testid="synthetic-preset-notice"
          role="status"
          style={{
            marginBottom: 14,
            padding: '10px 12px',
            borderRadius: 8,
            border: '1px solid var(--accent)',
            background: 'rgba(var(--accent-rgb), 0.08)',
            color: 'var(--fg)',
            fontSize: 13,
          }}
        >
          {presetNotice}
        </div>
      ) : null}
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
                  {recipeLabel(r)}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="input-row">
          <div style={{ flex: 1 }}>
            <SyntheticModelPicker
              value={generatorModel}
              onChange={setGeneratorModel}
              label="Generator Model"
              models={availableModels}
              loading={loadingAvailableModels}
              error={availableModelsError}
            />
          </div>
          <div style={{ flex: 1 }}>
            <SyntheticModelPicker
              value={judgeModel}
              onChange={setJudgeModel}
              label="Judge Model"
              models={availableModels}
              loading={loadingAvailableModels}
              error={availableModelsError}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>Max source chunks</label>
            <NumberField
              min={10}
              max={20000}
              value={maxSourceChunks}
              onCommit={setMaxSourceChunks}
            />
          </div>
          <div className="input-group">
            <label>Max pairs</label>
            <NumberField min={10} max={50000} value={maxPairs} onCommit={setMaxPairs} />
          </div>
          <div className="input-group">
            <label>Pairs per source</label>
            <NumberField
              min={1}
              max={20}
              value={pairsPerSource}
              onCommit={setPairsPerSource}
            />
          </div>
          <div className="input-group">
            <label>Curate threshold</label>
            <NumberField
              min={0}
              max={10}
              step={0.1}
              value={curateThreshold}
              onCommit={setCurateThreshold}
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
        {availableModelsError ? (
          <div style={{ fontSize: 12, color: 'var(--err)', marginTop: 8 }}>
            Unable to load runnable models right now. Check provider readiness and try again.
          </div>
        ) : availableModels.length === 0 && !loadingAvailableModels ? (
          <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginTop: 8 }}>
            No runnable generation models are available for this corpus: the LiteLLM gateway exposed no aliases. Check gateway readiness under Infrastructure and the catalog-backed aliases (including ragweld-local) in Chat settings.
          </div>
        ) : selectionUnavailable ? (
          <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginTop: 8 }}>
            The previously selected model is no longer routable. Pick a currently available model to continue.
          </div>
        ) : modelSelectionMissing ? (
          <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginTop: 8 }}>
            Select both generator and judge models to enable start actions.
          </div>
        ) : null}
      </section>

      <section style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 14, marginBottom: 16, background: 'var(--bg-elev1)' }}>
        <div style={{ fontWeight: 600, marginBottom: 10 }}>Runs</div>
        {loadingRuns ? <div style={{ color: 'var(--fg-muted)' }}>Loading runs...</div> : null}
        {!loadingRuns && runs.length === 0 ? <div style={{ color: 'var(--fg-muted)' }}>No synthetic runs yet.</div> : null}
        {unreadableRuns.length > 0 ? (
          <div className="studio-callout" style={{ marginBottom: 10 }} data-testid="synthetic-unreadable-runs">
            <div style={{ fontWeight: 600, marginBottom: 4 }}>
              {unreadableRuns.length} run director{unreadableRuns.length === 1 ? 'y' : 'ies'} could not be read
            </div>
            <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 6 }}>
              These runs exist under data/synthetic_runs but no longer validate (usually written by a provider that
              was replaced). They are listed here instead of being hidden; remove or migrate them deliberately.
            </div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
              {unreadableRuns.map((u) => (
                <li key={u.run_id}>
                  <span className="studio-mono">{u.run_id}</span> — {u.reason}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
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

            {selectedRun.status === 'failed' ? (
              <div
                className="studio-callout"
                data-testid="synthetic-run-failure"
                style={{ marginBottom: 10, borderColor: 'var(--err)' }}
              >
                <div style={{ fontWeight: 600, marginBottom: 4, color: 'var(--err)' }}>Run failed</div>
                <div style={{ fontSize: 14, color: 'var(--fg)', marginBottom: 6 }}>
                  {selectedRun.error || 'This run failed without recording a reason.'}
                </div>
                <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 8 }}>
                  Open “Live events” below for the run log. Retry re-launches with the same recipe, models, and parameters.
                </div>
                <button
                  className="small-button"
                  data-testid="synthetic-retry"
                  disabled={retrying || starting}
                  onClick={() => void retryRun()}
                >
                  {retrying ? 'Retrying…' : 'Retry'}
                </button>
              </div>
            ) : null}

            <div style={{ marginBottom: 10 }}>
              <LineageMeta
                bundleId={selectedRun.bundle_id}
                inputBundleId={selectedRun.input_bundle_id}
                lineageRef={selectedRun.lineage_ref}
                corpusId={String(activeRepo || '')}
                promotionBlockedReason={promotionBlockReason(selectedRun)}
                onPromote={promoteRun}
              />
            </div>

            <div className="studio-callout" style={{ marginBottom: 10 }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Quality Gate</div>
              <div className="studio-mono">
                threshold={fmtScore(selectedRun.summary?.quality_gate_threshold)} top1={fmtScore(selectedRun.summary?.quality_top1_accuracy)} topk={fmtScore(selectedRun.summary?.quality_topk_accuracy)} mrr={fmtScore(selectedRun.summary?.quality_mrr)} n={selectedRun.summary?.quality_sample_size ?? 0}
              </div>
              {selectedRun.summary?.quality_gate_passed === false ? (
                <div style={{ color: 'var(--err)', marginTop: 6 }}>
                  blocked: {selectedRun.summary?.quality_failure_reason || 'quality gate failed'}
                </div>
              ) : selectedRun.summary?.quality_gate_passed === true ? (
                <div style={{ color: 'var(--ok)', marginTop: 6 }}>
                  passed on {selectedRun.summary?.quality_sample_size ?? 0} sample question
                  {(selectedRun.summary?.quality_sample_size ?? 0) === 1 ? '' : 's'}
                </div>
              ) : (
                <div style={{ color: 'var(--fg-muted)', marginTop: 6 }}>not evaluated</div>
              )}
              <div style={{ color: 'var(--fg-muted)', marginTop: 6, fontSize: '13px' }}>
                The gate retrieves the run's own generated questions against this corpus. It is a self-consistency
                check on a small, self-generated sample — not external validation — so a perfect score is not
                evidence of retrieval quality on its own.
              </div>
            </div>

            <div className="studio-callout" style={{ marginBottom: 10 }} data-testid="synthetic-grounding-summary">
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Grounding &amp; Curation</div>
              <div data-testid="synthetic-avg-judge" style={{ marginBottom: 6 }}>
                Avg judge score{' '}
                <span style={{ fontWeight: 600 }}>{fmtScore(selectedRun.summary?.avg_judge_score)}</span> / 10
                <span style={{ color: 'var(--fg-muted)' }}> ({selectedRun.summary?.items_curated_in ?? 0} judged)</span>
              </div>
              <div className="studio-mono">
                sources={selectedRun.summary?.sources_used ?? 0} generated={selectedRun.summary?.items_generated ?? 0}{' '}
                ungrounded={selectedRun.summary?.items_rejected_ungrounded ?? 0} malformed={selectedRun.summary?.items_rejected_malformed ?? 0}{' '}
                judged={selectedRun.summary?.items_curated_in ?? 0} kept={selectedRun.summary?.items_curated_out ?? 0}{' '}
                triplets={selectedRun.summary?.triplets_mined ?? 0}
              </div>
              <div style={{ color: 'var(--fg-muted)', marginTop: 6, fontSize: '13px' }}>
                Rows are kept only when their evidence quote appears verbatim in the source chunk and the judge scores them at or
                above the curation threshold. Triplets pair each kept question with the highest-ranked non-expected documents the
                real retrieval lane returned for it.
              </div>
            </div>

            <div style={{ marginBottom: 10 }}>
              {(selectedArtifacts || []).map((a) => (
                <div key={`${a.kind}:${a.path}`} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                  <span style={{ minWidth: 180 }}>{labelForKind(a.kind)}</span>
                  <span className="studio-mono" title={a.path} style={{ color: 'var(--fg-muted)', maxWidth: 520, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {a.path}
                  </span>
                  <button
                    className="small-button"
                    data-testid={`synthetic-copy-path-${a.kind}`}
                    title={`Copy path: ${a.path}`}
                    onClick={() =>
                      void copyText(
                        a.path,
                        () => success('Copied artifact path.'),
                        () => notifyError('Clipboard unavailable — the full path is on hover.')
                      )
                    }
                  >
                    Copy path
                  </button>
                  {a.kind !== 'report_md' ? (
                    <button
                      className="small-button"
                      data-testid={`synthetic-preview-${a.kind}`}
                      disabled={previewing === a.kind}
                      onClick={() => void previewArtifact(a.kind)}
                    >
                      {previewing === a.kind ? 'Loading…' : 'Preview'}
                    </button>
                  ) : null}
                  {a.kind !== 'report_md' ? (
                    (() => {
                      const blockedReason = publishBlockReason(a.kind, selectedRun);
                      const isBlocked = Boolean(blockedReason);
                      const isPublishing = publishing === a.kind;
                      const blockedByFailure =
                        isQualityGatedArtifact(a.kind) && selectedRun?.summary?.quality_gate_passed === false;
                      return (
                        <>
                          <button
                            className="small-button"
                            data-testid={`synthetic-publish-${a.kind}`}
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
                  ) : (
                    <span style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
                      The run report is a human-readable summary; it is not published to a corpus store, so it has no Publish action.
                    </span>
                  )}
                </div>
              ))}
            </div>
            {artifactPreview ? (
              <div style={{ marginTop: 12 }} data-testid="synthetic-artifact-preview">
                <div style={{ fontWeight: 600, marginBottom: 6 }}>
                  {labelForKind(artifactPreview.kind)} preview ({artifactPreview.rows.length} row
                  {artifactPreview.rows.length === 1 ? '' : 's'})
                </div>
                <pre style={{ maxHeight: 280, overflow: 'auto', background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: 8, padding: 10 }}>
                  {artifactPreview.rows.length ? JSON.stringify(artifactPreview.rows, null, 2) : 'No rows to preview.'}
                </pre>
                <button className="small-button" onClick={() => setArtifactPreview(null)}>
                  Close preview
                </button>
              </div>
            ) : null}
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
