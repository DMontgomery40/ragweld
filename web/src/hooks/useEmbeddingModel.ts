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

  const currentModel = useMemo(() => {
    const t = String(embeddingType || '').toLowerCase();
    if (t === 'voyage') return String(voyageModel || '');
    if (t === 'openai') return String(embeddingModel || '');
    if (t === 'mlx') return String(embeddingModelMlx || '');
    return String(embeddingModelLocal || '');
  }, [embeddingType, embeddingModel, embeddingModelLocal, embeddingModelMlx, voyageModel]);

  const setCurrentModel = useCallback(
    (modelName: string) => {
      const t = String(embeddingType || '').toLowerCase();
      if (t === 'voyage') { setVoyageModel(modelName); return; }
      if (t === 'openai') { setEmbeddingModel(modelName); return; }
      if (t === 'mlx') { setEmbeddingModelMlx(modelName); return; }
      setEmbeddingModelLocal(modelName);
    },
    [embeddingType, setEmbeddingModel, setEmbeddingModelLocal, setEmbeddingModelMlx, setVoyageModel],
  );

  const tooltipKey = useMemo(() => {
    const t = String(embeddingType || '').toLowerCase();
    if (t === 'voyage') return 'VOYAGE_MODEL';
    if (t === 'openai') return 'EMBEDDING_MODEL';
    if (t === 'mlx') return 'EMBEDDING_MODEL_MLX';
    return 'EMBEDDING_MODEL_LOCAL';
  }, [embeddingType]);

  return { embeddingType, currentModel, setCurrentModel, tooltipKey };
}
