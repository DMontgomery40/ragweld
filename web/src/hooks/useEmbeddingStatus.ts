/**
 * useEmbeddingStatus Hook
 * 
 * Detects embedding configuration mismatches between the current config
 * and what was used to create the index. This is CRITICAL because mismatched
 * embeddings will cause search to return completely irrelevant results.
 */

import { useState, useEffect, useCallback } from 'react';
import { useAPI } from '@/hooks/useAPI';
import { useConfig } from '@/hooks/useConfig';
import { useRuntimeCapabilities } from '@/hooks/useRuntimeCapabilities';
import { useRepoStore } from '@/stores/useRepoStore';
import type { IndexStats } from '@/types/generated';
import { describeEmbeddingProviderStrategy } from '@/utils/embeddingStrategy';

export interface EmbeddingStatus {
  // Current configuration (from tribrid_config.json / env)
  configType: string;
  configStrategy: string;
  configDim: number;
  configModel: string;
  
  // Index configuration (from last_index.json)
  indexProvider: string | null;
  indexStrategy: string | null;
  indexType: string | null;
  indexDim: number | null;
  indexedAt: string | null;
  indexPath: string | null;
  
  // Mismatch status
  isMismatched: boolean;
  hasIndex: boolean;
  
  // Detailed comparison
  typeMatch: boolean;
  dimMatch: boolean;
  modelMatch: boolean;
  
  // Index stats
  totalChunks: number;
}

interface UseEmbeddingStatusResult {
  status: EmbeddingStatus | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useEmbeddingStatus(): UseEmbeddingStatusResult {
  const { api } = useAPI();
  const { config } = useConfig();
  const { capabilities } = useRuntimeCapabilities();
  const { activeRepo } = useRepoStore();

  const [status, setStatus] = useState<EmbeddingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const checkStatus = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const corpusId = String(activeRepo || '').trim();
      if (!corpusId || !config) {
        setStatus(null);
        return;
      }

      // Current config (TriBridConfig is the law)
      const emb = config.embedding;
      const provider = String(emb?.embedding_type || '').toLowerCase();
      const configType = provider || 'openai';
      const configStrategy = describeEmbeddingProviderStrategy(configType, capabilities || undefined).detail;
      const configDim = Number(emb?.embedding_dim || 0);
      let configModel = String(emb?.embedding_model || '');
      if (provider === 'voyage') configModel = String(emb?.voyage_model || '');
      if (provider === 'local' || provider === 'huggingface' || provider === 'ollama') {
        configModel = String(emb?.embedding_model_local || '');
      }

      // Index config (from Postgres corpus metadata via /api/index/{corpus_id}/stats)
      const response = await fetch(api(`index/${encodeURIComponent(corpusId)}/stats`));
      if (response.status === 404) {
        setStatus({
          configType,
          configStrategy,
          configDim,
          configModel,
          indexProvider: null,
          indexStrategy: null,
          indexType: null,
          indexDim: null,
          indexedAt: null,
          indexPath: null,
          hasIndex: false,
          isMismatched: false,
          typeMatch: true,
          dimMatch: true,
          modelMatch: true,
          totalChunks: 0,
        });
        return;
      }
      if (!response.ok) {
        throw new Error(`Failed to fetch index stats: ${response.status}`);
      }

      const data: IndexStats = await response.json();
      const totalChunks = Number(data.total_chunks || 0);
      const indexProviderRaw = String(data.embedding_provider || '').trim();
      const indexModelRaw = String(data.embedding_model || '').trim();
      const indexDimRaw = Number(data.embedding_dimensions || 0);

      // Treat empty/0 as “no dense embedding index” (e.g., skip-dense runs).
      const indexType = indexModelRaw ? indexModelRaw : null;
      const indexDim = indexDimRaw > 0 ? indexDimRaw : null;
      const indexProvider = indexProviderRaw ? indexProviderRaw : null;
      const indexStrategy = indexProvider
        ? describeEmbeddingProviderStrategy(indexProvider, capabilities || undefined).detail
        : null;
      const hasIndex = Boolean(indexType && indexDim && totalChunks > 0);

      const dimMatch = hasIndex ? configDim === indexDim : true;
      const modelMatch = hasIndex ? configModel === indexType : true;
      const typeMatch = hasIndex && indexProvider ? configType === String(indexProvider).toLowerCase() : true;

      setStatus({
        configType,
        configStrategy,
        configDim,
        configModel,
        indexProvider,
        indexStrategy,
        indexType,
        indexDim,
        indexedAt: data.last_indexed ? String(data.last_indexed) : null,
        indexPath: null,
        hasIndex,
        isMismatched: hasIndex ? !(typeMatch && dimMatch && modelMatch) : false,
        typeMatch,
        dimMatch,
        modelMatch,
        totalChunks,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error checking embedding status');
      console.error('[useEmbeddingStatus] Error:', err);
    } finally {
      setLoading(false);
    }
  }, [activeRepo, api, capabilities, config]);

  // Initial check on mount
  useEffect(() => {
    checkStatus();

    // Re-check on config changes and index completion
    const handleConfigChange = () => checkStatus();
    window.addEventListener('config-updated', handleConfigChange);
    window.addEventListener('index-completed', handleConfigChange);
    window.addEventListener('dashboard-refresh', handleConfigChange);
    window.addEventListener('tribrid-corpus-changed', handleConfigChange as EventListener);

    return () => {
      window.removeEventListener('config-updated', handleConfigChange);
      window.removeEventListener('index-completed', handleConfigChange);
      window.removeEventListener('dashboard-refresh', handleConfigChange);
      window.removeEventListener('tribrid-corpus-changed', handleConfigChange as EventListener);
    };
  }, [checkStatus]);

  return {
    status,
    loading,
    error,
    refresh: checkStatus,
  };
}
