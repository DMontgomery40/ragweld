import { useEffect, useMemo, useRef, useState } from 'react';
import { useAPI } from '@/hooks';
import { Button } from '@/components/ui/Button';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { PipelineProfile } from '@/components/Benchmark/PipelineProfile';
import { ResultsTable } from '@/components/Benchmark/ResultsTable';
import { SplitScreen } from '@/components/Benchmark/SplitScreen';
import type { ChatModelInfo, ChatModelsResponse } from '@/types/generated';

type BenchmarkRunRequest = {
  prompt: string;
  models: string[];
};

type BenchmarkRunResult = {
  model: string;
  response: string;
  latency_ms?: number;
  error?: string;
  breakdown_ms?: Record<string, number>;
  model_id?: string;
  model_name?: string;
};

type BenchmarkRunResponse = {
  results: BenchmarkRunResult[];
};

const SOURCE_LABELS: Record<ChatModelInfo['source'], string> = {
  cloud_direct: 'Cloud Direct',
  openrouter: 'OpenRouter',
  local: 'Local',
} as const;

const SOURCE_ORDER: Array<ChatModelInfo['source']> = ['cloud_direct', 'openrouter', 'local'] as const;

function toModelValue(model: ChatModelInfo): string {
  return model.source === 'local' ? `local:${model.id}` : model.id;
}

function toModelLabel(model: ChatModelInfo): string {
  return `${model.provider} · ${model.id}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isNumberRecord(value: unknown): value is Record<string, number> {
  if (!isRecord(value)) return false;
  for (const v of Object.values(value)) {
    if (typeof v !== 'number' || !Number.isFinite(v)) return false;
  }
  return true;
}

function normalizeBenchmarkRunResponse(payload: unknown): BenchmarkRunResponse {
  const resultsRaw = isRecord(payload) ? payload.results : payload;
  if (!Array.isArray(resultsRaw)) return { results: [] };

  const results: BenchmarkRunResult[] = [];
  for (const item of resultsRaw) {
    if (!isRecord(item)) continue;

    const model =
      typeof item.model === 'string'
        ? item.model
        : typeof item.model_name === 'string'
          ? item.model_name
          : typeof item.model_id === 'string'
            ? item.model_id
            : '';
    if (!model) continue;

    const response =
      typeof item.response === 'string'
        ? item.response
        : typeof item.output === 'string'
          ? item.output
          : typeof item.text === 'string'
            ? item.text
            : '';

    const latency_ms =
      typeof item.latency_ms === 'number' && Number.isFinite(item.latency_ms) ? item.latency_ms : undefined;

    const error =
      typeof item.error === 'string'
        ? item.error
        : item.error !== undefined && item.error !== null
          ? String(item.error)
          : undefined;

    const breakdown_ms = isNumberRecord(item.breakdown_ms) ? item.breakdown_ms : undefined;

    const model_id = typeof item.model_id === 'string' ? item.model_id : undefined;
    const model_name = typeof item.model_name === 'string' ? item.model_name : undefined;

    results.push({
      model,
      response,
      latency_ms,
      error,
      breakdown_ms,
      model_id,
      model_name,
    });
  }

  return { results };
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
  const [runResult, setRunResult] = useState<BenchmarkRunResponse | null>(null);

  const initSelectionRef = useRef(false);

  const groupedModels = useMemo(() => {
    const grouped = SOURCE_ORDER.map((source) => ({
      source,
      label: SOURCE_LABELS[source],
      items: availableModels.filter((m) => m.source === source),
    })).filter((g) => g.items.length > 0);

    return grouped;
  }, [availableModels]);

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
      response: r.response,
      latency_ms: r.latency_ms,
      error: r.error,
    }));
  }, [runResult]);

  const pipelineResults = useMemo(() => {
    return (runResult?.results || []).map((r) => ({
      model: r.model,
      model_id: r.model_id,
      model_name: r.model_name,
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
      const r = await fetch(api('benchmark/run'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const contentType = r.headers.get('content-type') || '';
      const payload: unknown = contentType.includes('application/json') ? await r.json() : await r.text();
      if (!r.ok) {
        throw new Error(typeof payload === 'string' ? payload : `${r.status} ${r.statusText}`);
      }

      setRunResult(normalizeBenchmarkRunResponse(payload));
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
                              title={toModelLabel(m)}
                            >
                              {toModelLabel(m)}
                            </div>
                            <div style={{ marginTop: 2, fontSize: 12, color: 'var(--fg-muted)' }}>
                              {m.source === 'local' ? 'Local' : m.provider}
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

