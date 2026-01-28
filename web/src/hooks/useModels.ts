/**
 * useModels - Hook for fetching model definitions from /api/models
 *
 * THIS IS THE ONLY WAY to get model options in the UI.
 * NO HARDCODED MODEL LISTS ANYWHERE.
 *
 * Usage:
 *   const { models, loading, providers } = useModels('EMB');  // Embedding models only
 *   const { models, loading, providers } = useModels('GEN');  // Generation models only
 *   const { models, loading, providers } = useModels('RERANK');  // Reranker models only
 *   const { models, loading, providers } = useModels();  // All models
 */
import { useState, useEffect, useCallback, useMemo } from 'react';

export type ComponentType = 'EMB' | 'GEN' | 'RERANK';

export interface ModelDefinition {
  provider: string;
  family: string;
  model: string;
  components: ComponentType[];
  dimensions?: number;
  context: number;
  input_per_1k?: number;
  output_per_1k?: number;
  embed_per_1k?: number;
  rerank_per_1k?: number;
  per_request?: number;
}

export interface UseModelsResult {
  models: ModelDefinition[];
  loading: boolean;
  error: string | null;
  providers: string[];
  getModelsForProvider: (provider: string) => ModelDefinition[];
  findModel: (provider: string, modelName: string) => ModelDefinition | undefined;
  refresh: () => Promise<void>;
}

// Global cache - shared across all hook instances
let modelsCache: ModelDefinition[] | null = null;
let cacheTimestamp: number = 0;
const CACHE_TTL_MS = 60000; // 60 seconds

const LOCAL_PROVIDERS = new Set(['ollama', 'huggingface', 'local', 'sentence-transformers']);

function isLocalProvider(provider: string): boolean {
  return LOCAL_PROVIDERS.has(provider.toLowerCase());
}

export function useModels(componentType?: ComponentType): UseModelsResult {
  const [models, setModels] = useState<ModelDefinition[]>(modelsCache || []);
  const [loading, setLoading] = useState<boolean>(!modelsCache);
  const [error, setError] = useState<string | null>(null);

  const fetchModels = useCallback(async () => {
    // Check cache validity
    if (modelsCache && Date.now() - cacheTimestamp < CACHE_TTL_MS) {
      setModels(modelsCache);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/models');
      if (!response.ok) {
        throw new Error(`Failed to fetch models: HTTP ${response.status}`);
      }
      const data: ModelDefinition[] = await response.json();

      // Update global cache
      modelsCache = data;
      cacheTimestamp = Date.now();

      setModels(data);
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : 'Unknown error fetching models';
      setError(errorMessage);
      console.error('useModels fetch error:', errorMessage);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchModels();
  }, [fetchModels]);

  // Filter by component type if specified
  const filteredModels = useMemo(() => {
    if (!componentType) return models;
    return models.filter(m => m.components?.includes(componentType));
  }, [models, componentType]);

  // Get unique providers (grouping local providers as "Local")
  const providers = useMemo(() => {
    const providerSet = new Set<string>();
    let hasLocal = false;

    filteredModels.forEach(m => {
      if (isLocalProvider(m.provider)) {
        hasLocal = true;
      } else {
        providerSet.add(m.provider);
      }
    });

    const cloudProviders = Array.from(providerSet).sort();
    return hasLocal ? ['Local', ...cloudProviders] : cloudProviders;
  }, [filteredModels]);

  const getModelsForProvider = useCallback((provider: string): ModelDefinition[] => {
    if (provider === 'Local') {
      return filteredModels.filter(m => isLocalProvider(m.provider));
    }
    return filteredModels.filter(m => m.provider.toLowerCase() === provider.toLowerCase());
  }, [filteredModels]);

  const findModel = useCallback((provider: string, modelName: string): ModelDefinition | undefined => {
    return models.find(m =>
      m.provider.toLowerCase() === provider.toLowerCase() &&
      m.model.toLowerCase() === modelName.toLowerCase()
    );
  }, [models]);

  return {
    models: filteredModels,
    loading,
    error,
    providers,
    getModelsForProvider,
    findModel,
    refresh: fetchModels,
  };
}

// Convenience hooks for specific component types
export const useEmbeddingModels = () => useModels('EMB');
export const useGenerationModels = () => useModels('GEN');
export const useRerankerModels = () => useModels('RERANK');

// Re-export for convenience
export default useModels;
