/**
 * useModels - Load models from models.json filtered by component type
 *
 * Replaces legacy app.js:172-218 pattern of loading models.json into state.models
 * and populating datalists. Now provides typed React hook for model selection.
 */

import { useState, useEffect, useMemo } from 'react';

export interface Model {
  provider: string;
  family: string;
  model: string;
  components: string[];
  dimensions?: number;
  context?: number;
  unit?: string;
  notes?: string;
  // Pricing fields (optional)
  input_per_1k?: number;
  output_per_1k?: number;
  embed_per_1k?: number;
  rerank_per_1k?: number;
  per_request?: number;
}

interface ModelsData {
  currency: string;
  last_updated: string;
  sources: string[];
  models: Model[];
}

type ComponentType = 'EMB' | 'GEN' | 'RERANK';

interface UseModelsResult {
  models: Model[];
  loading: boolean;
  error: string | null;
  /** Get unique providers for this component type */
  providers: string[];
  /** Get models for a specific provider */
  getModelsForProvider: (provider: string) => Model[];
  /** Find a specific model by provider and model name */
  findModel: (provider: string, modelName: string) => Model | undefined;
}

// Cache models.json globally to avoid refetching
let modelsCache: ModelsData | null = null;
let modelsFetchPromise: Promise<ModelsData> | null = null;

async function fetchModels(): Promise<ModelsData> {
  if (modelsCache) return modelsCache;
  if (modelsFetchPromise) return modelsFetchPromise;

  // Use Vite's base URL to correctly resolve the models.json path
  const baseUrl = import.meta.env.BASE_URL || '/';
  const modelsUrl = `${baseUrl}models.json`.replace(/\/+/g, '/');

  modelsFetchPromise = fetch(modelsUrl)
    .then(res => {
      if (!res.ok) throw new Error(`Failed to load models.json: ${res.status}`);
      return res.json();
    })
    .then((data: ModelsData) => {
      modelsCache = data;
      return data;
    })
    .catch(err => {
      modelsFetchPromise = null;
      throw err;
    });

  return modelsFetchPromise;
}

export function useModels(component: ComponentType): UseModelsResult {
  const [allModels, setAllModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    fetchModels()
      .then(data => {
        if (!mounted) return;
        setAllModels(data.models);
        setLoading(false);
      })
      .catch(err => {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : 'Failed to load models');
        setLoading(false);
      });

    return () => { mounted = false; };
  }, []);

  // Filter models by component type
  const models = useMemo(() => {
    return allModels.filter(m => m.components.includes(component));
  }, [allModels, component]);

  // Get unique providers
  const providers = useMemo(() => {
    const unique = new Set(models.map(m => m.provider));
    return Array.from(unique).sort();
  }, [models]);

  // Get models for a specific provider
  const getModelsForProvider = useMemo(() => {
    return (provider: string) => models.filter(m => m.provider === provider);
  }, [models]);

  // Find specific model
  const findModel = useMemo(() => {
    return (provider: string, modelName: string) =>
      models.find(m => m.provider === provider && m.model === modelName);
  }, [models]);

  return {
    models,
    loading,
    error,
    providers,
    getModelsForProvider,
    findModel,
  };
}

/**
 * Get recommended chunk size based on model's context window
 * Returns 80% of context to leave headroom for safety
 */
export function getRecommendedChunkSize(model: Model | undefined): number | null {
  if (!model?.context) return null;
  return Math.floor(model.context * 0.8);
}
