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
  const [genModel, setGenModel] = useConfigField<string>('GEN_MODEL', '');
  const [genTemperature, setGenTemperature] = useConfigField<number>('GEN_TEMPERATURE', 0.0);
  const [enrichModel, setEnrichModel] = useConfigField<string>('ENRICH_MODEL', '');
  const [enrichModelOllama, setEnrichModelOllama] = useConfigField<string>('ENRICH_MODEL_OLLAMA', '');
  const [ollamaUrl, setOllamaUrl] = useConfigField<string>('OLLAMA_URL', 'http://127.0.0.1:11434');
  const [openaiBaseUrl, setOpenaiBaseUrl] = useConfigField<string>('OPENAI_BASE_URL', '');
  const [genModelHttp, setGenModelHttp] = useConfigField<string>('GEN_MODEL_HTTP', '');
  const [genModelMcp, setGenModelMcp] = useConfigField<string>('GEN_MODEL_MCP', '');
  const [genModelCli, setGenModelCli] = useConfigField<string>('GEN_MODEL_CLI', '');
  const [enrichBackend, setEnrichBackend] = useConfigField<string>('ENRICH_BACKEND', '');
  const [genMaxTokens, setGenMaxTokens] = useConfigField<number>('GEN_MAX_TOKENS', 2048);
  const [genTopP, setGenTopP] = useConfigField<number>('GEN_TOP_P', 1.0);
  const [genTimeout, setGenTimeout] = useConfigField<number>('GEN_TIMEOUT', 60);
  const [genRetryMax, setGenRetryMax] = useConfigField<number>('GEN_RETRY_MAX', 2);
  const [enrichDisabled, setEnrichDisabled] = useConfigField<string>('ENRICH_DISABLED', '0');

  // --- Retrieval Parameters ------------------------------------------------
  const [multiQueryRewrites, setMultiQueryRewrites] = useConfigField<number>('MAX_QUERY_REWRITES', 2);
  const [finalK, setFinalK] = useConfigField<number>('FINAL_K', 10);
  const [useSemanticSynonyms, setUseSemanticSynonyms] = useConfigField<string>('USE_SEMANTIC_SYNONYMS', '1');
  const [synonymsPath, setSynonymsPath] = useConfigField<string>('AGRO_SYNONYMS_PATH', '');
  const [topkDense, setTopkDense] = useConfigField<number>('TOPK_DENSE', 75);
  const [vectorBackend, setVectorBackend] = useConfigField<string>('VECTOR_BACKEND', 'qdrant');
  const [topkSparse, setTopkSparse] = useConfigField<number>('TOPK_SPARSE', 75);
  const [hydrationMode, setHydrationMode] = useConfigField<string>('HYDRATION_MODE', 'lazy');
  const [hydrationMaxChars, setHydrationMaxChars] = useConfigField<number>('HYDRATION_MAX_CHARS', 2000);
  const [vendorMode, setVendorMode] = useConfigField<string>('VENDOR_MODE', 'prefer_first_party');
  const [bm25Weight, setBm25Weight] = useConfigField<number>('BM25_WEIGHT', 0.3);
  const [bm25K1, setBm25K1] = useConfigField<number>('BM25_K1', 1.2);
  const [bm25B, setBm25B] = useConfigField<number>('BM25_B', 0.4);
  const [vectorWeight, setVectorWeight] = useConfigField<number>('VECTOR_WEIGHT', 0.7);
  const [cardSearchEnabled, setCardSearchEnabled] = useConfigField<string>('CARD_SEARCH_ENABLED', '1');
  const [multiQueryM, setMultiQueryM] = useConfigField<number>('MULTI_QUERY_M', 4);
  const [confTop1, setConfTop1] = useConfigField<number>('CONF_TOP1', 0.62);
  const [confAvg5, setConfAvg5] = useConfigField<number>('CONF_AVG5', 0.55);

  // --- Advanced / Routing ---------------------------------------------------
  const [rrfKDiv, setRrfKDiv] = useConfigField<number>('RRF_K_DIV', 60);
  const [cardBonus, setCardBonus] = useConfigField<number>('CARD_BONUS', 0.08);
  const [filenameBoostExact, setFilenameBoostExact] = useConfigField<number>('FILENAME_BOOST_EXACT', 1.5);
  const [filenameBoostPartial, setFilenameBoostPartial] = useConfigField<number>('FILENAME_BOOST_PARTIAL', 1.2);
  const [langgraphFinalK, setLanggraphFinalK] = useConfigField<number>('LANGGRAPH_FINAL_K', 20);
  const [langgraphMaxQueryRewrites, setLanggraphMaxQueryRewrites] =
    useConfigField<number>('LANGGRAPH_MAX_QUERY_REWRITES', 3);
  const [fallbackConfidence, setFallbackConfidence] = useConfigField<number>('FALLBACK_CONFIDENCE', 0.55);
  const [layerBonusGui, setLayerBonusGui] = useConfigField<number>('LAYER_BONUS_GUI', 0.15);
  const [layerBonusRetrieval, setLayerBonusRetrieval] = useConfigField<number>('LAYER_BONUS_RETRIEVAL', 0.15);
  const [vendorPenalty, setVendorPenalty] = useConfigField<number>('VENDOR_PENALTY', -0.1);
  const [freshnessBonus, setFreshnessBonus] = useConfigField<number>('FRESHNESS_BONUS', 0.05);
  const [tracingMode, setTracingMode] = useConfigField<string>('TRACING_MODE', 'off');
  const [traceAutoLs, setTraceAutoLs] = useConfigField<string>('TRACE_AUTO_LS', '0');
  const [traceRetention, setTraceRetention] = useConfigField<number>('TRACE_RETENTION', 50);
  const [langchainTracingV2, setLangchainTracingV2] = useConfigField<string>('LANGCHAIN_TRACING_V2', '0');
  const [langchainEndpoint, setLangchainEndpoint] = useConfigField<string>('LANGCHAIN_ENDPOINT', '');
  const [langchainProject, setLangchainProject] = useConfigField<string>('LANGCHAIN_PROJECT', '');
  const [langtraceApiHost, setLangtraceApiHost] = useConfigField<string>('LANGTRACE_API_HOST', '');
  const [langtraceProjectId, setLangtraceProjectId] = useConfigField<string>('LANGTRACE_PROJECT_ID', '');

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
      const response = await fetch('/api/models');
      const data = await response.json();
      const models = Array.isArray(data?.models) ? data.models.map((m: any) => m.model) : [];
      if (models.length) {
        setAvailableModels(models);
      }
    } catch (error) {
      console.error('Failed to load models from /api/models:', error);
    }
  }, []);

  const syncConfigSnapshot = useCallback(() => {
    if (!config) {
      return;
    }

    const configAny = config as Record<string, any>;
    const configModels = Array.isArray(configAny?.available_models) ? configAny.available_models : null;
    const hintModels = Array.isArray(configAny?.hints?.available_models)
      ? configAny.hints.available_models
      : null;
    const derivedModels = configModels && configModels.length
      ? configModels
      : hintModels && hintModels.length
        ? hintModels
        : null;

    if (derivedModels) {
      setAvailableModels(derivedModels);
    }

    setHydrating(false);
  }, [config]);

  useEffect(() => {
    loadModels();
  }, [loadModels]);

  useEffect(() => {
    syncConfigSnapshot();
  }, [syncConfigSnapshot]);

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
      const repo = (config as any)?.env?.REPO ? `?repo=${encodeURIComponent((config as any).env.REPO)}` : '';
      const response = await fetch(`/api/traces/latest${repo}`);
      if (!response.ok) {
        throw new Error(`Trace request failed (${response.status})`);
      }
      const data: TracePayload = await response.json();
      const formatted = formatTracePayload(data, vectorBackend || 'qdrant').split('\n');
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
  }, [config, vectorBackend]);

  const handleOpenLangSmith = useCallback(async () => {
    try {
      const project = (config as any)?.env?.LANGCHAIN_PROJECT || 'agro';
      const qs = new URLSearchParams({ project, share: 'true' }).toString();
      const response = await fetch(`/api/langsmith/latest?${qs}`);
      if (!response.ok) {
        throw new Error('LangSmith lookup failed');
      }
      const payload = await response.json();
      if (payload?.url) {
        window.open(payload.url, '_blank', 'noopener,noreferrer');
      } else {
        alert('No recent LangSmith run found. Ask a question first.');
      }
    } catch (error) {
      alert(error instanceof Error ? error.message : 'Unable to open LangSmith');
    }
  }, [config]);

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
            <select value={enrichDisabled} onChange={(e) => setEnrichDisabled(e.target.value)}>
              <option value="0">Enabled</option>
              <option value="1">Disabled</option>
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
              min={0}
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
            <select value={useSemanticSynonyms} onChange={(e) => setUseSemanticSynonyms(e.target.value)}>
              <option value="1">On</option>
              <option value="0">Off</option>
            </select>
          </div>
          <div className="input-group">
            <label>
              Synonyms File Path
              <span className="help-icon" data-tooltip="AGRO_SYNONYMS_PATH">?</span>
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
              Dense Top-K
              <span className="help-icon" data-tooltip="TOPK_DENSE">?</span>
            </label>
            <input
              type="number"
              min={10}
              max={400}
              value={topkDense}
              onChange={(e) => setTopkDense(snapNumber(e.target.value, 75))}
            />
          </div>
          <div className="input-group">
            <label>
              Sparse Top-K
              <span className="help-icon" data-tooltip="TOPK_SPARSE">?</span>
            </label>
            <input
              type="number"
              min={10}
              max={400}
              value={topkSparse}
              onChange={(e) => setTopkSparse(snapNumber(e.target.value, 75))}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Vector Backend
              <span className="help-icon" data-tooltip="VECTOR_BACKEND">?</span>
            </label>
            <select value={vectorBackend} onChange={(e) => setVectorBackend(e.target.value)}>
              <option value="qdrant">Qdrant</option>
              <option value="pinecone">Pinecone</option>
              <option value="weaviate">Weaviate</option>
              <option value="redis">Redis</option>
            </select>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Hydration Mode
              <span className="help-icon" data-tooltip="HYDRATION_MODE">?</span>
            </label>
            <select value={hydrationMode} onChange={(e) => setHydrationMode(e.target.value)}>
              <option value="lazy">Lazy</option>
              <option value="aggressive">Aggressive</option>
              <option value="off">Off</option>
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
              <option value="prefer_third_party">Prefer third party</option>
              <option value="off">Off</option>
            </select>
          </div>
          <div className="input-group">
            <label>
              BM25 Weight
              <span className="help-icon" data-tooltip="BM25_WEIGHT">?</span>
            </label>
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={bm25Weight}
              onChange={(e) => setBm25Weight(snapNumber(e.target.value, 0.3))}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Vector Weight
              <span className="help-icon" data-tooltip="VECTOR_WEIGHT">?</span>
            </label>
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={vectorWeight}
              onChange={(e) => setVectorWeight(snapNumber(e.target.value, 0.7))}
            />
          </div>
          <div className="input-group">
            <label>
              BM25 k1
              <span className="help-icon" data-tooltip="BM25_K1">?</span>
            </label>
            <input
              type="number"
              min={0.2}
              max={3}
              step={0.1}
              value={bm25K1}
              onChange={(e) => setBm25K1(snapNumber(e.target.value, 1.2))}
            />
          </div>
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
            />
          </div>
          <div className="input-group">
            <label>
              Card Search
              <span className="help-icon" data-tooltip="CARD_SEARCH_ENABLED">?</span>
            </label>
            <select value={cardSearchEnabled} onChange={(e) => setCardSearchEnabled(e.target.value)}>
              <option value="1">Enabled</option>
              <option value="0">Disabled</option>
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
              Card Bonus
              <span className="help-icon" data-tooltip="CARD_BONUS">?</span>
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
        title="Routing Trace & LangSmith"
        description="Inspect LangGraph traces and jump directly into LangSmith for debugging."
        storageKey="retrieval-tracing"
        defaultExpanded={false}
      >
        <div className="input-row">
          <div className="input-group">
            <button className="small-button" onClick={handleLoadTrace} disabled={traceLoading}>
              {traceLoading ? 'Loading trace…' : 'Load Latest Trace'}
            </button>
          </div>
          <div className="input-group">
            <button className="small-button" onClick={handleOpenLangSmith}>
              Open in LangSmith
            </button>
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
            <select value={traceAutoLs} onChange={(e) => setTraceAutoLs(e.target.value)}>
              <option value="0">No</option>
              <option value="1">Yes</option>
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
              min={1}
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
            <select value={langchainTracingV2} onChange={(e) => setLangchainTracingV2(e.target.value)}>
              <option value="0">Off</option>
              <option value="1">On</option>
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
              placeholder="agro"
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
    return 'No traces yet. Enable LangChain tracing and run a query.';
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
    const rows = retrieval.data.candidates.slice(0, 10).map((candidate: any) => [
      (candidate.path || '').split('/').slice(-2).join('/'),
      candidate.bm25_rank ?? '',
      candidate.dense_rank ?? '',
    ]);
    parts.push('Pre-rerank candidates (top 10):');
    parts.push(formatTraceTable(rows, ['path', 'bm25', 'dense']));
    parts.push('');
  }

  if (rerank && Array.isArray(rerank.data?.scores)) {
    const rows = rerank.data.scores.slice(0, 10).map((score: any) => [
      (score.path || '').split('/').slice(-2).join('/'),
      score.score?.toFixed?.(3) ?? score.score ?? '',
    ]);
    parts.push('Rerank top-10:');
    parts.push(formatTraceTable(rows, ['path', 'score']));
    parts.push('');
  }

  if (gate) {
    parts.push(`Gate: top1>=${gate.data?.top1_thresh} avg5>=${gate.data?.avg5_thresh} → ${gate.data?.outcome}`);
    parts.push('');
  }

  const recentEvents = events.slice(-10);
  if (recentEvents.length) {
    parts.push('Events:');
    recentEvents.forEach((event) => {
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
