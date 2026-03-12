import { useState, useEffect, useMemo } from 'react';
import { modelsApi } from '@/api/models';
import type { ModelCatalogEntry, ModelCatalogResponse } from '@/types/generated';

export type Model = ModelCatalogEntry;

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

// Cache /api/models globally to avoid refetching.
const modelsCache = new Map<string, ModelCatalogResponse>();
const modelsFetchPromises = new Map<string, Promise<ModelCatalogResponse>>();

function getActiveCorpusKey(): string {
  try {
    const u = new URL(window.location.href);
    return (
      u.searchParams.get('corpus') ||
      u.searchParams.get('repo') ||
      localStorage.getItem('tribrid_active_corpus') ||
      localStorage.getItem('tribrid_active_repo') ||
      ''
    ).trim();
  } catch {
    return (
      localStorage.getItem('tribrid_active_corpus') ||
      localStorage.getItem('tribrid_active_repo') ||
      ''
    ).trim();
  }
}

async function fetchModels(corpusKey: string): Promise<ModelCatalogResponse> {
  if (modelsCache.has(corpusKey)) return modelsCache.get(corpusKey)!;
  if (modelsFetchPromises.has(corpusKey)) return modelsFetchPromises.get(corpusKey)!;

  const request = modelsApi
    .listAll()
    .then((data) => {
      modelsCache.set(corpusKey, data);
      return data;
    })
    .catch((err) => {
      modelsFetchPromises.delete(corpusKey);
      throw err;
    });

  modelsFetchPromises.set(corpusKey, request);
  return request;
}

export function useModels(component: ComponentType): UseModelsResult {
  const [allModels, setAllModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [corpusKey, setCorpusKey] = useState<string>(() => getActiveCorpusKey());

  useEffect(() => {
    const syncCorpusKey = () => setCorpusKey(getActiveCorpusKey());
    window.addEventListener('tribrid-corpus-changed', syncCorpusKey as EventListener);
    window.addEventListener('tribrid-corpus-loaded', syncCorpusKey as EventListener);
    return () => {
      window.removeEventListener('tribrid-corpus-changed', syncCorpusKey as EventListener);
      window.removeEventListener('tribrid-corpus-loaded', syncCorpusKey as EventListener);
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    fetchModels(corpusKey)
      .then((data) => {
        if (!mounted) return;
        const rows = Array.isArray(data?.models) ? data.models : [];
        setAllModels(rows);
        setLoading(false);
      })
      .catch((err) => {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : 'Failed to load models');
        setLoading(false);
      });

    return () => { mounted = false; };
  }, [corpusKey]);

  // Filter models by component type
  const models = useMemo(() => {
    return allModels.filter((m) => {
      const comps = Array.isArray(m.components) ? m.components.map((c) => String(c).toUpperCase()) : [];
      return comps.includes(component);
    });
  }, [allModels, component]);

  // Get unique providers
  const providers = useMemo(() => {
    const unique = new Set(
      models
        .map((m) => String(m.provider || '').trim())
        .filter(Boolean)
    );
    return Array.from(unique).sort((a, b) => a.localeCompare(b));
  }, [models]);

  // Get models for a specific provider
  const getModelsForProvider = useMemo(() => {
    return (provider: string) => {
      const p = String(provider || '').trim().toLowerCase();
      return models.filter((m) => String(m.provider || '').trim().toLowerCase() === p);
    };
  }, [models]);

  // Find specific model
  const findModel = useMemo(() => {
    return (provider: string, modelName: string) =>
      models.find(
        (m) =>
          String(m.provider || '').trim().toLowerCase() === String(provider || '').trim().toLowerCase() &&
          String(m.model || '').trim() === String(modelName || '').trim()
      );
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
  const context = Number(model?.context || 0);
  if (context <= 0) return null;
  return Math.floor(context * 0.8);
}
