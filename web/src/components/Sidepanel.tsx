import { useEffect } from 'react';
import { useConfigStore, useCostCalculatorStore } from '@/stores';
import { configApi } from '@/api/config';
import { EmbeddingMismatchWarning } from './ui/EmbeddingMismatchWarning';

export function Sidepanel() {
  const { config } = useConfigStore();
  const {
    // State
    inferenceProvider,
    inferenceModel,
    embeddingProvider,
    embeddingModel,
    rerankProvider,
    rerankModel,
    tokensIn,
    tokensOut,
    embeds,
    reranks,
    requestsPerDay,
    dailyCost,
    monthlyCost,
    calculating,
    providers,
    chatModels,
    embedModels,
    rerankModels,
    modelsLoading,
    // Actions
    setProvider,
    setModel,
    setTokensIn,
    setTokensOut,
    setEmbeds,
    setReranks,
    setRequestsPerDay,
    calculateCost,
    loadProviders,
    syncFromConfig,
  } = useCostCalculatorStore();

  // Load providers on mount
  useEffect(() => {
    loadProviders();
  }, [loadProviders]);

  // Sync from config when it loads
  useEffect(() => {
    if (config) {
      syncFromConfig(config);
    }
  }, [config, syncFromConfig]);

  const handleApplyChanges = async () => {
    try {
      // Build updates for different config sections
      const embeddingUpdates: Record<string, string> = {};
      const rerankerUpdates: Record<string, string> = {};
      const generationUpdates: Record<string, string> = {};

      // Generation model
      if (inferenceModel) {
        generationUpdates.model = inferenceModel;
      }

      // Embedding model and type
      if (embeddingModel) {
        embeddingUpdates.model = embeddingModel;
      }
      if (embeddingProvider) {
        const p = embeddingProvider.toLowerCase();
        if (['local', 'ollama', 'huggingface'].includes(p)) {
          embeddingUpdates.type = 'local';
        } else {
          embeddingUpdates.type = p;
        }
      }

      // Reranker configuration
      if (rerankProvider) {
        const p = rerankProvider.toLowerCase();
        if (p === 'cohere') {
          rerankerUpdates.mode = 'cloud';
          rerankerUpdates.cloud_provider = 'cohere';
          rerankerUpdates.cloud_model = rerankModel;
        } else if (p === 'voyage') {
          rerankerUpdates.mode = 'cloud';
          rerankerUpdates.cloud_provider = 'voyage';
          rerankerUpdates.cloud_model = rerankModel;
        } else if (['local', 'ollama', 'huggingface'].includes(p)) {
          rerankerUpdates.mode = 'local';
          rerankerUpdates.local_model = rerankModel;
        }
      }

      // Apply updates to appropriate sections via configApi
      if (Object.keys(embeddingUpdates).length > 0) {
        await configApi.patchSection('embedding', embeddingUpdates);
      }
      if (Object.keys(rerankerUpdates).length > 0) {
        await configApi.patchSection('reranker', rerankerUpdates);
      }
      if (Object.keys(generationUpdates).length > 0) {
        await configApi.patchSection('generation', generationUpdates);
      }

      // Dispatch config-updated event for other components
      window.dispatchEvent(new CustomEvent('config-updated', {
        detail: { embeddingUpdates, rerankerUpdates, generationUpdates }
      }));

      alert('Changes applied successfully');
    } catch (e) {
      console.error('[Sidepanel] Apply changes error:', e);
      alert(e instanceof Error ? e.message : 'Error applying changes');
    }
  };

  // TODO: Implement storage cleanup when /api/storage/cleanup endpoint exists

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: '16px' }}>
      {/* Embedding Mismatch Warning - Critical visibility */}
      <EmbeddingMismatchWarning variant="inline" showActions={true} />

      {/* Live Cost Calculator Widget */}
      <div
        style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '16px',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            marginBottom: '12px',
          }}
        >
          <span style={{ color: 'var(--accent)', fontSize: '8px' }}>●</span>
          <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--fg)' }}>
            Live Cost Calculator
          </span>
          <span
            style={{
              background: calculating ? 'var(--warn)' : 'var(--accent)',
              color: calculating ? 'var(--bg)' : 'var(--accent-contrast)',
              fontSize: '9px',
              fontWeight: 600,
              padding: '2px 6px',
              borderRadius: '4px',
              marginLeft: 'auto',
            }}
          >
            {calculating ? 'CALC...' : 'LIVE'}
          </span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {/* Inference Provider */}
          <div>
            <label style={labelStyle}>INFERENCE PROVIDER</label>
            <select
              value={inferenceProvider}
              onChange={(e) => setProvider('inference', e.target.value)}
              style={selectStyle}
              disabled={modelsLoading}
            >
              {providers.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>

          {/* Inference Model */}
          <div>
            <label style={labelStyle}>INFERENCE MODEL</label>
            <select
              value={inferenceModel}
              onChange={(e) => setModel('inference', e.target.value)}
              style={selectStyle}
            >
              {chatModels.length > 0 ? (
                chatModels.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))
              ) : (
                <option value={inferenceModel}>{inferenceModel || 'Loading...'}</option>
              )}
            </select>
          </div>

          {/* Embedding Provider & Model */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <label style={labelStyle}>EMBEDDING PROVIDER</label>
              <select
                value={embeddingProvider}
                onChange={(e) => setProvider('embedding', e.target.value)}
                style={selectStyle}
              >
                {providers.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label style={labelStyle}>EMBEDDING MODEL</label>
              <select
                value={embeddingModel}
                onChange={(e) => setModel('embedding', e.target.value)}
                style={selectStyle}
              >
                {embedModels.length > 0 ? (
                  embedModels.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))
                ) : (
                  <option value={embeddingModel}>{embeddingModel || 'Loading...'}</option>
                )}
              </select>
            </div>
          </div>

          {/* Reranker Provider & Model */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <label style={labelStyle}>RERANKER</label>
              <select
                value={rerankProvider}
                onChange={(e) => setProvider('rerank', e.target.value)}
                style={selectStyle}
              >
                {providers.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label style={labelStyle}>RERANK MODEL</label>
              <select
                value={rerankModel}
                onChange={(e) => setModel('rerank', e.target.value)}
                style={selectStyle}
              >
                {rerankModels.length > 0 ? (
                  rerankModels.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))
                ) : (
                  <option value={rerankModel}>{rerankModel || 'Loading...'}</option>
                )}
              </select>
            </div>
          </div>

          {/* Token Inputs */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <label style={labelStyle}>TOKENS IN</label>
              <input
                type="number"
                value={tokensIn}
                onChange={(e) => setTokensIn(Number(e.target.value))}
                style={inputStyle}
              />
            </div>
            <div>
              <label style={labelStyle}>TOKENS OUT</label>
              <input
                type="number"
                value={tokensOut}
                onChange={(e) => setTokensOut(Number(e.target.value))}
                style={inputStyle}
              />
            </div>
          </div>

          {/* Embeds & Reranks */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <label style={labelStyle}>EMBEDS</label>
              <input
                type="number"
                value={embeds}
                onChange={(e) => setEmbeds(Number(e.target.value))}
                style={inputStyle}
              />
            </div>
            <div>
              <label style={labelStyle}>RERANKS</label>
              <input
                type="number"
                value={reranks}
                onChange={(e) => setReranks(Number(e.target.value))}
                style={inputStyle}
              />
            </div>
          </div>

          {/* Requests Per Day */}
          <div>
            <label style={labelStyle}>REQUESTS / DAY</label>
            <input
              type="number"
              value={requestsPerDay}
              onChange={(e) => setRequestsPerDay(Number(e.target.value))}
              style={inputStyle}
            />
          </div>

          {/* Action Buttons */}
          <button
            onClick={calculateCost}
            disabled={calculating}
            style={{
              width: '100%',
              background: calculating ? 'var(--fg-muted)' : 'var(--link)',
              color: 'white',
              border: 'none',
              padding: '10px',
              borderRadius: '4px',
              fontWeight: 600,
              cursor: calculating ? 'not-allowed' : 'pointer',
              marginTop: '4px',
            }}
          >
            {calculating ? 'CALCULATING...' : 'CALCULATE COST'}
          </button>

          {/* Cost Results */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: '8px',
              marginTop: '8px',
            }}
          >
            <div>
              <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>
                DAILY
              </div>
              <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--fg)' }}>
                {dailyCost}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>
                MONTHLY
              </div>
              <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--fg)' }}>
                {monthlyCost}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Secrets Ingest Widget */}
      <div
        style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '16px',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            marginBottom: '12px',
          }}
        >
          <span style={{ color: 'var(--accent)', fontSize: '8px' }}>●</span>
          <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--fg)' }}>
            Secrets Ingest
          </span>
        </div>

        <div
          style={{
            border: '2px dashed var(--line)',
            borderRadius: '6px',
            padding: '32px 16px',
            textAlign: 'center',
            color: 'var(--fg-muted)',
            fontSize: '12px',
            marginBottom: '8px',
          }}
        >
          Drop any .env / .ini / .md
          <br />
          or click to upload
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
          <input
            type="checkbox"
            defaultChecked
            style={{
              width: '16px',
              height: '16px',
              cursor: 'pointer',
            }}
          />
          <span style={{ fontSize: '11px', color: 'var(--fg)' }}>Persist to defaults.json</span>
        </label>
      </div>

      {/* Apply Changes Button - Always at bottom */}
      <div
        style={{
          marginTop: 'auto',
          paddingTop: '16px',
        }}
      >
        <button
          onClick={handleApplyChanges}
          style={{
            width: '100%',
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            border: 'none',
            padding: '14px',
            borderRadius: '6px',
            fontWeight: 700,
            fontSize: '14px',
            cursor: 'pointer',
            boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
          }}
        >
          Apply Changes
        </button>
      </div>
    </div>
  );
}

// Shared styles
const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: '11px',
  color: 'var(--fg-muted)',
  marginBottom: '4px',
};

const selectStyle: React.CSSProperties = {
  width: '100%',
  background: 'var(--input-bg)',
  border: '1px solid var(--line)',
  color: 'var(--fg)',
  padding: '6px 8px',
  borderRadius: '4px',
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  background: 'var(--input-bg)',
  border: '1px solid var(--line)',
  color: 'var(--fg)',
  padding: '6px 8px',
  borderRadius: '4px',
};
