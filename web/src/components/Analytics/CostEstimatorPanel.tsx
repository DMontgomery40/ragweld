import { useEffect, useMemo, useState } from 'react';
import { useConfig } from '@/hooks';
import { useCost } from '@/hooks/useCost';
import { useRepoStore } from '@/stores/useRepoStore';
import type { CostEstimateLocal, CostIndexingEstimate, CostModelType } from '@/services/CostService';

function num(v: string, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export function CostEstimatorPanel() {
  const {
    providers,
    modelsByProvider,
    loadingCatalog,
    catalogError,
    estimateLocal,
    estimating,
    estimateError,
    lastLocalEstimate,
    lastIndexingEstimate,
    listModels,
    estimateIndexing,
  } = useCost();
  const { flushPendingPatches } = useConfig();
  const { activeRepo, repos, loadRepos } = useRepoStore();

  const providerOptions = useMemo(() => (providers.length ? providers : ['Local']), [providers]);

  const [provider, setProvider] = useState<string>('Local');
  const [model, setModel] = useState<string>('');

  const [inputTokens, setInputTokens] = useState('1200');
  const [outputTokens, setOutputTokens] = useState('200');
  const [embedTokens, setEmbedTokens] = useState('0');
  const [rerankRequests, setRerankRequests] = useState('0');
  const [indexPathOverride, setIndexPathOverride] = useState('');

  const [result, setResult] = useState<CostEstimateLocal | null>(null);
  const [indexingResult, setIndexingResult] = useState<CostIndexingEstimate | null>(null);
  const [modelType, setModelType] = useState<CostModelType>('chat');
  const [modelsForProvider, setModelsForProvider] = useState<string[]>([]);

  const activeCorpus = useMemo(() => {
    const rid = String(activeRepo || '').trim();
    if (!rid) return null;
    return repos.find((r) => r.corpus_id === rid || r.slug === rid || r.name === rid) || null;
  }, [activeRepo, repos]);
  const resolvedRepoPath = useMemo(() => String(activeCorpus?.path || ''), [activeCorpus]);
  const effectiveRepoPath = useMemo(
    () => (indexPathOverride.trim() ? indexPathOverride.trim() : resolvedRepoPath),
    [indexPathOverride, resolvedRepoPath]
  );

  useEffect(() => {
    if (providers.length && !providers.includes(provider)) setProvider(providers[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providers.length]);

  useEffect(() => {
    if (modelType === 'indexing') return;
    const fromCache = modelsByProvider[provider] || [];
    if (fromCache.length) {
      setModelsForProvider(fromCache);
      return;
    }
    void (async () => {
      try {
        const list = await listModels(provider);
        setModelsForProvider(list);
      } catch {
        setModelsForProvider([]);
      }
    })();
  }, [listModels, modelType, modelsByProvider, provider]);

  useEffect(() => {
    if (!modelsForProvider.length) return;
    if (!model || !modelsForProvider.includes(model)) setModel(modelsForProvider[0]);
  }, [model, modelsForProvider]);

  useEffect(() => {
    if (modelType === 'indexing' && !repos.length) {
      void loadRepos();
    }
  }, [loadRepos, modelType, repos.length]);

  useEffect(() => {
    if (modelType === 'indexing') {
      setIndexingResult(null);
    }
  }, [activeRepo, effectiveRepoPath, modelType]);

  const handleEstimate = async () => {
    if (modelType === 'indexing') {
      const rid = String(activeRepo || '').trim();
      if (!rid || !effectiveRepoPath) return;
      await flushPendingPatches();
      const out = await estimateIndexing({ corpus_id: rid, repo_path: effectiveRepoPath });
      setIndexingResult(out);
      return;
    }

    const req =
      modelType === 'chat'
        ? { chat: { provider, model, input_tokens: num(inputTokens), output_tokens: num(outputTokens) } }
        : modelType === 'embed'
          ? { embed: { provider, model, embed_tokens: num(embedTokens) } }
          : { rerank: { provider, model, requests: num(rerankRequests) } };

    const out = await estimateLocal(req);
    setResult(out);
  };

  const indexingRender =
    indexingResult ||
    (lastIndexingEstimate && lastIndexingEstimate.corpusId === String(activeRepo || '').trim()
      ? lastIndexingEstimate
      : null);
  const indexingTime =
    indexingRender?.estimatedSecondsLow != null && indexingRender?.estimatedSecondsHigh != null
      ? `${Math.round(Number(indexingRender.estimatedSecondsLow))}s–${Math.round(Number(indexingRender.estimatedSecondsHigh))}s`
      : 'N/A';
  const indexingEmbedSecondsApprox =
    indexingRender?.estimatedSecondsSemanticKg != null &&
    indexingRender?.estimatedSecondsLow != null &&
    indexingRender?.estimatedSecondsHigh != null
      ? Math.max(
          0,
          (Number(indexingRender.estimatedSecondsLow) + Number(indexingRender.estimatedSecondsHigh)) / 2 -
            Number(indexingRender.estimatedSecondsSemanticKg)
        )
      : null;

  return (
    <div
      data-testid="cost-estimator-panel"
      style={{
        background: 'var(--bg-elev1)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        padding: '16px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
        <div>
          <div style={{ fontSize: '14px', fontWeight: 800, color: 'var(--fg)' }}>Cost estimator</div>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>Local estimate using `models.json` pricing.</div>
        </div>
        {loadingCatalog ? <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>Loading catalog…</div> : null}
      </div>

      {catalogError && (
        <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--warn)' }}>
          Pricing catalog unavailable: {catalogError}
        </div>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: modelType === 'indexing' ? '160px 1fr' : '140px 1fr 1fr',
          gap: '12px',
          marginTop: '14px'
        }}
      >
        <div className="input-group">
          <label style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>Type</label>
          <select
            data-testid="cost-estimator-type"
            value={modelType}
            onChange={(e) => setModelType(e.target.value as CostModelType)}
            style={{ width: '100%' }}
          >
            <option value="chat">Chat</option>
            <option value="embed">Embedding</option>
            <option value="rerank">Rerank</option>
            <option value="indexing">Indexing</option>
          </select>
        </div>

        {modelType !== 'indexing' ? (
          <>
            <div className="input-group">
              <label style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>Provider</label>
              <select
                data-testid="cost-estimator-provider"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                style={{ width: '100%' }}
              >
                {providerOptions.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>

            <div className="input-group">
              <label style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>Model</label>
              <select data-testid="cost-estimator-model" value={model} onChange={(e) => setModel(e.target.value)} style={{ width: '100%' }}>
                {modelsForProvider.length ? (
                  modelsForProvider.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))
                ) : (
                  <option value={model}>{model || '—'}</option>
                )}
              </select>
            </div>
          </>
        ) : (
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', alignSelf: 'end' }}>
            Uses `/api/index/estimate` with current corpus config (embedding + semantic KG).
          </div>
        )}
      </div>

      {modelType === 'chat' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '12px' }}>
          <div className="input-group">
            <label style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>Input tokens</label>
            <input data-testid="cost-estimator-input-tokens" type="number" value={inputTokens} onChange={(e) => setInputTokens(e.target.value)} min={0} />
          </div>
          <div className="input-group">
            <label style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>Output tokens</label>
            <input data-testid="cost-estimator-output-tokens" type="number" value={outputTokens} onChange={(e) => setOutputTokens(e.target.value)} min={0} />
          </div>
        </div>
      )}

      {modelType === 'embed' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '12px', marginTop: '12px' }}>
          <div className="input-group">
            <label style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>Embedding tokens</label>
            <input data-testid="cost-estimator-embed-tokens" type="number" value={embedTokens} onChange={(e) => setEmbedTokens(e.target.value)} min={0} />
          </div>
        </div>
      )}

      {modelType === 'rerank' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '12px', marginTop: '12px' }}>
          <div className="input-group">
            <label style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>Requests</label>
            <input data-testid="cost-estimator-rerank-requests" type="number" value={rerankRequests} onChange={(e) => setRerankRequests(e.target.value)} min={0} />
          </div>
        </div>
      )}

      {modelType === 'indexing' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '12px', marginTop: '12px' }}>
          <div className="input-group">
            <label style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>Corpus</label>
            <input type="text" value={activeRepo || ''} disabled style={{ width: '100%' }} />
          </div>
          <div className="input-group">
            <label style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>Repo path</label>
            <input
              type="text"
              value={indexPathOverride}
              onChange={(e) => setIndexPathOverride(e.target.value)}
              placeholder={resolvedRepoPath || '/path/to/repo'}
            />
            <div style={{ marginTop: '6px', fontSize: '11px', color: 'var(--fg-muted)' }}>
              {effectiveRepoPath ? `Using: ${effectiveRepoPath}` : 'Select a corpus (or set a path override).'}
            </div>
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: '10px', alignItems: 'center', marginTop: '14px' }}>
        <button
          data-testid="cost-estimator-run"
          type="button"
          className="small-button"
          onClick={() => void handleEstimate()}
          disabled={estimating || (modelType === 'indexing' ? !(activeRepo && effectiveRepoPath) : !provider || !model)}
          style={{
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            fontWeight: 700,
            opacity: estimating || (modelType === 'indexing' ? !(activeRepo && effectiveRepoPath) : !provider || !model) ? 0.6 : 1,
            cursor: estimating ? 'wait' : 'pointer',
          }}
        >
          {estimating ? 'Estimating…' : 'Estimate'}
        </button>
        {estimateError && <div style={{ fontSize: '12px', color: 'var(--err)' }}>{estimateError}</div>}
        <div style={{ marginLeft: 'auto', fontSize: '11px', color: 'var(--fg-muted)' }}>
          {lastLocalEstimate?.modelsVersion ? `models: ${lastLocalEstimate.modelsVersion}` : ''}
        </div>
      </div>

      <div
        data-testid="cost-estimator-result"
        style={{
          marginTop: '14px',
          background: 'var(--code-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '12px',
          fontFamily: 'var(--font-mono)',
          fontSize: '12px',
          whiteSpace: 'pre-wrap',
          color: 'var(--fg)',
          minHeight: '52px',
        }}
      >
        {modelType === 'indexing'
          ? indexingRender
            ? `Total: ${
                indexingRender.totalCostUSD == null ? 'N/A' : `$${Number(indexingRender.totalCostUSD).toFixed(6)}`
              }\n` +
              `Embedding: ${
                indexingRender.embeddingCostUSD == null ? 'N/A' : `$${Number(indexingRender.embeddingCostUSD).toFixed(6)}`
              }\n` +
              `${
                indexingRender.semanticKgCostUSD != null
                  ? `Semantic KG: $${Number(indexingRender.semanticKgCostUSD).toFixed(6)}\n`
                  : ''
              }` +
              `Time: ${indexingTime}\n` +
              `${
                indexingRender.estimatedSecondsSemanticKg != null
                  ? `Time breakdown: Embed ${
                      indexingEmbedSecondsApprox == null ? 'N/A' : `~${Math.round(indexingEmbedSecondsApprox)}s`
                    } + KG ~${Math.round(Number(indexingRender.estimatedSecondsSemanticKg))}s\n`
                  : ''
              }` +
              `Chunks (est): ${Number(indexingRender.raw.estimated_total_chunks || 0).toLocaleString()}`
            : '—'
          : result
            ? `Total: $${result.totalUSD.toFixed(6)}\n` +
              Object.entries(result.breakdown)
                .map(([k, v]) => `${k}: $${Number(v?.costUSD || 0).toFixed(6)}`)
                .join('\n')
            : lastLocalEstimate
              ? `Total: $${lastLocalEstimate.totalUSD.toFixed(6)}`
              : '—'}
      </div>
    </div>
  );
}
