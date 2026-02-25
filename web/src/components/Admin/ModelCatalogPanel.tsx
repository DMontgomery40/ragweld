import { useEffect, useMemo, useState } from 'react';
import { modelsApi } from '@/api';
import { useModelFlows } from '@/hooks/useModelFlows';
import type { ModelsUpsertRequest } from '@/services/ModelFlowsService';
import type { ModelCatalogEntry } from '@/types/generated';

function numOrNull(v: string): number | null {
  if (v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

const KNOWN_PROVIDER_BASE_URLS: Record<string, string> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com',
  google: 'https://generativelanguage.googleapis.com',
  cohere: 'https://api.cohere.ai/v2',
  voyage: 'https://api.voyageai.com/v1',
  jina: 'https://api.jina.ai/v1',
  openrouter: 'https://openrouter.ai/api/v1',
  mistral: 'https://api.mistral.ai/v1',
  deepseek: 'https://api.deepseek.com/v1',
  ollama: 'http://127.0.0.1:11434',
  local: 'http://127.0.0.1:11434',
};

export function ModelCatalogPanel() {
  const { saving, error, lastResponse, upsertModel } = useModelFlows();

  const [provider, setProvider] = useState('openai');
  const [model, setModel] = useState('');
  const [family, setFamily] = useState<'gen' | 'embed' | 'rerank' | 'misc'>('gen');
  const [unit, setUnit] = useState<'1k_tokens' | 'request'>('1k_tokens');
  const [baseUrl, setBaseUrl] = useState('');
  const [baseUrlEdited, setBaseUrlEdited] = useState(false);
  const [catalogModels, setCatalogModels] = useState<ModelCatalogEntry[]>([]);

  const [inputPer1k, setInputPer1k] = useState('');
  const [outputPer1k, setOutputPer1k] = useState('');
  const [embedPer1k, setEmbedPer1k] = useState('');
  const [rerankPer1k, setRerankPer1k] = useState('');
  const [perRequest, setPerRequest] = useState('');

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const catalog = await modelsApi.listAll();
        if (!mounted) return;
        setCatalogModels(Array.isArray(catalog.models) ? catalog.models : []);
      } catch {
        if (!mounted) return;
        setCatalogModels([]);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const inferredBaseUrl = useMemo(() => {
    const p = String(provider || '').trim().toLowerCase();
    if (!p) return '';
    const fromCatalog = catalogModels.find(
      (m) => String(m.provider || '').trim().toLowerCase() === p && String(m.base_url || '').trim()
    );
    const catalogBase = String(fromCatalog?.base_url || '').trim();
    if (catalogBase) return catalogBase;
    return KNOWN_PROVIDER_BASE_URLS[p] || '';
  }, [catalogModels, provider]);

  useEffect(() => {
    if (baseUrlEdited && String(baseUrl || '').trim()) return;
    setBaseUrl(inferredBaseUrl);
  }, [baseUrlEdited, baseUrl, inferredBaseUrl]);

  const showPricing = useMemo(() => {
    if (family === 'gen') return { input: true, output: true, embed: false, rerank: false, req: false };
    if (family === 'embed') return { input: false, output: false, embed: true, rerank: false, req: false };
    if (family === 'rerank') return { input: false, output: false, embed: false, rerank: unit === '1k_tokens', req: unit === 'request' };
    return { input: false, output: false, embed: false, rerank: unit === '1k_tokens', req: unit === 'request' };
  }, [family, unit]);

  const handleSubmit = async () => {
    const payload: ModelsUpsertRequest = {
      provider: provider.trim(),
      model: model.trim(),
      family,
      base_url: baseUrl.trim() || undefined,
      unit,
      input_per_1k: showPricing.input ? numOrNull(inputPer1k) : null,
      output_per_1k: showPricing.output ? numOrNull(outputPer1k) : null,
      embed_per_1k: showPricing.embed ? numOrNull(embedPer1k) : null,
      rerank_per_1k: showPricing.rerank ? numOrNull(rerankPer1k) : null,
      per_request: showPricing.req ? numOrNull(perRequest) : null,
    };

    if (!payload.provider || !payload.model) {
      throw new Error('Provider and model are required');
    }

    await upsertModel(payload);
  };

  return (
    <div
      data-testid="model-catalog-panel"
      className="settings-section"
      style={{ borderLeft: '3px solid var(--link)' }}
    >
      <h3 style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ color: 'var(--link)' }}>●</span> New Model Out? If the catalog hasn't updated, add it here!
      </h3>
      <p className="small" style={{ marginTop: 0 }}>
        Add or update an entry in the runtime server-side model catalog (<code>POST /api/models/upsert</code>).
        Base URL auto-fills by provider and stays editable before submit.
      </p>

      {error && (
        <div style={{ color: 'var(--err)', fontSize: '12px', marginBottom: '12px' }}>
          {error}
        </div>
      )}

      <div className="input-row">
        <div className="input-group">
          <label>Provider</label>
          <input
            data-testid="model-catalog-provider"
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              setBaseUrlEdited(false);
            }}
            placeholder="openai"
          />
        </div>
        <div className="input-group">
          <label>Model</label>
          <input data-testid="model-catalog-model" value={model} onChange={(e) => setModel(e.target.value)} placeholder="gpt-4o-mini" />
        </div>
      </div>

      <div className="input-row">
        <div className="input-group">
          <label>Family</label>
          <select data-testid="model-catalog-family" value={family} onChange={(e) => setFamily(e.target.value as any)}>
            <option value="gen">Generation</option>
            <option value="embed">Embeddings</option>
            <option value="rerank">Reranker</option>
            <option value="misc">Misc</option>
          </select>
        </div>
        <div className="input-group">
          <label>Unit</label>
          <select data-testid="model-catalog-unit" value={unit} onChange={(e) => setUnit(e.target.value as any)}>
            <option value="1k_tokens">$ / 1k tokens</option>
            <option value="request">$ / request</option>
          </select>
        </div>
        <div className="input-group">
          <label>Base URL (optional)</label>
          <input
            data-testid="model-catalog-base-url"
            value={baseUrl}
            onChange={(e) => {
              setBaseUrl(e.target.value);
              setBaseUrlEdited(true);
            }}
            placeholder="http://127.0.0.1:11434"
          />
          <div style={{ marginTop: '4px', fontSize: '11px', color: 'var(--fg-muted)' }}>
            Autofill: {inferredBaseUrl || 'No known default'}
          </div>
        </div>
      </div>

      <details style={{ marginTop: '8px' }}>
        <summary style={{ cursor: 'pointer', fontSize: '12px', fontWeight: 700, color: 'var(--fg)' }}>
          Pricing fields
        </summary>
        <div style={{ marginTop: '12px' }}>
          <div className="input-row" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
            {showPricing.input && (
              <div className="input-group">
                <label>Input $ / 1k</label>
                <input data-testid="model-catalog-input-per-1k" type="number" value={inputPer1k} onChange={(e) => setInputPer1k(e.target.value)} step={0.0001} min={0} />
              </div>
            )}
            {showPricing.output && (
              <div className="input-group">
                <label>Output $ / 1k</label>
                <input data-testid="model-catalog-output-per-1k" type="number" value={outputPer1k} onChange={(e) => setOutputPer1k(e.target.value)} step={0.0001} min={0} />
              </div>
            )}
            {showPricing.embed && (
              <div className="input-group">
                <label>Embed $ / 1k</label>
                <input data-testid="model-catalog-embed-per-1k" type="number" value={embedPer1k} onChange={(e) => setEmbedPer1k(e.target.value)} step={0.0001} min={0} />
              </div>
            )}
            {showPricing.rerank && (
              <div className="input-group">
                <label>Rerank $ / 1k</label>
                <input data-testid="model-catalog-rerank-per-1k" type="number" value={rerankPer1k} onChange={(e) => setRerankPer1k(e.target.value)} step={0.0001} min={0} />
              </div>
            )}
            {showPricing.req && (
              <div className="input-group">
                <label>$ / request</label>
                <input data-testid="model-catalog-per-request" type="number" value={perRequest} onChange={(e) => setPerRequest(e.target.value)} step={0.0001} min={0} />
              </div>
            )}
          </div>
        </div>
      </details>

      <div className="input-row" style={{ marginTop: '12px' }}>
        <button
          data-testid="model-catalog-submit"
          className="small-button"
          onClick={() => void handleSubmit()}
          disabled={saving}
          style={{ width: '100%', background: 'var(--accent)', color: 'var(--accent-contrast)', fontWeight: 700 }}
        >
          {saving ? 'Saving…' : 'Upsert model'}
        </button>
      </div>

      {lastResponse ? (
        <pre
          data-testid="model-catalog-response"
          className="result-display"
          style={{ marginTop: '12px', background: 'var(--code-bg)', whiteSpace: 'pre-wrap' }}
        >
          {JSON.stringify(lastResponse, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}
