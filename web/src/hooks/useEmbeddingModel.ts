import { useCallback, useMemo } from 'react';
import { useConfigField } from './useConfig';

/**
 * Derives the active embedding model field, setter, and tooltip key
 * based on the current embedding_type (provider).
 */
export function useEmbeddingModel() {
  const [embeddingType] = useConfigField<string>('embedding.embedding_type', '');
  const [embeddingModel, setEmbeddingModel] = useConfigField<string>('embedding.embedding_model', '');
  const [voyageModel, setVoyageModel] = useConfigField<string>('embedding.voyage_model', '');
  const [embeddingModelLocal, setEmbeddingModelLocal] = useConfigField<string>('embedding.embedding_model_local', '');
  const [embeddingModelMlx, setEmbeddingModelMlx] = useConfigField<string>('embedding.embedding_model_mlx', '');
  const isLocalProvider = useCallback((provider: string) => {
    return provider === 'local' || provider === 'huggingface' || provider === 'ollama';
  }, []);

  const currentModel = useMemo(() => {
    const t = String(embeddingType || '').toLowerCase();
    if (t === 'voyage') return String(voyageModel || '');
    if (t === 'mlx') return String(embeddingModelMlx || '');
    if (isLocalProvider(t)) return String(embeddingModelLocal || '');
    return String(embeddingModel || '');
  }, [embeddingType, embeddingModel, embeddingModelLocal, embeddingModelMlx, isLocalProvider, voyageModel]);

  const setCurrentModel = useCallback(
    (modelName: string) => {
      const t = String(embeddingType || '').toLowerCase();
      if (t === 'voyage') { setVoyageModel(modelName); return; }
      if (t === 'mlx') { setEmbeddingModelMlx(modelName); return; }
      if (isLocalProvider(t)) { setEmbeddingModelLocal(modelName); return; }
      setEmbeddingModel(modelName);
    },
    [embeddingType, isLocalProvider, setEmbeddingModel, setEmbeddingModelLocal, setEmbeddingModelMlx, setVoyageModel],
  );

  const tooltipKey = useMemo(() => {
    const t = String(embeddingType || '').toLowerCase();
    if (t === 'voyage') return 'VOYAGE_MODEL';
    if (t === 'mlx') return 'EMBEDDING_MODEL_MLX';
    if (isLocalProvider(t)) return 'EMBEDDING_MODEL_LOCAL';
    return 'EMBEDDING_MODEL';
  }, [embeddingType, isLocalProvider]);

  return { embeddingType, currentModel, setCurrentModel, tooltipKey };
}
