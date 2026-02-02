import { useState, useEffect, useCallback, useRef } from 'react';
import { EmbeddingMismatchWarning } from '@/components/ui/EmbeddingMismatchWarning';
import { LiveTerminal, LiveTerminalHandle } from '@/components/LiveTerminal/LiveTerminal';
import { CollapsibleSection } from '@/components/ui/CollapsibleSection';
import { IntentMatrixEditor } from '@/components/RAG/IntentMatrixEditor';
import { PromptLink } from '@/components/ui/PromptLink';
import { ApiKeyStatus } from '@/components/ui/ApiKeyStatus';
import { createAlertError, createInlineError } from '@/utils/errorHelpers';
import { useConfig, useConfigField } from '@/hooks';

// Types for the trace preview helpers
interface TraceEvent {
  kind?: string;
  data?: Record<string, any>;
  msg?: string;
  ts?: string | number;
}

interface TracePayload {
  trace?: {
    events?: TraceEvent[];
  };
  repo?: string;
}

export function RetrievalSubtab() {
  // --- Shared UI state -----------------------------------------------------
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [hydrating, setHydrating] = useState(true);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceStatus, setTraceStatus] = useState<{ type: 'info' | 'error'; message: string } | null>(null);
  const traceTerminalRef = useRef<LiveTerminalHandle>(null);

  // --- Generation Models ---------------------------------------------------
  const [genModel, setGenModel] = useConfigField<string>('generation.gen_model', '');
  const [genTemperature, setGenTemperature] = useConfigField<number>('generation.gen_temperature', 0.0);
  const [enrichModel, setEnrichModel] = useConfigField<string>('generation.enrich_model', '');
  const [enrichModelOllama, setEnrichModelOllama] = useConfigField<string>('generation.enrich_model_ollama', '');
  const [ollamaUrl, setOllamaUrl] = useConfigField<string>('generation.ollama_url', 'http://127.0.0.1:11434/api');
  const [openaiBaseUrl, setOpenaiBaseUrl] = useConfigField<string>('generation.openai_base_url', '');
  const [genModelHttp, setGenModelHttp] = useConfigField<string>('generation.gen_model_http', '');
  const [genModelMcp, setGenModelMcp] = useConfigField<string>('generation.gen_model_mcp', '');
  const [genModelCli, setGenModelCli] = useConfigField<string>('generation.gen_model_cli', '');
  const [enrichBackend, setEnrichBackend] = useConfigField<string>('generation.enrich_backend', '');
  const [genMaxTokens, setGenMaxTokens] = useConfigField<number>('generation.gen_max_tokens', 2048);
  const [genTopP, setGenTopP] = useConfigField<number>('generation.gen_top_p', 1.0);
  const [genTimeout, setGenTimeout] = useConfigField<number>('generation.gen_timeout', 60);
  const [genRetryMax, setGenRetryMax] = useConfigField<number>('generation.gen_retry_max', 2);
  const [enrichDisabled, setEnrichDisabled] = useConfigField<number>('generation.enrich_disabled', 0);

  // --- Retrieval Parameters ------------------------------------------------
  const [multiQueryRewrites, setMultiQueryRewrites] = useConfigField<number>('retrieval.max_query_rewrites', 2);
  const [finalK, setFinalK] = useConfigField<number>('retrieval.final_k', 10);
  const [useSemanticSynonyms, setUseSemanticSynonyms] = useConfigField<number>('retrieval.use_semantic_synonyms', 1);
  const [synonymsPath, setSynonymsPath] = useConfigField<string>('retrieval.tribrid_synonyms_path', '');

  // Search legs (tri-brid)
  const [vectorSearchEnabled, setVectorSearchEnabled] = useConfigField<boolean>('vector_search.enabled', true);
  const [vectorSearchTopK, setVectorSearchTopK] = useConfigField<number>('vector_search.top_k', 50);
  const [vectorSimilarityThreshold, setVectorSimilarityThreshold] = useConfigField<number>('vector_search.similarity_threshold', 0.0);

  const [sparseSearchEnabled, setSparseSearchEnabled] = useConfigField<boolean>('sparse_search.enabled', true);
  const [sparseSearchTopK, setSparseSearchTopK] = useConfigField<number>('sparse_search.top_k', 50);
  const [bm25K1, setBm25K1] = useConfigField<number>('sparse_search.bm25_k1', 1.2);
  const [bm25B, setBm25B] = useConfigField<number>('sparse_search.bm25_b', 0.4);

  const [graphSearchEnabled, setGraphSearchEnabled] = useConfigField<boolean>('graph_search.enabled', true);
  const [graphMode, setGraphMode] = useConfigField<'chunk' | 'entity'>('graph_search.mode', 'chunk');
  const [graphMaxHops, setGraphMaxHops] = useConfigField<number>('graph_search.max_hops', 2);
  const [graphIncludeCommunities, setGraphIncludeCommunities] = useConfigField<boolean>('graph_search.include_communities', true);
  const [graphSearchTopK, setGraphSearchTopK] = useConfigField<number>('graph_search.top_k', 30);
  const [chunkNeighborWindow, setChunkNeighborWindow] = useConfigField<number>('graph_search.chunk_neighbor_window', 1);
  const [chunkSeedOverfetchMultiplier, setChunkSeedOverfetchMultiplier] =
    useConfigField<number>('graph_search.chunk_seed_overfetch_multiplier', 10);
  const [chunkEntityExpansionEnabled, setChunkEntityExpansionEnabled] =
    useConfigField<boolean>('graph_search.chunk_entity_expansion_enabled', true);
  const [chunkEntityExpansionWeight, setChunkEntityExpansionWeight] =
    useConfigField<number>('graph_search.chunk_entity_expansion_weight', 0.8);

  // Fusion config (tri-brid weights)
  const [fusionMethod, setFusionMethod] = useConfigField<'rrf' | 'weighted'>('fusion.method', 'rrf');
  const [fusionVectorWeight, setFusionVectorWeight] = useConfigField<number>('fusion.vector_weight', 0.4);
  const [fusionSparseWeight, setFusionSparseWeight] = useConfigField<number>('fusion.sparse_weight', 0.3);
  const [fusionGraphWeight, setFusionGraphWeight] = useConfigField<number>('fusion.graph_weight', 0.3);
  const [fusionRrfK, setFusionRrfK] = useConfigField<number>('fusion.rrf_k', 60);
  const [fusionNormalizeScores, setFusionNormalizeScores] = useConfigField<boolean>('fusion.normalize_scores', true);

  // Shared UI/behavior configs
  const [hydrationMode, setHydrationMode] = useConfigField<string>('hydration.hydration_mode', 'lazy');
  const [hydrationMaxChars, setHydrationMaxChars] = useConfigField<number>('hydration.hydration_max_chars', 2000);
  const [vendorMode, setVendorMode] = useConfigField<string>('scoring.vendor_mode', 'prefer_first_party');
  const [cardSearchEnabled, setCardSearchEnabled] = useConfigField<number>('retrieval.chunk_summary_search_enabled', 1);
  const [multiQueryM, setMultiQueryM] = useConfigField<number>('retrieval.multi_query_m', 4);
  const [confTop1, setConfTop1] = useConfigField<number>('retrieval.conf_top1', 0.62);
  const [confAvg5, setConfAvg5] = useConfigField<number>('retrieval.conf_avg5', 0.55);

  // --- Advanced / Routing ---------------------------------------------------
  const [rrfKDiv, setRrfKDiv] = useConfigField<number>('retrieval.rrf_k_div', 60);
  const [cardBonus, setCardBonus] = useConfigField<number>('scoring.chunk_summary_bonus', 0.08);
  const [filenameBoostExact, setFilenameBoostExact] = useConfigField<number>('scoring.filename_boost_exact', 1.5);
  const [filenameBoostPartial, setFilenameBoostPartial] = useConfigField<number>('scoring.filename_boost_partial', 1.2);
  const [langgraphFinalK, setLanggraphFinalK] = useConfigField<number>('retrieval.langgraph_final_k', 20);
  const [langgraphMaxQueryRewrites, setLanggraphMaxQueryRewrites] =
    useConfigField<number>('retrieval.langgraph_max_query_rewrites', 2);
  const [fallbackConfidence, setFallbackConfidence] = useConfigField<number>('retrieval.fallback_confidence', 0.55);
  const [layerBonusGui, setLayerBonusGui] = useConfigField<number>('layer_bonus.gui', 0.15);
  const [layerBonusRetrieval, setLayerBonusRetrieval] = useConfigField<number>('layer_bonus.retrieval', 0.15);
  const [vendorPenalty, setVendorPenalty] = useConfigField<number>('layer_bonus.vendor_penalty', -0.1);
  const [freshnessBonus, setFreshnessBonus] = useConfigField<number>('layer_bonus.freshness_bonus', 0.05);
  const [tracingMode, setTracingMode] = useConfigField<string>('tracing.tracing_mode', 'langsmith');
  const [traceAutoLs, setTraceAutoLs] = useConfigField<number>('tracing.trace_auto_ls', 1);
  const [traceRetention, setTraceRetention] = useConfigField<number>('tracing.trace_retention', 50);
  const [langchainTracingV2, setLangchainTracingV2] = useConfigField<number>('tracing.langchain_tracing_v2', 0);
  const [langchainEndpoint, setLangchainEndpoint] = useConfigField<string>(
    'tracing.langchain_endpoint',
    'https://api.smith.langchain.com',
  );
  const [langchainProject, setLangchainProject] = useConfigField<string>('tracing.langchain_project', 'tribrid');
  const [langtraceApiHost, setLangtraceApiHost] = useConfigField<string>('tracing.langtrace_api_host', '');
  const [langtraceProjectId, setLangtraceProjectId] = useConfigField<string>('tracing.langtrace_project_id', '');

  const {
    config,
    loading: configLoading,
    error: configError,
    reload,
    clearError,
  } = useConfig();

  // --- Derived helpers -----------------------------------------------------
  const loadModels = useCallback(async () => {
    try {
      const response = await fetch('/api/models/by-type/GEN');
      const data = await response.json();
      const models = Array.isArray(data) ? data.map((m: any) => m.model).filter(Boolean) : [];
      if (models.length) {
        setAvailableModels(models);
      }
    } catch (error) {
      console.error('Failed to load models from /api/models/by-type/GEN:', error);
    }
  }, []);

  useEffect(() => {
    loadModels();
  }, [loadModels]);
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
      const response = await fetch(`/api/traces/latest`);
      if (!response.ok) {
        throw new Error(`Trace request failed (${response.status})`);
      }
      const data: TracePayload = await response.json();
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

  if (hydrating) {
    return <div style={{ padding: '24px' }}>Loading configuration...</div>;
  }

  return (
    <>
      <EmbeddingMismatchWarning variant="inline" showActions />

      {configError && (
        <div className="settings-section" style={{ borderColor: 'var(--err)' }}>
          <h3>Configuration Error</h3>
          <p className="small">{configError}</p>
          <div className="input-row">
            <div className="input-group">
              <button className="small-button" onClick={handleReload}>
                Retry Load
              </button>
            </div>
            <div className="input-group">
              <button className="small-button" onClick={clearError}>
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}

      <CollapsibleSection
        title="Generation Models"
        description="Primary answer model plus overrides for HTTP, MCP, CLI, and enrichment pipelines."
        storageKey="retrieval-generation"
        defaultExpanded={true}
      >
        <div className="input-row">
          <div className="input-group">
            <label>
              Primary Model (GEN_MODEL)
              <span className="help-icon" data-tooltip="GEN_MODEL">?</span>
            </label>
            <select value={genModel} onChange={(e) => setGenModel(e.target.value)}>
              <option value="">Select a model...</option>
              {availableModels.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </div>
          <div className="input-group">
            <label>
              OpenAI API Key
              <span className="help-icon" data-tooltip="OPENAI_API_KEY">?</span>
            </label>
            <ApiKeyStatus keyName="OPENAI_API_KEY" label="OpenAI API Key" />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Default Temperature
              <span className="help-icon" data-tooltip="GEN_TEMPERATURE">?</span>
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
              Enrich Model
              <span className="help-icon" data-tooltip="ENRICH_MODEL">?</span>
            </label>
            <select value={enrichModel} onChange={(e) => setEnrichModel(e.target.value)}>
              <option value="">Select a model...</option>
              {availableModels.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Enrich Model (Ollama)
              <span className="help-icon" data-tooltip="ENRICH_MODEL_OLLAMA">?</span>
            </label>
            <select value={enrichModelOllama} onChange={(e) => setEnrichModelOllama(e.target.value)}>
              <option value="">Select a model...</option>
            </select>
          </div>
          <div className="input-group">
            <label>
              Anthropic API Key
              <span className="help-icon" data-tooltip="ANTHROPIC_API_KEY">?</span>
            </label>
            <ApiKeyStatus keyName="ANTHROPIC_API_KEY" label="Anthropic API Key" />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Google API Key
              <span className="help-icon" data-tooltip="GOOGLE_API_KEY">?</span>
            </label>
            <ApiKeyStatus keyName="GOOGLE_API_KEY" label="Google API Key" />
          </div>
          <div className="input-group">
            <label>
              Ollama URL
              <span className="help-icon" data-tooltip="OLLAMA_URL">?</span>
            </label>
            <input
              type="text"
              placeholder="http://127.0.0.1:11434"
              value={ollamaUrl}
              onChange={(e) => setOllamaUrl(e.target.value)}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              OpenAI Base URL
              <span className="help-icon" data-tooltip="OPENAI_BASE_URL">?</span>
            </label>
            <input
              type="text"
              placeholder="Proxy override"
              value={openaiBaseUrl}
              onChange={(e) => setOpenaiBaseUrl(e.target.value)}
            />
          </div>
          <div className="input-group">
            <label>
              HTTP Override Model
              <span className="help-icon" data-tooltip="GEN_MODEL_HTTP">?</span>
            </label>
            <select value={genModelHttp} onChange={(e) => setGenModelHttp(e.target.value)}>
              <option value="">Select a model...</option>
              {availableModels.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              MCP Override Model
              <span className="help-icon" data-tooltip="GEN_MODEL_MCP">?</span>
            </label>
            <select value={genModelMcp} onChange={(e) => setGenModelMcp(e.target.value)}>
              <option value="">Select a model...</option>
              {availableModels.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </div>
          <div className="input-group">
            <label>
              CLI Override Model
              <span className="help-icon" data-tooltip="GEN_MODEL_CLI">?</span>
            </label>
            <select value={genModelCli} onChange={(e) => setGenModelCli(e.target.value)}>
              <option value="">Select a model...</option>
              {availableModels.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Enrichment Backend
              <span className="help-icon" data-tooltip="ENRICH_BACKEND">?</span>
            </label>
            <input
              type="text"
              placeholder="grpc://..."
              value={enrichBackend}
              onChange={(e) => setEnrichBackend(e.target.value)}
            />
          </div>
          <div className="input-group">
            <label>
              Disable Enrichment
              <span className="help-icon" data-tooltip="ENRICH_DISABLED">?</span>
            </label>
            <select
              value={enrichDisabled}
              onChange={(e) => setEnrichDisabled(parseInt(e.target.value, 10))}
            >
              <option value={0}>Enabled</option>
              <option value={1}>Disabled</option>
            </select>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Max Tokens
              <span className="help-icon" data-tooltip="GEN_MAX_TOKENS">?</span>
            </label>
            <input
              type="number"
              min={100}
              max={8192}
              step={128}
              value={genMaxTokens}
              onChange={(e) => setGenMaxTokens(snapNumber(e.target.value, 2048))}
            />
          </div>
          <div className="input-group">
            <label>
              Top-P (Nucleus Sampling)
              <span className="help-icon" data-tooltip="GEN_TOP_P">?</span>
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

        <div className="input-row">
          <div className="input-group">
            <label>
              Generation Timeout (seconds)
              <span className="help-icon" data-tooltip="GEN_TIMEOUT">?</span>
            </label>
            <input
              type="number"
              min={10}
              max={300}
              step={5}
              value={genTimeout}
              onChange={(e) => setGenTimeout(snapNumber(e.target.value, 60))}
            />
          </div>
          <div className="input-group">
            <label>
              Retry Attempts
              <span className="help-icon" data-tooltip="GEN_RETRY_MAX">?</span>
            </label>
            <input
              type="number"
              min={1}
              max={5}
              value={genRetryMax}
              onChange={(e) => setGenRetryMax(snapNumber(e.target.value, 2))}
            />
          </div>
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title="Retrieval Parameters"
        description="Hybrid search blends BM25 and dense embeddings. Tune candidate counts and weights."
        storageKey="retrieval-params"
        defaultExpanded={true}
      >
        <div className="input-row">
          <div className="input-group">
            <label>
              Multi-Query Rewrites
              <span className="help-icon" data-tooltip="MAX_QUERY_REWRITES">?</span>
            </label>
            <input
              type="number"
              min={1}
              max={10}
              value={multiQueryRewrites}
              onChange={(e) => setMultiQueryRewrites(snapNumber(e.target.value, 2))}
            />
          </div>
          <div className="input-group">
            <label>
              Final K
              <span className="help-icon" data-tooltip="FINAL_K">?</span>
            </label>
            <input
              type="number"
              min={1}
              max={100}
              value={finalK}
              onChange={(e) => setFinalK(snapNumber(e.target.value, 10))}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Semantic Synonyms
              <span className="help-icon" data-tooltip="USE_SEMANTIC_SYNONYMS">?</span>
            </label>
            <select
              value={useSemanticSynonyms}
              onChange={(e) => setUseSemanticSynonyms(parseInt(e.target.value, 10))}
            >
              <option value={1}>On</option>
              <option value={0}>Off</option>
            </select>
          </div>
          <div className="input-group">
            <label>
              Synonyms File Path
              <span className="help-icon" data-tooltip="TRIBRID_SYNONYMS_PATH">?</span>
            </label>
            <input
              type="text"
              placeholder="data/semantic_synonyms.json"
              value={synonymsPath}
              onChange={(e) => setSynonymsPath(e.target.value)}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Vector Top-K (pgvector)
              <span className="help-icon" data-tooltip="VECTOR_SEARCH_TOP_K">?</span>
            </label>
            <input
              type="number"
              min={10}
              max={200}
              value={vectorSearchTopK}
              onChange={(e) => setVectorSearchTopK(snapNumber(e.target.value, 50))}
            />
          </div>
          <div className="input-group">
            <label>
              Sparse Top-K (BM25)
              <span className="help-icon" data-tooltip="SPARSE_SEARCH_TOP_K">?</span>
            </label>
            <input
              type="number"
              min={10}
              max={200}
              value={sparseSearchTopK}
              onChange={(e) => setSparseSearchTopK(snapNumber(e.target.value, 50))}
            />
          </div>
          <div className="input-group">
            <label>
              Graph Top-K (Neo4j)
              <span className="help-icon" data-tooltip="GRAPH_SEARCH_TOP_K">?</span>
            </label>
            <input
              type="number"
              min={5}
              max={100}
              value={graphSearchTopK}
              onChange={(e) => setGraphSearchTopK(snapNumber(e.target.value, 30))}
            />
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <label>
              <input
                type="checkbox"
                checked={vectorSearchEnabled}
                onChange={(e) => setVectorSearchEnabled(e.target.checked)}
              />{' '}
              Enable Vector Search (pgvector)
            </label>
          </div>
          <div className="input-group">
            <label>
              <input
                type="checkbox"
                checked={sparseSearchEnabled}
                onChange={(e) => setSparseSearchEnabled(e.target.checked)}
              />{' '}
              Enable Sparse Search (BM25)
            </label>
          </div>
          <div className="input-group">
            <label>
              <input
                type="checkbox"
                checked={graphSearchEnabled}
                onChange={(e) => setGraphSearchEnabled(e.target.checked)}
              />{' '}
              Enable Graph Search (Neo4j)
            </label>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Vector Similarity Threshold
              <span className="help-icon" data-tooltip="VECTOR_SIMILARITY_THRESHOLD">?</span>
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
          <div className="input-group">
            <label>
              Graph Max Hops
              <span className="help-icon" data-tooltip="GRAPH_MAX_HOPS">?</span>
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
              Include Communities
              <span className="help-icon" data-tooltip="GRAPH_INCLUDE_COMMUNITIES">?</span>
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
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Graph Mode
              <span className="help-icon" data-tooltip="GRAPH_SEARCH_MODE">?</span>
            </label>
            <select
              data-testid="graph-search-mode"
              value={graphMode}
              onChange={(e) => setGraphMode(e.target.value as any)}
              disabled={!graphSearchEnabled}
            >
              <option value="chunk">Chunk (Neo4j vectors)</option>
              <option value="entity">Entity (legacy)</option>
            </select>
          </div>

          {graphMode === 'chunk' ? (
            <>
              <div className="input-group">
                <label>
                  Chunk Neighbor Window
                  <span className="help-icon" data-tooltip="GRAPH_CHUNK_NEIGHBOR_WINDOW">?</span>
                </label>
                <input
                  data-testid="graph-chunk-neighbor-window"
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
                  Seed Overfetch Multiplier
                  <span className="help-icon" data-tooltip="GRAPH_CHUNK_SEED_OVERFETCH">?</span>
                </label>
                <input
                  data-testid="graph-chunk-seed-overfetch"
                  type="number"
                  min={1}
                  max={50}
                  value={chunkSeedOverfetchMultiplier}
                  onChange={(e) => setChunkSeedOverfetchMultiplier(snapNumber(e.target.value, 10))}
                  disabled={!graphSearchEnabled}
                />
              </div>
            </>
          ) : (
            <div className="input-group" />
          )}
        </div>

        {graphMode === 'chunk' && (
          <div className="input-row">
            <div className="input-group">
              <label>
                <input
                  data-testid="graph-chunk-entity-expansion-enabled"
                  type="checkbox"
                  checked={chunkEntityExpansionEnabled}
                  onChange={(e) => setChunkEntityExpansionEnabled(e.target.checked)}
                  disabled={!graphSearchEnabled}
                />{' '}
                Expand via entities (IN_CHUNK)
              </label>
            </div>
            <div className="input-group">
              <label>
                Entity Expansion Weight
                <span className="help-icon" data-tooltip="GRAPH_CHUNK_ENTITY_EXPANSION_WEIGHT">?</span>
              </label>
              <input
                data-testid="graph-chunk-entity-expansion-weight"
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={chunkEntityExpansionWeight}
                onChange={(e) => setChunkEntityExpansionWeight(snapNumber(e.target.value, 0.8))}
                disabled={!graphSearchEnabled || !chunkEntityExpansionEnabled}
              />
            </div>
            <div className="input-group" />
          </div>
        )}

        <div className="input-row">
          <div className="input-group">
            <label>
              Hydration Mode
              <span className="help-icon" data-tooltip="HYDRATION_MODE">?</span>
            </label>
            <select value={hydrationMode} onChange={(e) => setHydrationMode(e.target.value)}>
              <option value="lazy">Lazy</option>
              <option value="eager">Eager</option>
              <option value="none">Off</option>
            </select>
          </div>
          <div className="input-group">
            <label>
              Hydration Max Chars
              <span className="help-icon" data-tooltip="HYDRATION_MAX_CHARS">?</span>
            </label>
            <input
              type="number"
              min={200}
              max={20000}
              step={100}
              value={hydrationMaxChars}
              onChange={(e) => setHydrationMaxChars(snapNumber(e.target.value, 2000))}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Vendor Mode
              <span className="help-icon" data-tooltip="VENDOR_MODE">?</span>
            </label>
            <select value={vendorMode} onChange={(e) => setVendorMode(e.target.value)}>
              <option value="prefer_first_party">Prefer first party</option>
              <option value="prefer_vendor">Prefer vendor</option>
              <option value="neutral">Neutral</option>
            </select>
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <label>
              Fusion Method
              <span className="help-icon" data-tooltip="FUSION_METHOD">?</span>
            </label>
            <select value={fusionMethod} onChange={(e) => setFusionMethod(e.target.value as any)}>
              <option value="rrf">RRF</option>
              <option value="weighted">Weighted</option>
            </select>
          </div>
          <div className="input-group">
            <label>
              Normalize Scores
              <span className="help-icon" data-tooltip="FUSION_NORMALIZE_SCORES">?</span>
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

        <div className="input-row">
          <div className="input-group">
            <label>
              RRF k
              <span className="help-icon" data-tooltip="FUSION_RRF_K">?</span>
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
              Vector Weight
              <span className="help-icon" data-tooltip="FUSION_VECTOR_WEIGHT">?</span>
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
              Sparse Weight
              <span className="help-icon" data-tooltip="FUSION_SPARSE_WEIGHT">?</span>
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
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Graph Weight
              <span className="help-icon" data-tooltip="FUSION_GRAPH_WEIGHT">?</span>
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
          <div className="input-group">
            <label>
              BM25 k1
              <span className="help-icon" data-tooltip="BM25_K1">?</span>
            </label>
            <input
              type="number"
              min={0.5}
              max={3}
              step={0.1}
              value={bm25K1}
              onChange={(e) => setBm25K1(snapNumber(e.target.value, 1.2))}
              disabled={!sparseSearchEnabled}
            />
          </div>
          <div className="input-group" />
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              BM25 b
              <span className="help-icon" data-tooltip="BM25_B">?</span>
            </label>
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={bm25B}
              onChange={(e) => setBm25B(snapNumber(e.target.value, 0.4))}
              disabled={!sparseSearchEnabled}
            />
          </div>
          <div className="input-group">
            <label>
              Chunk Summary Search
              <span className="help-icon" data-tooltip="CHUNK_SUMMARY_SEARCH_ENABLED">?</span>
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

        <div className="input-row">
          <div className="input-group">
            <label>
              Multi-Query M
              <span className="help-icon" data-tooltip="MULTI_QUERY_M">?</span>
            </label>
            <input
              type="number"
              min={1}
              max={10}
              value={multiQueryM}
              onChange={(e) => setMultiQueryM(snapNumber(e.target.value, 4))}
            />
          </div>
          <div className="input-group">
            <label>
              Confidence Top1
              <span className="help-icon" data-tooltip="CONF_TOP1">?</span>
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
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Confidence AVG5
              <span className="help-icon" data-tooltip="CONF_AVG5">?</span>
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
          <div className="input-group" />
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title="Advanced RAG Tuning"
        description="Fine-tune reranker settings, LangGraph bonuses, and freshness tuning."
        storageKey="retrieval-advanced"
        defaultExpanded={false}
      >
        <div className="input-row">
          <div className="input-group">
            <label>
              RRF K Div
              <span className="help-icon" data-tooltip="RRF_K_DIV">?</span>
            </label>
            <input
              type="number"
              min={10}
              max={200}
              value={rrfKDiv}
              onChange={(e) => setRrfKDiv(snapNumber(e.target.value, 60))}
            />
          </div>
          <div className="input-group">
            <label>
              Chunk Summary Bonus
              <span className="help-icon" data-tooltip="CHUNK_SUMMARY_BONUS">?</span>
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
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Filename Boost (Exact)
              <span className="help-icon" data-tooltip="FILENAME_BOOST_EXACT">?</span>
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
              Filename Boost (Partial)
              <span className="help-icon" data-tooltip="FILENAME_BOOST_PARTIAL">?</span>
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

        <div className="input-row">
          <div className="input-group">
            <label>
              LangGraph Final K
              <span className="help-icon" data-tooltip="LANGGRAPH_FINAL_K">?</span>
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
              Max Query Rewrites (LangGraph)
              <span className="help-icon" data-tooltip="LANGGRAPH_MAX_QUERY_REWRITES">?</span>
            </label>
            <input
              type="number"
              min={0}
              max={10}
              value={langgraphMaxQueryRewrites}
              onChange={(e) => setLanggraphMaxQueryRewrites(snapNumber(e.target.value, 3))}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Fallback Confidence
              <span className="help-icon" data-tooltip="FALLBACK_CONFIDENCE">?</span>
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
          <div className="input-group">
            <label>
              Layer Bonus (GUI)
              <span className="help-icon" data-tooltip="LAYER_BONUS_GUI">?</span>
            </label>
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={layerBonusGui}
              onChange={(e) => setLayerBonusGui(snapNumber(e.target.value, 0.15))}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Layer Bonus (Retrieval)
              <span className="help-icon" data-tooltip="LAYER_BONUS_RETRIEVAL">?</span>
            </label>
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={layerBonusRetrieval}
              onChange={(e) => setLayerBonusRetrieval(snapNumber(e.target.value, 0.15))}
            />
          </div>
          <div className="input-group">
            <label>
              Vendor Penalty
              <span className="help-icon" data-tooltip="VENDOR_PENALTY">?</span>
            </label>
            <input
              type="number"
              min={-1}
              max={0}
              step={0.05}
              value={vendorPenalty}
              onChange={(e) => setVendorPenalty(snapNumber(e.target.value, -0.1))}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Freshness Bonus
              <span className="help-icon" data-tooltip="FRESHNESS_BONUS">?</span>
            </label>
            <input
              type="number"
              min={0}
              max={0.5}
              step={0.01}
              value={freshnessBonus}
              onChange={(e) => setFreshnessBonus(snapNumber(e.target.value, 0.05))}
            />
          </div>
          <div className="input-group" />
        </div>

        {/* Intent Matrix JSON Editor */}
        <IntentMatrixEditor />

        {/* Quick links to edit related system prompts */}
        <div className="related-prompts">
          <span className="related-prompts-label">Related Prompts:</span>
          <PromptLink promptKey="main_rag_chat">System Prompt</PromptLink>
          <PromptLink promptKey="query_expansion">Query Expansion</PromptLink>
          <PromptLink promptKey="query_rewrite">Query Rewrite</PromptLink>
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title="Routing Trace (Local)"
        description="Preview the latest in-memory request trace. External exporters (LangSmith/LangTrace) are not wired yet; settings below are reserved for future integrations."
        storageKey="retrieval-tracing"
        defaultExpanded={false}
      >
        <div className="input-row">
          <div className="input-group">
            <button className="small-button" onClick={handleLoadTrace} disabled={traceLoading}>
              {traceLoading ? 'Loading trace…' : 'Load Latest Trace'}
            </button>
          </div>
          <div className="input-group" style={{ display: 'flex', alignItems: 'center' }}>
            <span className="small" style={{ color: 'var(--fg-muted)' }}>
              LangSmith deep-linking is not implemented yet.
            </span>
          </div>
        </div>

        {traceStatus ? (
          <div
            className="result-display"
            style={{ color: traceStatus.type === 'error' ? 'var(--err)' : 'var(--fg-muted)' }}
          >
            {traceStatus.message}
          </div>
        ) : null}

        <div style={{ marginTop: 16 }}>
          <LiveTerminal
            id="retrieval_trace_terminal"
            title="Routing Trace Preview"
            initialContent={['Trigger "Load Latest Trace" to preview router telemetry.']}
            ref={traceTerminalRef}
          />
        </div>

        <div className="input-row" style={{ marginTop: 24 }}>
          <div className="input-group">
            <label>
              Tracing Mode
              <span className="help-icon" data-tooltip="TRACING_MODE">?</span>
            </label>
            <select value={tracingMode} onChange={(e) => setTracingMode(e.target.value)}>
              <option value="off">Off</option>
              <option value="local">Local</option>
              <option value="langsmith">LangSmith</option>
            </select>
          </div>
          <div className="input-group">
            <label>
              Auto-open LangSmith
              <span className="help-icon" data-tooltip="TRACE_AUTO_LS">?</span>
            </label>
            <select
              value={traceAutoLs}
              onChange={(e) => setTraceAutoLs(parseInt(e.target.value, 10))}
            >
              <option value={0}>No</option>
              <option value={1}>Yes</option>
            </select>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Trace Retention
              <span className="help-icon" data-tooltip="TRACE_RETENTION">?</span>
            </label>
            <input
              type="number"
              min={10}
              max={500}
              value={traceRetention}
              onChange={(e) => setTraceRetention(snapNumber(e.target.value, 50))}
            />
          </div>
          <div className="input-group">
            <label>
              LangChain Tracing v2
              <span className="help-icon" data-tooltip="LANGCHAIN_TRACING_V2">?</span>
            </label>
            <select
              value={langchainTracingV2}
              onChange={(e) => setLangchainTracingV2(parseInt(e.target.value, 10))}
            >
              <option value={0}>Off</option>
              <option value={1}>On</option>
            </select>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              LangSmith Endpoint
              <span className="help-icon" data-tooltip="LANGCHAIN_ENDPOINT">?</span>
            </label>
            <input
              type="text"
              placeholder="https://api.smith.langchain.com"
              value={langchainEndpoint}
              onChange={(e) => setLangchainEndpoint(e.target.value)}
            />
          </div>
          <div className="input-group">
            <label>
              LangSmith API Key
              <span className="help-icon" data-tooltip="LANGCHAIN_API_KEY">?</span>
            </label>
            <ApiKeyStatus keyName="LANGCHAIN_API_KEY" label="LangChain API Key" />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              LangSmith Project
              <span className="help-icon" data-tooltip="LANGCHAIN_PROJECT">?</span>
            </label>
            <input
              type="text"
              placeholder="tribrid"
              value={langchainProject}
              onChange={(e) => setLangchainProject(e.target.value)}
            />
          </div>
          <div className="input-group">
            <label>
              LangSmith User Key
              <span className="help-icon" data-tooltip="LANGSMITH_API_KEY">?</span>
            </label>
            <ApiKeyStatus keyName="LANGSMITH_API_KEY" label="LangSmith API Key" />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              LangTrace API Host
              <span className="help-icon" data-tooltip="LANGTRACE_API_HOST">?</span>
            </label>
            <input
              type="text"
              placeholder="https://api.langtrace.dev"
              value={langtraceApiHost}
              onChange={(e) => setLangtraceApiHost(e.target.value)}
            />
          </div>
          <div className="input-group">
            <label>
              LangTrace Project ID
              <span className="help-icon" data-tooltip="LANGTRACE_PROJECT_ID">?</span>
            </label>
            <input
              type="text"
              value={langtraceProjectId}
              onChange={(e) => setLangtraceProjectId(e.target.value)}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              LangTrace API Key
              <span className="help-icon" data-tooltip="LANGTRACE_API_KEY">?</span>
            </label>
            <ApiKeyStatus keyName="LANGTRACE_API_KEY" label="LangTrace API Key" />
          </div>
          <div className="input-group" />
        </div>
      </CollapsibleSection>
    </>
  );
}

function snapNumber(value: string, fallback: number) {
  if (value === '') return fallback;
  const next = Number(value);
  return Number.isFinite(next) ? next : fallback;
}

function formatTracePayload(payload: TracePayload, vectorBackend: string): string {
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
