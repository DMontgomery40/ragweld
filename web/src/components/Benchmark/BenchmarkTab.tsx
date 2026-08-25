import { useEffect, useMemo, useRef, useState } from 'react';
import { useAPI } from '@/hooks';
import { withCorpusScope } from '@/api/client';
import { Button } from '@/components/ui/Button';
import { LineageMeta } from '@/components/ui/LineageMeta';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { PipelineProfile } from '@/components/Benchmark/PipelineProfile';
import { ResultsTable } from '@/components/Benchmark/ResultsTable';
import { SplitScreen } from '@/components/Benchmark/SplitScreen';
import type { BenchmarkRun, BenchmarkRunRequest, ChatModelInfo, ChatModelsResponse } from '@/types/generated';
import { chatModelDetail, chatModelLabel, chatModelName, groupChatModels } from '@/components/Chat/modelLabel';

function toModelValue(model: ChatModelInfo): string {
  return String(model.override || model.id || '').trim();
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

  const [availableModels, setAvailableModels] = useState<ChatModelInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);

  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [prompt, setPrompt] = useState('');

  const [runLoading, setRunLoading] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<BenchmarkRun | null>(null);

  const initSelectionRef = useRef(false);

  const groupedModels = useMemo(
    () =>
      groupChatModels(availableModels.filter((m) => m.source === 'litellm')).map(({ group, models }) => ({
        source: group,
        label: `${group} (${models.length})`,
        items: models,
      })),
    [availableModels]
  );

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

  useEffect(() => {
    if (initSelectionRef.current) return;
    if (availableModels.length < 2) return;
    initSelectionRef.current = true;
    setSelectedModels([toModelValue(availableModels[0]), toModelValue(availableModels[1])]);
  }, [availableModels]);

  const splitResults = useMemo(() => {
    return (runResult?.results || []).map((r) => ({
      model: r.model,
      response: r.response ?? '',
      latency_ms: r.latency_ms,
      error: r.error ?? undefined,
      context_chunks_used: r.context_chunks_used ?? 0,
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
            <div style={{ marginTop: 10, color: 'var(--fg-muted)', fontSize: 12 }}>No models available.</div>
          ) : (
            <div style={{ marginTop: 12, display: 'grid', gap: 12 }}>
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

                      return (
                        <label
                          key={value}
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
        <ResultsTable results={splitResults} />
        {splitResults.length > 0 ? <SplitScreen results={splitResults} /> : null}
        <PipelineProfile results={pipelineResults} />
      </section>
    </div>
  );
}
