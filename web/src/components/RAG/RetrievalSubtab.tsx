import { useState, useEffect, useCallback, useRef, type CSSProperties } from 'react';
import { EmbeddingMismatchWarning } from '@/components/ui/EmbeddingMismatchWarning';
import { showToast } from '@/utils/toast';
import { LiveTerminal, type LiveTerminalHandle } from '@/components/LiveTerminal/LiveTerminal';
import { IntentMatrixEditor } from '@/components/RAG/IntentMatrixEditor';
import { SyntheticCallout } from '@/components/RAG/SyntheticCallout';
import { ModelAssignments } from '@/components/RAG/ModelAssignments';
import { ModelPicker as ChatModelPicker } from '@/components/Chat/ModelPicker';
import { PromptLink } from '@/components/ui/PromptLink';
import { ApiKeyStatus } from '@/components/ui/ApiKeyStatus';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { SECRET_REDACTED } from '@/api/secrets';
import { createAlertError, createInlineError } from '@/utils/errorHelpers';
import { NumberField } from '@/components/ui/NumberField';
import { useAPI, useConfig, useConfigField } from '@/hooks';
import { tracesApi } from '@/api';
import { useRepoStore } from '@/stores/useRepoStore';
import type { ChatModelInfo, ChatModelsResponse, GraphStats, TracesLatestResponse } from '@/types/generated';

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

// Reason shown when a dependent control is inert because its parent is off.
// >=12px per the legibility floor (do not reuse the 11px description tier here).
const INERT_NOTE_STYLE: CSSProperties = {
  fontSize: 12,
  color: 'var(--fg-muted)',
  marginTop: 6,
  lineHeight: 1.4,
};

const PUBLIC_BROWSER_LINK_HINT = 'Browser links use this; ingestion/tracking uses the local URL.';

export function RetrievalSubtab() {
  const { api } = useAPI();
  const [selectedCard, setSelectedCard] = useState<RetrievalCardId>('search_paths');
  const [opsTracingView, setOpsTracingView] = useState<OpsTracingViewId>('runtime_compatibility');
  const [hydrating, setHydrating] = useState(true);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceStatus, setTraceStatus] = useState<{ type: 'info' | 'error'; message: string } | null>(null);
  const traceTerminalRef = useRef<LiveTerminalHandle>(null);

  const { repos, activeRepo, setActiveRepo, loadRepos } = useRepoStore();

  // --- Generation ---------------------------------------------------------
  const [genModel, setGenModel] = useConfigField<string>('generation.gen_model', '');
  const [genTemperature, setGenTemperature] = useConfigField<number>('generation.gen_temperature', 0.0);
  const [enrichModel, setEnrichModel] = useConfigField<string>('generation.enrich_model', '');
  const [genModelHttp, setGenModelHttp] = useConfigField<string>('generation.gen_model_http', '');
  const [genModelMcp, setGenModelMcp] = useConfigField<string>('generation.gen_model_mcp', '');
  const [genModelCli, setGenModelCli] = useConfigField<string>('generation.gen_model_cli', '');
  const [genMaxTokens, setGenMaxTokens] = useConfigField<number>('generation.gen_max_tokens', 512);
  const [genTopP, setGenTopP] = useConfigField<number>('generation.gen_top_p', 1.0);
  const [genTimeout, setGenTimeout] = useConfigField<number>('generation.gen_timeout', 600);
  const [enrichDisabled, setEnrichDisabled] = useConfigField<boolean>('generation.enrich_disabled', false);
  const [generationModels, setGenerationModels] = useState<ChatModelInfo[]>([]);

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

  useEffect(() => {
    const corpus = String(activeRepo || '').trim();
    if (!corpus) {
      setGraphReadiness(null);
      return;
    }
    // Through `api()` and an AbortController like every other request in this file, not a
    // hand-rolled absolute fetch that sidesteps base-URL resolution (review F-06).
    const controller = new AbortController();
    fetch(api(`graph/${encodeURIComponent(corpus)}/stats`), { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then((stats) => setGraphReadiness(stats as GraphStats))
      .catch((cause) => {
        if (cause instanceof DOMException && cause.name === 'AbortError') return;
        // Readiness is advisory: if it cannot be read, the card says nothing rather than
        // guessing that the graph is empty.
        setGraphReadiness(null);
      });
    return () => controller.abort();
  }, [activeRepo, api]);

  // --- Retrieval ----------------------------------------------------------
  const [multiQueryRewrites, setMultiQueryRewrites] = useConfigField<number>('retrieval.max_query_rewrites', 2);
  const [langgraphMaxQueryRewrites, setLanggraphMaxQueryRewrites] =
    useConfigField<number>('retrieval.langgraph_max_query_rewrites', 2);
  const [fallbackConfidence, setFallbackConfidence] = useConfigField<number>('retrieval.fallback_confidence', 0.55);
  const [finalK, setFinalK] = useConfigField<number>('retrieval.final_k', 10);
  const [evalFinalK, setEvalFinalK] = useConfigField<number>('retrieval.eval_final_k', 5);
  const [confTop1, setConfTop1] = useConfigField<number>('retrieval.conf_top1', 0.62);
  const [confAvg5, setConfAvg5] = useConfigField<number>('retrieval.conf_avg5', 0.55);
  const [confAny, setConfAny] = useConfigField<number>('retrieval.conf_any', 0.55);
  const [evalMulti, setEvalMulti] = useConfigField<boolean>('retrieval.eval_multi', true);
  const [queryExpansionEnabled, setQueryExpansionEnabled] = useConfigField<boolean>('retrieval.query_expansion_enabled', true);
  const [cardSearchEnabled, setCardSearchEnabled] = useConfigField<boolean>('retrieval.chunk_summary_search_enabled', true);
  const [maxChunksPerFile, setMaxChunksPerFile] = useConfigField<number>('retrieval.max_chunks_per_file', 3);
  const [dedupBy, setDedupBy] = useConfigField<'chunk_id' | 'file_path'>('retrieval.dedup_by', 'chunk_id');
  const [neighborWindow, setNeighborWindow] = useConfigField<number>('retrieval.neighbor_window', 1);
  const [minScoreVector, setMinScoreVector] = useConfigField<number>('retrieval.min_score_vector', 0.0);
  const [minScoreSparse, setMinScoreSparse] = useConfigField<number>('retrieval.min_score_sparse', 0.0);
  const [minScoreGraph, setMinScoreGraph] = useConfigField<number>('retrieval.min_score_graph', 0.0);
  const [enableMmr, setEnableMmr] = useConfigField<boolean>('retrieval.enable_mmr', false);
  const [mmrLambda, setMmrLambda] = useConfigField<number>('retrieval.mmr_lambda', 0.7);
  const [multiQueryM, setMultiQueryM] = useConfigField<number>('retrieval.multi_query_m', 4);
  const [useSemanticSynonyms, setUseSemanticSynonyms] = useConfigField<boolean>('retrieval.use_semantic_synonyms', true);
  const [synonymsPath, setSynonymsPath] = useConfigField<string>('retrieval.tribrid_synonyms_path', '');
  const [retrievalHydrationMode, setRetrievalHydrationMode] = useConfigField<string>('retrieval.hydration_mode', 'lazy');
  const [retrievalHydrationMaxChars, setRetrievalHydrationMaxChars] = useConfigField<number>('retrieval.hydration_max_chars', 2000);

  // --- Vector search ------------------------------------------------------
  const [vectorSearchEnabled, setVectorSearchEnabled] = useConfigField<boolean>('vector_search.enabled', true);
  const [vectorSearchTopK, setVectorSearchTopK] = useConfigField<number>('vector_search.top_k', 50);
  const [vectorSimilarityThreshold, setVectorSimilarityThreshold] = useConfigField<number>('vector_search.similarity_threshold', 0.0);

  // --- Sparse search ------------------------------------------------------
  const [sparseSearchEnabled, setSparseSearchEnabled] = useConfigField<boolean>('sparse_search.enabled', true);
  const [sparseSearchTopK, setSparseSearchTopK] = useConfigField<number>('sparse_search.top_k', 50);
  const [sparseBm25K1, setSparseBm25K1] = useConfigField<number>('sparse_search.bm25_k1', 1.2);
  const [sparseBm25B, setSparseBm25B] = useConfigField<number>('sparse_search.bm25_b', 0.4);

  // --- Graph search -------------------------------------------------------
  // M-66: the graph leg's settings say nothing about whether this corpus HAS a graph.
  // Graph reported 0 entities / 0 relationships for nasa-apollo-11 while this card showed
  // graph search on, top-k 30, weight 0.3 and entity expansion enabled, with nothing to
  // suggest the entity half could not fire.
  const [graphReadiness, setGraphReadiness] = useState<GraphStats | null>(null);
  const [graphIndexingEnabled] = useConfigField<boolean>('graph_indexing.enabled', true);
  const [buildCodeGraph] = useConfigField<boolean>('graph_indexing.build_code_graph', false);
  const [graphSearchEnabled, setGraphSearchEnabled] = useConfigField<boolean>('graph_search.enabled', true);
  const [chunkNeighborWindow, setChunkNeighborWindow] = useConfigField<number>('graph_search.chunk_neighbor_window', 1);
  const [graphMaxHops, setGraphMaxHops] = useConfigField<number>('graph_search.max_hops', 2);
  const [graphIncludeCommunities, setGraphIncludeCommunities] = useConfigField<boolean>('graph_search.include_communities', true);
  const [graphSearchTopK, setGraphSearchTopK] = useConfigField<number>('graph_search.top_k', 30);
  const activeCorpus = repos.find(
    (corpus) => corpus.corpus_id === activeRepo || corpus.slug === activeRepo || corpus.name === activeRepo,
  );
  const graphPolicyLabel = activeCorpus?.internal
    ? 'Excluded internal corpus'
    : !graphIndexingEnabled
      ? 'Graph disabled'
      : buildCodeGraph
        ? 'Code AST graph'
        : 'Semantic entity graph';

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
  const [tracingEnabled, setTracingEnabled] = useConfigField<boolean>('tracing.tracing_enabled', true);
  const [traceSamplingRate, setTraceSamplingRate] = useConfigField<number>('tracing.trace_sampling_rate', 1.0);
  const [metricsEnabled, setMetricsEnabled] = useConfigField<boolean>('tracing.metrics_enabled', true);
  const [alertIncludeResolved, setAlertIncludeResolved] = useConfigField<boolean>('tracing.alert_include_resolved', true);
  const [alertWebhookTimeout, setAlertWebhookTimeout] = useConfigField<number>('tracing.alert_webhook_timeout', 5);
  const [logLevel, setLogLevel] = useConfigField<string>('tracing.log_level', 'INFO');
  const [tracingMode, setTracingMode] = useConfigField<string>('tracing.tracing_mode', 'local');
  const [traceRetention, setTraceRetention] = useConfigField<number>('tracing.trace_retention', 50);
  const [tribridLogPath, setTribridLogPath] = useConfigField<string>('tracing.tribrid_log_path', 'data/logs/queries.jsonl');
  const [alertNotifySeverities, setAlertNotifySeverities] = useConfigField<string>('tracing.alert_notify_severities', 'critical,warning');
  const [otelExportEnabled, setOtelExportEnabled] = useConfigField<boolean>('tracing.otel_export_enabled', true);
  const [otlpEndpoint, setOtlpEndpoint] = useConfigField<string>('tracing.otlp_endpoint', '');
  const [otlpHeaders, setOtlpHeaders] = useConfigField<string>('tracing.otlp_headers', '');
  const [otelServiceName, setOtelServiceName] = useConfigField<string>('tracing.otel_service_name', 'ragweld-api');
  const [langfuseEnabled, setLangfuseEnabled] = useConfigField<boolean>('tracing.langfuse_enabled', false);
  const [langfuseBaseUrl, setLangfuseBaseUrl] = useConfigField<string>('tracing.langfuse_base_url', '');
  const [langfusePublicBaseUrl, setLangfusePublicBaseUrl] = useConfigField<string>(
    'tracing.langfuse_public_base_url',
    'http://127.0.0.1:53000',
  );
  const [langfuseProject, setLangfuseProject] = useConfigField<string>('tracing.langfuse_project', 'ragweld');
  const [tempoBaseUrl, setTempoBaseUrl] = useConfigField<string>('tracing.tempo_base_url', '');
  const [alloyBaseUrl, setAlloyBaseUrl] = useConfigField<string>('tracing.alloy_base_url', '');
  const [costTrackingEnabled, setCostTrackingEnabled] = useConfigField<boolean>('tracing.cost_tracking_enabled', true);

  // --- Hydration ----------------------------------------------------------
  const [hydrationMode, setHydrationMode] = useConfigField<string>('hydration.hydration_mode', 'lazy');
  const [hydrationMaxChars, setHydrationMaxChars] = useConfigField<number>('hydration.hydration_max_chars', 2000);

  // --- Semantic cache -----------------------------------------------------
  const [semanticCacheEnabled, setSemanticCacheEnabled] = useConfigField<boolean>('semantic_cache.enabled', false);
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
    useConfigField<boolean>('semantic_cache.bypass_if_images', true);
  const [semanticCacheMaxTemperatureForWrite, setSemanticCacheMaxTemperatureForWrite] =
    useConfigField<number>('semantic_cache.max_temperature_for_write', 0.5);

  const {
    config,
    loading: configLoading,
    error: configError,
    reload,
    clearError,
  } = useConfig();
  const productionModelRoutingLocked = String(config?.ui?.runtime_mode || '').trim().toLowerCase() === 'production';


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
      showToast(error instanceof Error ? error.message : 'Failed to reload configuration', 'error');
      setHydrating(false);
    }
  }, [reload, clearError]);

  const handleLoadTrace = useCallback(async () => {
    setTraceLoading(true);
    setTraceStatus(null);
    try {
      const data: TracesLatestResponse = await tracesApi.getLatest();
      const formatted = formatTracePayload(data, 'qdrant').split('\n');
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
      <SyntheticCallout context="retrieval" />

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

          {/* Generation alias lives once, in Generation > Answer Routing (with the
              HTTP/MCP overrides and the chat-prompt link). It was duplicated here. */}

          <div className="input-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              Final K
              <TooltipIcon name="FINAL_K" />
            </label>
            <NumberField
              min={1}
              max={100}
              value={finalK}
              onCommit={setFinalK}
            />
          </div>

          <div className="input-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              Query Rewrites
              <TooltipIcon name="MAX_QUERY_REWRITES" />
            </label>
            <NumberField
              min={1}
              max={10}
              value={multiQueryRewrites}
              onCommit={setMultiQueryRewrites}
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
                color: selectedCard === card.id ? 'var(--accent-text)' : 'var(--fg)',
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
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={useSemanticSynonyms}
                      onChange={(e) => setUseSemanticSynonyms(e.target.checked)}
                    />
                    <span className="toggle-track" aria-hidden="true">
                      <span className="toggle-thumb"></span>
                    </span>
                    <span className="toggle-label">
                      Semantic Synonyms <TooltipIcon name="USE_SEMANTIC_SYNONYMS" />
                    </span>
                  </label>
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
                    <NumberField
                      min={10}
                      max={200}
                      value={vectorSearchTopK}
                      onCommit={setVectorSearchTopK}
                      disabled={!vectorSearchEnabled}
                    />
                  </div>
                  <div className="input-group">
                    <label>
                      Vector Similarity Threshold <TooltipIcon name="VECTOR_SIMILARITY_THRESHOLD" />
                    </label>
                    <NumberField
                      min={0}
                      max={1}
                      step={0.01}
                      value={vectorSimilarityThreshold}
                      onCommit={setVectorSimilarityThreshold}
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
                    <NumberField
                      min={10}
                      max={200}
                      value={sparseSearchTopK}
                      onCommit={setSparseSearchTopK}
                      disabled={!sparseSearchEnabled}
                    />
                  </div>
                  <div className="input-group">
                    <label>
                      BM25 k1 <TooltipIcon name="BM25_K1" />
                    </label>
                    <NumberField
                      min={0.5}
                      max={3}
                      step={0.1}
                      value={sparseBm25K1}
                      onCommit={setSparseBm25K1}
                      disabled={!sparseSearchEnabled}
                    />
                  </div>
                  <div className="input-group">
                    <label>
                      BM25 b <TooltipIcon name="BM25_B" />
                    </label>
                    <NumberField
                      min={0}
                      max={1}
                      step={0.05}
                      value={sparseBm25B}
                      onCommit={setSparseBm25B}
                      disabled={!sparseSearchEnabled}
                    />
                  </div>
                </div>

                <div style={INNER_PANEL_STYLE}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--fg)', marginBottom: 10 }}>Graph Leg</div>
                  <div
                    data-testid="retrieval-graph-policy-badge"
                    style={{
                      display: 'inline-flex',
                      marginBottom: 10,
                      borderRadius: 999,
                      padding: '5px 9px',
                      background: activeCorpus?.internal ? 'rgba(var(--warn-rgb), 0.12)' : 'rgba(var(--accent-rgb), 0.1)',
                      color: activeCorpus?.internal ? 'var(--warn)' : 'var(--fg)',
                      fontSize: 12,
                      fontWeight: 700,
                    }}
                  >
                    {graphPolicyLabel}
                  </div>
                  {graphReadiness ? (
                    <div
                      style={{
                        marginBottom: 10,
                        padding: '9px 11px',
                        borderRadius: 8,
                        border: '1px solid var(--line)',
                        background:
                          (graphReadiness.total_entities ?? 0) === 0
                            ? 'rgba(var(--warn-rgb), 0.12)'
                            : 'rgba(var(--accent-rgb), 0.07)',
                        fontSize: 11.5,
                        lineHeight: 1.5,
                        color: 'var(--fg)',
                      }}
                      data-testid="retrieval-graph-readiness"
                    >
                      {(graphReadiness.total_entities ?? 0) === 0 ? (
                        <>
                          <strong>This corpus has no entity graph.</strong> Qdrant can still identify dense seed chunks,
                          but relationship traversal cannot contribute. Enable graph indexing in RAG &gt; Indexing,
                          confirm the derived corpus policy, and re-index to populate it.
                        </>
                      ) : (
                        <>
                          Graph ready: {(graphReadiness.total_entities ?? 0).toLocaleString()} entities,{' '}
                          {(graphReadiness.total_relationships ?? 0).toLocaleString()} relationships,{' '}
                          {(graphReadiness.total_communities ?? 0).toLocaleString()} communities.
                          {(graphReadiness.total_relationships ?? 0) === 0
                            ? ' With no relationships, traversal has nothing to walk.'
                            : ''}
                        </>
                      )}
                    </div>
                  ) : null}
                  <div className="input-group">
                    <label>
                      Qdrant Seed Top-K <TooltipIcon name="GRAPH_SEARCH_TOP_K" />
                    </label>
                    <NumberField
                      min={5}
                      max={100}
                      value={graphSearchTopK}
                      onCommit={setGraphSearchTopK}
                      disabled={!graphSearchEnabled}
                    />
                  </div>
                  <div className="input-group">
                    <label>
                      Graph Max Hops <TooltipIcon name="GRAPH_MAX_HOPS" />
                    </label>
                    <NumberField
                      min={1}
                      max={5}
                      value={graphMaxHops}
                      onCommit={setGraphMaxHops}
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
                      disabled={!graphSearchEnabled}
                    >
                      <option value="1">Enabled</option>
                      <option value="0">Disabled</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label>
                      Related Chunk Window <TooltipIcon name="GRAPH_CHUNK_NEIGHBOR_WINDOW" />
                    </label>
                    <NumberField
                      min={0}
                      max={10}
                      value={chunkNeighborWindow}
                      onCommit={setChunkNeighborWindow}
                      disabled={!graphSearchEnabled}
                    />
                  </div>
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
                  <NumberField
                    data-testid="max-chunks-per-file"
                    min={1}
                    max={50}
                    value={maxChunksPerFile}
                    onCommit={setMaxChunksPerFile}
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
                  <NumberField
                    min={0}
                    max={10}
                    value={neighborWindow}
                    onCommit={setNeighborWindow}
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
                  <NumberField
                    min={0}
                    max={1}
                    step={0.05}
                    value={mmrLambda}
                    onCommit={setMmrLambda}
                    disabled={!enableMmr}
                  />
                  {!enableMmr ? (
                    <div style={INERT_NOTE_STYLE} data-testid="mmr-lambda-inert-note">
                      Not used while MMR is off.
                    </div>
                  ) : null}
                </div>
                <div className="input-group" />
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    Min Score (vector) <TooltipIcon name="MIN_SCORE_VECTOR" />
                  </label>
                  <NumberField
                    min={0}
                    max={1}
                    step={0.01}
                    value={minScoreVector}
                    onCommit={setMinScoreVector}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Min Score (sparse) <TooltipIcon name="MIN_SCORE_SPARSE" />
                  </label>
                  <NumberField
                    min={0}
                    max={10}
                    step={0.01}
                    value={minScoreSparse}
                    onCommit={setMinScoreSparse}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Min Score (graph) <TooltipIcon name="MIN_SCORE_GRAPH" />
                  </label>
                  <NumberField
                    min={0}
                    max={10}
                    step={0.01}
                    value={minScoreGraph}
                    onCommit={setMinScoreGraph}
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
                  <NumberField
                    min={1}
                    max={200}
                    value={fusionRrfK}
                    onCommit={setFusionRrfK}
                    disabled={fusionMethod !== 'rrf'}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Vector Weight <TooltipIcon name="FUSION_VECTOR_WEIGHT" />
                  </label>
                  <NumberField
                    min={0}
                    max={1}
                    step={0.05}
                    value={fusionVectorWeight}
                    onCommit={setFusionVectorWeight}
                    disabled={fusionMethod !== 'weighted'}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Sparse Weight <TooltipIcon name="FUSION_SPARSE_WEIGHT" />
                  </label>
                  <NumberField
                    min={0}
                    max={1}
                    step={0.05}
                    value={fusionSparseWeight}
                    onCommit={setFusionSparseWeight}
                    disabled={fusionMethod !== 'weighted'}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Graph Weight <TooltipIcon name="FUSION_GRAPH_WEIGHT" />
                  </label>
                  <NumberField
                    min={0}
                    max={1}
                    step={0.05}
                    value={fusionGraphWeight}
                    onCommit={setFusionGraphWeight}
                    disabled={fusionMethod !== 'weighted'}
                  />
                </div>
              </div>
              <div style={INERT_NOTE_STYLE} data-testid="fusion-inert-note">
                {fusionMethod === 'rrf'
                  ? 'Vector / Sparse / Graph weights are not used by the "rrf" method (they apply only to "weighted").'
                  : 'RRF K is not used by the "weighted" method (it applies only to "rrf").'}
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
                  <NumberField
                    min={0}
                    max={1}
                    step={0.01}
                    value={cardBonus}
                    onCommit={setCardBonus}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Filename Boost (Exact) <TooltipIcon name="FILENAME_BOOST_EXACT" />
                  </label>
                  <NumberField
                    min={1}
                    max={5}
                    step={0.1}
                    value={filenameBoostExact}
                    onCommit={setFilenameBoostExact}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Filename Boost (Partial) <TooltipIcon name="FILENAME_BOOST_PARTIAL" />
                  </label>
                  <NumberField
                    min={1}
                    max={3}
                    step={0.1}
                    value={filenameBoostPartial}
                    onCommit={setFilenameBoostPartial}
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
                  <NumberField
                    min={0}
                    max={0.5}
                    step={0.01}
                    value={layerBonusGui}
                    onCommit={setLayerBonusGui}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Retrieval <TooltipIcon name="LAYER_BONUS_RETRIEVAL" />
                  </label>
                  <NumberField
                    min={0}
                    max={0.5}
                    step={0.01}
                    value={layerBonusRetrieval}
                    onCommit={setLayerBonusRetrieval}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Indexer <TooltipIcon name="LAYER_BONUS_INDEXER" />
                  </label>
                  <NumberField
                    min={0}
                    max={0.5}
                    step={0.01}
                    value={layerBonusIndexer}
                    onCommit={setLayerBonusIndexer}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Vendor Penalty <TooltipIcon name="VENDOR_PENALTY" />
                  </label>
                  <NumberField
                    min={-0.5}
                    max={0}
                    step={0.01}
                    value={vendorPenalty}
                    onCommit={setVendorPenalty}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Freshness Bonus <TooltipIcon name="FRESHNESS_BONUS" />
                  </label>
                  <NumberField
                    min={0}
                    max={0.3}
                    step={0.01}
                    value={freshnessBonus}
                    onCommit={setFreshnessBonus}
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
                <div className="input-group" data-testid="retrieval-generation-answer-alias">
                  <label>{productionModelRoutingLocked ? 'Non-chat generation alias' : 'Generation Alias'}</label>
                  <ChatModelPicker
                    value={genModel}
                    onChange={setGenModel}
                    models={generationModels}
                    valueMode="id"
                    allowEmpty
                    disabled={productionModelRoutingLocked}
                    ariaDescribedBy={productionModelRoutingLocked ? 'retrieval-generation-answer-alias-lock-note' : undefined}
                  />
                  {productionModelRoutingLocked ? (
                    <div
                      id="retrieval-generation-answer-alias-lock-note"
                      style={{ color: 'var(--fg-muted)', fontSize: 11, marginTop: 5, lineHeight: 1.4 }}
                    >
                      Chat uses its own model picker. This non-chat answer pipeline is locked by the production deployment.
                    </div>
                  ) : null}
                  <PromptLink promptKey="main_rag_chat">Edit Chat Prompt</PromptLink>
                </div>
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>HTTP Alias Override</label>
                  <ChatModelPicker
                    value={genModelHttp}
                    onChange={setGenModelHttp}
                    models={generationModels}
                    valueMode="id"
                    allowEmpty
                  />
                </div>
                <div className="input-group">
                  <label>MCP Alias Override</label>
                  <ChatModelPicker
                    value={genModelMcp}
                    onChange={setGenModelMcp}
                    models={generationModels}
                    valueMode="id"
                    allowEmpty
                  />
                </div>
                <div className="input-group">
                  <label>CLI Alias Override</label>
                  <ChatModelPicker
                    value={genModelCli}
                    onChange={setGenModelCli}
                    models={generationModels}
                    valueMode="id"
                    allowEmpty
                  />
                </div>
              </div>
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-generation-enrichment-routing">
              <div style={SECTION_TITLE_STYLE}>2) Enrichment Routing</div>
              <div style={SECTION_DESC_STYLE}>
                Select a gateway alias and explicitly disable enrichment when pure retrieval answers are preferred.
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>Enrichment Alias</label>
                  <ChatModelPicker
                    value={enrichModel}
                    onChange={setEnrichModel}
                    models={generationModels}
                    valueMode="id"
                  />
                </div>
                <div className="input-group">
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={enrichDisabled}
                      onChange={(e) => setEnrichDisabled(e.target.checked)}
                    />
                    <span className="toggle-track" aria-hidden="true">
                      <span className="toggle-thumb"></span>
                    </span>
                    <span className="toggle-label">
                      Disable Enrichment <TooltipIcon name="ENRICH_DISABLED" />
                    </span>
                  </label>
                </div>
              </div>
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-generation-provider-readiness">
              <div style={SECTION_TITLE_STYLE}>3) Provider Readiness</div>
              <div style={SECTION_DESC_STYLE}>
                Confirm the application-to-gateway credential before using generation aliases.
              </div>

              <div className="input-row">
                <div className="input-group">
                  <label>
                    LiteLLM Client Key
                  </label>
                  <ApiKeyStatus keyName="LITELLM_API_KEY" label="LiteLLM Client Key" />
                </div>
              </div>
            </div>

            <div style={{ ...SECTION_STYLE, marginBottom: 14 }} data-testid="retrieval-section-generation-sampling-budget">
              <div style={SECTION_TITLE_STYLE}>4) Sampling Budget</div>
              <div style={SECTION_DESC_STYLE}>
                Set creativity and output budget controls that directly affect answer style, length, and variability.
              </div>

              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                <div className="input-group">
                  <label>
                    Temperature <TooltipIcon name="GEN_TEMPERATURE" />
                  </label>
                  <NumberField
                    min={0}
                    max={2}
                    step={0.01}
                    value={genTemperature}
                    onCommit={setGenTemperature}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Max Tokens <TooltipIcon name="GEN_MAX_TOKENS" />
                  </label>
                  <NumberField
                    min={100}
                    max={16000}
                    step={1}
                    value={genMaxTokens}
                    onCommit={setGenMaxTokens}
                  />
                </div>
                <div className="input-group">
                  <label>
                    Top P <TooltipIcon name="GEN_TOP_P" />
                  </label>
                  <NumberField
                    min={0}
                    max={1}
                    step={0.01}
                    value={genTopP}
                    onCommit={setGenTopP}
                  />
                </div>
              </div>
            </div>

            <div style={SECTION_STYLE} data-testid="retrieval-section-generation-reliability">
              <div style={SECTION_TITLE_STYLE}>5) Reliability / Timeouts</div>
              <div style={SECTION_DESC_STYLE}>
                Bound application request duration. Gateway retry and fallback policy is fixed in LiteLLM deployment config.
              </div>

              <div className="input-row">
                <div className="input-group">
                  <label>
                    GEN Timeout <TooltipIcon name="GEN_TIMEOUT" />
                  </label>
                  <NumberField
                    min={10}
                    max={900}
                    value={genTimeout}
                    onCommit={setGenTimeout}
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
                  color: opsTracingView === 'runtime_compatibility' ? 'var(--accent-text)' : 'var(--fg)',
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
                  color: opsTracingView === 'observability_integrations' ? 'var(--accent-text)' : 'var(--fg)',
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
                      <NumberField
                        min={500}
                        max={10000}
                        value={hydrationMaxChars || retrievalHydrationMaxChars}
                        onCommit={setUnifiedHydrationMaxChars}
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
                      <NumberField
                        min={1}
                        max={50}
                        value={evalFinalK}
                        onCommit={setEvalFinalK}
                      />
                    </div>
                    <div className="input-group">
                      <label className="toggle">
                        <input
                          type="checkbox"
                          checked={evalMulti}
                          onChange={(e) => setEvalMulti(e.target.checked)}
                        />
                        <span className="toggle-track" aria-hidden="true">
                          <span className="toggle-thumb"></span>
                        </span>
                        <span className="toggle-label">
                          Eval Multi <TooltipIcon name="EVAL_MULTI" />
                        </span>
                      </label>
                    </div>
                    <div className="input-group">
                      <label className="toggle">
                        <input
                          type="checkbox"
                          checked={queryExpansionEnabled}
                          onChange={(e) => setQueryExpansionEnabled(e.target.checked)}
                        />
                        <span className="toggle-track" aria-hidden="true">
                          <span className="toggle-thumb"></span>
                        </span>
                        <span className="toggle-label">
                          Query Expansion <TooltipIcon name="QUERY_EXPANSION_ENABLED" />
                        </span>
                      </label>
                    </div>
                    <div className="input-group">
                      <label className="toggle">
                        <input
                          type="checkbox"
                          checked={cardSearchEnabled}
                          onChange={(e) => setCardSearchEnabled(e.target.checked)}
                        />
                        <span className="toggle-track" aria-hidden="true">
                          <span className="toggle-thumb"></span>
                        </span>
                        <span className="toggle-label">
                          Chunk Summary Search <TooltipIcon name="CHUNK_SUMMARY_SEARCH_ENABLED" />
                        </span>
                      </label>
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        Confidence Top1 <TooltipIcon name="CONF_TOP1" />
                      </label>
                      <NumberField
                        min={0}
                        max={1}
                        step={0.01}
                        value={confTop1}
                        onCommit={setConfTop1}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Confidence Avg5 <TooltipIcon name="CONF_AVG5" />
                      </label>
                      <NumberField
                        min={0}
                        max={1}
                        step={0.01}
                        value={confAvg5}
                        onCommit={setConfAvg5}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Confidence Any <TooltipIcon name="CONF_ANY" />
                      </label>
                      <NumberField
                        min={0}
                        max={1}
                        step={0.01}
                        value={confAny}
                        onCommit={setConfAny}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Multi Query M <TooltipIcon name="MULTI_QUERY_M" />
                      </label>
                      <NumberField
                        min={1}
                        max={10}
                        value={multiQueryM}
                        onCommit={setMultiQueryM}
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        LangGraph Max Rewrites <TooltipIcon name="LANGGRAPH_MAX_QUERY_REWRITES" />
                      </label>
                      <NumberField
                        min={1}
                        max={10}
                        value={langgraphMaxQueryRewrites}
                        onCommit={setLanggraphMaxQueryRewrites}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Fallback Confidence <TooltipIcon name="FALLBACK_CONFIDENCE" />
                      </label>
                      <NumberField
                        min={0}
                        max={1}
                        step={0.01}
                        value={fallbackConfidence}
                        onCommit={setFallbackConfidence}
                      />
                    </div>
                  </div>
                </div>

                <div style={SECTION_STYLE} data-testid="retrieval-section-ops-semantic-cache">
                  <div style={SECTION_TITLE_STYLE}>3) Semantic Cache</div>
                  <div style={SECTION_DESC_STYLE}>
                    Configure semantic cache policy for retrieval, answer generation, and chat generation.
                  </div>
                  {!semanticCacheEnabled ? (
                    <div style={{ ...INERT_NOTE_STYLE, marginTop: 0, marginBottom: 10 }} data-testid="semantic-cache-inert-note">
                      Cache is off — the settings below are not used until Cache Enabled is on.
                    </div>
                  ) : null}

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label className="toggle">
                        <input
                          type="checkbox"
                          checked={semanticCacheEnabled}
                          onChange={(e) => setSemanticCacheEnabled(e.target.checked)}
                        />
                        <span className="toggle-track" aria-hidden="true">
                          <span className="toggle-thumb"></span>
                        </span>
                        <span className="toggle-label">
                          Cache Enabled <TooltipIcon name="SEMANTIC_CACHE_ENABLED" />
                        </span>
                      </label>
                    </div>
                    <div className="input-group">
                      <label>Cache Mode <TooltipIcon name="SEMANTIC_CACHE_MODE" /></label>
                      <select
                        value={semanticCacheMode}
                        onChange={(e) => setSemanticCacheMode(e.target.value as 'read_write' | 'read_only' | 'write_only')}
                        disabled={!semanticCacheEnabled}
                      >
                        <option value="read_write">read_write</option>
                        <option value="read_only">read_only</option>
                        <option value="write_only">write_only</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>Max Entries <TooltipIcon name="SEMANTIC_CACHE_MAX_ENTRIES" /></label>
                      <NumberField
                        min={100}
                        max={500000}
                        value={semanticCacheMaxEntries}
                        onCommit={setSemanticCacheMaxEntries}
                        disabled={!semanticCacheEnabled}
                      />
                    </div>
                    <div className="input-group">
                      <label>Min Query Chars <TooltipIcon name="SEMANTIC_CACHE_MIN_QUERY_CHARS" /></label>
                      <NumberField
                        min={1}
                        max={200}
                        value={semanticCacheMinQueryChars}
                        onCommit={setSemanticCacheMinQueryChars}
                        disabled={!semanticCacheEnabled}
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>Similarity Threshold (Search) <TooltipIcon name="SEMANTIC_CACHE_SIMILARITY_THRESHOLD_SEARCH" /></label>
                      <NumberField
                        min={0}
                        max={1}
                        step={0.01}
                        value={semanticCacheThresholdSearch}
                        onCommit={setSemanticCacheThresholdSearch}
                        disabled={!semanticCacheEnabled}
                      />
                    </div>
                    <div className="input-group">
                      <label>Similarity Threshold (Answer) <TooltipIcon name="SEMANTIC_CACHE_SIMILARITY_THRESHOLD_ANSWER" /></label>
                      <NumberField
                        min={0}
                        max={1}
                        step={0.01}
                        value={semanticCacheThresholdAnswer}
                        onCommit={setSemanticCacheThresholdAnswer}
                        disabled={!semanticCacheEnabled}
                      />
                    </div>
                    <div className="input-group">
                      <label>Similarity Threshold (Chat) <TooltipIcon name="SEMANTIC_CACHE_SIMILARITY_THRESHOLD_CHAT" /></label>
                      <NumberField
                        min={0}
                        max={1}
                        step={0.01}
                        value={semanticCacheThresholdChat}
                        onCommit={setSemanticCacheThresholdChat}
                        disabled={!semanticCacheEnabled}
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>TTL Seconds (Search) <TooltipIcon name="SEMANTIC_CACHE_TTL_SECONDS_SEARCH" /></label>
                      <NumberField
                        min={10}
                        max={86400}
                        value={semanticCacheTtlSearch}
                        onCommit={setSemanticCacheTtlSearch}
                        disabled={!semanticCacheEnabled}
                      />
                    </div>
                    <div className="input-group">
                      <label>TTL Seconds (Answer) <TooltipIcon name="SEMANTIC_CACHE_TTL_SECONDS_ANSWER" /></label>
                      <NumberField
                        min={10}
                        max={86400}
                        value={semanticCacheTtlAnswer}
                        onCommit={setSemanticCacheTtlAnswer}
                        disabled={!semanticCacheEnabled}
                      />
                    </div>
                    <div className="input-group">
                      <label>TTL Seconds (Chat) <TooltipIcon name="SEMANTIC_CACHE_TTL_SECONDS_CHAT" /></label>
                      <NumberField
                        min={10}
                        max={86400}
                        value={semanticCacheTtlChat}
                        onCommit={setSemanticCacheTtlChat}
                        disabled={!semanticCacheEnabled}
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>Chat History Window <TooltipIcon name="SEMANTIC_CACHE_CHAT_HISTORY_WINDOW" /></label>
                      <NumberField
                        min={0}
                        max={50}
                        value={semanticCacheChatHistoryWindow}
                        onCommit={setSemanticCacheChatHistoryWindow}
                        disabled={!semanticCacheEnabled}
                      />
                    </div>
                    <div className="input-group">
                      <label className="toggle">
                        <input
                          type="checkbox"
                          checked={semanticCacheBypassIfImages}
                          onChange={(e) => setSemanticCacheBypassIfImages(e.target.checked)}
                          disabled={!semanticCacheEnabled}
                        />
                        <span className="toggle-track" aria-hidden="true">
                          <span className="toggle-thumb"></span>
                        </span>
                        <span className="toggle-label">
                          Bypass if Images <TooltipIcon name="SEMANTIC_CACHE_BYPASS_IF_IMAGES" />
                        </span>
                      </label>
                    </div>
                    <div className="input-group">
                      <label>Max Temperature for Write <TooltipIcon name="SEMANTIC_CACHE_MAX_TEMPERATURE_FOR_WRITE" /></label>
                      <NumberField
                        min={0}
                        max={2}
                        step={0.05}
                        value={semanticCacheMaxTemperatureForWrite}
                        onCommit={setSemanticCacheMaxTemperatureForWrite}
                        disabled={!semanticCacheEnabled}
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
                    Configure local buffering, canonical OTel mode, and request-level retention before downstream export and cost attribution.
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>
                        Tracing Mode <TooltipIcon name="TRACING_MODE" />
                      </label>
                      <select value={tracingMode} onChange={(e) => setTracingMode(e.target.value)}>
                        <option value="off">off</option>
                        <option value="local">local</option>
                        <option value="otel">otel</option>
                        <option value="otel_langfuse">otel_langfuse</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label className="toggle">
                        <input
                          type="checkbox"
                          checked={tracingEnabled}
                          onChange={(e) => setTracingEnabled(e.target.checked)}
                        />
                        <span className="toggle-track" aria-hidden="true">
                          <span className="toggle-thumb"></span>
                        </span>
                        <span className="toggle-label">
                          Tracing Enabled <TooltipIcon name="TRACING_ENABLED" />
                        </span>
                      </label>
                    </div>
                    <div className="input-group">
                      <label>
                        Trace Sampling Rate <TooltipIcon name="TRACE_SAMPLING_RATE" />
                      </label>
                      <NumberField
                        min={0}
                        max={1}
                        step={0.01}
                        value={traceSamplingRate}
                        onCommit={setTraceSamplingRate}
                      />
                    </div>
                    <div className="input-group">
                      <label>
                        Trace Retention <TooltipIcon name="TRACE_RETENTION" />
                      </label>
                      <NumberField
                        min={10}
                        max={500}
                        value={traceRetention}
                        onCommit={setTraceRetention}
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label className="toggle">
                        <input
                          type="checkbox"
                          checked={otelExportEnabled}
                          onChange={(e) => setOtelExportEnabled(e.target.checked)}
                        />
                        <span className="toggle-track" aria-hidden="true">
                          <span className="toggle-thumb"></span>
                        </span>
                        <span className="toggle-label">
                          OTel Export
                        </span>
                      </label>
                    </div>
                    <div className="input-group">
                      <label className="toggle">
                        <input
                          type="checkbox"
                          checked={metricsEnabled}
                          onChange={(e) => setMetricsEnabled(e.target.checked)}
                        />
                        <span className="toggle-track" aria-hidden="true">
                          <span className="toggle-thumb"></span>
                        </span>
                        <span className="toggle-label">
                          Metrics Enabled <TooltipIcon name="METRICS_ENABLED" />
                        </span>
                      </label>
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
                    Define alert semantics plus OTLP export, service identity, and collector endpoints for the online request path.
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label className="toggle">
                        <input
                          type="checkbox"
                          checked={alertIncludeResolved}
                          onChange={(e) => setAlertIncludeResolved(e.target.checked)}
                        />
                        <span className="toggle-track" aria-hidden="true">
                          <span className="toggle-thumb"></span>
                        </span>
                        <span className="toggle-label">
                          Include Resolved Alerts <TooltipIcon name="ALERT_INCLUDE_RESOLVED" />
                        </span>
                      </label>
                    </div>
                    <div className="input-group">
                      <label>
                        Alert Webhook Timeout <TooltipIcon name="ALERT_WEBHOOK_TIMEOUT" />
                      </label>
                      <NumberField
                        min={1}
                        max={30}
                        value={alertWebhookTimeout}
                        onCommit={setAlertWebhookTimeout}
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

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
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
                    <div className="input-group">
                      <label>OTLP Endpoint <TooltipIcon name="OTLP_ENDPOINT" /></label>
                      <input
                        type="text"
                        value={otlpEndpoint}
                        onChange={(e) => setOtlpEndpoint(e.target.value)}
                        placeholder="http://127.0.0.1:4318/v1/traces"
                      />
                    </div>
                    <div className="input-group">
                      <label>OTel Service Name <TooltipIcon name="OTEL_SERVICE_NAME" /></label>
                      <input
                        type="text"
                        value={otelServiceName}
                        onChange={(e) => setOtelServiceName(e.target.value)}
                        placeholder="ragweld-api"
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    <div className="input-group">
                      <label>OTLP Headers <TooltipIcon name="OTLP_HEADERS" /></label>
                      <input
                        type="text"
                        value={otlpHeaders}
                        onChange={(e) => setOtlpHeaders(e.target.value)}
                        placeholder="X-Scope-OrgID=1"
                      />
                      <div
                        data-testid="otlp-headers-secret-note"
                        style={{ fontSize: '11.5px', color: 'var(--fg-muted)', marginTop: '6px', lineHeight: 1.5 }}
                      >
                        An authorization header is held in the backend and served back as{' '}
                        <code>{SECRET_REDACTED}</code>; leave that marker in place to keep it.
                        Everything else here is shown and saved in clear.
                      </div>
                    </div>
                    <div className="input-group">
                      <label className="toggle">
                        <input
                          type="checkbox"
                          checked={costTrackingEnabled}
                          onChange={(e) => setCostTrackingEnabled(e.target.checked)}
                        />
                        <span className="toggle-track" aria-hidden="true">
                          <span className="toggle-thumb"></span>
                        </span>
                        <span className="toggle-label">
                          Cost Tracking <TooltipIcon name="COST_TRACKING_ENABLED" />
                        </span>
                      </label>
                    </div>
                  </div>
                </div>

                <div style={SECTION_STYLE} data-testid="retrieval-section-ops-integrations">
                  <div style={SECTION_TITLE_STYLE}>4) Integrations</div>
                  <div style={SECTION_DESC_STYLE}>
                    Configure Langfuse, Tempo, and Alloy endpoints used for live request tracing and operator drilldown.
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label className="toggle">
                        <input
                          type="checkbox"
                          checked={langfuseEnabled}
                          onChange={(e) => setLangfuseEnabled(e.target.checked)}
                        />
                        <span className="toggle-track" aria-hidden="true">
                          <span className="toggle-thumb"></span>
                        </span>
                        <span className="toggle-label">
                          Langfuse Enabled <TooltipIcon name="LANGFUSE_ENABLED" />
                        </span>
                      </label>
                    </div>
                    <div className="input-group">
                      <label>Langfuse Base URL <TooltipIcon name="LANGFUSE_BASE_URL" /></label>
                      <input
                        type="text"
                        value={langfuseBaseUrl}
                        onChange={(e) => setLangfuseBaseUrl(e.target.value)}
                        placeholder="https://cloud.langfuse.com"
                      />
                    </div>
                    <div className="input-group">
                      <label>Langfuse Browser URL <TooltipIcon name="LANGFUSE_PUBLIC_BASE_URL" /></label>
                      <input
                        data-testid="retrieval-langfuse-public-base-url"
                        type="text"
                        value={langfusePublicBaseUrl}
                        onChange={(e) => setLangfusePublicBaseUrl(e.target.value)}
                        placeholder="http://127.0.0.1:53000"
                      />
                      <div
                        data-testid="retrieval-langfuse-public-base-url-hint"
                        style={{ fontSize: 12, color: 'var(--fg-muted)', lineHeight: 1.4, marginTop: 6 }}
                      >
                        {PUBLIC_BROWSER_LINK_HINT}
                      </div>
                    </div>
                    <div className="input-group">
                      <label>Langfuse Project <TooltipIcon name="LANGFUSE_PROJECT" /></label>
                      <input
                        type="text"
                        value={langfuseProject}
                        onChange={(e) => setLangfuseProject(e.target.value)}
                        placeholder="ragweld"
                      />
                    </div>
                  </div>

                  <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }}>
                    <div className="input-group">
                      <label>Tempo Base URL <TooltipIcon name="TEMPO_BASE_URL" /></label>
                      <input
                        type="text"
                        value={tempoBaseUrl}
                        onChange={(e) => setTempoBaseUrl(e.target.value)}
                        placeholder="http://127.0.0.1:53200"
                      />
                    </div>
                    <div className="input-group">
                      <label>Alloy Base URL <TooltipIcon name="ALLOY_BASE_URL" /></label>
                      <input
                        type="text"
                        value={alloyBaseUrl}
                        onChange={(e) => setAlloyBaseUrl(e.target.value)}
                        placeholder="http://127.0.0.1:52345"
                      />
                    </div>
                    <div className="input-group">
                      <label>Langfuse Keys <TooltipIcon name="LANGFUSE_PUBLIC_KEY" /></label>
                      <div style={{ display: 'grid', gap: 8 }}>
                        <ApiKeyStatus keyName="LANGFUSE_PUBLIC_KEY" label="Langfuse Public Key" />
                        <ApiKeyStatus keyName="LANGFUSE_SECRET_KEY" label="Langfuse Secret Key" />
                      </div>
                    </div>
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

function formatTracePayload(payload: TracesLatestResponse, vectorBackend: string): string {
  if (!payload?.trace) {
    return 'No traces yet. Set tracing mode to local, OTel, or OTel + Langfuse and run a query.';
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
