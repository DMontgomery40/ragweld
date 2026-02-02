import { useEffect, useMemo, useState } from 'react';
import { useConfigStore } from '@/stores';
import { EmbeddingMismatchWarning } from './ui/EmbeddingMismatchWarning';
import { useModels } from '@/hooks';

export function Sidepanel() {
  const config = useConfigStore((s) => s.config);
  const patchSection = useConfigStore((s) => s.patchSection);

  const {
    models: genModels,
    loading: genLoading,
    error: genError,
  } = useModels('GEN');
  const {
    providers: embeddingProviders,
    getModelsForProvider: getEmbeddingModelsForProvider,
    loading: embeddingModelsLoading,
    error: embeddingModelsError,
  } = useModels('EMB');
  const {
    providers: rerankProviders,
    getModelsForProvider: getRerankModelsForProvider,
    loading: rerankModelsLoading,
    error: rerankModelsError,
  } = useModels('RERANK');

  const genModelOptions = useMemo(() => {
    const unique = new Set(genModels.map((m) => m.model));
    return Array.from(unique).sort();
  }, [genModels]);

  const [genModel, setGenModel] = useState<string>('');
  const [embeddingProvider, setEmbeddingProvider] = useState<string>('openai');
  const [embeddingModel, setEmbeddingModel] = useState<string>('');
  const [rerankProvider, setRerankProvider] = useState<string>('cohere');
  const [rerankModel, setRerankModel] = useState<string>('');

  // Sync quick-model state from config (when it loads)
  useEffect(() => {
    if (!config) return;

    setGenModel(String(config.generation?.gen_model || ''));

    const embType = String(config.embedding?.embedding_type || 'openai');
    setEmbeddingProvider(embType);
    const embTypeLower = embType.toLowerCase();
    let embModel = String(config.embedding?.embedding_model || '');
    if (embTypeLower === 'voyage') embModel = String(config.embedding?.voyage_model || '');
    if (embTypeLower === 'local' || embTypeLower === 'huggingface' || embTypeLower === 'ollama') {
      embModel = String(config.embedding?.embedding_model_local || '');
    }
    setEmbeddingModel(embModel);

    const rrMode = String(config.reranking?.reranker_mode || '').toLowerCase();
    if (rrMode === 'cloud') {
      setRerankProvider(String(config.reranking?.reranker_cloud_provider || 'cohere'));
      setRerankModel(String(config.reranking?.reranker_cloud_model || ''));
    } else if (rrMode === 'local') {
      setRerankProvider('local');
      setRerankModel(String(config.reranking?.reranker_local_model || ''));
    } else if (rrMode === 'learning') {
      setRerankProvider('learning');
      setRerankModel(String(config.reranking?.reranker_local_model || ''));
    } else if (rrMode === 'none') {
      setRerankProvider('none');
      setRerankModel('');
    }
  }, [config]);

  const embeddingProviderOptions = useMemo(() => {
    const s = new Set<string>(embeddingProviders);
    if (embeddingProvider && !s.has(embeddingProvider)) s.add(embeddingProvider);
    return Array.from(s).sort();
  }, [embeddingProviders, embeddingProvider]);

  const embeddingModelOptions = useMemo(() => {
    const models = getEmbeddingModelsForProvider(embeddingProvider).map((m) => m.model);
    return Array.from(new Set(models)).sort();
  }, [embeddingProvider, getEmbeddingModelsForProvider]);

  const rerankProviderOptions = useMemo(() => {
    const s = new Set<string>(rerankProviders);
    // Ensure common logical modes remain selectable even if absent from models.json
    s.add('local');
    s.add('learning');
    s.add('none');
    if (rerankProvider && !s.has(rerankProvider)) s.add(rerankProvider);
    return Array.from(s).sort();
  }, [rerankProviders, rerankProvider]);

  const rerankModelOptions = useMemo(() => {
    if (!rerankProvider || rerankProvider === 'none') return [];
    if (rerankProvider === 'local' || rerankProvider === 'learning') {
      // For local/learning, present all RERANK models across providers as a fallback.
      const localModels = getRerankModelsForProvider('local').map((m) => m.model);
      const hfModels = getRerankModelsForProvider('huggingface').map((m) => m.model);
      const all = [...localModels, ...hfModels];
      return Array.from(new Set(all)).sort();
    }
    const models = getRerankModelsForProvider(rerankProvider).map((m) => m.model);
    return Array.from(new Set(models)).sort();
  }, [getRerankModelsForProvider, rerankProvider]);

  const handleApplyChanges = async () => {
    try {
      // Build updates for different config sections (TriBridConfig is the law)
      const embeddingUpdates: Record<string, unknown> = {};
      const rerankingUpdates: Record<string, unknown> = {};
      const generationUpdates: Record<string, unknown> = {};

      // Generation model
      if (genModel) {
        generationUpdates.gen_model = genModel;
      }

      // Embedding provider + model
      if (embeddingProvider) {
        const p = embeddingProvider.toLowerCase();
        if (p === 'voyage') {
          embeddingUpdates.embedding_type = 'voyage';
          if (embeddingModel) embeddingUpdates.voyage_model = embeddingModel;
        } else if (p === 'local' || p === 'ollama' || p === 'huggingface') {
          embeddingUpdates.embedding_type = 'local';
          if (embeddingModel) embeddingUpdates.embedding_model_local = embeddingModel;
        } else {
          embeddingUpdates.embedding_type = p;
          if (embeddingModel) embeddingUpdates.embedding_model = embeddingModel;
        }
      }

      // Reranker provider + model
      if (rerankProvider) {
        const p = rerankProvider.toLowerCase();
        if (p === 'none') {
          rerankingUpdates.reranker_mode = 'none';
        } else if (p === 'learning') {
          rerankingUpdates.reranker_mode = 'learning';
          if (rerankModel) rerankingUpdates.reranker_local_model = rerankModel;
        } else if (p === 'cohere' || p === 'voyage' || p === 'jina') {
          rerankingUpdates.reranker_mode = 'cloud';
          rerankingUpdates.reranker_cloud_provider = p;
          if (rerankModel) rerankingUpdates.reranker_cloud_model = rerankModel;
        } else {
          rerankingUpdates.reranker_mode = 'local';
          if (rerankModel) rerankingUpdates.reranker_local_model = rerankModel;
        }
      }

      // Apply updates to appropriate sections via Zustand store (keeps app in sync)
      if (Object.keys(embeddingUpdates).length > 0) {
        await patchSection('embedding', embeddingUpdates);
      }
      if (Object.keys(rerankingUpdates).length > 0) {
        await patchSection('reranking', rerankingUpdates);
      }
      if (Object.keys(generationUpdates).length > 0) {
        await patchSection('generation', generationUpdates);
      }

      // Dispatch config-updated event for legacy listeners
      window.dispatchEvent(
        new CustomEvent('config-updated', {
          detail: { embeddingUpdates, rerankingUpdates, generationUpdates },
        })
      );

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

      {/* Quick model switcher (no cost calculator) */}
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
            Quick Model Switcher
          </span>
        </div>

        {(genError || embeddingModelsError || rerankModelsError) ? (
          <div style={{ color: 'var(--err)', fontSize: '12px', marginBottom: '10px' }}>
            {genError || embeddingModelsError || rerankModelsError}
          </div>
        ) : null}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div>
            <label style={labelStyle}>GENERATION MODEL</label>
            <select
              value={genModel}
              onChange={(e) => setGenModel(e.target.value)}
              style={selectStyle}
              disabled={genLoading}
            >
              {genModelOptions.length > 0 ? (
                genModelOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))
              ) : (
                <option value={genModel}>{genLoading ? 'Loading…' : (genModel || '—')}</option>
              )}
            </select>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <label style={labelStyle}>EMBEDDING PROVIDER</label>
              <select
                value={embeddingProvider}
                onChange={(e) => {
                  const next = e.target.value;
                  setEmbeddingProvider(next);
                  const nextModels = getEmbeddingModelsForProvider(next).map((m) => m.model);
                  const nextUnique = Array.from(new Set(nextModels)).sort();
                  if (nextUnique.length > 0 && !nextUnique.includes(embeddingModel)) {
                    setEmbeddingModel(nextUnique[0]);
                  }
                }}
                style={selectStyle}
                disabled={embeddingModelsLoading}
              >
                {embeddingProviderOptions.map((p) => (
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
                onChange={(e) => setEmbeddingModel(e.target.value)}
                style={selectStyle}
                disabled={embeddingModelsLoading}
              >
                {embeddingModelOptions.length > 0 ? (
                  embeddingModelOptions.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))
                ) : (
                  <option value={embeddingModel}>{embeddingModelsLoading ? 'Loading…' : (embeddingModel || '—')}</option>
                )}
              </select>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <label style={labelStyle}>RERANKER</label>
              <select
                value={rerankProvider}
                onChange={(e) => {
                  const next = e.target.value;
                  setRerankProvider(next);
                  const nextModels =
                    next === 'none' ? [] : getRerankModelsForProvider(next).map((m) => m.model);
                  const nextUnique = Array.from(new Set(nextModels)).sort();
                  if (next !== 'none' && nextUnique.length > 0 && !nextUnique.includes(rerankModel)) {
                    setRerankModel(nextUnique[0]);
                  }
                  if (next === 'none') setRerankModel('');
                }}
                style={selectStyle}
                disabled={rerankModelsLoading}
              >
                {rerankProviderOptions.map((p) => (
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
                onChange={(e) => setRerankModel(e.target.value)}
                style={selectStyle}
                disabled={rerankModelsLoading || rerankProvider === 'none'}
              >
                {rerankProvider === 'none' ? (
                  <option value="">(disabled)</option>
                ) : rerankModelOptions.length > 0 ? (
                  rerankModelOptions.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))
                ) : (
                  <option value={rerankModel}>{rerankModelsLoading ? 'Loading…' : (rerankModel || '—')}</option>
                )}
              </select>
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
