import { useState, useEffect, useCallback, useRef, type CSSProperties } from 'react';
import { EmbeddingMismatchWarning } from '@/components/ui/EmbeddingMismatchWarning';
import { LiveTerminal, type LiveTerminalHandle } from '@/components/LiveTerminal/LiveTerminal';
import { IntentMatrixEditor } from '@/components/RAG/IntentMatrixEditor';
import { ModelAssignments } from '@/components/RAG/ModelAssignments';
import { ModelPicker } from '@/components/RAG/ModelPicker';
import { PromptLink } from '@/components/ui/PromptLink';
import { ApiKeyStatus } from '@/components/ui/ApiKeyStatus';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { createAlertError, createInlineError } from '@/utils/errorHelpers';
import { useConfig, useConfigField } from '@/hooks';
import { tracesApi } from '@/api';
import { useRepoStore } from '@/stores/useRepoStore';
import type { TracesLatestResponse } from '@/types/generated';

type RetrievalCardId = 'search_paths' | 'fusion_scoring' | 'generation' | 'ops_tracing';
type OpsTracingViewId = 'runtime_compatibility' | 'observability_integrations';

const RETRIEVAL_CARDS: Array<{
  id: RetrievalCardId;
  icon: string;
  label: string;
  description: string;
}> = [
  {
    id: 'search_paths',
    icon: '🧭',
    label: 'Search Paths',
    description: 'Vector, sparse, graph, and retrieval shaping controls',
  },
  {
    id: 'fusion_scoring',
    icon: '⚖️',
    label: 'Fusion & Scoring',
    description: 'Fusion strategy, scoring boosts, layer weighting',
  },
  {
    id: 'generation',
    icon: '🧠',
    label: 'Generation',
    description: 'Answer and enrichment models, budgets, transport overrides',
  },
  {
    id: 'ops_tracing',
    icon: '📈',
    label: 'Ops & Tracing',
    description: 'Hydration, compatibility knobs, trace/telemetry settings',
  },
];

const PANEL_STYLE = {
  background: 'var(--card-bg)',
  border: '1px solid var(--line)',
  borderRadius: '12px',
  padding: '24px',
};

const ACTION_BUTTON_STYLE: CSSProperties = {
  padding: '10px 12px',
  borderRadius: '8px',
  border: '1px solid var(--line)',
  background: 'var(--bg-elev1)',
  color: 'var(--fg)',
  cursor: 'pointer',
  fontSize: '12px',
  fontWeight: 600,
};

const SECTION_STYLE: CSSProperties = {
  border: '1px solid var(--line)',
  borderRadius: 10,
  padding: 14,
  background: 'var(--bg-elev1)',
};

const INNER_PANEL_STYLE: CSSProperties = {
  border: '1px solid var(--line)',
  borderRadius: 8,
  padding: 12,
  background: 'var(--card-bg)',
};

const CARD_TITLE_STYLE: CSSProperties = {
  fontSize: 14,
  fontWeight: 700,
  color: 'var(--fg)',
  marginBottom: 16,
};

const SECTION_TITLE_STYLE: CSSProperties = {
  fontSize: 12,
  fontWeight: 700,
  color: 'var(--fg)',
  marginBottom: 4,
};

const SECTION_DESC_STYLE: CSSProperties = {
  fontSize: 11,
  color: 'var(--fg-muted)',
  marginBottom: 12,
};

export function RetrievalSubtab() {
  const [selectedCard, setSelectedCard] = useState<RetrievalCardId>('search_paths');
  const [opsTracingView, setOpsTracingView] = useState<OpsTracingViewId>('runtime_compatibility');
  const [hydrating, setHydrating] = useState(true);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceStatus, setTraceStatus] = useState<{ type: 'info' | 'error'; message: string } | null>(null);
  const traceTerminalRef = useRef<LiveTerminalHandle>(null);

  const { repos, activeRepo, setActiveRepo, loadRepos } = useRepoStore();

  // --- Generation ---------------------------------------------------------
  const [genModel, setGenModel] = useConfigField<string>('generation.gen_model', '');
  const [genModelOllama, setGenModelOllama] = useConfigField<string>('generation.gen_model_ollama', '');
  const [genTemperature, setGenTemperature] = useConfigField<number>('generation.gen_temperature', 0.0);
  const [enrichModel, setEnrichModel] = useConfigField<string>('generation.enrich_model', '');
  const [enrichModelOllama, setEnrichModelOllama] = useConfigField<string>('generation.enrich_model_ollama', '');
  const [ollamaUrl, setOllamaUrl] = useConfigField<string>('generation.ollama_url', 'http://127.0.0.1:11434/api');
  const [openaiBaseUrl, setOpenaiBaseUrl] = useConfigField<string>('generation.openai_base_url', '');
  const [genModelHttp, setGenModelHttp] = useConfigField<string>('generation.gen_model_http', '');
  const [genModelMcp, setGenModelMcp] = useConfigField<string>('generation.gen_model_mcp', '');
  const [genModelCli, setGenModelCli] = useConfigField<string>('generation.gen_model_cli', '');
  const [genBackend] = useConfigField<string>('generation.gen_backend', 'openai');
  const [enrichBackend, setEnrichBackend] = useConfigField<string>('generation.enrich_backend', 'openai');
  const [genMaxTokens, setGenMaxTokens] = useConfigField<number>('generation.gen_max_tokens', 2048);
  const [genTopP, setGenTopP] = useConfigField<number>('generation.gen_top_p', 1.0);
  const [genTimeout, setGenTimeout] = useConfigField<number>('generation.gen_timeout', 60);
  const [genRetryMax, setGenRetryMax] = useConfigField<number>('generation.gen_retry_max', 2);
  const [enrichDisabled, setEnrichDisabled] = useConfigField<number>('generation.enrich_disabled', 0);
  const [ollamaNumCtx, setOllamaNumCtx] = useConfigField<number>('generation.ollama_num_ctx', 8192);
  const [ollamaRequestTimeout, setOllamaRequestTimeout] = useConfigField<number>('generation.ollama_request_timeout', 300);
  const [ollamaStreamIdleTimeout, setOllamaStreamIdleTimeout] =
    useConfigField<number>('generation.ollama_stream_idle_timeout', 60);

  // --- Retrieval ----------------------------------------------------------
  const [rrfKDiv, setRrfKDiv] = useConfigField<number>('retrieval.rrf_k_div', 60);
  const [langgraphFinalK, setLanggraphFinalK] = useConfigField<number>('retrieval.langgraph_final_k', 20);
  const [multiQueryRewrites, setMultiQueryRewrites] = useConfigField<number>('retrieval.max_query_rewrites', 2);
  const [langgraphMaxQueryRewrites, setLanggraphMaxQueryRewrites] =
    useConfigField<number>('retrieval.langgraph_max_query_rewrites', 2);
  const [fallbackConfidence, setFallbackConfidence] = useConfigField<number>('retrieval.fallback_confidence', 0.55);
  const [finalK, setFinalK] = useConfigField<number>('retrieval.final_k', 10);
  const [evalFinalK, setEvalFinalK] = useConfigField<number>('retrieval.eval_final_k', 5);
  const [confTop1, setConfTop1] = useConfigField<number>('retrieval.conf_top1', 0.62);
  const [confAvg5, setConfAvg5] = useConfigField<number>('retrieval.conf_avg5', 0.55);
  const [confAny, setConfAny] = useConfigField<number>('retrieval.conf_any', 0.55);
  const [evalMulti, setEvalMulti] = useConfigField<number>('retrieval.eval_multi', 1);
  const [queryExpansionEnabled, setQueryExpansionEnabled] = useConfigField<number>('retrieval.query_expansion_enabled', 1);
  const [retrievalBm25Weight, setRetrievalBm25Weight] = useConfigField<number>('retrieval.bm25_weight', 0.3);
  const [retrievalBm25K1, setRetrievalBm25K1] = useConfigField<number>('retrieval.bm25_k1', 1.2);
  const [retrievalBm25B, setRetrievalBm25B] = useConfigField<number>('retrieval.bm25_b', 0.4);
  const [retrievalVectorWeight, setRetrievalVectorWeight] = useConfigField<number>('retrieval.vector_weight', 0.7);
  const [cardSearchEnabled, setCardSearchEnabled] = useConfigField<number>('retrieval.chunk_summary_search_enabled', 1);
  const [maxChunksPerFile, setMaxChunksPerFile] = useConfigField<number>('retrieval.max_chunks_per_file', 3);
  const [dedupBy, setDedupBy] = useConfigField<'chunk_id' | 'file_path'>('retrieval.dedup_by', 'chunk_id');
  const [neighborWindow, setNeighborWindow] = useConfigField<number>('retrieval.neighbor_window', 1);
  const [minScoreVector, setMinScoreVector] = useConfigField<number>('retrieval.min_score_vector', 0.0);
  const [minScoreSparse, setMinScoreSparse] = useConfigField<number>('retrieval.min_score_sparse', 0.0);
  const [minScoreGraph, setMinScoreGraph] = useConfigField<number>('retrieval.min_score_graph', 0.0);
  const [enableMmr, setEnableMmr] = useConfigField<boolean>('retrieval.enable_mmr', false);
  const [mmrLambda, setMmrLambda] = useConfigField<number>('retrieval.mmr_lambda', 0.7);
  const [multiQueryM, setMultiQueryM] = useConfigField<number>('retrieval.multi_query_m', 4);
  const [useSemanticSynonyms, setUseSemanticSynonyms] = useConfigField<number>('retrieval.use_semantic_synonyms', 1);
  const [synonymsPath, setSynonymsPath] = useConfigField<string>('retrieval.tribrid_synonyms_path', '');
  const [topkDense, setTopkDense] = useConfigField<number>('retrieval.topk_dense', 75);
  const [topkSparse, setTopkSparse] = useConfigField<number>('retrieval.topk_sparse', 75);
  const [retrievalHydrationMode, setRetrievalHydrationMode] = useConfigField<string>('retrieval.hydration_mode', 'lazy');
  const [retrievalHydrationMaxChars, setRetrievalHydrationMaxChars] = useConfigField<number>('retrieval.hydration_max_chars', 2000);
  void retrievalBm25K1;
  void retrievalBm25B;

  // --- Vector search ------------------------------------------------------
  const [vectorSearchEnabled, setVectorSearchEnabled] = useConfigField<boolean>('vector_search.enabled', true);
  const [vectorSearchTopK, setVectorSearchTopK] = useConfigField<number>('vector_search.top_k', 50);
  const [vectorSimilarityThreshold, setVectorSimilarityThreshold] = useConfigField<number>('vector_search.similarity_threshold', 0.0);

  // --- Sparse search ------------------------------------------------------
  const [sparseSearchEngine, setSparseSearchEngine] = useConfigField<'postgres_fts' | 'pg_search_bm25'>(
    'sparse_search.engine',
    'postgres_fts',
  );
  const [sparseSearchQueryMode, setSparseSearchQueryMode] = useConfigField<'plain' | 'phrase' | 'boolean'>(
    'sparse_search.query_mode',
    'plain',
  );
  const [sparseSearchHighlight, setSparseSearchHighlight] = useConfigField<boolean>('sparse_search.highlight', false);
  const [sparseRelaxOnEmpty, setSparseRelaxOnEmpty] = useConfigField<boolean>('sparse_search.relax_on_empty', true);
  const [sparseRelaxMaxTerms, setSparseRelaxMaxTerms] = useConfigField<number>('sparse_search.relax_max_terms', 8);
  const [sparseFilePathFallback, setSparseFilePathFallback] = useConfigField<boolean>('sparse_search.file_path_fallback', true);
  const [sparseFilePathMaxTerms, setSparseFilePathMaxTerms] = useConfigField<number>('sparse_search.file_path_max_terms', 6);
  const [sparseSearchEnabled, setSparseSearchEnabled] = useConfigField<boolean>('sparse_search.enabled', true);
  const [sparseSearchTopK, setSparseSearchTopK] = useConfigField<number>('sparse_search.top_k', 50);
  const [sparseBm25K1, setSparseBm25K1] = useConfigField<number>('sparse_search.bm25_k1', 1.2);
  const [sparseBm25B, setSparseBm25B] = useConfigField<number>('sparse_search.bm25_b', 0.4);

  // --- Graph search -------------------------------------------------------
  const [graphMode, setGraphMode] = useConfigField<'chunk' | 'entity'>('graph_search.mode', 'chunk');
  const [graphSearchEnabled, setGraphSearchEnabled] = useConfigField<boolean>('graph_search.enabled', true);
  const [chunkNeighborWindow, setChunkNeighborWindow] = useConfigField<number>('graph_search.chunk_neighbor_window', 1);
  const [chunkSeedOverfetchMultiplier, setChunkSeedOverfetchMultiplier] =
    useConfigField<number>('graph_search.chunk_seed_overfetch_multiplier', 10);
  const [chunkEntityExpansionEnabled, setChunkEntityExpansionEnabled] =
    useConfigField<boolean>('graph_search.chunk_entity_expansion_enabled', true);
  const [chunkEntityExpansionWeight, setChunkEntityExpansionWeight] =
    useConfigField<number>('graph_search.chunk_entity_expansion_weight', 0.8);
  const [graphMaxHops, setGraphMaxHops] = useConfigField<number>('graph_search.max_hops', 2);
  const [graphIncludeCommunities, setGraphIncludeCommunities] = useConfigField<boolean>('graph_search.include_communities', true);
  const [graphSearchTopK, setGraphSearchTopK] = useConfigField<number>('graph_search.top_k', 30);

  // --- Fusion -------------------------------------------------------------
  const [fusionMethod, setFusionMethod] = useConfigField<'rrf' | 'weighted'>('fusion.method', 'rrf');
  const [fusionVectorWeight, setFusionVectorWeight] = useConfigField<number>('fusion.vector_weight', 0.4);
  const [fusionSparseWeight, setFusionSparseWeight] = useConfigField<number>('fusion.sparse_weight', 0.3);
  const [fusionGraphWeight, setFusionGraphWeight] = useConfigField<number>('fusion.graph_weight', 0.3);
  const [fusionRrfK, setFusionRrfK] = useConfigField<number>('fusion.rrf_k', 60);
  const [fusionNormalizeScores, setFusionNormalizeScores] = useConfigField<boolean>('fusion.normalize_scores', true);

  // --- Scoring ------------------------------------------------------------
  const [cardBonus, setCardBonus] = useConfigField<number>('scoring.chunk_summary_bonus', 0.08);
  const [filenameBoostExact, setFilenameBoostExact] = useConfigField<number>('scoring.filename_boost_exact', 1.5);
  const [filenameBoostPartial, setFilenameBoostPartial] = useConfigField<number>('scoring.filename_boost_partial', 1.2);
  const [vendorMode, setVendorMode] = useConfigField<string>('scoring.vendor_mode', 'prefer_first_party');
  const [pathBoosts, setPathBoosts] = useConfigField<string>('scoring.path_boosts', '/gui,/server,/indexer,/retrieval');

  // --- Layer bonus --------------------------------------------------------
  const [layerBonusGui, setLayerBonusGui] = useConfigField<number>('layer_bonus.gui', 0.15);
  const [layerBonusRetrieval, setLayerBonusRetrieval] = useConfigField<number>('layer_bonus.retrieval', 0.15);
  const [layerBonusIndexer, setLayerBonusIndexer] = useConfigField<number>('layer_bonus.indexer', 0.15);
  const [vendorPenalty, setVendorPenalty] = useConfigField<number>('layer_bonus.vendor_penalty', -0.1);
  const [freshnessBonus, setFreshnessBonus] = useConfigField<number>('layer_bonus.freshness_bonus', 0.05);
  const [layerIntentMatrix, setLayerIntentMatrix] = useConfigField<Record<string, Record<string, number>>>(
    'layer_bonus.intent_matrix',
    {},
  );
  void layerIntentMatrix;
  void setLayerIntentMatrix;

  // --- Tracing ------------------------------------------------------------
  const [tracingEnabled, setTracingEnabled] = useConfigField<number>('tracing.tracing_enabled', 1);
  const [traceSamplingRate, setTraceSamplingRate] = useConfigField<number>('tracing.trace_sampling_rate', 1.0);
  const [prometheusPort, setPrometheusPort] = useConfigField<number>('tracing.prometheus_port', 9090);
  const [metricsEnabled, setMetricsEnabled] = useConfigField<number>('tracing.metrics_enabled', 1);
  const [alertIncludeResolved, setAlertIncludeResolved] = useConfigField<number>('tracing.alert_include_resolved', 1);
  const [alertWebhookTimeout, setAlertWebhookTimeout] = useConfigField<number>('tracing.alert_webhook_timeout', 5);
  const [logLevel, setLogLevel] = useConfigField<string>('tracing.log_level', 'INFO');
  const [tracingMode, setTracingMode] = useConfigField<string>('tracing.tracing_mode', 'langsmith');
  const [traceAutoLs, setTraceAutoLs] = useConfigField<number>('tracing.trace_auto_ls', 1);
  const [traceRetention, setTraceRetention] = useConfigField<number>('tracing.trace_retention', 50);
  const [tribridLogPath, setTribridLogPath] = useConfigField<string>('tracing.tribrid_log_path', 'data/logs/queries.jsonl');
  const [alertNotifySeverities, setAlertNotifySeverities] = useConfigField<string>('tracing.alert_notify_severities', 'critical,warning');
  const [langchainEndpoint, setLangchainEndpoint] = useConfigField<string>(
    'tracing.langchain_endpoint',
    'https://api.smith.langchain.com',
  );
  const [langchainProject, setLangchainProject] = useConfigField<string>('tracing.langchain_project', 'tribrid');
  const [langchainTracingV2, setLangchainTracingV2] = useConfigField<number>('tracing.langchain_tracing_v2', 0);
  const [langtraceApiHost, setLangtraceApiHost] = useConfigField<string>('tracing.langtrace_api_host', '');
  const [langtraceProjectId, setLangtraceProjectId] = useConfigField<string>('tracing.langtrace_project_id', '');

  // --- Hydration ----------------------------------------------------------
  const [hydrationMode, setHydrationMode] = useConfigField<string>('hydration.hydration_mode', 'lazy');
  const [hydrationMaxChars, setHydrationMaxChars] = useConfigField<number>('hydration.hydration_max_chars', 2000);

  // --- Semantic cache -----------------------------------------------------
  const [semanticCacheEnabled, setSemanticCacheEnabled] = useConfigField<number>('semantic_cache.enabled', 0);
  const [semanticCacheMode, setSemanticCacheMode] =
    useConfigField<'read_write' | 'read_only' | 'write_only'>('semantic_cache.mode', 'read_write');
  const [semanticCacheMaxEntries, setSemanticCacheMaxEntries] = useConfigField<number>('semantic_cache.max_entries', 5000);
  const [semanticCacheMinQueryChars, setSemanticCacheMinQueryChars] =
    useConfigField<number>('semantic_cache.min_query_chars', 3);
  const [semanticCacheThresholdSearch, setSemanticCacheThresholdSearch] =
    useConfigField<number>('semantic_cache.similarity_threshold_search', 0.9);
  const [semanticCacheThresholdAnswer, setSemanticCacheThresholdAnswer] =
    useConfigField<number>('semantic_cache.similarity_threshold_answer', 0.93);
  const [semanticCacheThresholdChat, setSemanticCacheThresholdChat] =
    useConfigField<number>('semantic_cache.similarity_threshold_chat', 0.95);
  const [semanticCacheTtlSearch, setSemanticCacheTtlSearch] = useConfigField<number>('semantic_cache.ttl_seconds_search', 900);
  const [semanticCacheTtlAnswer, setSemanticCacheTtlAnswer] = useConfigField<number>('semantic_cache.ttl_seconds_answer', 1800);
  const [semanticCacheTtlChat, setSemanticCacheTtlChat] = useConfigField<number>('semantic_cache.ttl_seconds_chat', 600);
  const [semanticCacheChatHistoryWindow, setSemanticCacheChatHistoryWindow] =
    useConfigField<number>('semantic_cache.chat_history_window', 6);
  const [semanticCacheBypassIfImages, setSemanticCacheBypassIfImages] =
    useConfigField<number>('semantic_cache.bypass_if_images', 1);
  const [semanticCacheMaxTemperatureForWrite, setSemanticCacheMaxTemperatureForWrite] =
    useConfigField<number>('semantic_cache.max_temperature_for_write', 0.5);

  const {
    config,
    loading: configLoading,
    error: configError,
    reload,
    clearError,
  } = useConfig();


  useEffect(() => {
    if (!repos.length) {
      void loadRepos();
    }
  }, [repos.length, loadRepos]);

  useEffect(() => {
    if (config) {
      setHydrating(false);
    }
  }, [config]);

  useEffect(() => {
    if (!configLoading && !config) {
      setHydrating(false);
    }
  }, [configLoading, config]);

  useEffect(() => {
    if (configError) {
      setHydrating(false);
    }
  }, [configError]);

  const handleReload = useCallback(async () => {
    try {
      setHydrating(true);
      clearError();
      await reload();
    } catch (error) {
      console.error('Failed to reload configuration:', error);
      alert(error instanceof Error ? error.message : 'Failed to reload configuration');
      setHydrating(false);
    }
  }, [reload, clearError]);

  const handleLoadTrace = useCallback(async () => {
    setTraceLoading(true);
    setTraceStatus(null);
    try {
      const data: TracesLatestResponse = await tracesApi.getLatest();
      const formatted = formatTracePayload(data, 'pgvector').split('\n');
      traceTerminalRef.current?.setTitle(`Routing Trace • ${new Date().toLocaleTimeString()}`);
      traceTerminalRef.current?.setContent(formatted);
      setTraceStatus({
        type: 'info',
        message: `Trace refreshed at ${new Date().toLocaleTimeString()}`,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to load routing trace';
      const alertText = createAlertError('Routing trace failed', { message });
      traceTerminalRef.current?.setTitle('Routing Trace • Error');
      traceTerminalRef.current?.setContent(alertText.split('\n'));
      setTraceStatus({
        type: 'error',
        message: createInlineError('Failed to load trace'),
      });
    } finally {
      setTraceLoading(false);
    }
  }, []);

  const setUnifiedBm25K1 = useCallback(
    (value: number) => {
      setSparseBm25K1(value);
      setRetrievalBm25K1(value);
    },
    [setSparseBm25K1, setRetrievalBm25K1],
  );

  const setUnifiedBm25B = useCallback(
    (value: number) => {
      setSparseBm25B(value);
      setRetrievalBm25B(value);
    },
    [setSparseBm25B, setRetrievalBm25B],
  );

  const setUnifiedHydrationMode = useCallback(
    (value: string) => {
      setHydrationMode(value);
      setRetrievalHydrationMode(value);
    },
    [setHydrationMode, setRetrievalHydrationMode],
  );

  const setUnifiedHydrationMaxChars = useCallback(
    (value: number) => {
      setHydrationMaxChars(value);
      setRetrievalHydrationMaxChars(value);
    },
    [setHydrationMaxChars, setRetrievalHydrationMaxChars],
  );

  useEffect(() => {
    if (selectedCard === 'ops_tracing') {
      setOpsTracingView('runtime_compatibility');
    }
  }, [selectedCard]);

  if (hydrating) {
    return (
      <div className="subtab-panel" style={{ padding: '24px' }}>
        Loading configuration...
      </div>
    );
  }

  return (
    <div className="subtab-panel" style={{ padding: '24px' }} data-testid="retrieval-subtab">
      <div style={{ marginBottom: 22 }}>
        <h3
          style={{
            fontSize: '18px',
            fontWeight: 600,
            color: 'var(--fg)',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            marginBottom: 6,
          }}
        >
          <span style={{ fontSize: 22 }}>🔎</span>
          Retrieval
        </h3>
        <div style={{ fontSize: 13, color: 'var(--fg-muted)' }}>
          Configure search paths, fusion/scoring, generation model routing, and operations telemetry.
        </div>
      </div>

      <EmbeddingMismatchWarning variant="inline" showActions />

      {configError && (
        <div style={{ ...PANEL_STYLE, borderColor: 'var(--err)', marginBottom: 18 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--err)', marginBottom: 8 }}>Configuration Error</div>
          <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 12 }}>{configError}</div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button type="button" style={ACTION_BUTTON_STYLE} onClick={handleReload}>
              Retry Load
            </button>
            <button type="button" style={ACTION_BUTTON_STYLE} onClick={clearError}>
              Dismiss
            </button>
          </div>
        </div>
      )}

      <div style={{ ...PANEL_STYLE, marginBottom: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg)', marginBottom: 14 }}>Universal Controls</div>

        <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 16 }}>
          <div className="input-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              Corpus
              <TooltipIcon name="REPO" />
            </label>
            <select value={activeRepo} onChange={(e) => void setActiveRepo(e.target.value)}>
              {!repos.length ? <option value="">No corpora</option> : repos.map((r) => (
                <option key={r.corpus_id} value={r.corpus_id}>{r.name || r.corpus_id}</option>
              ))}
            </select>
          </div>

          <div className="input-group">
            <ModelPicker
              componentType="GEN"
              provider={genBackend}
              value={genModel}
              onChange={setGenModel}
              label="Primary Model"
              tooltipKey="GEN_MODEL"
              allowCustom
            />
          </div>

          <div className="input-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              Final K
              <TooltipIcon name="FINAL_K" />
            </label>
            <input
              type="number"
              min={1}
              max={200}
              value={finalK}
              onChange={(e) => setFinalK(snapNumber(e.target.value, 10))}
            />
          </div>

          <div className="input-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              Query Rewrites
              <TooltipIcon name="MAX_QUERY_REWRITES" />
            </label>
            <input
              type="number"
              min={1}
              max={10}
              value={multiQueryRewrites}
              onChange={(e) => setMultiQueryRewrites(snapNumber(e.target.value, 2))}
            />
          </div>
        </div>

        <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16, marginTop: 8 }}>
          <div className="input-group">
            <label>
              <input
                type="checkbox"
                checked={vectorSearchEnabled}
                onChange={(e) => setVectorSearchEnabled(e.target.checked)}
              />{' '}
              Enable Vector Search <TooltipIcon name="VECTOR_SEARCH_ENABLED" />
            </label>
          </div>
          <div className="input-group">
            <label>
              <input
                type="checkbox"
                checked={sparseSearchEnabled}
                onChange={(e) => setSparseSearchEnabled(e.target.checked)}
              />{' '}
              Enable Sparse Search <TooltipIcon name="SPARSE_SEARCH_ENABLED" />
            </label>
          </div>
          <div className="input-group">
            <label>
              <input
                type="checkbox"
                checked={graphSearchEnabled}
                onChange={(e) => setGraphSearchEnabled(e.target.checked)}
              />{' '}
              Enable Graph Search <TooltipIcon name="GRAPH_SEARCH_ENABLED" />
            </label>
          </div>
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
          gap: 12,
          marginBottom: 20,
        }}
      >
        {RETRIEVAL_CARDS.map((card) => (
          <button
            key={card.id}
            type="button"
            onClick={() => setSelectedCard(card.id)}
            data-testid={`retrieval-card-${card.id}`}
            style={{
              padding: '16px 14px',
              borderRadius: 12,
              border: selectedCard === card.id ? '2px solid var(--accent)' : '1px solid var(--line)',
              background:
                selectedCard === card.id
                  ? 'linear-gradient(135deg, rgba(var(--accent-rgb), 0.15), rgba(var(--accent-rgb), 0.05))'
                  : 'var(--card-bg)',
              textAlign: 'left',
              cursor: 'pointer',
            }}
          >
            <div style={{ fontSize: 24, marginBottom: 8 }}>{card.icon}</div>
            <div
              style={{
                fontSize: 13,
                fontWeight: 700,
                color: selectedCard === card.id ? 'var(--accent)' : 'var(--fg)',
                marginBottom: 6,
              }}
            >
              {card.label}
            </div>
            <div style={{ fontSize: 11, color: 'var(--fg-muted)', lineHeight: 1.4 }}>{card.description}</div>
          </button>
        ))}
      </div>

      <div style={PANEL_STYLE}>
        {selectedCard === 'search_paths' && (
          <div>
            <h4 style={CARD_TITLE_STYLE}>
              Search Paths
            </h4>

            <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 16 }}>
              Configure each retrieval leg independently, then shape merged candidates.
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-search-query-enrichment">
              <div style={SECTION_TITLE_STYLE}>1) Query Enrichment</div>
              <div style={SECTION_DESC_STYLE}>
                Controls applied before retrieval leg scoring.
              </div>
              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    Semantic Synonyms <TooltipIcon name="USE_SEMANTIC_SYNONYMS" />
                  </label>
                  <select value={useSemanticSynonyms} onChange={(e) => setUseSemanticSynonyms(parseInt(e.target.value, 10))}>
                    <option value={1}>On</option>
                    <option value={0}>Off</option>
                  </select>
                </div>
                <div className="input-group">
                  <label>
                    Synonyms File Path <TooltipIcon name="TRIBRID_SYNONYMS_PATH" />
                  </label>
                  <input
                    type="text"
                    value={synonymsPath}
                    onChange={(e) => setSynonymsPath(e.target.value)}
                    placeholder="data/semantic_synonyms.json"
                  />
                </div>
              </div>
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-search-legs">
              <div style={SECTION_TITLE_STYLE}>2) Search Legs</div>
              <div style={SECTION_DESC_STYLE}>
                Tune vector, sparse, and graph retrieval independently.
              </div>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                  gap: 14,
                }}
              >
                <div style={INNER_PANEL_STYLE}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--fg)', marginBottom: 10 }}>Vector Leg</div>
                  <div className="input-group">
                    <label>
                      Vector Top-K <TooltipIcon name="VECTOR_SEARCH_TOP_K" />
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={200}
                      value={vectorSearchTopK}
                      onChange={(e) => setVectorSearchTopK(snapNumber(e.target.value, 50))}
                      disabled={!vectorSearchEnabled}
                    />
                  </div>
                  <div className="input-group">
                    <label>
                      Vector Similarity Threshold <TooltipIcon name="VECTOR_SIMILARITY_THRESHOLD" />
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      value={vectorSimilarityThreshold}
                      onChange={(e) => setVectorSimilarityThreshold(snapNumber(e.target.value, 0.0))}
                      disabled={!vectorSearchEnabled}
                    />
                  </div>
                </div>

                <div style={INNER_PANEL_STYLE}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--fg)', marginBottom: 10 }}>Sparse Leg</div>
                  <div className="input-group">
                    <label>
                      Sparse Top-K <TooltipIcon name="SPARSE_SEARCH_TOP_K" />
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={200}
                      value={sparseSearchTopK}
                      onChange={(e) => setSparseSearchTopK(snapNumber(e.target.value, 50))}
                      disabled={!sparseSearchEnabled}
                    />
                  </div>
                  <div className="input-group">
                    <label>
                      Sparse Engine <TooltipIcon name="SPARSE_SEARCH_ENGINE" />
                    </label>
                    <select
                      data-testid="sparse-engine"
                      value={sparseSearchEngine}
                      onChange={(e) => setSparseSearchEngine(e.target.value as any)}
                      disabled={!sparseSearchEnabled}
                    >
                      <option value="postgres_fts">postgres_fts</option>
                      <option value="pg_search_bm25">pg_search_bm25</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      Sparse Query Mode <TooltipIcon name="SPARSE_SEARCH_QUERY_MODE" />
                    </label>
                    <select
                      value={sparseSearchQueryMode}
                      onChange={(e) => setSparseSearchQueryMode(e.target.value as any)}
                      disabled={!sparseSearchEnabled}
                    >
                      <option value="plain">plain</option>
                      <option value="phrase">phrase</option>
                      <option value="boolean">boolean</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      BM25 k1 <TooltipIcon name="BM25_K1" />
                    </label>
                    <input
                      type="number"
                      min={0.5}
                      max={3}
                      step={0.1}
                      value={sparseBm25K1}
                      onChange={(e) => setUnifiedBm25K1(snapNumber(e.target.value, 1.2))}
                      disabled={!sparseSearchEnabled}
                    />
                  </div>
                  <div className="input-group">
                    <label>
                      BM25 b <TooltipIcon name="BM25_B" />
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      value={sparseBm25B}
                      onChange={(e) => setUnifiedBm25B(snapNumber(e.target.value, 0.4))}
                      disabled={!sparseSearchEnabled}
                    />
                  </div>
                  <div className="input-group">
                    <label>
                      <input
                        type="checkbox"
                        checked={sparseSearchHighlight}
                        onChange={(e) => setSparseSearchHighlight(e.target.checked)}
                        disabled={!sparseSearchEnabled}
                      />{' '}
                      Highlight <TooltipIcon name="SPARSE_SEARCH_HIGHLIGHT" />
                    </label>
                  </div>
                  <div className="input-group">
                    <label>
                      Relax on Empty <TooltipIcon name="SPARSE_SEARCH_RELAX_ON_EMPTY" />
                    </label>
                    <select
                      value={sparseRelaxOnEmpty ? '1' : '0'}
                      onChange={(e) => setSparseRelaxOnEmpty(e.target.value === '1')}
                      disabled={!sparseSearchEnabled}
                    >
                      <option value="1">Enabled</option>
                      <option value="0">Disabled</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      Relax Max Terms <TooltipIcon name="SPARSE_SEARCH_RELAX_MAX_TERMS" />
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={32}
                      value={sparseRelaxMaxTerms}
                      onChange={(e) => setSparseRelaxMaxTerms(snapNumber(e.target.value, 8))}
                      disabled={!sparseSearchEnabled || !sparseRelaxOnEmpty}
                    />
                  </div>
                  <div className="input-group">
                    <label>
                      File Path Fallback <TooltipIcon name="SPARSE_SEARCH_FILE_PATH_FALLBACK" />
                    </label>
                    <select
                      value={sparseFilePathFallback ? '1' : '0'}
                      onChange={(e) => setSparseFilePathFallback(e.target.value === '1')}
                      disabled={!sparseSearchEnabled}
                    >
                      <option value="1">Enabled</option>
                      <option value="0">Disabled</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      File Path Max Terms <TooltipIcon name="SPARSE_SEARCH_FILE_PATH_MAX_TERMS" />
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={32}
                      value={sparseFilePathMaxTerms}
                      onChange={(e) => setSparseFilePathMaxTerms(snapNumber(e.target.value, 6))}
                      disabled={!sparseSearchEnabled || !sparseFilePathFallback}
                    />
                  </div>
                </div>

                <div style={INNER_PANEL_STYLE}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--fg)', marginBottom: 10 }}>Graph Leg</div>
                  <div className="input-group">
                    <label>
                      Graph Top-K <TooltipIcon name="GRAPH_SEARCH_TOP_K" />
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={200}
                      value={graphSearchTopK}
                      onChange={(e) => setGraphSearchTopK(snapNumber(e.target.value, 30))}
                      disabled={!graphSearchEnabled}
                    />
                  </div>
                  <div className="input-group">
                    <label>
                      Graph Mode <TooltipIcon name="GRAPH_SEARCH_MODE" />
                    </label>
                    <select
                      data-testid="graph-search-mode"
                      value={graphMode}
                      onChange={(e) => setGraphMode(e.target.value as any)}
                      disabled={!graphSearchEnabled}
                    >
                      <option value="chunk">chunk</option>
                      <option value="entity">entity</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      Graph Max Hops <TooltipIcon name="GRAPH_MAX_HOPS" />
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={5}
                      value={graphMaxHops}
                      onChange={(e) => setGraphMaxHops(snapNumber(e.target.value, 2))}
                      disabled={!graphSearchEnabled}
                    />
                  </div>
                  <div className="input-group">
                    <label>
                      Include Communities <TooltipIcon name="GRAPH_INCLUDE_COMMUNITIES" />
                    </label>
                    <select
                      value={graphIncludeCommunities ? '1' : '0'}
                      onChange={(e) => setGraphIncludeCommunities(e.target.value === '1')}
                      disabled={!graphSearchEnabled || graphMode !== 'entity'}
                    >
                      <option value="1">Enabled</option>
                      <option value="0">Disabled</option>
                    </select>
                  </div>

                  {graphMode === 'chunk' && (
                    <>
                      <div className="input-group">
                        <label>
                          Chunk Neighbor Window <TooltipIcon name="GRAPH_CHUNK_NEIGHBOR_WINDOW" />
                        </label>
                        <input
                          type="number"
                          min={0}
                          max={10}
                          value={chunkNeighborWindow}
                          onChange={(e) => setChunkNeighborWindow(snapNumber(e.target.value, 1))}
                          disabled={!graphSearchEnabled}
                        />
                      </div>
                      <div className="input-group">
                        <label>
                          Seed Overfetch Multiplier <TooltipIcon name="GRAPH_CHUNK_SEED_OVERFETCH" />
                        </label>
                        <input
                          type="number"
                          min={1}
                          max={50}
                          value={chunkSeedOverfetchMultiplier}
                          onChange={(e) => setChunkSeedOverfetchMultiplier(snapNumber(e.target.value, 10))}
                          disabled={!graphSearchEnabled}
                        />
                      </div>
                      <div className="input-group">
                        <label>
                          <input
                            type="checkbox"
                            checked={chunkEntityExpansionEnabled}
                            onChange={(e) => setChunkEntityExpansionEnabled(e.target.checked)}
                            disabled={!graphSearchEnabled}
                          />{' '}
                          Expand via Entities <TooltipIcon name="GRAPH_CHUNK_ENTITY_EXPANSION_ENABLED" />
                        </label>
                      </div>
                      <div className="input-group">
                        <label>
                          Entity Expansion Weight <TooltipIcon name="GRAPH_CHUNK_ENTITY_EXPANSION_WEIGHT" />
                        </label>
                        <input
                          type="number"
                          min={0}
                          max={1}
                          step={0.05}
                          value={chunkEntityExpansionWeight}
                          onChange={(e) => setChunkEntityExpansionWeight(snapNumber(e.target.value, 0.8))}
                          disabled={!graphSearchEnabled || !chunkEntityExpansionEnabled}
                        />
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>

            <div style={SECTION_STYLE} data-testid="retrieval-section-search-shaping">
              <div style={SECTION_TITLE_STYLE}>3) Result Shaping</div>
              <div style={SECTION_DESC_STYLE}>
                Control deduplication, diversification, and minimum score thresholds.
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    Max Chunks per File <TooltipIcon name="MAX_CHUNKS_PER_FILE" />
                  </label>
                  <input
                    data-testid="max-chunks-per-file"
                    type="number"
                    min={1}
                    max={50}
                    value={maxChunksPerFile}
                    onChange={(e) => setMaxChunksPerFile(snapNumber(e.target.value, 3))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Dedup By <TooltipIcon name="DEDUP_BY" />
                  </label>
                  <select value={dedupBy} onChange={(e) => setDedupBy(e.target.value as any)}>
                    <option value="chunk_id">chunk_id</option>
                    <option value="file_path">file_path</option>
                  </select>
                </div>
                <div className="input-group">
                  <label>
                    Neighbor Window <TooltipIcon name="NEIGHBOR_WINDOW" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    value={neighborWindow}
                    onChange={(e) => setNeighborWindow(snapNumber(e.target.value, 1))}
                    disabled={dedupBy === 'file_path'}
                  />
                </div>
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    <input type="checkbox" checked={enableMmr} onChange={(e) => setEnableMmr(e.target.checked)} /> Enable MMR
                    <TooltipIcon name="ENABLE_MMR" />
                  </label>
                </div>
                <div className="input-group">
                  <label>
                    MMR Lambda <TooltipIcon name="MMR_LAMBDA" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={mmrLambda}
                    onChange={(e) => setMmrLambda(snapNumber(e.target.value, 0.7))}
                    disabled={!enableMmr}
                  />
                </div>
                <div className="input-group" />
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    Min Score (vector) <TooltipIcon name="MIN_SCORE_VECTOR" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={minScoreVector}
                    onChange={(e) => setMinScoreVector(snapNumber(e.target.value, 0.0))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Min Score (sparse) <TooltipIcon name="MIN_SCORE_SPARSE" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    step={0.01}
                    value={minScoreSparse}
                    onChange={(e) => setMinScoreSparse(snapNumber(e.target.value, 0.0))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Min Score (graph) <TooltipIcon name="MIN_SCORE_GRAPH" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    step={0.01}
                    value={minScoreGraph}
                    onChange={(e) => setMinScoreGraph(snapNumber(e.target.value, 0.0))}
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {selectedCard === 'fusion_scoring' && (
          <div>
            <h4 style={CARD_TITLE_STYLE}>
              Fusion & Scoring
            </h4>

            <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 16 }}>
              Configure how retrieval legs merge into a ranked list, then tune score shaping and intent-aware layer weighting.
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-fusion-strategy">
              <div style={SECTION_TITLE_STYLE}>1) Fusion Strategy</div>
              <div style={SECTION_DESC_STYLE}>
                Choose robust rank fusion (`rrf`) or explicit weighting (`weighted`) for vector/sparse/graph legs.
              </div>
              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    Fusion Method <TooltipIcon name="FUSION_METHOD" />
                  </label>
                  <select value={fusionMethod} onChange={(e) => setFusionMethod(e.target.value as any)}>
                    <option value="rrf">rrf</option>
                    <option value="weighted">weighted</option>
                  </select>
                </div>
                <div className="input-group">
                  <label>
                    Normalize Scores <TooltipIcon name="FUSION_NORMALIZE_SCORES" />
                  </label>
                  <select
                    value={fusionNormalizeScores ? '1' : '0'}
                    onChange={(e) => setFusionNormalizeScores(e.target.value === '1')}
                  >
                    <option value="1">Enabled</option>
                    <option value="0">Disabled</option>
                  </select>
                </div>
                <div className="input-group" />
              </div>
              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    RRF K <TooltipIcon name="FUSION_RRF_K" />
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={fusionRrfK}
                    onChange={(e) => setFusionRrfK(snapNumber(e.target.value, 60))}
                    disabled={fusionMethod !== 'rrf'}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Vector Weight <TooltipIcon name="FUSION_VECTOR_WEIGHT" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={fusionVectorWeight}
                    onChange={(e) => setFusionVectorWeight(snapNumber(e.target.value, 0.4))}
                    disabled={fusionMethod !== 'weighted'}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Sparse Weight <TooltipIcon name="FUSION_SPARSE_WEIGHT" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={fusionSparseWeight}
                    onChange={(e) => setFusionSparseWeight(snapNumber(e.target.value, 0.3))}
                    disabled={fusionMethod !== 'weighted'}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Graph Weight <TooltipIcon name="FUSION_GRAPH_WEIGHT" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={fusionGraphWeight}
                    onChange={(e) => setFusionGraphWeight(snapNumber(e.target.value, 0.3))}
                    disabled={fusionMethod !== 'weighted'}
                  />
                </div>
              </div>
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-scoring-boosts">
              <div style={SECTION_TITLE_STYLE}>2) Scoring Boosts</div>
              <div style={SECTION_DESC_STYLE}>
                Add deterministic scoring nudges after fusion for chunk-summary hits and filename matches.
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    Chunk Summary Bonus <TooltipIcon name="CHUNK_SUMMARY_BONUS" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={cardBonus}
                    onChange={(e) => setCardBonus(snapNumber(e.target.value, 0.08))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Filename Boost (Exact) <TooltipIcon name="FILENAME_BOOST_EXACT" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={5}
                    step={0.1}
                    value={filenameBoostExact}
                    onChange={(e) => setFilenameBoostExact(snapNumber(e.target.value, 1.5))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Filename Boost (Partial) <TooltipIcon name="FILENAME_BOOST_PARTIAL" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={5}
                    step={0.1}
                    value={filenameBoostPartial}
                    onChange={(e) => setFilenameBoostPartial(snapNumber(e.target.value, 1.2))}
                  />
                </div>
              </div>
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-source-preference">
              <div style={SECTION_TITLE_STYLE}>3) Source Preference</div>
              <div style={SECTION_DESC_STYLE}>
                Balance first-party vs vendor code paths and apply explicit path prefix boosts where needed.
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 16 }}>
                <div className="input-group">
                  <label>
                    Vendor Mode <TooltipIcon name="VENDOR_MODE" />
                  </label>
                  <select value={vendorMode} onChange={(e) => setVendorMode(e.target.value)}>
                    <option value="prefer_first_party">prefer_first_party</option>
                    <option value="prefer_vendor">prefer_vendor</option>
                    <option value="neutral">neutral</option>
                  </select>
                </div>
                <div className="input-group">
                  <label>
                    Path Boosts (CSV) <TooltipIcon name="PATH_BOOSTS" />
                  </label>
                  <input
                    type="text"
                    value={pathBoosts}
                    onChange={(e) => setPathBoosts(e.target.value)}
                    placeholder="/gui,/server,/indexer,/retrieval"
                  />
                </div>
              </div>
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-layer-weights">
              <div style={SECTION_TITLE_STYLE}>4) Layer Weights</div>
              <div style={SECTION_DESC_STYLE}>
                Apply static boosts/penalties at layer level before intent-specific overrides.
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    GUI <TooltipIcon name="LAYER_BONUS_GUI" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={0.5}
                    step={0.01}
                    value={layerBonusGui}
                    onChange={(e) => setLayerBonusGui(snapNumber(e.target.value, 0.15))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Retrieval <TooltipIcon name="LAYER_BONUS_RETRIEVAL" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={0.5}
                    step={0.01}
                    value={layerBonusRetrieval}
                    onChange={(e) => setLayerBonusRetrieval(snapNumber(e.target.value, 0.15))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Indexer <TooltipIcon name="LAYER_BONUS_INDEXER" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={0.5}
                    step={0.01}
                    value={layerBonusIndexer}
                    onChange={(e) => setLayerBonusIndexer(snapNumber(e.target.value, 0.15))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Vendor Penalty <TooltipIcon name="VENDOR_PENALTY" />
                  </label>
                  <input
                    type="number"
                    min={-0.5}
                    max={0}
                    step={0.01}
                    value={vendorPenalty}
                    onChange={(e) => setVendorPenalty(snapNumber(e.target.value, -0.1))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Freshness Bonus <TooltipIcon name="FRESHNESS_BONUS" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={0.3}
                    step={0.01}
                    value={freshnessBonus}
                    onChange={(e) => setFreshnessBonus(snapNumber(e.target.value, 0.05))}
                  />
                </div>
              </div>
            </div>

            <div style={SECTION_STYLE} data-testid="retrieval-section-intent-overrides">
              <div style={SECTION_TITLE_STYLE}>5) Intent Overrides</div>
              <div style={SECTION_DESC_STYLE}>
                Use intent matrix rules to bias retrieval layers per task type, then validate with prompt context links.
              </div>
              <IntentMatrixEditor />

              <div className="related-prompts" style={{ marginTop: 10 }}>
                <span className="related-prompts-label">Related Prompts:</span>
                <PromptLink promptKey="main_rag_chat">System Prompt</PromptLink>
                <PromptLink promptKey="query_expansion">Query Expansion</PromptLink>
                <PromptLink promptKey="query_rewrite">Query Rewrite</PromptLink>
              </div>
            </div>
          </div>
        )}

        {selectedCard === 'generation' && (
          <div>
            <h4 style={CARD_TITLE_STYLE}>
              Generation
            </h4>

            <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 16 }}>
              Define answer and enrichment model routing, then tune generation budgets and transport reliability safeguards.
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-generation-answer-routing">
              <div style={SECTION_TITLE_STYLE}>1) Answer Routing</div>
              <div style={SECTION_DESC_STYLE}>
                Choose the primary answer model and optional transport-specific model overrides.
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <ModelPicker
                    componentType="GEN"
                    provider={genBackend}
                    value={genModel}
                    onChange={setGenModel}
                    label="Primary Model"
                    tooltipKey="GEN_MODEL"
                    allowCustom
                  />
                  <PromptLink promptKey="main_rag_chat">Edit Chat Prompt</PromptLink>
                </div>
                <div className="input-group">
                  <label>
                    Ollama Model <TooltipIcon name="GEN_MODEL_OLLAMA" />
                  </label>
                  <input
                    type="text"
                    value={genModelOllama}
                    onChange={(e) => setGenModelOllama(e.target.value)}
                    placeholder="qwen3-coder:30b"
                  />
                </div>
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <ModelPicker
                    componentType="GEN"
                    provider={genBackend}
                    value={genModelHttp}
                    onChange={setGenModelHttp}
                    label="HTTP Override"
                    tooltipKey="GEN_MODEL_HTTP"
                    allowCustom
                  />
                </div>
                <div className="input-group">
                  <ModelPicker
                    componentType="GEN"
                    provider={genBackend}
                    value={genModelMcp}
                    onChange={setGenModelMcp}
                    label="MCP Override"
                    tooltipKey="GEN_MODEL_MCP"
                    allowCustom
                  />
                </div>
                <div className="input-group">
                  <ModelPicker
                    componentType="GEN"
                    provider={genBackend}
                    value={genModelCli}
                    onChange={setGenModelCli}
                    label="CLI Override"
                    tooltipKey="GEN_MODEL_CLI"
                    allowCustom
                  />
                </div>
              </div>
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-generation-enrichment-routing">
              <div style={SECTION_TITLE_STYLE}>2) Enrichment Routing</div>
              <div style={SECTION_DESC_STYLE}>
                Select enrichment models/backend and explicitly disable enrichment when pure retrieval answers are preferred.
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <ModelPicker
                    componentType="GEN"
                    provider={enrichBackend}
                    value={enrichModel}
                    onChange={setEnrichModel}
                    label="Enrich Model"
                    tooltipKey="ENRICH_MODEL"
                    allowCustom
                  />
                </div>
                <div className="input-group">
                  <label>
                    Enrich Model (Ollama) <TooltipIcon name="ENRICH_MODEL_OLLAMA" />
                  </label>
                  <input
                    type="text"
                    value={enrichModelOllama}
                    onChange={(e) => setEnrichModelOllama(e.target.value)}
                    placeholder="qwen3-coder:14b"
                  />
                </div>
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    Enrichment Backend <TooltipIcon name="ENRICH_BACKEND" />
                  </label>
                  <select value={enrichBackend} onChange={(e) => setEnrichBackend(e.target.value)}>
                    <option value="openai">openai</option>
                    <option value="ollama">ollama</option>
                    <option value="mlx">mlx</option>
                  </select>
                </div>
                <div className="input-group">
                  <label>
                    Disable Enrichment <TooltipIcon name="ENRICH_DISABLED" />
                  </label>
                  <select value={enrichDisabled} onChange={(e) => setEnrichDisabled(parseInt(e.target.value, 10))}>
                    <option value={0}>Enabled</option>
                    <option value={1}>Disabled</option>
                  </select>
                </div>
              </div>
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-generation-provider-readiness">
              <div style={SECTION_TITLE_STYLE}>3) Provider Readiness</div>
              <div style={SECTION_DESC_STYLE}>
                Confirm provider credentials before choosing models that depend on those services.
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    OpenAI API Key <TooltipIcon name="OPENAI_API_KEY" />
                  </label>
                  <ApiKeyStatus keyName="OPENAI_API_KEY" label="OpenAI API Key" />
                </div>
                <div className="input-group">
                  <label>
                    Anthropic API Key <TooltipIcon name="ANTHROPIC_API_KEY" />
                  </label>
                  <ApiKeyStatus keyName="ANTHROPIC_API_KEY" label="Anthropic API Key" />
                </div>
                <div className="input-group">
                  <label>
                    Google API Key <TooltipIcon name="GOOGLE_API_KEY" />
                  </label>
                  <ApiKeyStatus keyName="GOOGLE_API_KEY" label="Google API Key" />
                </div>
              </div>
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-generation-endpoint-overrides">
              <div style={SECTION_TITLE_STYLE}>4) Endpoint Overrides</div>
              <div style={SECTION_DESC_STYLE}>
                Override transport endpoints for local gateways, proxies, or self-hosted OpenAI-compatible deployments.
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    Ollama URL <TooltipIcon name="OLLAMA_URL" />
                  </label>
                  <input
                    type="text"
                    value={ollamaUrl}
                    onChange={(e) => setOllamaUrl(e.target.value)}
                    placeholder="http://127.0.0.1:11434/api"
                  />
                </div>
                <div className="input-group">
                  <label>
                    OpenAI Base URL <TooltipIcon name="OPENAI_BASE_URL" />
                  </label>
                  <input
                    type="text"
                    value={openaiBaseUrl}
                    onChange={(e) => setOpenaiBaseUrl(e.target.value)}
                    placeholder="Proxy override"
                  />
                </div>
              </div>
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-generation-sampling-budget">
              <div style={SECTION_TITLE_STYLE}>5) Sampling Budget</div>
              <div style={SECTION_DESC_STYLE}>
                Set creativity and output budget controls that directly affect answer style, length, and variability.
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    Temperature <TooltipIcon name="GEN_TEMPERATURE" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={2}
                    step={0.01}
                    value={genTemperature}
                    onChange={(e) => setGenTemperature(snapNumber(e.target.value, 0.0))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Max Tokens <TooltipIcon name="GEN_MAX_TOKENS" />
                  </label>
                  <input
                    type="number"
                    min={100}
                    max={8192}
                    step={1}
                    value={genMaxTokens}
                    onChange={(e) => setGenMaxTokens(snapNumber(e.target.value, 2048))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Top P <TooltipIcon name="GEN_TOP_P" />
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={genTopP}
                    onChange={(e) => setGenTopP(snapNumber(e.target.value, 1.0))}
                  />
                </div>
              </div>
            </div>

            <div style={SECTION_STYLE} data-testid="retrieval-section-generation-reliability">
              <div style={SECTION_TITLE_STYLE}>6) Reliability / Timeouts</div>
              <div style={SECTION_DESC_STYLE}>
                Bound request duration and retry strategy for stable execution across local and cloud generation backends.
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    GEN Timeout <TooltipIcon name="GEN_TIMEOUT" />
                  </label>
                  <input
                    type="number"
                    min={10}
                    max={300}
                    value={genTimeout}
                    onChange={(e) => setGenTimeout(snapNumber(e.target.value, 60))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Retry Attempts <TooltipIcon name="GEN_RETRY_MAX" />
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={genRetryMax}
                    onChange={(e) => setGenRetryMax(snapNumber(e.target.value, 2))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Ollama Num Ctx <TooltipIcon name="OLLAMA_NUM_CTX" />
                  </label>
                  <input
                    type="number"
                    min={2048}
                    max={32768}
                    value={ollamaNumCtx}
                    onChange={(e) => setOllamaNumCtx(snapNumber(e.target.value, 8192))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Ollama Request Timeout <TooltipIcon name="OLLAMA_REQUEST_TIMEOUT" />
                  </label>
                  <input
                    type="number"
                    min={30}
                    max={1200}
                    value={ollamaRequestTimeout}
                    onChange={(e) => setOllamaRequestTimeout(snapNumber(e.target.value, 300))}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Ollama Stream Idle Timeout <TooltipIcon name="OLLAMA_STREAM_IDLE_TIMEOUT" />
                  </label>
                  <input
                    type="number"
                    min={5}
                    max={300}
                    value={ollamaStreamIdleTimeout}
                    onChange={(e) => setOllamaStreamIdleTimeout(snapNumber(e.target.value, 60))}
                  />
                </div>
              </div>
            </div>

            <details style={{ ...SECTION_STYLE, marginTop: 14 }} data-testid="retrieval-section-model-assignments">
              <summary style={{ ...SECTION_TITLE_STYLE, cursor: 'pointer', marginBottom: 0 }}>
                Model Assignments Overview
              </summary>
              <div style={{ marginTop: 12 }}>
                <ModelAssignments />
              </div>
            </details>
          </div>
        )}

        {selectedCard === 'ops_tracing' && (
          <div>
            <h4 style={CARD_TITLE_STYLE}>
              Ops & Tracing
            </h4>

            <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 16 }}>
              Tune runtime compatibility gates separately from tracing and telemetry integrations.
            </div>

            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }} data-testid="retrieval-ops-tabs">
              <button
                type="button"
                data-testid="retrieval-ops-tab-runtime"
                onClick={() => setOpsTracingView('runtime_compatibility')}
                style={{
                  ...ACTION_BUTTON_STYLE,
                  border:
                    opsTracingView === 'runtime_compatibility' ? '1px solid var(--accent)' : '1px solid var(--line)',
                  background:
                    opsTracingView === 'runtime_compatibility'
                      ? 'rgba(var(--accent-rgb), 0.14)'
                      : 'var(--bg-elev1)',
                  color: opsTracingView === 'runtime_compatibility' ? 'var(--accent)' : 'var(--fg)',
                }}
              >
                Runtime Compatibility
              </button>
              <button
                type="button"
                data-testid="retrieval-ops-tab-observability"
                onClick={() => setOpsTracingView('observability_integrations')}
                style={{
                  ...ACTION_BUTTON_STYLE,
                  border:
                    opsTracingView === 'observability_integrations' ? '1px solid var(--accent)' : '1px solid var(--line)',
                  background:
                    opsTracingView === 'observability_integrations'
                      ? 'rgba(var(--accent-rgb), 0.14)'
                      : 'var(--bg-elev1)',
                  color: opsTracingView === 'observability_integrations' ? 'var(--accent)' : 'var(--fg)',
                }}
              >
                Observability & Integrations
              </button>
            </div>

            {opsTracingView === 'runtime_compatibility' && (
              <div data-testid="retrieval-ops-runtime-panel">
                <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-ops-hydration">
                  <div style={SECTION_TITLE_STYLE}>1) Hydration</div>
                  <div style={SECTION_DESC_STYLE}>
                    Control content hydration mode and max character expansion before handing results to answer generation.
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        Hydration Mode <TooltipIcon name="HYDRATION_MODE" />
                      </label>
                      <select
                        value={hydrationMode || retrievalHydrationMode}
                        onChange={(e) => setUnifiedHydrationMode(e.target.value)}
                      >
                        <option value="lazy">lazy</option>
                        <option value="eager">eager</option>
                        <option value="none">none</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>
                        Hydration Max Chars <TooltipIcon name="HYDRATION_MAX_CHARS" />
                      </label>
                      <input
                        type="number"
                        min={200}
                        max={20000}
                        value={hydrationMaxChars || retrievalHydrationMaxChars}
                        onChange={(e) => setUnifiedHydrationMaxChars(snapNumber(e.target.value, 2000))}
                      />
                    </div>
                  </div>
                </div>

                <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-ops-compatibility">
                  <div style={SECTION_TITLE_STYLE}>2) Compatibility & Evaluation</div>
                  <div style={SECTION_DESC_STYLE}>
                    Keep retrieval/eval behavior aligned with compatibility gates used by LangGraph and fallback policies.
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        Eval Final K <TooltipIcon name="EVAL_FINAL_K" />
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        value={evalFinalK}
                        onChange={(e) => setEvalFinalK(snapNumber(e.target.value, 5))}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Eval Multi <TooltipIcon name="EVAL_MULTI" />
                      </label>
                      <select value={evalMulti} onChange={(e) => setEvalMulti(parseInt(e.target.value, 10))}>
                        <option value={1}>Enabled</option>
                        <option value={0}>Disabled</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>
                        Query Expansion <TooltipIcon name="QUERY_EXPANSION_ENABLED" />
                      </label>
                      <select
                        value={queryExpansionEnabled}
                        onChange={(e) => setQueryExpansionEnabled(parseInt(e.target.value, 10))}
                      >
                        <option value={1}>Enabled</option>
                        <option value={0}>Disabled</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>
                        Chunk Summary Search <TooltipIcon name="CHUNK_SUMMARY_SEARCH_ENABLED" />
                      </label>
                      <select
                        value={cardSearchEnabled}
                        onChange={(e) => setCardSearchEnabled(parseInt(e.target.value, 10))}
                      >
                        <option value={1}>Enabled</option>
                        <option value={0}>Disabled</option>
                      </select>
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        Confidence Top1 <TooltipIcon name="CONF_TOP1" />
                      </label>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={confTop1}
                        onChange={(e) => setConfTop1(snapNumber(e.target.value, 0.62))}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Confidence Avg5 <TooltipIcon name="CONF_AVG5" />
                      </label>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={confAvg5}
                        onChange={(e) => setConfAvg5(snapNumber(e.target.value, 0.55))}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Confidence Any <TooltipIcon name="CONF_ANY" />
                      </label>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={confAny}
                        onChange={(e) => setConfAny(snapNumber(e.target.value, 0.55))}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Multi Query M <TooltipIcon name="MULTI_QUERY_M" />
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={20}
                        value={multiQueryM}
                        onChange={(e) => setMultiQueryM(snapNumber(e.target.value, 4))}
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        LangGraph Final K <TooltipIcon name="LANGGRAPH_FINAL_K" />
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        value={langgraphFinalK}
                        onChange={(e) => setLanggraphFinalK(snapNumber(e.target.value, 20))}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        LangGraph Max Rewrites <TooltipIcon name="LANGGRAPH_MAX_QUERY_REWRITES" />
                      </label>
                      <input
                        type="number"
                        min={0}
                        max={10}
                        value={langgraphMaxQueryRewrites}
                        onChange={(e) => setLanggraphMaxQueryRewrites(snapNumber(e.target.value, 2))}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Fallback Confidence <TooltipIcon name="FALLBACK_CONFIDENCE" />
                      </label>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={fallbackConfidence}
                        onChange={(e) => setFallbackConfidence(snapNumber(e.target.value, 0.55))}
                      />
                    </div>
                  </div>
                </div>

                <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-ops-retrieval-balance">
                  <div style={SECTION_TITLE_STYLE}>3) Retrieval Balance</div>
                  <div style={SECTION_DESC_STYLE}>
                    Tune hybrid weighting and candidate fan-out for compatibility with existing retrieval/evaluation flows.
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        RRF K Div <TooltipIcon name="RRF_K_DIV" />
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={200}
                        value={rrfKDiv}
                        onChange={(e) => setRrfKDiv(snapNumber(e.target.value, 60))}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Retrieval BM25 Weight <TooltipIcon name="BM25_WEIGHT" />
                      </label>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={retrievalBm25Weight}
                        onChange={(e) => setRetrievalBm25Weight(snapNumber(e.target.value, 0.3))}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Retrieval Vector Weight <TooltipIcon name="VECTOR_WEIGHT" />
                      </label>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={retrievalVectorWeight}
                        onChange={(e) => setRetrievalVectorWeight(snapNumber(e.target.value, 0.7))}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        TopK Dense <TooltipIcon name="TOPK_DENSE" />
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={200}
                        value={topkDense}
                        onChange={(e) => setTopkDense(snapNumber(e.target.value, 75))}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        TopK Sparse <TooltipIcon name="TOPK_SPARSE" />
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={200}
                        value={topkSparse}
                        onChange={(e) => setTopkSparse(snapNumber(e.target.value, 75))}
                      />
                    </div>
                  </div>
                </div>

                <div style={SECTION_STYLE} data-testid="retrieval-section-ops-semantic-cache">
                  <div style={SECTION_TITLE_STYLE}>4) Semantic Cache</div>
                  <div style={SECTION_DESC_STYLE}>
                    Configure semantic cache policy for retrieval, answer generation, and chat generation.
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>Cache Enabled</label>
                      <select value={semanticCacheEnabled} onChange={(e) => setSemanticCacheEnabled(parseInt(e.target.value, 10))}>
                        <option value={1}>Enabled</option>
                        <option value={0}>Disabled</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>Cache Mode</label>
                      <select
                        value={semanticCacheMode}
                        onChange={(e) => setSemanticCacheMode(e.target.value as 'read_write' | 'read_only' | 'write_only')}
                        disabled={semanticCacheEnabled === 0}
                      >
                        <option value="read_write">read_write</option>
                        <option value="read_only">read_only</option>
                        <option value="write_only">write_only</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>Max Entries</label>
                      <input
                        type="number"
                        min={100}
                        max={500000}
                        value={semanticCacheMaxEntries}
                        onChange={(e) => setSemanticCacheMaxEntries(snapNumber(e.target.value, 5000))}
                        disabled={semanticCacheEnabled === 0}
                      />
                    </div>
                    <div className="input-group">
                      <label>Min Query Chars</label>
                      <input
                        type="number"
                        min={1}
                        max={200}
                        value={semanticCacheMinQueryChars}
                        onChange={(e) => setSemanticCacheMinQueryChars(snapNumber(e.target.value, 3))}
                        disabled={semanticCacheEnabled === 0}
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>Similarity Threshold (Search)</label>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={semanticCacheThresholdSearch}
                        onChange={(e) => setSemanticCacheThresholdSearch(snapNumber(e.target.value, 0.9))}
                        disabled={semanticCacheEnabled === 0}
                      />
                    </div>
                    <div className="input-group">
                      <label>Similarity Threshold (Answer)</label>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={semanticCacheThresholdAnswer}
                        onChange={(e) => setSemanticCacheThresholdAnswer(snapNumber(e.target.value, 0.93))}
                        disabled={semanticCacheEnabled === 0}
                      />
                    </div>
                    <div className="input-group">
                      <label>Similarity Threshold (Chat)</label>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={semanticCacheThresholdChat}
                        onChange={(e) => setSemanticCacheThresholdChat(snapNumber(e.target.value, 0.95))}
                        disabled={semanticCacheEnabled === 0}
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>TTL Seconds (Search)</label>
                      <input
                        type="number"
                        min={10}
                        max={86400}
                        value={semanticCacheTtlSearch}
                        onChange={(e) => setSemanticCacheTtlSearch(snapNumber(e.target.value, 900))}
                        disabled={semanticCacheEnabled === 0}
                      />
                    </div>
                    <div className="input-group">
                      <label>TTL Seconds (Answer)</label>
                      <input
                        type="number"
                        min={10}
                        max={86400}
                        value={semanticCacheTtlAnswer}
                        onChange={(e) => setSemanticCacheTtlAnswer(snapNumber(e.target.value, 1800))}
                        disabled={semanticCacheEnabled === 0}
                      />
                    </div>
                    <div className="input-group">
                      <label>TTL Seconds (Chat)</label>
                      <input
                        type="number"
                        min={10}
                        max={86400}
                        value={semanticCacheTtlChat}
                        onChange={(e) => setSemanticCacheTtlChat(snapNumber(e.target.value, 600))}
                        disabled={semanticCacheEnabled === 0}
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>Chat History Window</label>
                      <input
                        type="number"
                        min={0}
                        max={50}
                        value={semanticCacheChatHistoryWindow}
                        onChange={(e) => setSemanticCacheChatHistoryWindow(snapNumber(e.target.value, 6))}
                        disabled={semanticCacheEnabled === 0}
                      />
                    </div>
                    <div className="input-group">
                      <label>Bypass if Images</label>
                      <select
                        value={semanticCacheBypassIfImages}
                        onChange={(e) => setSemanticCacheBypassIfImages(parseInt(e.target.value, 10))}
                        disabled={semanticCacheEnabled === 0}
                      >
                        <option value={1}>Enabled</option>
                        <option value={0}>Disabled</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>Max Temperature for Write</label>
                      <input
                        type="number"
                        min={0}
                        max={2}
                        step={0.05}
                        value={semanticCacheMaxTemperatureForWrite}
                        onChange={(e) => setSemanticCacheMaxTemperatureForWrite(snapNumber(e.target.value, 0.5))}
                        disabled={semanticCacheEnabled === 0}
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}

            {opsTracingView === 'observability_integrations' && (
              <div data-testid="retrieval-ops-observability-panel">
                <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-ops-trace-preview">
                  <div style={SECTION_TITLE_STYLE}>1) Trace Preview</div>
                  <div style={SECTION_DESC_STYLE}>
                    Inspect latest routing trace output to validate decision flow and candidate/reranker behavior.
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 16, alignItems: 'center' }}>
                    <div className="input-group">
                      <button
                        type="button"
                        data-testid="retrieval-load-latest-trace"
                        style={ACTION_BUTTON_STYLE}
                        onClick={handleLoadTrace}
                        disabled={traceLoading}
                      >
                        {traceLoading ? 'Loading trace…' : 'Load Latest Trace'}
                      </button>
                    </div>
                    <div className="input-group">
                      <span className="small" style={{ color: 'var(--fg-muted)' }}>
                        Trace preview reads latest local run telemetry.
                      </span>
                    </div>
                  </div>

                  {traceStatus ? (
                    <div className="result-display" style={{ color: traceStatus.type === 'error' ? 'var(--err)' : 'var(--fg-muted)' }}>
                      {traceStatus.message}
                    </div>
                  ) : null}

                  <div style={{ marginTop: 10 }}>
                    <LiveTerminal
                      id="retrieval_trace_terminal"
                      title="Routing Trace Preview"
                      initialContent={['Trigger "Load Latest Trace" to preview router telemetry.']}
                      ref={traceTerminalRef}
                    />
                  </div>
                </div>

                <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-ops-tracing-core">
                  <div style={SECTION_TITLE_STYLE}>2) Tracing Core</div>
                  <div style={SECTION_DESC_STYLE}>
                    Configure trace mode, enablement, retention, and sampling before downstream metrics/alerts.
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        Tracing Mode <TooltipIcon name="TRACING_MODE" />
                      </label>
                      <select value={tracingMode} onChange={(e) => setTracingMode(e.target.value)}>
                        <option value="off">off</option>
                        <option value="local">local</option>
                        <option value="langsmith">langsmith</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>
                        Tracing Enabled <TooltipIcon name="TRACING_ENABLED" />
                      </label>
                      <select value={tracingEnabled} onChange={(e) => setTracingEnabled(parseInt(e.target.value, 10))}>
                        <option value={1}>Enabled</option>
                        <option value={0}>Disabled</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>
                        Trace Sampling Rate <TooltipIcon name="TRACE_SAMPLING_RATE" />
                      </label>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={traceSamplingRate}
                        onChange={(e) => setTraceSamplingRate(snapNumber(e.target.value, 1.0))}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Trace Retention <TooltipIcon name="TRACE_RETENTION" />
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={1000}
                        value={traceRetention}
                        onChange={(e) => setTraceRetention(snapNumber(e.target.value, 50))}
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        Auto-open LangSmith <TooltipIcon name="TRACE_AUTO_LS" />
                      </label>
                      <select value={traceAutoLs} onChange={(e) => setTraceAutoLs(parseInt(e.target.value, 10))}>
                        <option value={1}>Enabled</option>
                        <option value={0}>Disabled</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>
                        Metrics Enabled <TooltipIcon name="METRICS_ENABLED" />
                      </label>
                      <select value={metricsEnabled} onChange={(e) => setMetricsEnabled(parseInt(e.target.value, 10))}>
                        <option value={1}>Enabled</option>
                        <option value={0}>Disabled</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>
                        Prometheus Port <TooltipIcon name="PROMETHEUS_PORT" />
                      </label>
                      <input
                        type="number"
                        min={1024}
                        max={65535}
                        value={prometheusPort}
                        onChange={(e) => setPrometheusPort(snapNumber(e.target.value, 9090))}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Log Level <TooltipIcon name="LOG_LEVEL" />
                      </label>
                      <select value={logLevel} onChange={(e) => setLogLevel(e.target.value)}>
                        <option value="DEBUG">DEBUG</option>
                        <option value="INFO">INFO</option>
                        <option value="WARNING">WARNING</option>
                        <option value="ERROR">ERROR</option>
                      </select>
                    </div>
                  </div>
                </div>

                <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-ops-alerting">
                  <div style={SECTION_TITLE_STYLE}>3) Alerting & Export</div>
                  <div style={SECTION_DESC_STYLE}>
                    Define alert notification semantics and local trace persistence path for audit/replay workflows.
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        Include Resolved Alerts <TooltipIcon name="ALERT_INCLUDE_RESOLVED" />
                      </label>
                      <select
                        value={alertIncludeResolved}
                        onChange={(e) => setAlertIncludeResolved(parseInt(e.target.value, 10))}
                      >
                        <option value={1}>Enabled</option>
                        <option value={0}>Disabled</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>
                        Alert Webhook Timeout <TooltipIcon name="ALERT_WEBHOOK_TIMEOUT" />
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={60}
                        value={alertWebhookTimeout}
                        onChange={(e) => setAlertWebhookTimeout(snapNumber(e.target.value, 5))}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Notify Severities <TooltipIcon name="ALERT_NOTIFY_SEVERITIES" />
                      </label>
                      <input
                        type="text"
                        value={alertNotifySeverities}
                        onChange={(e) => setAlertNotifySeverities(e.target.value)}
                        placeholder="critical,warning"
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        Tribrid Log Path <TooltipIcon name="TRIBRID_LOG_PATH" />
                      </label>
                      <input
                        type="text"
                        value={tribridLogPath}
                        onChange={(e) => setTribridLogPath(e.target.value)}
                        placeholder="data/logs/queries.jsonl"
                      />
                    </div>
                    <div className="input-group" />
                  </div>
                </div>

                <div style={SECTION_STYLE} data-testid="retrieval-section-ops-integrations">
                  <div style={SECTION_TITLE_STYLE}>4) Integrations</div>
                  <div style={SECTION_DESC_STYLE}>
                    Configure LangSmith/LangTrace endpoints and credentials used for external trace ingestion and analysis.
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        LangSmith Endpoint <TooltipIcon name="LANGCHAIN_ENDPOINT" />
                      </label>
                      <input
                        type="text"
                        value={langchainEndpoint}
                        onChange={(e) => setLangchainEndpoint(e.target.value)}
                        placeholder="https://api.smith.langchain.com"
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        LangSmith Project <TooltipIcon name="LANGCHAIN_PROJECT" />
                      </label>
                      <input
                        type="text"
                        value={langchainProject}
                        onChange={(e) => setLangchainProject(e.target.value)}
                        placeholder="tribrid"
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        LangChain Tracing V2 <TooltipIcon name="LANGCHAIN_TRACING_V2" />
                      </label>
                      <select
                        value={langchainTracingV2}
                        onChange={(e) => setLangchainTracingV2(parseInt(e.target.value, 10))}
                      >
                        <option value={1}>Enabled</option>
                        <option value={0}>Disabled</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>
                        LangChain API Key <TooltipIcon name="LANGCHAIN_API_KEY" />
                      </label>
                      <ApiKeyStatus keyName="LANGCHAIN_API_KEY" label="LangChain API Key" />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        LangSmith User Key <TooltipIcon name="LANGSMITH_API_KEY" />
                      </label>
                      <ApiKeyStatus keyName="LANGSMITH_API_KEY" label="LangSmith API Key" />
                    </div>
                    <div className="input-group" />
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        LangTrace API Host <TooltipIcon name="LANGTRACE_API_HOST" />
                      </label>
                      <input
                        type="text"
                        value={langtraceApiHost}
                        onChange={(e) => setLangtraceApiHost(e.target.value)}
                        placeholder="https://api.langtrace.dev"
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        LangTrace Project ID <TooltipIcon name="LANGTRACE_PROJECT_ID" />
                      </label>
                      <input
                        type="text"
                        value={langtraceProjectId}
                        onChange={(e) => setLangtraceProjectId(e.target.value)}
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        LangTrace API Key <TooltipIcon name="LANGTRACE_API_KEY" />
                      </label>
                      <ApiKeyStatus keyName="LANGTRACE_API_KEY" label="LangTrace API Key" />
                    </div>
                    <div className="input-group" />
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function snapNumber(value: string, fallback: number) {
  if (value === '') return fallback;
  const next = Number(value);
  return Number.isFinite(next) ? next : fallback;
}

function formatTracePayload(payload: TracesLatestResponse, vectorBackend: string): string {
  if (!payload?.trace) {
    return 'No traces yet. Set Tracing Mode to Local/LangSmith (not Off) and run a query.';
  }
  const events = Array.isArray(payload.trace.events) ? payload.trace.events : [];
  const parts: string[] = [];

  const findEvent = (kind: string) => events.find((ev) => ev.kind === kind);
  const decide = findEvent('router.decide');
  const rerank = findEvent('reranker.rank');
  const gate = findEvent('gating.outcome');

  const header = [
    `Policy: ${decide?.data?.policy ?? '—'}`,
    `Intent: ${decide?.data?.intent ?? '—'}`,
    `Final K: ${rerank?.data?.output_topK ?? '—'}`,
    `Vector: ${vectorBackend}`,
  ];

  parts.push(header.join('  •  '));
  parts.push('');

  const retrieval = findEvent('retriever.retrieve');
  if (retrieval && Array.isArray(retrieval.data?.candidates)) {
    const rows = retrieval.data.candidates.map((candidate: any) => [
      (candidate.path || '').split('/').slice(-2).join('/'),
      candidate.bm25_rank ?? '',
      candidate.dense_rank ?? '',
    ]);
    parts.push(`Pre-rerank candidates (${retrieval.data.candidates.length}):`);
    parts.push(formatTraceTable(rows, ['path', 'bm25', 'dense']));
    parts.push('');
  }

  if (rerank && Array.isArray(rerank.data?.scores)) {
    const rows = rerank.data.scores.map((score: any) => [
      (score.path || '').split('/').slice(-2).join('/'),
      score.score?.toFixed?.(3) ?? score.score ?? '',
    ]);
    parts.push(`Rerank (${rerank.data.scores.length}):`);
    parts.push(formatTraceTable(rows, ['path', 'score']));
    parts.push('');
  }

  if (gate) {
    parts.push(`Gate: top1>=${gate.data?.top1_thresh} avg5>=${gate.data?.avg5_thresh} → ${gate.data?.outcome}`);
    parts.push('');
  }

  const allEvents = events;
  if (allEvents.length) {
    parts.push(`Events (${allEvents.length}):`);
    allEvents.forEach((event) => {
      const when = new Date(event.ts ?? Date.now()).toLocaleTimeString();
      const name = (event.kind ?? '').padEnd(18);
      parts.push(`  ${when}  ${name}  ${event.msg ?? ''}`);
    });
  }

  return parts.join('\n');
}

function formatTraceTable(rows: Array<Array<string | number>>, headers: string[]): string {
  const all = [headers, ...rows];
  const widths = headers.map((_, col) => Math.max(...all.map((row) => String(row[col] ?? '').length)));
  const formatLine = (row: Array<string | number>) =>
    row
      .map((cell, idx) => String(cell ?? '').padEnd(widths[idx]))
      .join('  ')
      .trimEnd();

  return ['```', formatLine(headers), formatLine(widths.map((w) => '-'.repeat(w))), ...rows.map(formatLine), '```']
    .filter(Boolean)
    .join('\n');
}
