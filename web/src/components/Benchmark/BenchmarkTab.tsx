import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAPI, useConfig, useRuntimeCapabilities } from '@/hooks';
import { withCorpusScope } from '@/api/client';
import { getReadiness } from '@/api/dashboard';
import { Button } from '@/components/ui/Button';
import { LineageMeta } from '@/components/ui/LineageMeta';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { PipelineProfile } from '@/components/Benchmark/PipelineProfile';
import { ResultsTable } from '@/components/Benchmark/ResultsTable';
import { CostAttribution } from '@/components/Benchmark/CostAttribution';
import { SplitScreen } from '@/components/Benchmark/SplitScreen';
import {
  defaultBenchmarkSelection,
  describeLocalLane,
  localLaneState,
  toModelValue,
} from '@/components/Benchmark/defaultSelection';
import type {
  BenchmarkRun,
  BenchmarkRunRequest,
  BenchmarkRunsResponse,
  ChatModelInfo,
  ChatModelsResponse,
  ReadinessStatus,
} from '@/types/generated';
import { chatModelDetail, chatModelLabel, chatModelName, groupChatModels } from '@/components/Chat/modelLabel';

function estimatePromptTokens(text: string): number {
  // A deliberately coarse chars/4 heuristic; the estimate is flagged approximate in the UI.
  return Math.max(1, Math.ceil(text.trim().length / 4));
}

const BENCHMARK_EST_OUTPUT_TOKENS = 500;

function formatUsd(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '$0';
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function toModelLabel(model: ChatModelInfo): string {
  return chatModelLabel(model);
}

/** Run-level grounding truth derived from the rows: every model that answered used corpus context. */
function groundingState(run: BenchmarkRun): { grounded: boolean; ungroundedModels: string[] } {
  const answered = (run.results || []).filter((r) => !r.error);
  const ungroundedModels = answered.filter((r) => (r.context_chunks_used ?? 0) === 0).map((r) => r.model);
  const retrievalGrounded = Boolean(run.retrieval?.grounded);
  return { grounded: retrievalGrounded && answered.length > 0 && ungroundedModels.length === 0, ungroundedModels };
}

export default function BenchmarkTab() {
  const { api } = useAPI();
  const { config } = useConfig();

  const [availableModels, setAvailableModels] = useState<ChatModelInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);

  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [prompt, setPrompt] = useState('');
  const [modelFilter, setModelFilter] = useState('');

  const [runLoading, setRunLoading] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<BenchmarkRun | null>(null);

  const [pastRuns, setPastRuns] = useState<BenchmarkRun[]>([]);

  const initSelectionRef = useRef(false);

  // The local serving lane is only a default when this host really serves it: switched on
  // in the effective config (runtime capabilities) and answering its readiness probe.
  const { capabilities, loading: capabilitiesLoading, error: capabilitiesError } = useRuntimeCapabilities();
  const [readiness, setReadiness] = useState<ReadinessStatus | null>(null);
  const [readinessSettled, setReadinessSettled] = useState(false);
  useEffect(() => {
    let mounted = true;
    getReadiness()
      .then((status) => {
        if (mounted) setReadiness(status);
      })
      .catch(() => {
        if (mounted) setReadiness(null);
      })
      .finally(() => {
        if (mounted) setReadinessSettled(true);
      });
    return () => {
      mounted = false;
    };
  }, []);
  // The alias this corpus answers with, resolved the way the chat picker resolves it: the
  // configured LiteLLM default while that lane is on. It anchors the default selection so a
  // first benchmark compares the corpus's own answer model, not the catalog's first rows (S41).
  const answeringAlias = useMemo(
    () => (config?.chat?.litellm?.enabled ? String(config?.chat?.litellm?.default_model || '').trim() : ''),
    [config?.chat?.litellm?.enabled, config?.chat?.litellm?.default_model]
  );
  const localLane = useMemo(
    () => (capabilities ? localLaneState(capabilities, readiness) : null),
    [capabilities, readiness]
  );

  // 387 checkboxes with no filter (B-14) — match on the same label + alias the row shows.
  const filterText = modelFilter.trim().toLowerCase();
  const litellmModels = useMemo(() => availableModels.filter((m) => m.source === 'litellm'), [availableModels]);
  // The page's display order, flattened: local serving row first, then providers A-Z, names A-Z.
  const orderedModels = useMemo(() => groupChatModels(litellmModels).flatMap((group) => group.models), [litellmModels]);
  const groupedModels = useMemo(
    () =>
      groupChatModels(litellmModels)
        .map(({ group, models }) => {
          const items = filterText
            ? models.filter((m) => `${chatModelLabel(m)} ${m.id} ${chatModelName(m)}`.toLowerCase().includes(filterText))
            : models;
          return { source: group, label: `${group} (${items.length})`, items };
        })
        .filter((group) => group.items.length > 0),
    [litellmModels, filterText]
  );

  const selectedModelInfos = useMemo(
    () => availableModels.filter((m) => selectedModels.includes(toModelValue(m))),
    [availableModels, selectedModels]
  );

  // Approximate pre-run cost across the selected models: prompt tokens in + a fixed output
  // estimate out, priced from the catalog per-1k figures every row already prints (B-15).
  const costEstimate = useMemo(() => {
    const promptTokens = estimatePromptTokens(prompt);
    let total = 0;
    let priced = 0;
    for (const model of selectedModelInfos) {
      const inputPer1k = typeof model.input_per_1k === 'number' ? model.input_per_1k : null;
      const outputPer1k = typeof model.output_per_1k === 'number' ? model.output_per_1k : null;
      if (inputPer1k === null && outputPer1k === null) continue;
      priced += 1;
      total += (promptTokens / 1000) * (inputPer1k ?? 0) + (BENCHMARK_EST_OUTPUT_TOKENS / 1000) * (outputPer1k ?? 0);
    }
    return { total, priced, count: selectedModelInfos.length, promptTokens };
  }, [prompt, selectedModelInfos]);

  const loadPastRuns = useCallback(async () => {
    try {
      const r = await fetch(withCorpusScope(api('benchmark/results?limit=10')));
      if (!r.ok) {
        setPastRuns([]);
        return;
      }
      const d = (await r.json()) as BenchmarkRunsResponse;
      setPastRuns(Array.isArray(d?.runs) ? (d.runs as BenchmarkRun[]) : []);
    } catch {
      setPastRuns([]);
    }
  }, [api]);

  useEffect(() => {
    void loadPastRuns();
  }, [loadPastRuns]);

  const selectedCount = selectedModels.length;
  const selectionOk = selectedCount >= 2 && selectedCount <= 4;
  const promptOk = prompt.trim().length > 0;
  const canRun = selectionOk && promptOk && !runLoading;

  useEffect(() => {
    (async () => {
      setModelsLoading(true);
      setModelsError(null);
      try {
        const r = await fetch(api('chat/models'));
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        const d = (await r.json()) as ChatModelsResponse;
        const models = Array.isArray(d?.models) ? (d.models as ChatModelInfo[]) : [];
        setAvailableModels(models);
      } catch (e) {
        setAvailableModels([]);
        setModelsError(e instanceof Error ? e.message : String(e));
      } finally {
        setModelsLoading(false);
      }
    })();
  }, [api]);

  // Default selection waits for the lane truth. If capabilities never load there is no
  // default at all (the operator picks by hand) rather than a guess at a live lane.
  useEffect(() => {
    if (initSelectionRef.current) return;
    if (orderedModels.length < 2) return;
    if (!localLane || !readinessSettled) return;
    // The answering alias is config truth, and this effect runs once: initialising before the
    // config has loaded would anchor on nothing and never re-run (S41).
    if (!config) return;
    initSelectionRef.current = true;
    setSelectedModels(defaultBenchmarkSelection(orderedModels, localLane, { answeringAlias }));
  }, [answeringAlias, config, orderedModels, localLane, readinessSettled]);

  const splitResults = useMemo(() => {
    return (runResult?.results || []).map((r) => ({
      model: r.model,
      response: r.response ?? '',
      latency_ms: r.latency_ms,
      error: r.error ?? undefined,
      context_chunks_used: r.context_chunks_used ?? 0,
      cost_summary: r.cost_summary,
    }));
  }, [runResult]);

  const pipelineResults = useMemo(() => {
    return (runResult?.results || []).map((r) => ({
      model: r.model,
      model_id: r.model_id ?? undefined,
      model_name: r.model_name ?? undefined,
      breakdown_ms: r.breakdown_ms,
    }));
  }, [runResult]);

  const onToggleModel = (value: string) => {
    setSelectedModels((prev) => {
      const set = new Set(prev);
      const currentlySelected = set.has(value);
      if (currentlySelected) {
        set.delete(value);
        return Array.from(set);
      }

      if (set.size >= 4) return prev;
      set.add(value);
      return Array.from(set);
    });
  };

  const onRun = async () => {
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) return;
    if (selectedModels.length < 2 || selectedModels.length > 4) return;

    setRunLoading(true);
    setRunError(null);
    setRunResult(null);

    const body: BenchmarkRunRequest = {
      prompt: trimmedPrompt,
      models: selectedModels,
    };

    try {
      const scopedUrl = withCorpusScope(api('benchmark/run'));
      const scopedResponse = await fetch(scopedUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const contentType = scopedResponse.headers.get('content-type') || '';
      const payload: unknown = contentType.includes('application/json') ? await scopedResponse.json() : await scopedResponse.text();
      if (!scopedResponse.ok) {
        throw new Error(typeof payload === 'string' ? payload : `${scopedResponse.status} ${scopedResponse.statusText}`);
      }

      setRunResult(payload as BenchmarkRun);
      void loadPastRuns();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e));
      setRunResult(null);
    } finally {
      setRunLoading(false);
    }
  };

  return (
    <div className="tab-content" data-testid="benchmark-tab" style={{ display: 'grid', gap: 16 }}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(320px, 520px) 1fr',
          gap: 16,
          alignItems: 'start',
        }}
      >
        <section
          style={{
            background: 'var(--bg-elev1)',
            border: '1px solid var(--line)',
            borderRadius: 12,
            padding: 16,
          }}
          aria-label="Benchmark model selection"
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg)' }}>Models</div>
            <div style={{ fontSize: 12, color: selectionOk ? 'var(--fg-muted)' : 'var(--warn)' }}>
              Select 2–4 ({selectedCount}/4)
            </div>
          </div>

          <input
            type="search"
            data-testid="benchmark-model-filter"
            value={modelFilter}
            onChange={(e) => setModelFilter(e.target.value)}
            placeholder="Filter models by name or alias…"
            aria-label="Filter benchmark models"
            style={{
              width: '100%',
              marginTop: 10,
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '8px 10px',
              borderRadius: '8px',
              fontSize: '13px',
            }}
          />

          {!capabilitiesLoading && capabilitiesError ? (
            <div
              data-testid="benchmark-capabilities-error"
              style={{ marginTop: 10, fontSize: 12, color: 'var(--warn)', lineHeight: 1.5 }}
            >
              Runtime capabilities unavailable ({capabilitiesError}); no models were pre-selected. Pick them by hand.
            </div>
          ) : null}

          {modelsLoading ? (
            <div style={{ padding: '12px 0' }}>
              <LoadingSpinner size="md" color="accent" label="Loading models…" />
            </div>
          ) : modelsError ? (
            <div
              style={{
                marginTop: 10,
                padding: '10px 12px',
                borderRadius: 10,
                border: '1px solid rgba(255, 107, 107, 0.35)',
                background: 'rgba(255, 107, 107, 0.10)',
                color: 'var(--err)',
                fontSize: 12,
              }}
            >
              Failed to load models: {modelsError}
            </div>
          ) : groupedModels.length === 0 ? (
            <div style={{ marginTop: 10, color: 'var(--fg-muted)', fontSize: 12 }}>
              {filterText ? `No models match "${modelFilter.trim()}".` : 'No models available.'}
            </div>
          ) : (
            // Capped so the (potentially hundreds of) model rows scroll here instead of growing
            // the page and pushing the Prompt/Run column off screen (B-14).
            <div
              data-testid="benchmark-model-list"
              style={{ marginTop: 12, display: 'grid', gap: 12, maxHeight: '46vh', overflowY: 'auto', paddingRight: 4 }}
            >
              {groupedModels.map((group) => (
                <div key={group.source}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--fg-muted)', marginBottom: 8 }}>
                    {group.label}
                  </div>
                  <div style={{ display: 'grid', gap: 8 }}>
                    {group.items.map((m) => {
                      const value = toModelValue(m);
                      const checked = selectedModels.includes(value);
                      const wouldExceed = !checked && selectedModels.length >= 4;
                      const isLocalLane = Boolean(localLane?.alias) && String(m.id || '').trim() === localLane?.alias;

                      return (
                        <label
                          key={value}
                          data-testid="benchmark-model-row"
                          data-alias={m.id}
                          style={{
                            display: 'flex',
                            alignItems: 'flex-start',
                            gap: 10,
                            padding: '8px 10px',
                            borderRadius: 10,
                            border: '1px solid var(--line)',
                            background: 'var(--bg-elev2)',
                            opacity: wouldExceed ? 0.65 : 1,
                            cursor: wouldExceed ? 'not-allowed' : 'pointer',
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={wouldExceed}
                            onChange={() => onToggleModel(value)}
                            aria-label={`Select ${toModelLabel(m)}`}
                            style={{ marginTop: 2 }}
                          />
                          <div style={{ minWidth: 0 }}>
                            <div
                              style={{
                                fontSize: 12,
                                fontWeight: 700,
                                color: 'var(--fg)',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                              title={chatModelDetail(m)}
                            >
                              {chatModelName(m)}
                            </div>
                            <div style={{ marginTop: 2, fontSize: 12, color: 'var(--fg-muted)' }}>
                              {chatModelDetail(m)}
                            </div>
                            {isLocalLane && localLane ? (
                              <div
                                data-testid="benchmark-local-lane-state"
                                data-reachable={localLane.reachable ? 'true' : 'false'}
                                style={{
                                  marginTop: 3,
                                  fontSize: 12,
                                  fontWeight: 600,
                                  color: localLane.reachable ? 'var(--ok)' : 'var(--warn)',
                                }}
                              >
                                {describeLocalLane(localLane)}
                              </div>
                            ) : null}
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section
          style={{
            background: 'var(--bg-elev1)',
            border: '1px solid var(--line)',
            borderRadius: 12,
            padding: 16,
          }}
          aria-label="Benchmark prompt and run"
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg)' }}>Prompt</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {runLoading ? <LoadingSpinner size="sm" color="accent" /> : null}
              <Button
                data-testid="benchmark-run"
                variant="primary"
                size="md"
                onClick={() => void onRun()}
                disabled={!canRun}
                title={!promptOk ? 'Enter a prompt' : !selectionOk ? 'Select 2–4 models' : 'Run benchmark'}
              >
                {runLoading ? 'Running…' : 'Run'}
              </Button>
            </div>
          </div>

          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Enter a prompt to run across multiple models…"
            disabled={runLoading}
            rows={6}
            style={{
              width: '100%',
              marginTop: 12,
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '12px',
              borderRadius: '10px',
              fontSize: '13px',
              fontFamily: 'inherit',
              resize: 'vertical',
              minHeight: 120,
            }}
            aria-label="Benchmark prompt"
          />

          <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <div style={{ fontSize: 12, color: selectionOk ? 'var(--fg-muted)' : 'var(--warn)' }}>
              {selectionOk ? 'Ready when you are.' : 'Select between 2 and 4 models to run.'}
            </div>
            <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>{promptOk ? `${prompt.trim().length} chars` : ''}</div>
          </div>

          {selectionOk && promptOk ? (
            <div
              data-testid="benchmark-cost-estimate"
              style={{ marginTop: 8, fontSize: 12, color: 'var(--fg-muted)', lineHeight: 1.5 }}
            >
              Estimated cost{' '}
              <strong style={{ color: 'var(--fg)' }}>~{formatUsd(costEstimate.total)}</strong>{' '}
              for {costEstimate.count} model{costEstimate.count === 1 ? '' : 's'}
              {costEstimate.priced < costEstimate.count
                ? ` (${costEstimate.count - costEstimate.priced} with no catalog pricing)`
                : ''}
              {' — approximate: ~'}
              {costEstimate.promptTokens} prompt tokens in, ~{BENCHMARK_EST_OUTPUT_TOKENS} out per model.
            </div>
          ) : null}

          {runResult?.retrieval ? (() => {
            const grounding = groundingState(runResult);
            const retrieval = runResult.retrieval;
            const paths = retrieval.source_paths ?? [];
            return (
              <div
                data-testid="benchmark-grounding"
                data-grounded={grounding.grounded ? 'true' : 'false'}
                role="status"
                style={{
                  marginTop: 12,
                  padding: '10px 12px',
                  borderRadius: 10,
                  border: grounding.grounded ? '1px solid rgba(var(--ok-rgb), 0.35)' : '1px solid rgba(var(--warn-rgb), 0.45)',
                  background: grounding.grounded ? 'rgba(var(--ok-rgb), 0.10)' : 'rgba(var(--warn-rgb), 0.12)',
                  color: 'var(--fg)',
                  fontSize: 13,
                  lineHeight: 1.5,
                }}
              >
                {grounding.grounded ? (
                  <>
                    <strong>Grounded:</strong> {retrieval.chunk_count} chunk{retrieval.chunk_count === 1 ? '' : 's'} retrieved from{' '}
                    <code>{retrieval.corpus_id}</code>; every answering model used corpus context (see the Context column).
                    {paths.length > 0 ? (
                      <span style={{ color: 'var(--fg-muted)' }}>
                        {' '}
                        ({paths.slice(0, 4).join(', ')}
                        {paths.length > 4 ? ', …' : ''})
                      </span>
                    ) : null}
                  </>
                ) : retrieval.grounded ? (
                  <>
                    <strong>Partially grounded:</strong> {retrieval.chunk_count} chunk{retrieval.chunk_count === 1 ? '' : 's'} were retrieved, but{' '}
                    {grounding.ungroundedModels.length > 0
                      ? `${grounding.ungroundedModels.join(', ')} answered with no corpus context (nothing fit the context window)`
                      : 'no model produced an answer'}
                    .
                  </>
                ) : (
                  <>
                    <strong>Not grounded:</strong> the answers below were generated without retrieval —{' '}
                    {retrieval.reason || 'no retrieval context'}.
                  </>
                )}
              </div>
            );
          })() : null}

          {runResult ? (
            <div style={{ marginTop: 12 }}>
              <LineageMeta
                bundleId={runResult.bundle_id}
                inputBundleId={runResult.input_bundle_id}
                lineageRef={runResult.lineage_ref}
              />
            </div>
          ) : null}

          {runError ? (
            <div
              style={{
                marginTop: 12,
                padding: '10px 12px',
                borderRadius: 10,
                border: '1px solid rgba(255, 107, 107, 0.35)',
                background: 'rgba(255, 107, 107, 0.10)',
                color: 'var(--err)',
                fontSize: 12,
                whiteSpace: 'pre-wrap',
              }}
              role="status"
              aria-live="polite"
            >
              Benchmark failed: {runError}
            </div>
          ) : null}
        </section>
      </div>

      <section style={{ display: 'grid', gap: 12 }} aria-label="Benchmark results">
        {runResult ? (
          <>
            <div data-testid="benchmark-run-cost" style={{ padding: 12, border: '1px solid var(--line)', borderRadius: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>Run cost</div>
              <CostAttribution summary={runResult.cost_summary} showDetail />
            </div>
            <ResultsTable results={splitResults} />
            {splitResults.length > 0 ? <SplitScreen results={splitResults} /> : null}
            <PipelineProfile results={pipelineResults} />
          </>
        ) : (
          <div
            data-testid="benchmark-empty-state"
            style={{
              background: 'var(--bg-elev1)',
              border: '1px solid var(--line)',
              borderRadius: 12,
              padding: 16,
              display: 'grid',
              gap: 14,
            }}
          >
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg)' }}>What a benchmark produces</div>
              <div style={{ marginTop: 6, fontSize: 13, color: 'var(--fg-muted)', lineHeight: 1.55 }}>
                Running sends the same prompt to every model you select and shows their answers side by side, each
                model&apos;s latency and per-stage pipeline timing, and — when a corpus is scoped — the retrieval
                grounding each answer used. Select 2–4 models, enter a prompt, and press Run.
              </div>
            </div>

            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--fg-muted)', marginBottom: 8 }}>Recent runs</div>
              {pastRuns.length === 0 ? (
                <div data-testid="benchmark-no-past-runs" style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
                  No past runs yet. Your saved runs will appear here.
                </div>
              ) : (
                <div data-testid="benchmark-past-runs" style={{ display: 'grid', gap: 8 }}>
                  {pastRuns.map((run) => {
                    const startedAt = Number(run.started_at_ms || 0);
                    const modelCount = (run.models || []).length;
                    return (
                      <button
                        key={run.run_id}
                        type="button"
                        onClick={() => setRunResult(run)}
                        style={{
                          textAlign: 'left',
                          background: 'var(--bg-elev2)',
                          border: '1px solid var(--line)',
                          borderRadius: 10,
                          padding: '8px 10px',
                          color: 'var(--fg)',
                          cursor: 'pointer',
                          display: 'grid',
                          gap: 3,
                        }}
                      >
                        <span
                          style={{ fontSize: 12.5, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        >
                          {String(run.prompt || '').trim() || '(no prompt)'}
                        </span>
                        <span style={{ fontSize: 11.5, color: 'var(--fg-muted)' }}>
                          {modelCount} model{modelCount === 1 ? '' : 's'}
                          {run.corpus_id ? ` · ${run.corpus_id}` : ''}
                          {startedAt ? ` · ${new Date(startedAt).toLocaleString()}` : ''}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
