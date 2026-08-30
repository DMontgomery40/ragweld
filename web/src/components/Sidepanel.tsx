import { useEffect, useMemo, useState } from 'react';
import { useConfigStore } from '@/stores';
import { showToast } from '@/utils/toast';
import { EmbeddingMismatchWarning } from './ui/EmbeddingMismatchWarning';
import { ModelPicker as ChatModelPicker } from './Chat/ModelPicker';
import { useAPI, useEmbeddingModel, useModels } from '@/hooks';
import { useRepoStore } from '@/stores/useRepoStore';
import type { ChatModelInfo, ChatModelsResponse } from '@/types/generated';

export function Sidepanel() {
  const config = useConfigStore((s) => s.config);
  const patchSection = useConfigStore((s) => s.patchSection);
  const { api } = useAPI();
  const activeRepo = useRepoStore((s) => s.activeRepo);
  const {
    providers: embeddingProviders,
    getModelsForProvider: getEmbeddingModelsForProvider,
    loading: embeddingModelsLoading,
    error: embeddingModelsError,
  } = useModels('EMB', { selectionRole: 'embedding_provider' });
  const {
    providers: rerankProviders,
    getModelsForProvider: getRerankModelsForProvider,
    loading: rerankModelsLoading,
    error: rerankModelsError,
  } = useModels('RERANK', { selectionRole: 'reranker_cloud' });

  // Embedding model (derived from config via shared hook)
  const { embeddingType: configEmbeddingType, currentModel: configEmbeddingModel } = useEmbeddingModel();

  const [genModel, setGenModel] = useState<string>('');
  const [generationModels, setGenerationModels] = useState<ChatModelInfo[]>([]);
  const [embeddingProvider, setEmbeddingProvider] = useState<string>('openai');
  const [embeddingModel, setEmbeddingModel] = useState<string>('');
  const [rerankProvider, setRerankProvider] = useState<string>('cohere');
  const [rerankModel, setRerankModel] = useState<string>('');

  // Sync quick-model state from config (when it loads)
  useEffect(() => {
    if (!config) return;

    setGenModel(String(config.generation?.gen_model || ''));

    // Embedding provider + model (via useEmbeddingModel hook)
    setEmbeddingProvider(configEmbeddingType || 'openai');
    setEmbeddingModel(configEmbeddingModel);

    const rrMode = String(config.reranking?.reranker_mode || '').toLowerCase();
    if (rrMode === 'cloud') {
      setRerankProvider(String(config.reranking?.reranker_cloud_provider || 'litellm'));
      setRerankModel(String(config.reranking?.reranker_cloud_model || ''));
    } else if (rrMode === 'learning') {
      setRerankProvider('learning');
      setRerankModel('');
    } else if (rrMode === 'none') {
      setRerankProvider('none');
      setRerankModel('');
    }
  }, [config, configEmbeddingType, configEmbeddingModel]);

  useEffect(() => {
    const controller = new AbortController();
    const scope = String(activeRepo || '').trim();
    const query = scope ? `?corpus_id=${encodeURIComponent(scope)}` : '';
    fetch(api(`chat/models${query}`), { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then((payload) => {
        const rows = (payload as ChatModelsResponse).models;
        setGenerationModels(Array.isArray(rows) ? rows : []);
      })
      .catch((cause) => {
        if (cause instanceof DOMException && cause.name === 'AbortError') return;
        setGenerationModels([]);
      });
    return () => controller.abort();
  }, [activeRepo, api]);

  const generationAliasUnavailable = Boolean(
    genModel && !generationModels.some((model) => String(model.id || '').trim() === genModel),
  );

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
    const s = new Set<string>(
      rerankProviders.filter((p) => !['local', 'huggingface'].includes(String(p || '').toLowerCase()))
    );
    // Ensure common logical modes remain selectable even if absent from models.json
    s.add('learning');
    s.add('none');
    if (rerankProvider && !s.has(rerankProvider)) s.add(rerankProvider);
    return Array.from(s).sort();
  }, [rerankProviders, rerankProvider]);

  const rerankModelOptions = useMemo(() => {
    if (!rerankProvider || rerankProvider === 'none') return [];
    if (rerankProvider === 'learning') return [];
    const models = getRerankModelsForProvider(rerankProvider).map((m) => m.model);
    return Array.from(new Set(models)).sort();
  }, [getRerankModelsForProvider, rerankProvider]);

  const handleApplyChanges = async () => {
    try {
      if (generationAliasUnavailable) {
        throw new Error(`Generation alias '${genModel}' is not available from LiteLLM`);
      }
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
        if (p === 'mlx') {
          embeddingUpdates.embedding_type = 'mlx';
          if (embeddingModel) embeddingUpdates.embedding_model_mlx = embeddingModel;
        } else if (p === 'voyage') {
          embeddingUpdates.embedding_type = 'voyage';
          if (embeddingModel) embeddingUpdates.voyage_model = embeddingModel;
        } else if (p === 'local' || p === 'ollama' || p === 'huggingface') {
          embeddingUpdates.embedding_type = p;
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
        } else {
          rerankingUpdates.reranker_mode = 'cloud';
          rerankingUpdates.reranker_cloud_provider = p;
          if (rerankModel) rerankingUpdates.reranker_cloud_model = rerankModel;
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

      showToast('Changes applied successfully', 'success');
    } catch (e) {
      console.error('[Sidepanel] Apply changes error:', e);
      showToast(e instanceof Error ? e.message : 'Error applying changes', 'error');
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
          <span style={{ color: 'var(--accent-text)', fontSize: '8px' }}>●</span>
          <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--fg)' }}>
            Quick Model Switcher
          </span>
        </div>

        {(embeddingModelsError || rerankModelsError) ? (
          <div style={{ color: 'var(--err)', fontSize: '12px', marginBottom: '10px' }}>
            {embeddingModelsError || rerankModelsError}
          </div>
        ) : null}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div>
            <ChatModelPicker
              value={genModel}
              onChange={setGenModel}
              models={generationModels}
              valueMode="id"
            />
            {generationAliasUnavailable ? (
              <div style={{ color: 'var(--err)', fontSize: '11px', marginTop: '4px' }}>
                Choose an available LiteLLM alias before applying changes.
              </div>
            ) : null}
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
                      {`${embeddingProvider} · ${m}`}
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
                  if (next === 'learning') {
                    setRerankModel('');
                    return;
                  }
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
                disabled={rerankModelsLoading || rerankProvider === 'none' || rerankProvider === 'learning'}
              >
                {rerankProvider === 'none' ? (
                  <option value="">(disabled)</option>
                ) : rerankProvider === 'learning' ? (
                  <option value="">(learning reranker)</option>
                ) : rerankModelOptions.length > 0 ? (
                  rerankModelOptions.map((m) => (
                    <option key={m} value={m}>
                      {`${rerankProvider} · ${m}`}
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

      {/* Apply Changes Button - Always at bottom */}
      <div
        style={{
          marginTop: 'auto',
          paddingTop: '16px',
        }}
      >
        <button
          onClick={handleApplyChanges}
          disabled={generationAliasUnavailable}
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
