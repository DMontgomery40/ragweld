/**
 * IndexingSubtab - Enterprise RAG Indexing Configuration
 *
 * Follows RerankerConfigSubtab pattern:
 * - useConfig with get()/set() for all config values
 * - Component cards for selecting configuration section
 * - Dynamic config panels per component
 * - Advanced settings in collapsible details
 * - Index stats panel with summary cards
 * - LiveTerminal with slide animation
 *
 * Target users: Advanced RAG engineers who train cross-encoders
 * and monitor loss functions in Grafana.
 */

import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { useConfig } from '@/hooks';
import { useEmbeddingStatus } from '@/hooks/useEmbeddingStatus';
import { useErrorHandler } from '@/hooks/useErrorHandler';
import { useRepoStore } from '@/stores/useRepoStore';
import { useDockerStore } from '@/stores/useDockerStore';
import { LiveTerminal, type LiveTerminalHandle } from '@/components/LiveTerminal';
import { TerminalService } from '@/services/TerminalService';
import { EmbeddingMismatchWarning } from '@/components/ui/EmbeddingMismatchWarning';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { getIndexStats, type IndexStats } from '@/api/dashboard';

// CostLogic is loaded globally from cost_logic.js (same as RerankerConfigSubtab)
declare global {
  interface Window {
    CostLogic: {
      listProviders: () => Promise<string[]>;
      listModels: (provider: string, type?: string) => Promise<string[]>;
    };
  }
}

// ============================================================================
// TYPES
// ============================================================================

type IndexingComponent = 'embedding' | 'chunking' | 'bm25' | 'enrichment';

const COMPONENT_CARDS: Array<{
  id: IndexingComponent;
  icon: string;
  label: string;
  description: string;
}> = [
  { id: 'embedding', icon: '🔢', label: 'Embedding', description: 'Vector generation provider and model' },
  { id: 'chunking', icon: '🧩', label: 'Chunking', description: 'Code splitting strategy and sizes' },
  { id: 'bm25', icon: '📝', label: 'BM25', description: 'Sparse search tokenization' },
  { id: 'enrichment', icon: '✨', label: 'Enrichment', description: 'Code understanding and semantic cards' },
];

// Embedding providers loaded dynamically from models.json via useModels('EMB')

const CHUNKING_STRATEGIES = [
  { id: 'ast', label: 'AST-aware', description: 'Parse code structure, preserve functions' },
  { id: 'greedy', label: 'Greedy', description: 'Simple token-based splitting' },
  { id: 'hybrid', label: 'Hybrid', description: 'AST with greedy fallback' },
];

// ============================================================================
// COMPONENT
// ============================================================================

export function IndexingSubtab() {
  // ==========================================================================
  // HOOKS (following RerankerConfigSubtab pattern)
  // ==========================================================================

  const { get, set, error: configError } = useConfig();
  const { refresh: refreshEmbedding } = useEmbeddingStatus();
  const { handleApiError } = useErrorHandler();
  const { activeRepo, repos, loadRepos } = useRepoStore();
  const { containers, fetchContainers } = useDockerStore();

  // Terminal ref
  const terminalRef = useRef<LiveTerminalHandle>(null);

  // ==========================================================================
  // UI STATE
  // ==========================================================================

  const [selectedComponent, setSelectedComponent] = useState<IndexingComponent>('embedding');
  const [isIndexing, setIsIndexing] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 100, status: 'Ready' });
  const [terminalVisible, setTerminalVisible] = useState(false);

  // Models from models.json via CostLogic (same pattern as RerankerConfigSubtab)
  const [allProviders, setAllProviders] = useState<string[]>([]);
  const [embeddingModels, setEmbeddingModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);

  // Index stats
  const [indexStats, setIndexStats] = useState<IndexStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsExpanded, setStatsExpanded] = useState(false);

  // API key status
  const [apiKeyConfigured, setApiKeyConfigured] = useState<boolean | null>(null);

  const [useGlobalSettings, setUseGlobalSettings] = useState(true);
  const [repoIndexingConfig, setRepoIndexingConfig] = useState<Record<string, any> | null>(null);
  // Vocab preview state
  const [vocabPreview, setVocabPreview] = useState<{ term: string; doc_count: number }[]>([]);
  const [vocabLoading, setVocabLoading] = useState(false);
  const [vocabTopN, setVocabTopN] = useState(50);
  const [vocabTotal, setVocabTotal] = useState(0);
  const [vocabExpanded, setVocabExpanded] = useState(false);
  // Compatibility warnings state
  const [compatibilityWarnings, setCompatibilityWarnings] = useState<{
    type: 'error' | 'warning' | 'info';
    message: string;
    recommendation: string;
  }[]>([]);



  // ==========================================================================
  // CONFIG VALUES (via useConfig get/set - NOT useConfigField!)
  // ==========================================================================

  // Embedding
  const embeddingType = String(get('EMBEDDING_TYPE', 'openai'));
  const embeddingModel = String(get('EMBEDDING_MODEL', 'text-embedding-3-large'));
  const embeddingDim = Number(get('EMBEDDING_DIM', 3072));
  const voyageModel = String(get('VOYAGE_MODEL', 'voyage-code-3'));
  const embeddingModelLocal = String(get('EMBEDDING_MODEL_LOCAL', 'all-MiniLM-L6-v2'));
  const embeddingBatchSize = Number(get('EMBEDDING_BATCH_SIZE', 64));
  const embeddingMaxTokens = Number(get('EMBEDDING_MAX_TOKENS', 8000));
  const embeddingCacheEnabled = Number(get('EMBEDDING_CACHE_ENABLED', 1));
  const embeddingTimeout = Number(get('EMBEDDING_TIMEOUT', 30));
  const embeddingRetryMax = Number(get('EMBEDDING_RETRY_MAX', 3));

  // Chunking
  const chunkSize = Number(get('CHUNK_SIZE', 1000));
  const chunkOverlap = Number(get('CHUNK_OVERLAP', 200));
  const chunkingStrategy = String(get('CHUNKING_STRATEGY', 'ast'));
  const astOverlapLines = Number(get('AST_OVERLAP_LINES', 20));
  const maxChunkTokens = Number(get('MAX_CHUNK_TOKENS', 8000));
  const maxIndexableFileSize = Number(get('MAX_INDEXABLE_FILE_SIZE', 2000000));
  const minChunkChars = Number(get('MIN_CHUNK_CHARS', 50));
  const greedyFallbackTarget = Number(get('GREEDY_FALLBACK_TARGET', 800));
  const preserveImports = Number(get('PRESERVE_IMPORTS', 1));

  // BM25
  const bm25Tokenizer = String(get('BM25_TOKENIZER', 'stemmer'));
  const bm25StemmerLang = String(get('BM25_STEMMER_LANG', 'english'));
  const bm25StopwordsLang = String(get('BM25_STOPWORDS_LANG', 'en'));

  // Resolved tokenizer description (computed from Zustand config values, no API call)
  const resolvedTokenizerDesc = useMemo(() => {
    if (bm25Tokenizer === 'stemmer') {
      return `Stemmer (${bm25StemmerLang}) with ${bm25StopwordsLang} stopwords`;
    } else if (bm25Tokenizer === 'whitespace') {
      return 'Whitespace tokenizer (preserves code identifiers)';
    }
    return `${bm25Tokenizer} tokenizer`;
  }, [bm25Tokenizer, bm25StemmerLang, bm25StopwordsLang]);

  // Enrichment / Run Options
  const skipDense = Number(get('SKIP_DENSE', 0));
  const enrichChunks = Number(get('ENRICH_CODE_CHUNKS', 1));

  // ==========================================================================
  // DERIVED STATE
  // ==========================================================================

  const qdrantContainer = containers.find(c => c.name?.toLowerCase().includes('qdrant'));
  const isQdrantReady = qdrantContainer?.status?.toLowerCase().includes('running') ?? false;

  /**
   * canIndex: Determines if the Index Now button should be enabled.
   *
   * MODE-AWARE LOGIC:
   * - BM25-only (SKIP_DENSE=1): Only requires repo selected and not currently indexing.
   *   Qdrant is NOT needed because BM25 uses local filesystem storage, not a vector DB.
   * - Hybrid (SKIP_DENSE=0): Additionally requires Qdrant running for vector storage.
   *
   * This allows users who explicitly choose BM25-only mode to index without
   * needing to spin up Qdrant infrastructure.
   */
  const canIndex = skipDense === 1
    ? !isIndexing && !!activeRepo                    // BM25-only: no Qdrant needed
    : isQdrantReady && !isIndexing && !!activeRepo;  // Hybrid: Qdrant required

  /**
   * VALIDATION GATE FLAGS (derived from compatibilityWarnings computed in useEffect)
   *
   * MODE-AWARE ERROR LOGIC:
   * - In Hybrid mode (SKIP_DENSE=0): Qdrant down is handled by canIndex, not here.
   *   Embedding dimension mismatch is handled by <EmbeddingMismatchWarning>.
   * - In BM25-only mode (SKIP_DENSE=1): No embedding-related errors apply.
   *   hasValidationErrors should only catch actual BM25 config errors (rare).
   *
   * WARNING TYPES (non-blocking, informational):
   * - SKIP_DENSE enabled (legitimate user choice, but user should be aware)
   * - Small/large chunk sizes affecting retrieval quality
   * - Stemmer vs whitespace tokenizer considerations
   *
   * NOTE: hasValidationErrors is currently UNUSED because there are no actual
   * error-level issues in compatibilityWarnings after fixing SKIP_DENSE to warning.
   * Kept for future use if we add actual blocking errors (e.g., invalid BM25 config).
   */
  const hasValidationErrors = compatibilityWarnings.some(w => w.type === 'error');
  const hasValidationWarnings = compatibilityWarnings.some(w => w.type === 'warning');

  // Current model based on provider
  const currentModel = useMemo(() => {
    switch (embeddingType) {
      case 'openai': return embeddingModel;
      case 'voyage': return voyageModel;
      default: return embeddingModelLocal;
    }
  }, [embeddingType, embeddingModel, voyageModel, embeddingModelLocal]);

  // API key env name
  const apiKeyEnvName = useMemo(() => {
    switch (embeddingType) {
      case 'openai': return 'OPENAI_API_KEY';
      case 'voyage': return 'VOYAGE_API_KEY';
      default: return null;
    }
  }, [embeddingType]);

  // ==========================================================================
  // EFFECTS
  // ==========================================================================

  // Load repos on mount
  useEffect(() => {
    if (repos.length === 0) {
      loadRepos();
    }
  }, [repos.length, loadRepos]);

  // Fetch containers on mount
  useEffect(() => {
    fetchContainers();
  }, [fetchContainers]);

  // Load providers from CostLogic (same pattern as RerankerConfigSubtab)
  const loadProviders = useCallback(async () => {
    setModelsLoading(true);
    setModelsError(null);
    try {
      const providers = await window.CostLogic.listProviders();
      setAllProviders(providers);
    } catch (e: any) {
      console.error('[IndexingSubtab] Failed to load providers:', e);
      setModelsError(e?.message || 'Failed to load providers');
    } finally {
      setModelsLoading(false);
    }
  }, []);

  // Load embedding models when provider changes (same pattern as Sidepanel)
  const loadEmbeddingModels = useCallback(async (provider: string) => {
    if (!provider) {
      setEmbeddingModels([]);
      return;
    }
    try {
      const models = await window.CostLogic.listModels(provider, 'embed');
      setEmbeddingModels(models);
    } catch (e: any) {
      console.error('[IndexingSubtab] Failed to load models:', e);
      setEmbeddingModels([]);
    }
  }, []);

  useEffect(() => {
    loadProviders();
  }, [loadProviders]);

  useEffect(() => {
    loadEmbeddingModels(embeddingType);
  }, [embeddingType, loadEmbeddingModels]);

  // Filter providers that have embed models
  const embProviders = useMemo(() => {
    // Show all providers - model dropdown will be empty if no embed models for that provider
    return allProviders;
  }, [allProviders]);

  // Check API key status (never expose actual key)
  useEffect(() => {
    if (apiKeyEnvName) {
      fetch(`/api/secrets/check?keys=${apiKeyEnvName}`)
        .then(r => r.json())
        .then(data => setApiKeyConfigured(data[apiKeyEnvName] === true))
        .catch(() => setApiKeyConfigured(null));
    } else {
      setApiKeyConfigured(null);
    }
  }, [apiKeyEnvName]);

  // Load index stats
  const loadStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const stats = await getIndexStats();
      setIndexStats(stats);
    } catch (e) {
      console.error('[IndexingSubtab] Failed to load stats:', e);
    } finally {
      setStatsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

    // Load repo-specific indexing config when activeRepo changes
    useEffect(() => {
        if (!activeRepo) return;

        const repo = repos.find(r => r.name === activeRepo);
        if (repo?.indexing) {
            setRepoIndexingConfig(repo.indexing);
            setUseGlobalSettings(repo.indexing.use_global !== false);
        } else {
            setRepoIndexingConfig(null);
            setUseGlobalSettings(true);
        }
    }, [activeRepo, repos]);
    // Check compatibility warnings when config changes
  useEffect(() => {
    const warnings: typeof compatibilityWarnings = [];

    // Code model + stemmer tokenizer warning
    if (bm25Tokenizer === 'stemmer' && chunkingStrategy === 'ast') {
      warnings.push({
        type: 'info',
        message: 'Stemmer tokenizer may alter code identifiers',
        recommendation: 'Consider "whitespace" tokenizer for code-heavy repos to preserve exact function/variable names'
      });
    }

    // Small chunks with code warning
    if (chunkSize < 300 && chunkingStrategy === 'ast') {
      warnings.push({
        type: 'warning',
        message: `Chunk size (${chunkSize}) may be too small for code`,
        recommendation: 'AST chunking works best with 500-1500 token chunks to capture full functions'
      });
    }

    // Large chunks warning
    if (chunkSize > 2000) {
      warnings.push({
        type: 'warning',
        message: `Large chunk size (${chunkSize}) may reduce retrieval precision`,
        recommendation: 'Consider 800-1500 for balanced context and precision'
      });
    }

    // Greedy chunking warning
    if (chunkingStrategy === 'greedy') {
      warnings.push({
        type: 'info',
        message: 'Greedy chunking ignores code structure',
        recommendation: 'Use AST or Hybrid strategy for code repos to preserve function boundaries'
      });
    }

    // Skip dense warning - BM25-only is a valid user choice, NOT an error
    // User explicitly chose to skip embeddings; this should be a warning, not a blocker
    if (skipDense === 1) {
      warnings.push({
        type: 'warning',
        message: 'BM25-only mode - semantic search unavailable',
        recommendation: 'Enable dense vectors for hybrid retrieval (recommended for most use cases)'
      });
    }

    setCompatibilityWarnings(warnings);
  }, [bm25Tokenizer, chunkingStrategy, chunkSize, skipDense]);

  // ==========================================================================
  // HANDLERS
  // ==========================================================================

  const handleProviderChange = useCallback(async (provider: string) => {
    set('EMBEDDING_TYPE', provider);
    // Auto-select first model from models.json when provider changes (same pattern as RerankerConfigSubtab)
    try {
      const models = await window.CostLogic.listModels(provider, 'embed');
      if (models.length > 0 && !models.includes(embeddingModel)) {
        set('EMBEDDING_MODEL', models[0]);
      }
    } catch (e) {
      console.error('[IndexingSubtab] Failed to load models for provider:', e);
    }
  }, [set, embeddingModel]);

  const handleStartIndex = useCallback(async () => {
    if (!activeRepo) return;

    setIsIndexing(true);
    setProgress({ current: 0, total: 100, status: 'Starting...' });
    setTerminalVisible(true);

    // Clear and show terminal
    terminalRef.current?.show?.();
    terminalRef.current?.clear?.();
    terminalRef.current?.setTitle?.(`Indexing: ${activeRepo}`);
    terminalRef.current?.appendLine?.(`🚀 Starting indexing for ${activeRepo}`);
    terminalRef.current?.appendLine?.(`   Provider: ${embeddingType}, Model: ${currentModel}`);
    terminalRef.current?.appendLine?.(`   Chunk Size: ${chunkSize}, Strategy: ${chunkingStrategy}`);

    try {
      TerminalService.streamIndexRun('indexing_terminal', {
        repo: activeRepo,
        skip_dense: skipDense === 1,
        enrich: enrichChunks === 1,
        onLine: (line) => {
          terminalRef.current?.appendLine?.(line);
        },
        onProgress: (percent, message) => {
          setProgress({ current: percent, total: 100, status: message || `Progress: ${percent}%` });
          terminalRef.current?.updateProgress?.(percent, message);
        },
        onError: (err) => {
          terminalRef.current?.appendLine?.(`\x1b[31mError: ${err}\x1b[0m`);
          setProgress(prev => ({ ...prev, status: `Error: ${err}` }));
          setIsIndexing(false);
        },
        onComplete: async () => {
          terminalRef.current?.updateProgress?.(100, 'Complete');
          terminalRef.current?.appendLine?.(`\x1b[32m✓ Indexing complete!\x1b[0m`);
          setProgress({ current: 100, total: 100, status: 'Complete' });
          setIsIndexing(false);
          refreshEmbedding();
          loadStats();
        }
      });
    } catch (error) {
      const msg = handleApiError(error, 'Indexing');
      terminalRef.current?.appendLine?.(`\x1b[31mFailed: ${msg}\x1b[0m`);
      setProgress(prev => ({ ...prev, status: `Failed: ${msg}` }));
      setIsIndexing(false);
    }
  }, [activeRepo, embeddingType, currentModel, chunkSize, chunkingStrategy, skipDense, enrichChunks, handleApiError, refreshEmbedding, loadStats]);
const handleToggleGlobalSettings = useCallback(async (useGlobal: boolean) => {
    if (!activeRepo) return;

    setUseGlobalSettings(useGlobal);
    try {
        await useRepoStore.getState().updateRepoIndexing(activeRepo, { use_global: useGlobal });
    } catch (e) {
        console.error('[IndexingSubtab] Failed to update use_global:', e);
    }
}, [activeRepo]);

const loadVocabPreview = useCallback(async () => {
  if (!activeRepo) return;
  
  setVocabLoading(true);
  try {
    const response = await fetch(`/api/index/vocab-preview?repo=${activeRepo}&top_n=${vocabTopN}`);
    if (!response.ok) throw new Error('Failed to load vocab');
    const data = await response.json();
    setVocabPreview(data.terms || []);
    setVocabTotal(data.total_terms || 0);
  } catch (e) {
    console.error('[IndexingSubtab] Vocab preview error:', e);
    setVocabPreview([]);
  } finally {
    setVocabLoading(false);
  }
}, [activeRepo, vocabTopN]);

  const handleStopIndex = useCallback(() => {
    TerminalService.disconnect('indexing_terminal');
    setIsIndexing(false);
    setProgress(prev => ({ ...prev, status: 'Stopped' }));
    terminalRef.current?.appendLine?.(`\x1b[33m⚠ Indexing stopped by user\x1b[0m`);
  }, []);

  // ==========================================================================
  // RENDER HELPERS
  // ==========================================================================

  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  // ==========================================================================
  // RENDER
  // ==========================================================================

  return (
    <div className="subtab-panel" style={{ padding: '24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '28px' }}>
        <h3 style={{
          fontSize: '18px',
          fontWeight: 600,
          color: 'var(--fg)',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          marginBottom: '8px'
        }}>
          <span style={{ fontSize: '22px' }}>📦</span>
          Code Indexing
          <TooltipIcon name="INDEXING" />
        </h3>
        <p style={{
          fontSize: '14px',
          color: 'var(--fg-muted)',
          lineHeight: 1.6,
          maxWidth: '800px'
        }}>
          Configure embedding generation, code chunking, sparse search, and enrichment.
          Each component can be tuned independently for optimal retrieval quality.
        </p>
      </div>

      {/* Error Banner */}
      {(configError || modelsError) && (
        <div style={{
          background: 'rgba(var(--error-rgb), 0.1)',
          border: '1px solid var(--error)',
          borderRadius: '8px',
          padding: '12px 16px',
          marginBottom: '20px',
          color: 'var(--error)',
          fontSize: '13px'
        }}>
          {configError || modelsError}
        </div>
      )}

      {/* Embedding Mismatch Warning */}
      <EmbeddingMismatchWarning variant="inline" showActions />

      {/* Qdrant Warning */}
      {!isQdrantReady && (
        <div style={{
          background: 'rgba(var(--warn-rgb), 0.1)',
          border: '1px solid var(--warn)',
          borderRadius: '8px',
          padding: '12px 16px',
          marginBottom: '20px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '13px'
        }}>
          <span style={{ fontSize: '16px' }}>⚠️</span>
          <span style={{ color: 'var(--warn)' }}>
            Qdrant not running. Start it in the <strong>Infrastructure</strong> tab before indexing.
          </span>
        </div>
      )}

      {/* Repository Selection + Per-Repo Config Toggle */}
          <div style={{ marginBottom: '24px' }}>
        <div style={{ display: 'flex', gap: '20px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
            {/* Repo Dropdown */}
            <div style={{ flex: '1', minWidth: '200px', maxWidth: '400px' }}>
                <label style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    marginBottom: '8px',
                    fontSize: '13px',
                    fontWeight: 600,
                    color: 'var(--fg)'
                }}>
                    Target Repository
                    <TooltipIcon name="REPO" />
                </label>
                <select
                    value={activeRepo}
                    onChange={(e) => useRepoStore.getState().setActiveRepo(e.target.value)}
                    style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: !useGlobalSettings ? '2px solid var(--accent)' : '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px'
                    }}
                >
                    {repos.length === 0 ? (
                        <option value="">No repositories</option>
                    ) : (
                        repos.map(repo => (
                            <option key={repo.name} value={repo.name}>
                                {repo.name} {repo.indexing && !repo.indexing.use_global ? '⚙️' : ''}
                            </option>
                        ))
                    )}
                </select>
            </div>

            {/* Use Global Settings Toggle */}
            <div style={{
                padding: '12px 16px',
                background: useGlobalSettings ? 'var(--bg-elev2)' : 'rgba(var(--accent-rgb), 0.1)',
                border: useGlobalSettings ? '1px solid var(--line)' : '2px solid var(--accent)',
                borderRadius: '8px',
                transition: 'all 0.2s ease'
            }}>
                <label style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    cursor: 'pointer'
                }}>
                    <input
                        type="checkbox"
                        checked={useGlobalSettings}
                        onChange={(e) => handleToggleGlobalSettings(e.target.checked)}
                        style={{ width: '16px', height: '16px' }}
                    />
                    <div>
                        <div style={{
                            fontSize: '13px',
                            fontWeight: 600,
                            color: useGlobalSettings ? 'var(--fg)' : 'var(--accent)'
                        }}>
                            Use Global Settings
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
                            {useGlobalSettings
                                ? 'Using shared indexing config'
                                : `Custom config for ${activeRepo}`
                            }
                        </div>
                    </div>
                    <TooltipIcon name="PER_REPO_INDEXING" />
                </label>
            </div>
        </div>

        {/* Override indicator banner */}
        {!useGlobalSettings && repoIndexingConfig && (
            <div style={{
                marginTop: '12px',
                padding: '10px 14px',
                background: 'rgba(var(--accent-rgb), 0.08)',
                border: '1px solid var(--accent)',
                borderRadius: '6px',
                fontSize: '12px',
                color: 'var(--accent)',
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
            }}>
                <span>⚙️</span>
                <span>
              <strong>{activeRepo}</strong> has custom indexing settings.
              Changes below will only affect this repository.
            </span>
            </div>
        )}
    </div>

      {/* Compatibility Warnings */}
      {compatibilityWarnings.length > 0 && (
        <div style={{ marginBottom: '20px' }}>
          {compatibilityWarnings.map((warn, idx) => (
            <div
              key={idx}
              style={{
                padding: '12px 16px',
                marginBottom: '8px',
                background: warn.type === 'error' 
                  ? 'rgba(var(--error-rgb), 0.1)'
                  : warn.type === 'warning'
                    ? 'rgba(var(--warn-rgb), 0.1)'
                    : 'rgba(var(--accent-rgb), 0.08)',
                border: `1px solid ${
                  warn.type === 'error' 
                    ? 'var(--error)' 
                    : warn.type === 'warning' 
                      ? 'var(--warn)' 
                      : 'var(--accent)'
                }`,
                borderRadius: '8px',
                fontSize: '13px'
              }}
            >
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                marginBottom: '4px',
                color: warn.type === 'error' 
                  ? 'var(--error)' 
                  : warn.type === 'warning' 
                    ? 'var(--warn)' 
                    : 'var(--accent)',
                fontWeight: 600
              }}>
                <span>{warn.type === 'error' ? '❌' : warn.type === 'warning' ? '⚠️' : 'ℹ️'}</span>
                {warn.message}
              </div>
              <div style={{ color: 'var(--fg-muted)', fontSize: '12px', marginLeft: '24px' }}>
                💡 {warn.recommendation}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Component Cards Grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: '16px',
        marginBottom: '24px'
      }}>
        {COMPONENT_CARDS.map(comp => {
          // SKIP_DENSE visual de-emphasis: dim embedding card when skipDense is enabled
          // Card remains clickable so users can still view/modify settings
          const isEmbeddingInactive = comp.id === 'embedding' && skipDense === 1;
          return (
          <button
            key={comp.id}
            onClick={() => setSelectedComponent(comp.id)}
            style={{
              padding: '20px 16px',
              background: selectedComponent === comp.id
                ? 'linear-gradient(135deg, rgba(var(--accent-rgb), 0.15), rgba(var(--accent-rgb), 0.05))'
                : 'var(--card-bg)',
              border: selectedComponent === comp.id
                ? '2px solid var(--accent)'
                : '1px solid var(--line)',
              borderRadius: '12px',
              cursor: 'pointer',
              textAlign: 'left',
              transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
              position: 'relative',
              overflow: 'hidden',
              opacity: isEmbeddingInactive ? 0.5 : 1
            }}
          >
            {selectedComponent === comp.id && (
              <div style={{
                position: 'absolute',
                top: '8px',
                right: '8px',
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                background: 'var(--accent)',
                boxShadow: '0 0 8px var(--accent)'
              }} />
            )}
            <div style={{ fontSize: '28px', marginBottom: '10px' }}>{comp.icon}</div>
            <div style={{
              fontSize: '14px',
              fontWeight: 600,
              color: selectedComponent === comp.id ? 'var(--accent)' : 'var(--fg)',
              marginBottom: '6px'
            }}>
              {comp.label}
            </div>
            <div style={{
              fontSize: '12px',
              color: 'var(--fg-muted)',
              lineHeight: 1.4
            }}>
              {comp.description}
            </div>
          </button>
          );
        })}
      </div>

      {/* Dynamic Config Panel */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '12px',
        padding: '24px',
        marginBottom: '24px'
      }}>
        {/* EMBEDDING PANEL */}
        {selectedComponent === 'embedding' && (
          <div>
            {/* SKIP_DENSE banner - outside dimmed content */}
            {skipDense === 1 && (
              <div style={{
                background: 'rgba(var(--warning-rgb, 255, 170, 0), 0.15)',
                border: '1px solid var(--warning, #ffaa00)',
                borderRadius: '8px',
                padding: '12px 16px',
                marginBottom: '16px',
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                color: 'var(--warning, #ffaa00)'
              }}>
                <span style={{ fontSize: '18px' }}>⚠️</span>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '13px' }}>Semantic Search Disabled</div>
                  <div style={{ fontSize: '11px', opacity: 0.9 }}>
                    SKIP_DENSE is enabled. Only BM25 keyword matching will be used.
                  </div>
                </div>
              </div>
            )}
            {/* Dimmed content wrapper */}
            <div style={{
              opacity: skipDense === 1 ? 0.5 : 1,
              pointerEvents: skipDense === 1 ? 'none' : 'auto',
              transition: 'opacity 0.2s ease'
            }}>
            <h4 style={{
              fontSize: '14px',
              fontWeight: 600,
              color: 'var(--fg)',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              🔢 Embedding Configuration
              <TooltipIcon name="EMBEDDING_TYPE" />
            </h4>

            {/* Provider Sub-Cards - loaded from models.json via CostLogic */}
            {modelsLoading ? (
              <div style={{ padding: '20px', textAlign: 'center', color: 'var(--fg-muted)' }}>
                Loading providers...
              </div>
            ) : (
              <div style={{
                display: 'grid',
                gridTemplateColumns: `repeat(${Math.min(embProviders.length, 4)}, 1fr)`,
                gap: '12px',
                marginBottom: '20px'
              }}>
                {embProviders.map((provider: string) => (
                  <button
                    key={provider}
                    onClick={() => handleProviderChange(provider)}
                    style={{
                      padding: '12px',
                      background: embeddingType === provider
                        ? 'rgba(var(--accent-rgb), 0.1)'
                        : 'var(--bg-elev2)',
                      border: embeddingType === provider
                        ? '2px solid var(--accent)'
                        : '1px solid var(--line)',
                      borderRadius: '8px',
                      cursor: 'pointer',
                      textAlign: 'center',
                      transition: 'all 0.2s ease'
                    }}
                  >
                    <div style={{
                      fontSize: '12px',
                      fontWeight: 600,
                      color: embeddingType === provider ? 'var(--accent)' : 'var(--fg)'
                    }}>
                      {provider}
                    </div>
                  </button>
                ))}
              </div>
            )}

            {/* Model Selection - models loaded from models.json via CostLogic */}
            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Model
                  <TooltipIcon name="EMBEDDING_MODEL" />
                </label>
                <select
                  value={embeddingModel}
                  onChange={(e) => set('EMBEDDING_MODEL', e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px'
                  }}
                >
                  {embeddingModels.length > 0 ? (
                    embeddingModels.map(m => <option key={m} value={m}>{m}</option>)
                  ) : (
                    <option value="">No models for {embeddingType}</option>
                  )}
                </select>
              </div>

              {embeddingType === 'openai' && (
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    Dimensions
                    <TooltipIcon name="EMBEDDING_DIM" />
                  </label>
                  <select
                    value={embeddingDim}
                    onChange={(e) => set('EMBEDDING_DIM', parseInt(e.target.value))}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px'
                    }}
                  >
                    <option value={3072}>3072 (full quality)</option>
                    <option value={1536}>1536 (balanced)</option>
                    <option value={512}>512 (compact)</option>
                  </select>
                </div>
              )}
            </div>

            {/* API Key Status */}
            {apiKeyEnvName && (
              <div style={{
                marginTop: '16px',
                padding: '12px 16px',
                background: apiKeyConfigured === true
                  ? 'rgba(var(--ok-rgb), 0.1)'
                  : 'rgba(var(--warn-rgb), 0.1)',
                borderRadius: '8px',
                border: `1px solid ${apiKeyConfigured === true ? 'var(--ok)' : 'var(--warn)'}`,
                fontSize: '12px'
              }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  color: apiKeyConfigured === true ? 'var(--ok)' : 'var(--warn)'
                }}>
                  <span style={{ fontSize: '14px' }}>{apiKeyConfigured === true ? '✓' : '⚠'}</span>
                  <span style={{ fontWeight: 600 }}>
                    {apiKeyEnvName}: {apiKeyConfigured === true ? 'Configured' : 'Not configured'}
                  </span>
                </div>
                {apiKeyConfigured !== true && (
                  <div style={{ marginTop: '4px', color: 'var(--fg-muted)' }}>
                    Add <code style={{
                      background: 'var(--bg-elev2)',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '11px'
                    }}>{apiKeyEnvName}=your_key</code> to your <code style={{
                      background: 'var(--bg-elev2)',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '11px'
                    }}>.env</code> file.
                  </div>
                )}
              </div>
            )}
            </div>{/* close dimmed content wrapper */}
          </div>
        )}

        {/* CHUNKING PANEL */}
        {selectedComponent === 'chunking' && (
          <div>
            <h4 style={{
              fontSize: '14px',
              fontWeight: 600,
              color: 'var(--fg)',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              🧩 Chunking Configuration
              <TooltipIcon name="CHUNKING_STRATEGY" />
            </h4>

            {/* Strategy Cards */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: '12px',
              marginBottom: '20px'
            }}>
              {CHUNKING_STRATEGIES.map(strat => (
                <button
                  key={strat.id}
                  onClick={() => set('CHUNKING_STRATEGY', strat.id)}
                  style={{
                    padding: '16px',
                    background: chunkingStrategy === strat.id
                      ? 'rgba(var(--accent-rgb), 0.1)'
                      : 'var(--bg-elev2)',
                    border: chunkingStrategy === strat.id
                      ? '2px solid var(--accent)'
                      : '1px solid var(--line)',
                    borderRadius: '8px',
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'all 0.2s ease'
                  }}
                >
                  <div style={{
                    fontSize: '13px',
                    fontWeight: 600,
                    color: chunkingStrategy === strat.id ? 'var(--accent)' : 'var(--fg)',
                    marginBottom: '4px'
                  }}>
                    {strat.label}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
                    {strat.description}
                  </div>
                </button>
              ))}
            </div>

            {/* Chunk Parameters */}
            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px' }}>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Chunk Size
                  <TooltipIcon name="CHUNK_SIZE" />
                </label>
                <input
                  type="number"
                  value={chunkSize}
                  onChange={(e) => set('CHUNK_SIZE', parseInt(e.target.value) || 1000)}
                  min={100}
                  max={10000}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px'
                  }}
                />
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Chunk Overlap
                  <TooltipIcon name="CHUNK_OVERLAP" />
                </label>
                <input
                  type="number"
                  value={chunkOverlap}
                  onChange={(e) => set('CHUNK_OVERLAP', parseInt(e.target.value) || 200)}
                  min={0}
                  max={1000}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px'
                  }}
                />
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  AST Overlap Lines
                  <TooltipIcon name="AST_OVERLAP_LINES" />
                </label>
                <input
                  type="number"
                  value={astOverlapLines}
                  onChange={(e) => set('AST_OVERLAP_LINES', parseInt(e.target.value) || 20)}
                  min={0}
                  max={100}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px'
                  }}
                />
              </div>
            </div>

            {/* Row 2: Token Limits */}
            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginTop: '16px' }}>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Max Chunk Tokens
                  <TooltipIcon name="MAX_CHUNK_TOKENS" />
                </label>
                <input
                  type="number"
                  value={maxChunkTokens}
                  onChange={(e) => set('MAX_CHUNK_TOKENS', parseInt(e.target.value) || 8000)}
                  min={100}
                  max={32000}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px'
                  }}
                />
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Min Chunk Chars
                  <TooltipIcon name="MIN_CHUNK_CHARS" />
                </label>
                <input
                  type="number"
                  value={minChunkChars}
                  onChange={(e) => set('MIN_CHUNK_CHARS', parseInt(e.target.value) || 50)}
                  min={10}
                  max={500}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px'
                  }}
                />
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Greedy Fallback Target
                  <TooltipIcon name="GREEDY_FALLBACK_TARGET" />
                </label>
                <input
                  type="number"
                  value={greedyFallbackTarget}
                  onChange={(e) => set('GREEDY_FALLBACK_TARGET', parseInt(e.target.value) || 800)}
                  min={200}
                  max={2000}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px'
                  }}
                />
              </div>
            </div>

            {/* Preserve Imports Toggle */}
            <div style={{ marginTop: '16px' }}>
              <label style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                cursor: 'pointer'
              }}>
                <input
                  type="checkbox"
                  checked={preserveImports === 1}
                  onChange={(e) => set('PRESERVE_IMPORTS', e.target.checked ? 1 : 0)}
                />
                <span style={{ fontSize: '13px', color: 'var(--fg)' }}>Preserve Imports</span>
                <TooltipIcon name="PRESERVE_IMPORTS" />
              </label>
              <p style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px', marginLeft: '24px' }}>
                Keep import statements at the top of each chunk for better code understanding
              </p>
            </div>
          </div>
        )}

        {/* BM25 PANEL */}
        {selectedComponent === 'bm25' && (
          <div>
            <h4 style={{
              fontSize: '14px',
              fontWeight: 600,
              color: 'var(--fg)',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              📝 BM25 / Tokenization
              <TooltipIcon name="BM25_TOKENIZER" />
            </h4>

            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px' }}>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Tokenizer
                  <TooltipIcon name="BM25_TOKENIZER" />
                </label>
                <select
                  value={bm25Tokenizer}
                  onChange={(e) => set('BM25_TOKENIZER', e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px'
                  }}
                >
                  <option value="stemmer">Stemmer</option>
                  <option value="word">Word</option>
                  <option value="whitespace">Whitespace</option>
                </select>
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Stemmer Language
                  <TooltipIcon name="BM25_STEMMER_LANG" />
                </label>
                <input
                  type="text"
                  value={bm25StemmerLang}
                  onChange={(e) => set('BM25_STEMMER_LANG', e.target.value)}
                  placeholder="english"
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px'
                  }}
                />
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Stopwords Language
                  <TooltipIcon name="BM25_STOPWORDS_LANG" />
                </label>
                <input
                  type="text"
                  value={bm25StopwordsLang}
                  onChange={(e) => set('BM25_STOPWORDS_LANG', e.target.value)}
                  placeholder="en"
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px'
                  }}
                />
              </div>
            </div>

            {/* Resolved tokenizer display */}
            <div style={{
              marginTop: '12px',
              fontSize: '12px',
              color: 'var(--fg-muted)',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}>
              <strong>Resolved:</strong> {resolvedTokenizerDesc}
              <TooltipIcon name="BM25_TOKENIZER_RESOLVED" />
            </div>

            <div style={{
              marginTop: '16px',
              padding: '12px 16px',
              background: 'var(--bg-elev2)',
              borderRadius: '8px',
              fontSize: '12px',
              color: 'var(--fg-muted)'
            }}>
              <strong>BM25</strong> (Best Matching 25) provides sparse keyword search alongside dense vector search.
              The tokenizer determines how text is split into searchable terms.
            </div>
          </div>
        )}

        {/* ENRICHMENT PANEL */}
        {selectedComponent === 'enrichment' && (
          <div>
            <h4 style={{
              fontSize: '14px',
              fontWeight: 600,
              color: 'var(--fg)',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              ✨ Enrichment & Processing
              <TooltipIcon name="ENRICH_CODE_CHUNKS" />
            </h4>

            <div style={{ display: 'grid', gap: '16px' }}>
              <div style={{
                padding: '16px',
                background: 'var(--bg-elev2)',
                borderRadius: '8px',
                border: enrichChunks === 1 ? '2px solid var(--accent)' : '1px solid var(--line)'
              }}>
                <label style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  cursor: 'pointer'
                }}>
                  <input
                    type="checkbox"
                    checked={enrichChunks === 1}
                    onChange={(e) => set('ENRICH_CODE_CHUNKS', e.target.checked ? 1 : 0)}
                    style={{ width: '18px', height: '18px' }}
                  />
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--fg)' }}>
                      Enrich Code Chunks
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                      Add semantic descriptions to code chunks using LLM analysis
                    </div>
                  </div>
                  <TooltipIcon name="ENRICH_CODE_CHUNKS" />
                </label>
              </div>

              <div style={{
                padding: '16px',
                background: 'var(--bg-elev2)',
                borderRadius: '8px',
                border: skipDense === 1 ? '2px solid var(--warn)' : '1px solid var(--line)'
              }}>
                <label style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  cursor: 'pointer'
                }}>
                  <input
                    type="checkbox"
                    checked={skipDense === 1}
                    onChange={(e) => set('SKIP_DENSE', e.target.checked ? 1 : 0)}
                    style={{ width: '18px', height: '18px' }}
                  />
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--fg)' }}>
                      Skip Dense Vectors
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                      Only generate BM25 index (faster, no embedding API calls)
                    </div>
                  </div>
                  <TooltipIcon name="SKIP_DENSE" />
                </label>
                {skipDense === 1 && (
                  <div style={{
                    marginTop: '8px',
                    padding: '8px 12px',
                    background: 'rgba(var(--warn-rgb), 0.1)',
                    borderRadius: '4px',
                    color: 'var(--warn)',
                    fontSize: '11px'
                  }}>
                    ⚠️ Semantic search will be unavailable without dense vectors
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Advanced Settings */}
      <details style={{ marginBottom: '24px' }}>
        <summary style={{
          cursor: 'pointer',
          fontSize: '14px',
          fontWeight: 500,
          color: 'var(--fg-muted)',
          padding: '12px 0'
        }}>
          Advanced Settings
        </summary>
        <div style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '20px',
          marginTop: '8px'
        }}>
          <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginBottom: '16px' }}>
            <div className="input-group">
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                Batch Size
                <TooltipIcon name="EMBEDDING_BATCH_SIZE" />
              </label>
              <input
                type="number"
                value={embeddingBatchSize}
                onChange={(e) => set('EMBEDDING_BATCH_SIZE', parseInt(e.target.value) || 64)}
                min={1}
                max={256}
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '6px',
                  color: 'var(--fg)',
                  fontSize: '13px'
                }}
              />
            </div>
            <div className="input-group">
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                Max Tokens
                <TooltipIcon name="EMBEDDING_MAX_TOKENS" />
              </label>
              <input
                type="number"
                value={embeddingMaxTokens}
                onChange={(e) => set('EMBEDDING_MAX_TOKENS', parseInt(e.target.value) || 8000)}
                min={100}
                max={16000}
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '6px',
                  color: 'var(--fg)',
                  fontSize: '13px'
                }}
              />
            </div>
            <div className="input-group">
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                Timeout (s)
                <TooltipIcon name="EMBEDDING_TIMEOUT" />
              </label>
              <input
                type="number"
                value={embeddingTimeout}
                onChange={(e) => set('EMBEDDING_TIMEOUT', parseInt(e.target.value) || 30)}
                min={5}
                max={120}
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '6px',
                  color: 'var(--fg)',
                  fontSize: '13px'
                }}
              />
            </div>
          </div>
          <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px' }}>
            <div className="input-group">
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                Max Retries
                <TooltipIcon name="EMBEDDING_RETRY_MAX" />
              </label>
              <input
                type="number"
                value={embeddingRetryMax}
                onChange={(e) => set('EMBEDDING_RETRY_MAX', parseInt(e.target.value) || 3)}
                min={0}
                max={10}
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '6px',
                  color: 'var(--fg)',
                  fontSize: '13px'
                }}
              />
            </div>
            <div className="input-group">
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                Max File Size (MB)
                <TooltipIcon name="MAX_INDEXABLE_FILE_SIZE" />
              </label>
              <input
                type="number"
                value={Math.round(maxIndexableFileSize / 1000000)}
                onChange={(e) => set('MAX_INDEXABLE_FILE_SIZE', (parseFloat(e.target.value) || 2) * 1000000)}
                min={0.01}
                max={10}
                step={0.1}
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '6px',
                  color: 'var(--fg)',
                  fontSize: '13px'
                }}
              />
            </div>
            <div className="input-group">
              <label style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                cursor: 'pointer',
                marginTop: '28px'
              }}>
                <input
                  type="checkbox"
                  checked={embeddingCacheEnabled === 1}
                  onChange={(e) => set('EMBEDDING_CACHE_ENABLED', e.target.checked ? 1 : 0)}
                />
                <span style={{ fontSize: '13px' }}>Enable Cache</span>
                <TooltipIcon name="EMBEDDING_CACHE_ENABLED" />
              </label>
            </div>
          </div>

          {/* Vocab Preview Panel */}
          <details
            open={vocabExpanded}
            onToggle={(e) => setVocabExpanded((e.target as HTMLDetailsElement).open)}
            style={{ marginTop: '20px' }}
          >
            <summary style={{
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: 600,
              color: 'var(--fg)',
              padding: '8px 0',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              🔍 Vocabulary Preview
              <TooltipIcon name="BM25_VOCAB_PREVIEW" />
            </summary>

            <div style={{
              marginTop: '12px',
              padding: '16px',
              background: 'var(--bg-elev2)',
              borderRadius: '8px',
              border: '1px solid var(--line)'
            }}>
              {/* Controls */}
              <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '12px' }}>
                <label style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
                  Top N:
                  <input
                    type="number"
                    value={vocabTopN}
                    onChange={(e) => setVocabTopN(Math.max(10, Math.min(500, parseInt(e.target.value) || 50)))}
                    min={10}
                    max={500}
                    style={{
                      width: '70px',
                      marginLeft: '8px',
                      padding: '4px 8px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '4px',
                      color: 'var(--fg)',
                      fontSize: '12px'
                    }}
                  />
                </label>
                <button
                  onClick={loadVocabPreview}
                  disabled={vocabLoading}
                  style={{
                    padding: '6px 12px',
                    fontSize: '12px',
                    background: 'var(--accent)',
                    color: '#000',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: vocabLoading ? 'wait' : 'pointer',
                    opacity: vocabLoading ? 0.7 : 1
                  }}
                >
                  {vocabLoading ? 'Loading...' : 'Load Vocabulary'}
                </button>
              </div>

              {/* Vocab Grid */}
              {vocabPreview.length > 0 ? (
                <>
                  <div style={{
                    maxHeight: '280px',
                    overflowY: 'auto',
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
                    gap: '4px',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '11px'
                  }}>
                    {vocabPreview.map((item, idx) => (
                      <div
                        key={`${item.term}-${idx}`}
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          padding: '4px 8px',
                          background: 'var(--bg)',
                          borderRadius: '4px'
                        }}
                      >
                        <span style={{ color: 'var(--fg)', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {item.term}
                        </span>
                        <span style={{ color: 'var(--fg-muted)', marginLeft: '8px' }}>
                          {item.doc_count}
                        </span>
                      </div>
                    ))}
                  </div>
                  <div style={{
                    marginTop: '8px',
                    fontSize: '11px',
                    color: 'var(--fg-muted)',
                    display: 'flex',
                    justifyContent: 'space-between'
                  }}>
                    <span>Tokenizer: {bm25Tokenizer}</span>
                    <span>Showing {vocabPreview.length} of {vocabTotal} terms</span>
                  </div>
                </>
              ) : (
                <div style={{ fontSize: '12px', color: 'var(--fg-muted)', textAlign: 'center', padding: '20px' }}>
                  Click "Load Vocabulary" to inspect tokenized terms
                </div>
              )}
            </div>
          </details>
        </div>
      </details>

      {/* Index Stats Panel */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        marginBottom: '24px'
      }}>
        <button
          onClick={() => setStatsExpanded(!statsExpanded)}
          style={{
            width: '100%',
            padding: '16px',
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '16px' }}>📊</span>
            <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--fg)' }}>Index Stats</span>
            <button
              onClick={(e) => { e.stopPropagation(); loadStats(); }}
              style={{
                padding: '4px 8px',
                fontSize: '11px',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg-muted)',
                cursor: 'pointer'
              }}
            >
              ↻ Refresh
            </button>
          </div>
          <span style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
            {statsExpanded ? '▼' : '▶'}
          </span>
        </button>

        {statsExpanded && indexStats && (
          <div style={{ padding: '0 16px 16px' }}>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
              gap: '12px'
            }}>
              {[
                { label: 'Total Storage', value: formatBytes(indexStats.total_storage || 0), icon: '💾' },
                { label: 'Qdrant Vectors', value: formatBytes(indexStats.qdrant_size || 0), icon: '🔷' },
                { label: 'BM25 Index', value: formatBytes(indexStats.bm25_index_size || 0), icon: '📑' },
                { label: 'Chunks JSON', value: formatBytes(indexStats.chunks_json_size || 0), icon: '📦' },
                { label: 'Keywords', value: String(indexStats.keyword_count || 0), icon: '🔑' },
                { label: 'Repos Indexed', value: String(indexStats.profile_count || 0), icon: '📁' },
              ].map(item => (
                <div key={item.label} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '10px',
                  background: 'var(--bg)',
                  borderRadius: '8px',
                  border: '1px solid var(--line)'
                }}>
                  <span style={{ fontSize: '20px' }}>{item.icon}</span>
                  <div>
                    <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--fg)' }}>{item.value}</div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>{item.label}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Action Panel */}
      <div style={{
        background: 'linear-gradient(135deg, var(--bg) 0%, var(--bg-elev1) 100%)',
        border: '1px solid var(--line)',
        borderRadius: '12px',
        padding: '20px',
        marginBottom: '24px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: isIndexing ? '16px' : 0 }}>
          {isIndexing ? (
            <>
              <button
                onClick={handleStopIndex}
                style={{
                  padding: '12px 24px',
                  fontSize: '14px',
                  fontWeight: 600,
                  background: 'var(--error)',
                  color: 'white',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)'
                }}
              >
                Stop Indexing
              </button>
              <div style={{ flex: 1 }}>
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  marginBottom: '6px',
                  fontSize: '12px'
                }}>
                  <span style={{ color: 'var(--fg)' }}>{progress.status}</span>
                  <span style={{ color: 'var(--accent)', fontWeight: 600 }}>{progress.current}%</span>
                </div>
                <div style={{
                  height: '6px',
                  background: 'var(--line)',
                  borderRadius: '3px',
                  overflow: 'hidden'
                }}>
                  <div style={{
                    width: `${progress.current}%`,
                    height: '100%',
                    background: 'linear-gradient(90deg, var(--accent), var(--link))',
                    borderRadius: '3px',
                    transition: 'width 0.3s ease'
                  }} />
                </div>
              </div>
            </>
          ) : (
            <>
              <button
                onClick={handleStartIndex}
                disabled={!canIndex}
                style={{
                  padding: '12px 32px',
                  fontSize: '14px',
                  fontWeight: 600,
                  background: canIndex ? 'var(--accent)' : 'var(--bg-elev2)',
                  color: canIndex ? '#000' : 'var(--fg-muted)',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: canIndex ? 'pointer' : 'not-allowed',
                  transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}
              >
                <span>🚀</span>
                Index Now
              </button>
              {terminalVisible && (
                <button
                  onClick={() => setTerminalVisible(false)}
                  style={{
                    padding: '10px 14px',
                    background: 'var(--bg-elev2)',
                    color: 'var(--fg-muted)',
                    border: '1px solid var(--line)',
                    borderRadius: '8px',
                    fontSize: '13px',
                    cursor: 'pointer'
                  }}
                >
                  ✕ Hide Logs
                </button>
              )}
            </>
          )}
        </div>

        {/* Live Terminal - slides down */}
        <div style={{
          maxHeight: terminalVisible ? '400px' : '0',
          opacity: terminalVisible ? 1 : 0,
          overflow: 'hidden',
          transition: 'max-height 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease',
          marginTop: terminalVisible ? '16px' : '0'
        }}>
          <LiveTerminal
            ref={terminalRef}
            id="indexing_terminal"
            title="Indexing Output"
            initialContent={['Ready for indexing...']}
          />
        </div>
      </div>
    </div>
  );
}
