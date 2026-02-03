import { useEffect, useMemo, useState } from 'react';
import { useCost } from '@/hooks/useCost';
import type { CostEstimateLocal, CostModelType } from '@/services/CostService';
 
function num(v: string, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}
 
export function CostEstimatorPanel() {
  const { providers, modelsByProvider, loadingCatalog, catalogError, estimateLocal, estimating, estimateError, lastLocalEstimate, listModels } =
    useCost();
 
  const providerOptions = useMemo(() => providers.length ? providers : ['Local'], [providers]);
 
  const [provider, setProvider] = useState<string>('Local');
  const [model, setModel] = useState<string>('');
 
  const [inputTokens, setInputTokens] = useState('1200');
  const [outputTokens, setOutputTokens] = useState('200');
  const [embedTokens, setEmbedTokens] = useState('0');
  const [rerankRequests, setRerankRequests] = useState('0');
 
  const [result, setResult] = useState<CostEstimateLocal | null>(null);
  const [modelType, setModelType] = useState<CostModelType>('chat');
  const [modelsForProvider, setModelsForProvider] = useState<string[]>([]);
 
  useEffect(() => {
    // Keep provider in a valid state when catalog loads.
    if (providers.length && !providers.includes(provider)) setProvider(providers[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providers.length]);
 
  useEffect(() => {
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
  }, [listModels, modelsByProvider, provider]);
 
  useEffect(() => {
    // Ensure chosen model exists when provider changes
    if (!modelsForProvider.length) return;
    if (!model || !modelsForProvider.includes(model)) setModel(modelsForProvider[0]);
  }, [model, modelsForProvider]);
 
  const handleEstimate = async () => {
    const req =
      modelType === 'chat'
        ? { chat: { provider, model, input_tokens: num(inputTokens), output_tokens: num(outputTokens) } }
        : modelType === 'embed'
          ? { embed: { provider, model, embed_tokens: num(embedTokens) } }
          : { rerank: { provider, model, requests: num(rerankRequests) } };
 
    const out = await estimateLocal(req);
    setResult(out);
  };
 
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
        {loadingCatalog ? (
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>Loading catalog…</div>
        ) : null}
      </div>
 
      {catalogError && (
        <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--warn)' }}>
          Pricing catalog unavailable: {catalogError}
        </div>
      )}
 
      <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr 1fr', gap: '12px', marginTop: '14px' }}>
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
          </select>
        </div>
 
        <div className="input-group">
          <label style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>Provider</label>
          <select data-testid="cost-estimator-provider" value={provider} onChange={(e) => setProvider(e.target.value)} style={{ width: '100%' }}>
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
 
      <div style={{ display: 'flex', gap: '10px', alignItems: 'center', marginTop: '14px' }}>
        <button
          data-testid="cost-estimator-run"
          type="button"
          className="small-button"
          onClick={() => void handleEstimate()}
          disabled={estimating || !provider || !model}
          style={{
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            fontWeight: 700,
            opacity: estimating || !provider || !model ? 0.6 : 1,
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
        {result
          ? `Total: $${result.totalUSD.toFixed(6)}\n` +
            Object.entries(result.breakdown)
              .map(([k, v]) => `${k}: $${Number(v?.costUSD || 0).toFixed(6)}`)
              .join('\n')
          : (lastLocalEstimate ? `Total: $${lastLocalEstimate.totalUSD.toFixed(6)}` : '—')}
      </div>
    </div>
  );
}

