/**
 * IndexingSubtab (TriBrid) — Restored production-quality layout.
 *
 * Goal:
 * - Keep the *layout* and UX patterns from the legacy IndexingSubtab (cards, panels, advanced details, slide-down terminal)
 * - Wire everything to TriBridConfig (Pydantic is the law) and corpus-first state (useRepoStore)
 * - No hardcoded model lists (load from /api/models)
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAPI, useConfig, useConfigField } from '@/hooks';
import { useRepoStore } from '@/stores/useRepoStore';
import { LiveTerminal, type LiveTerminalHandle } from '@/components/LiveTerminal/LiveTerminal';
import { TerminalService } from '@/services/TerminalService';
import { RepositoryConfig } from '@/components/RAG/RepositoryConfig';
import { EmbeddingMismatchWarning } from '@/components/ui/EmbeddingMismatchWarning';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { indexingApi } from '@/api';
import { formatBytes, formatCurrency, formatDuration, formatNumber } from '@/utils/formatters';
import type { IndexEstimate, IndexRequest, IndexStats, IndexStatus, VocabPreviewResponse, VocabPreviewTerm } from '@/types/generated';
import { describeEmbeddingProviderStrategy } from '@/utils/embeddingStrategy';

type IndexingComponent = 'embedding' | 'chunking' | 'bm25' | 'enrichment';

const COMPONENT_CARDS: Array<{
  id: IndexingComponent;
  icon: string;
  label: string;
  description: string;
}> = [
  { id: 'embedding', icon: '🔢', label: 'Embedding', description: 'Provider, model, dimensions, batching' },
  { id: 'chunking', icon: '🧩', label: 'Chunking', description: 'Strategy, size, overlap, limits' },
  { id: 'bm25', icon: '📝', label: 'Tokenization', description: 'Chunk tokenizer + Postgres FTS tokenizer + large-file mode' },
  { id: 'enrichment', icon: '🧠', label: 'Graph & Options', description: 'Graph build + dense skip mode' },
];

const CHUNKING_STRATEGIES = [
  { id: 'fixed_tokens', label: 'Fixed tokens', description: 'Token-window chunking (best default for text corpora)' },
  { id: 'recursive', label: 'Recursive', description: 'Separator-based chunking packed by token target (docs/transcripts)' },
  { id: 'markdown', label: 'Markdown', description: 'Split by headings then pack by tokens (docs/notes)' },
  { id: 'sentence', label: 'Sentence', description: 'Sentence boundaries packed by tokens (prose)' },
  { id: 'qa_blocks', label: 'Q/A blocks', description: 'Detect Q:/A: blocks then pack by tokens (interviews/dumps)' },
  { id: 'fixed_chars', label: 'Fixed chars', description: 'Character windowing with overlap (fallback, legacy)' },
  { id: 'ast', label: 'AST-aware', description: 'Preserve functions/blocks (best for code)' },
  { id: 'hybrid', label: 'Hybrid', description: 'AST with fallback behavior' },
];

export function IndexingSubtab() {
  const { api } = useAPI();
  const { config } = useConfig();
  const { activeRepo, repos, loadRepos, setActiveRepo } = useRepoStore();

  // Terminal ref (slide-down UI)
  const terminalRef = useRef<LiveTerminalHandle>(null);

  // UI state
  const [selectedComponent, setSelectedComponent] = useState<IndexingComponent>('embedding');
  const [isIndexing, setIsIndexing] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 100, status: 'Ready' });
  const [terminalVisible, setTerminalVisible] = useState(false);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const [indexEstimate, setIndexEstimate] = useState<IndexEstimate | null>(null);
  const [estimateLoading, setEstimateLoading] = useState(false);

  // Job options
  const [forceReindex, setForceReindex] = useState(false);
  const [pathOverride, setPathOverride] = useState('');

  // Config fields (TriBridConfig-backed)
  const [embeddingType, setEmbeddingType] = useConfigField<string>('embedding.embedding_type', '');
  const [embeddingModel, setEmbeddingModel] = useConfigField<string>('embedding.embedding_model', '');
  const [voyageModel, setVoyageModel] = useConfigField<string>('embedding.voyage_model', '');
  const [embeddingModelLocal, setEmbeddingModelLocal] = useConfigField<string>('embedding.embedding_model_local', '');
  const [embeddingDim, setEmbeddingDim] = useConfigField<number>('embedding.embedding_dim', 0);
  const [embeddingBatchSize, setEmbeddingBatchSize] = useConfigField<number>('embedding.embedding_batch_size', 0);
  const [embeddingMaxTokens, setEmbeddingMaxTokens] = useConfigField<number>('embedding.embedding_max_tokens', 0);
  const [embeddingCacheEnabled, setEmbeddingCacheEnabled] = useConfigField<number>('embedding.embedding_cache_enabled', 1);
  const [embeddingTimeout, setEmbeddingTimeout] = useConfigField<number>('embedding.embedding_timeout', 0);
  const [embeddingRetryMax, setEmbeddingRetryMax] = useConfigField<number>('embedding.embedding_retry_max', 0);
  const [embeddingBackend, setEmbeddingBackend] =
    useConfigField<'deterministic' | 'provider'>('embedding.embedding_backend', 'deterministic');
  const [autoSetDimensions, setAutoSetDimensions] =
    useConfigField<boolean>('embedding.auto_set_dimensions', true);
  const [embeddingInputTruncation, setEmbeddingInputTruncation] =
    useConfigField<'error' | 'truncate_end' | 'truncate_middle'>('embedding.input_truncation', 'truncate_end');
  const [embedTextPrefix, setEmbedTextPrefix] = useConfigField<string>('embedding.embed_text_prefix', '');
  const [embedTextSuffix, setEmbedTextSuffix] = useConfigField<string>('embedding.embed_text_suffix', '');
  const [contextualChunkEmbeddings, setContextualChunkEmbeddings] =
    useConfigField<'off' | 'prepend_context' | 'late_chunking_local_only'>(
      'embedding.contextual_chunk_embeddings',
      'off'
    );
  const [lateChunkingMaxDocTokens, setLateChunkingMaxDocTokens] =
    useConfigField<number>('embedding.late_chunking_max_doc_tokens', 8192);
  void embeddingBackend;
  void setEmbeddingBackend;
  void setAutoSetDimensions;
  void embeddingInputTruncation;
  void setEmbeddingInputTruncation;
  void embedTextPrefix;
  void setEmbedTextPrefix;
  void embedTextSuffix;
  void setEmbedTextSuffix;
  void contextualChunkEmbeddings;
  void setContextualChunkEmbeddings;
  void lateChunkingMaxDocTokens;
  void setLateChunkingMaxDocTokens;

  const [chunkSize, setChunkSize] = useConfigField<number>('chunking.chunk_size', 0);
  const [chunkOverlap, setChunkOverlap] = useConfigField<number>('chunking.chunk_overlap', 0);
  const [chunkingStrategy, setChunkingStrategy] = useConfigField<string>('chunking.chunking_strategy', '');
  const [astOverlapLines, setAstOverlapLines] = useConfigField<number>('chunking.ast_overlap_lines', 0);
  const [maxChunkTokens, setMaxChunkTokens] = useConfigField<number>('chunking.max_chunk_tokens', 0);
  const [maxIndexableFileSize, setMaxIndexableFileSize] = useConfigField<number>('chunking.max_indexable_file_size', 0);
  const [minChunkChars, setMinChunkChars] = useConfigField<number>('chunking.min_chunk_chars', 0);
  const [greedyFallbackTarget, setGreedyFallbackTarget] = useConfigField<number>('chunking.greedy_fallback_target', 0);
  const [preserveImports, setPreserveImports] = useConfigField<number>('chunking.preserve_imports', 1);
  const [targetTokens, setTargetTokens] = useConfigField<number>('chunking.target_tokens', 512);
  const [overlapTokens, setOverlapTokens] = useConfigField<number>('chunking.overlap_tokens', 64);
  const [separators, setSeparators] = useConfigField<string[]>('chunking.separators', ['\n\n', '\n', '. ', ' ', '']);
  const [separatorKeep, setSeparatorKeep] = useConfigField<'none' | 'prefix' | 'suffix'>('chunking.separator_keep', 'suffix');
  const [recursiveMaxDepth, setRecursiveMaxDepth] = useConfigField<number>('chunking.recursive_max_depth', 10);
  const [markdownMaxHeadingLevel, setMarkdownMaxHeadingLevel] = useConfigField<number>('chunking.markdown_max_heading_level', 4);
  const [markdownIncludeCodeFences, setMarkdownIncludeCodeFences] = useConfigField<boolean>(
    'chunking.markdown_include_code_fences',
    true
  );
  const [emitChunkOrdinal, setEmitChunkOrdinal] = useConfigField<boolean>('chunking.emit_chunk_ordinal', true);
  const [emitParentDocId, setEmitParentDocId] = useConfigField<boolean>('chunking.emit_parent_doc_id', true);

  const [tokenizationStrategy, setTokenizationStrategy] = useConfigField<string>('tokenization.strategy', 'tiktoken');
  const [tiktokenEncoding, setTiktokenEncoding] = useConfigField<string>('tokenization.tiktoken_encoding', 'o200k_base');
  const [hfTokenizerName, setHfTokenizerName] = useConfigField<string>('tokenization.hf_tokenizer_name', 'gpt2');
  const [normalizeUnicode, setNormalizeUnicode] = useConfigField<boolean>('tokenization.normalize_unicode', true);
  const [lowercaseTokenizer, setLowercaseTokenizer] = useConfigField<boolean>('tokenization.lowercase', false);
  const [maxTokensPerChunkHard, setMaxTokensPerChunkHard] = useConfigField<number>(
    'tokenization.max_tokens_per_chunk_hard',
    8192
  );
  const [tokenEstimateOnly, setTokenEstimateOnly] = useConfigField<boolean>('tokenization.estimate_only', false);

  const [bm25Tokenizer, setBm25Tokenizer] = useConfigField<string>('indexing.bm25_tokenizer', '');
  const [bm25StemmerLang, setBm25StemmerLang] = useConfigField<string>('indexing.bm25_stemmer_lang', '');
  const [bm25StopwordsLang, setBm25StopwordsLang] = useConfigField<string>('indexing.bm25_stopwords_lang', '');
  const [indexMaxFileSizeMb, setIndexMaxFileSizeMb] = useConfigField<number>('indexing.index_max_file_size_mb', 250);
  const [largeFileMode, setLargeFileMode] = useConfigField<'read_all' | 'stream'>('indexing.large_file_mode', 'stream');
  const [largeFileStreamChunkChars, setLargeFileStreamChunkChars] = useConfigField<number>(
    'indexing.large_file_stream_chunk_chars',
    2_000_000
  );

  const [parquetExtractMaxRows, setParquetExtractMaxRows] = useConfigField<number>('indexing.parquet_extract_max_rows', 5000);
  const [parquetExtractMaxChars, setParquetExtractMaxChars] = useConfigField<number>(
    'indexing.parquet_extract_max_chars',
    2_000_000
  );
  const [parquetExtractMaxCellChars, setParquetExtractMaxCellChars] = useConfigField<number>(
    'indexing.parquet_extract_max_cell_chars',
    20_000
  );
  const [parquetExtractTextColumnsOnly, setParquetExtractTextColumnsOnly] = useConfigField<number>(
    'indexing.parquet_extract_text_columns_only',
    1
  );
  const [parquetExtractIncludeColumnNames, setParquetExtractIncludeColumnNames] = useConfigField<number>(
    'indexing.parquet_extract_include_column_names',
    1
  );

  const [skipDense, setSkipDense] = useConfigField<number>('indexing.skip_dense', 0);
  const [graphIndexingEnabled, setGraphIndexingEnabled] = useConfigField<boolean>('graph_indexing.enabled', true);
  const [lexicalGraphEnabled, setLexicalGraphEnabled] = useConfigField<boolean>('graph_indexing.build_lexical_graph', true);
  const [storeChunkEmbeddings, setStoreChunkEmbeddings] = useConfigField<boolean>('graph_indexing.store_chunk_embeddings', true);
  const [semanticKgEnabled, setSemanticKgEnabled] = useConfigField<boolean>('graph_indexing.semantic_kg_enabled', false);
  const [semanticKgMode, setSemanticKgMode] = useConfigField<'heuristic' | 'llm'>('graph_indexing.semantic_kg_mode', 'heuristic');
  const [semanticKgMaxChunks, setSemanticKgMaxChunks] = useConfigField<number>('graph_indexing.semantic_kg_max_chunks', 200);
  const [semanticKgMaxConcepts, setSemanticKgMaxConcepts] = useConfigField<number>(
    'graph_indexing.semantic_kg_max_concepts_per_chunk',
    8
  );

  // Models (from /api/models, no hardcoded lists)
  const [embedModels, setEmbedModels] = useState<any[]>([]);
  const [embedProviders, setEmbedProviders] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);

  // Index stats + status
  const [_indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [indexStats, setIndexStats] = useState<IndexStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsExpanded, setStatsExpanded] = useState(false);

  // Vocab preview state
  const [vocabPreview, setVocabPreview] = useState<VocabPreviewTerm[]>([]);
  const [vocabLoading, setVocabLoading] = useState(false);
  const [vocabTopN, setVocabTopN] = useState(50);
  const [vocabTotal, setVocabTotal] = useState(0);
  const [vocabExpanded, setVocabExpanded] = useState(false);

  // Ensure corpora loaded
  useEffect(() => {
    if (!repos.length) {
      void loadRepos();
    }
  }, [repos.length, loadRepos]);

  // Resolve selected corpus path from store
  const activeCorpus = useMemo(() => {
    const id = (activeRepo || '').trim();
    if (!id) return undefined;
    return repos.find(r => r.corpus_id === id || r.slug === id || r.name === id);
  }, [activeRepo, repos]);

  const resolvedPath = useMemo(() => String(activeCorpus?.path || ''), [activeCorpus]);
  const effectivePath = useMemo(() => (pathOverride.trim() ? pathOverride.trim() : resolvedPath), [pathOverride, resolvedPath]);

  useEffect(() => {
    setIndexEstimate(null);
  }, [activeRepo, effectivePath]);

  // Derived model field (based on provider)
  const currentModel = useMemo(() => {
    const t = String(embeddingType || '').toLowerCase();
    if (t === 'voyage') return String(voyageModel || '');
    if (t === 'openai') return String(embeddingModel || '');
    return String(embeddingModelLocal || '');
  }, [embeddingType, embeddingModel, embeddingModelLocal, voyageModel]);

  const setCurrentModel = useCallback((modelName: string) => {
    const t = String(embeddingType || '').toLowerCase();
    if (t === 'voyage') {
      setVoyageModel(modelName);
      return;
    }
    if (t === 'openai') {
      setEmbeddingModel(modelName);
      return;
    }
    setEmbeddingModelLocal(modelName);
  }, [embeddingType, setEmbeddingModel, setEmbeddingModelLocal, setVoyageModel]);

  // Models loading (EMB only)
  useEffect(() => {
    (async () => {
      setModelsLoading(true);
      setModelsError(null);
      try {
        const r = await fetch(api('/api/models/by-type/EMB'));
        if (!r.ok) throw new Error(`Failed to load embedding models (${r.status})`);
        const data = await r.json();
        const list = Array.isArray(data) ? data : [];
        setEmbedModels(list);
        const providers = Array.from(
          new Set(
            list
              .map((m: any) => String(m?.provider || '').trim())
              .filter(Boolean)
          )
        ).sort((a, b) => a.localeCompare(b));
        setEmbedProviders(providers);
      } catch (e) {
        setModelsError(e instanceof Error ? e.message : 'Failed to load models');
        setEmbedModels([]);
        setEmbedProviders([]);
      } finally {
        setModelsLoading(false);
      }
    })();
  }, [api]);

  // Provider-specific embedding model list
  const providerEmbedModels = useMemo(() => {
    const p = String(embeddingType || '').toLowerCase();
    if (!p) return [];
    return embedModels
      .filter((m: any) => String(m?.provider || '').toLowerCase() === p)
      .map((m: any) => ({
        model: String(m?.model || ''),
        dimensions: typeof m?.dimensions === 'number' ? m.dimensions : null,
      }))
      .filter((m: any) => Boolean(m.model));
  }, [embedModels, embeddingType]);

  // If provider changes and current model isn't valid, auto-select first model (from models.json only)
  useEffect(() => {
    if (!providerEmbedModels.length) return;
    const existing = String(currentModel || '').trim();
    if (existing && providerEmbedModels.some(m => m.model === existing)) return;
    setCurrentModel(providerEmbedModels[0].model);
  }, [currentModel, providerEmbedModels, setCurrentModel]);

  // If selected model has known dimensions, keep embedding_dim aligned (no hardcoded dims)
  useEffect(() => {
    const hit = providerEmbedModels.find(m => m.model === currentModel);
    const dims = hit?.dimensions;
    if (autoSetDimensions && typeof dims === 'number' && dims > 0 && embeddingDim !== dims) {
      setEmbeddingDim(dims);
    }
  }, [autoSetDimensions, currentModel, embeddingDim, providerEmbedModels, setEmbeddingDim]);

  // Resolved tokenizer description (UX-only helper)
  const resolvedTokenizerDesc = useMemo(() => {
    const tok = String(bm25Tokenizer || '').toLowerCase();
    if (!tok) return '—';
    if (tok === 'stemmer') {
      const lang = bm25StemmerLang || '—';
      const sw = bm25StopwordsLang || '—';
      return `Stemmer (${lang}) with ${sw} stopwords`;
    }
    if (tok === 'whitespace') return 'Whitespace-ish (no stemming)';
    if (tok === 'lowercase') return 'Lowercase (no stemming)';
    return tok;
  }, [bm25Tokenizer, bm25StemmerLang, bm25StopwordsLang]);

  const chunkingStrategyNorm = useMemo(() => String(chunkingStrategy || '').trim().toLowerCase(), [chunkingStrategy]);
  const usesTokenChunking = useMemo(
    () => ['fixed_tokens', 'recursive', 'markdown', 'sentence', 'qa_blocks'].includes(chunkingStrategyNorm),
    [chunkingStrategyNorm]
  );

  const separatorsText = useMemo(() => {
    const list = Array.isArray(separators) ? separators : [];
    // Display escaped newlines so users can edit safely.
    return list.map((s) => String(s ?? '').replace(/\n/g, '\\n')).join('\n');
  }, [separators]);

  const updateSeparatorsFromText = useCallback(
    (raw: string) => {
      const lines = String(raw || '')
        .split('\n')
        .map((l) => l.trimEnd());
      const parsed = lines.map((l) => l.replace(/\\n/g, '\n'));
      setSeparators(parsed);
    },
    [setSeparators]
  );

  const canIndex = useMemo(() => {
    const rid = String(activeRepo || '').trim();
    const pathOk = Boolean(effectivePath && effectivePath.trim());
    return Boolean(rid && pathOk && !isIndexing);
  }, [activeRepo, effectivePath, isIndexing]);

  const refreshStatus = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid) return;
    try {
      const r = await fetch(api(`index/${encodeURIComponent(rid)}/status`));
      if (!r.ok) return;
      const data: IndexStatus = await r.json();
      setIndexStatus(data);
    } catch {
      // ignore
    }
  }, [activeRepo, api]);

  const loadStats = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid) return;
    setStatsLoading(true);
    try {
      const r = await fetch(api(`index/${encodeURIComponent(rid)}/stats`));
      if (!r.ok) {
        setIndexStats(null);
        return;
      }
      const data: IndexStats = await r.json();
      setIndexStats(data);
    } catch {
      setIndexStats(null);
    } finally {
      setStatsLoading(false);
    }
  }, [activeRepo, api]);

  useEffect(() => {
    void refreshStatus();
    void loadStats();
  }, [refreshStatus, loadStats]);

  const resetTerminal = useCallback((title: string) => {
    const t = terminalRef.current;
    t?.show();
    t?.clear();
    t?.setTitle(title);
  }, []);

  const startStream = useCallback(() => {
    const rid = String(activeRepo || '').trim();
    if (!rid) return;
    TerminalService.connectToStream('indexing_terminal', `operations/index?corpus_id=${encodeURIComponent(rid)}`, {
      onLine: (line) => terminalRef.current?.appendLine(line),
      onProgress: (percent, message) => {
        setProgress({ current: percent, total: 100, status: message || `Progress: ${percent}%` });
        terminalRef.current?.updateProgress(percent, message);
      },
      onError: (err) => {
        terminalRef.current?.appendLine(`\x1b[31mERROR: ${err}\x1b[0m`);
        setProgress(prev => ({ ...prev, status: `Error: ${err}` }));
        setIsIndexing(false);
      },
      onComplete: () => {
        terminalRef.current?.updateProgress(100, 'Complete');
        terminalRef.current?.appendLine(`\x1b[32m✓ Indexing complete!\x1b[0m`);
        setProgress({ current: 100, total: 100, status: 'Complete' });
        setIsIndexing(false);
        void loadStats();
        void refreshStatus();
      },
    });
  }, [activeRepo, loadStats, refreshStatus]);

  const handleStopIndex = useCallback(() => {
    TerminalService.disconnect('indexing_terminal');
    setIsIndexing(false);
    setProgress(prev => ({ ...prev, status: 'Stopped' }));
    terminalRef.current?.appendLine(`\x1b[33m⚠ Indexing stopped by user\x1b[0m`);
  }, []);

  const handleStartIndex = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid) return;
    if (!effectivePath.trim()) return;

    try {
      const body: IndexRequest = {
        corpus_id: rid,
        repo_path: effectivePath,
        force_reindex: Boolean(forceReindex),
      };

      setErrorBanner(null);
      setEstimateLoading(true);
      let estimate: IndexEstimate | null = null;
      try {
        estimate = await indexingApi.estimate(body);
        setIndexEstimate(estimate);
      } catch (e) {
        estimate = null;
        // Estimate failures should never block indexing; keep it best-effort.
        terminalRef.current?.appendLine?.(
          `\x1b[33m⚠ Index estimate unavailable: ${e instanceof Error ? e.message : 'unknown error'}\x1b[0m`
        );
      } finally {
        setEstimateLoading(false);
      }

      if (estimate) {
        const cost =
          estimate.embedding_cost_usd == null ? 'N/A' : formatCurrency(Number(estimate.embedding_cost_usd || 0));
        const time =
          estimate.estimated_seconds_low != null && estimate.estimated_seconds_high != null
            ? `${formatDuration(Number(estimate.estimated_seconds_low) * 1000)}–${formatDuration(
                Number(estimate.estimated_seconds_high) * 1000
              )}`
            : 'N/A';
        const msg = [
          `Index estimate for "${rid}"`,
          `Files: ${formatNumber(Number(estimate.total_files || 0))} • Size: ${formatBytes(
            Number(estimate.total_size_bytes || 0)
          )}`,
          `Tokens (est): ${formatNumber(Number(estimate.estimated_total_tokens || 0))} • Chunks (est): ${formatNumber(
            Number(estimate.estimated_total_chunks || 0)
          )}`,
          `Embedding: ${String(estimate.embedding_provider || '—')}/${String(estimate.embedding_model || '—')} (${
            estimate.embedding_backend
          }, skip_dense=${estimate.skip_dense ? 'yes' : 'no'})`,
          `Cost (est): ${cost} • Time (est): ${time}`,
          '',
          'Start indexing now?',
        ].join('\n');

        if (!window.confirm(msg)) {
          return;
        }
      }

      setIsIndexing(true);
      setProgress({ current: 0, total: 100, status: 'Starting...' });
      setTerminalVisible(true);
      resetTerminal(`Indexing: ${rid}`);

      terminalRef.current?.appendLine(`🚀 Starting indexing for ${rid}`);
      terminalRef.current?.appendLine(`   Provider: ${String(embeddingType || '')}, Model: ${String(currentModel || '')}`);
      terminalRef.current?.appendLine(`   Chunk Size: ${chunkSize}, Strategy: ${chunkingStrategy}`);
      terminalRef.current?.appendLine(`   Graph indexing: ${graphIndexingEnabled ? 'enabled' : 'disabled'} • Skip dense: ${skipDense ? 'yes' : 'no'}`);

      const r = await fetch(api('index'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const text = await r.text().catch(() => '');
        throw new Error(text || `Index request failed (${r.status})`);
      }
      const st: IndexStatus = await r.json();
      setIndexStatus(st);

      // Start streaming logs/progress immediately after kickoff
      startStream();
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Indexing failed';
      setErrorBanner(msg);
      terminalRef.current?.appendLine(`\x1b[31mFailed: ${msg}\x1b[0m`);
      setIsIndexing(false);
    }
  }, [
    activeRepo,
    api,
    chunkSize,
    chunkingStrategy,
    currentModel,
    effectivePath,
    embeddingType,
    forceReindex,
    graphIndexingEnabled,
    resetTerminal,
    skipDense,
    startStream,
  ]);

  const handleDeleteIndex = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid) return;
    if (!confirm(`Delete index for corpus "${rid}"?`)) return;

    setErrorBanner(null);
    setIsIndexing(false);
    setProgress({ current: 0, total: 100, status: 'Deleting...' });
    try {
      const r = await fetch(api(`index/${encodeURIComponent(rid)}`), { method: 'DELETE' });
      if (!r.ok) {
        const text = await r.text().catch(() => '');
        throw new Error(text || `Delete failed (${r.status})`);
      }
      setIndexStats(null);
      setIndexStatus(null);
      await loadStats();
      await refreshStatus();
    } catch (e) {
      setErrorBanner(e instanceof Error ? e.message : 'Delete failed');
    }
  }, [activeRepo, api, loadStats, refreshStatus]);

  const loadVocabPreview = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid) return;
    setVocabLoading(true);
    try {
      const url = api(`/api/index/vocab-preview?corpus_id=${encodeURIComponent(rid)}&top_n=${encodeURIComponent(String(vocabTopN))}`);
      const r = await fetch(url);
      if (!r.ok) {
        const text = await r.text().catch(() => '');
        throw new Error(text || `Vocab preview failed (${r.status})`);
      }
      const data: VocabPreviewResponse = await r.json();
      setVocabPreview(Array.isArray(data.terms) ? data.terms : []);
      setVocabTotal(Number(data.total_terms || 0));
    } catch (e) {
      setVocabPreview([]);
      setVocabTotal(0);
      terminalRef.current?.appendLine?.(
        `\x1b[33m⚠ Vocabulary preview unavailable: ${e instanceof Error ? e.message : 'unknown error'}\x1b[0m`
      );
    } finally {
      setVocabLoading(false);
    }
  }, [activeRepo, api, vocabTopN]);

  // Avoid rendering “blank defaults” before config arrives
  if (!config) {
    return (
      <div className="subtab-panel" style={{ padding: '24px' }}>
        <div style={{ color: 'var(--fg-muted)' }}>Loading configuration…</div>
      </div>
    );
  }

  return (
    <div className="subtab-panel" style={{ padding: '24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '28px' }}>
        <h3
          style={{
            fontSize: '18px',
            fontWeight: 600,
            color: 'var(--fg)',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            marginBottom: '8px',
          }}
        >
          <span style={{ fontSize: '22px' }}>📦</span>
          Code Indexing
          <TooltipIcon name="INDEXING" />
        </h3>
        <p
          style={{
            fontSize: '14px',
            color: 'var(--fg-muted)',
            lineHeight: 1.6,
            maxWidth: '900px',
            margin: 0,
          }}
        >
          Configure embeddings, chunking, sparse tokenization, and graph build behavior. This is corpus-scoped.
        </p>
      </div>

      {errorBanner && (
        <div
          style={{
            background: 'rgba(var(--error-rgb), 0.1)',
            border: '1px solid var(--error)',
            borderRadius: '8px',
            padding: '12px 16px',
            marginBottom: '20px',
            color: 'var(--error)',
            fontSize: '13px',
          }}
        >
          {errorBanner}
        </div>
      )}

      {/* Embedding mismatch warning (critical) */}
      <EmbeddingMismatchWarning variant="inline" showActions />

      {/* Corpus selection + resolved path */}
      <div style={{ marginBottom: '24px' }}>
        <div style={{ display: 'flex', gap: '20px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: '240px', maxWidth: '480px' }}>
            <label
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                marginBottom: '8px',
                fontSize: '13px',
                fontWeight: 600,
                color: 'var(--fg)',
              }}
            >
              Target Corpus
              <TooltipIcon name="REPO" />
            </label>
            <select
              data-testid="target-corpus-select"
              value={activeRepo}
              onChange={(e) => void setActiveRepo(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 12px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '6px',
                color: 'var(--fg)',
                fontSize: '13px',
              }}
            >
              {!repos.length ? (
                <option value="">No corpora</option>
              ) : (
                repos.map((r) => (
                  <option key={r.corpus_id} value={r.corpus_id}>
                    {r.name || r.corpus_id}
                  </option>
                ))
              )}
            </select>
          </div>

          <div style={{ flex: 1, minWidth: '320px' }}>
            <label
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                marginBottom: '8px',
                fontSize: '13px',
                fontWeight: 600,
                color: 'var(--fg)',
              }}
            >
              Corpus path (auto-resolved; override optional)
              <TooltipIcon name="REPO_PATH" />
            </label>
            <input
              data-testid="corpus-path-override"
              value={pathOverride}
              onChange={(e) => setPathOverride(e.target.value)}
              placeholder={resolvedPath || '/absolute/path/to/corpus'}
              style={{
                width: '100%',
                padding: '10px 12px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '6px',
                color: 'var(--fg)',
                fontSize: '13px',
              }}
            />
            <div style={{ marginTop: '6px', fontSize: '11px', color: 'var(--fg-muted)' }}>
              Using: <span style={{ fontFamily: 'var(--font-mono)' }}>{effectivePath || '—'}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Corpus settings (stored in Postgres corpora.meta). */}
      <details style={{ marginBottom: '24px' }} data-testid="indexing-corpus-settings">
        <summary style={{ cursor: 'pointer', fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>
          ⚙️ Corpus settings (exclude paths, keywords, boosts)
        </summary>
        <div style={{ marginTop: '12px' }}>
          <RepositoryConfig />
        </div>
      </details>

      {/* Compatibility / mode callouts */}
      {skipDense === 1 && (
        <div
          style={{
            background: 'rgba(var(--warn-rgb), 0.1)',
            border: '1px solid var(--warn)',
            borderRadius: '8px',
            padding: '12px 16px',
            marginBottom: '20px',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '10px',
            fontSize: '12px',
            color: 'var(--fg)',
          }}
        >
          <span style={{ fontSize: '18px' }}>⚠️</span>
          <div>
            <div style={{ fontWeight: 700, color: 'var(--warn)', marginBottom: '4px' }}>
              Dense embeddings are disabled (Skip Dense)
            </div>
            <div style={{ color: 'var(--fg-muted)' }}>
              This enables graph-only / sparse-only workflows. Vector retrieval will not work until you re-index with dense enabled.
            </div>
          </div>
        </div>
      )}

      {/* Component cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: '16px',
          marginBottom: '24px',
        }}
      >
        {COMPONENT_CARDS.map((comp) => (
          <button
            key={comp.id}
            data-testid={`indexing-component-card-${comp.id}`}
            onClick={() => setSelectedComponent(comp.id)}
            style={{
              padding: '20px 16px',
              background:
                selectedComponent === comp.id
                  ? 'linear-gradient(135deg, rgba(var(--accent-rgb), 0.15), rgba(var(--accent-rgb), 0.05))'
                  : 'var(--card-bg)',
              border: selectedComponent === comp.id ? '2px solid var(--accent)' : '1px solid var(--line)',
              borderRadius: '12px',
              cursor: 'pointer',
              textAlign: 'left',
              transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            {selectedComponent === comp.id && (
              <div
                style={{
                  position: 'absolute',
                  top: '8px',
                  right: '8px',
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  background: 'var(--accent)',
                  boxShadow: '0 0 8px var(--accent)',
                }}
              />
            )}
            <div style={{ fontSize: '28px', marginBottom: '10px' }}>{comp.icon}</div>
            <div
              style={{
                fontSize: '14px',
                fontWeight: 600,
                color: selectedComponent === comp.id ? 'var(--accent)' : 'var(--fg)',
                marginBottom: '6px',
              }}
            >
              {comp.label}
            </div>
            <div style={{ fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.4 }}>{comp.description}</div>
          </button>
        ))}
      </div>

      {/* Dynamic config panel */}
      <div
        style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '12px',
          padding: '24px',
          marginBottom: '24px',
        }}
      >
        {/* EMBEDDING */}
        {selectedComponent === 'embedding' && (
          <div>
            <h4
              style={{
                fontSize: '14px',
                fontWeight: 600,
                color: 'var(--fg)',
                marginBottom: '16px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              🔢 Embedding Configuration
              <TooltipIcon name="EMBEDDING_TYPE" />
            </h4>

            {modelsError && (
              <div style={{ padding: '12px', borderRadius: '8px', border: '1px solid var(--warn)', marginBottom: '16px' }}>
                <div style={{ color: 'var(--warn)', fontWeight: 700, fontSize: '12px' }}>Model list unavailable</div>
                <div style={{ color: 'var(--fg-muted)', fontSize: '12px', marginTop: '4px' }}>{modelsError}</div>
              </div>
            )}

            {/* Provider cards */}
            {modelsLoading ? (
              <div style={{ padding: '20px', textAlign: 'center', color: 'var(--fg-muted)' }}>Loading providers…</div>
            ) : (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: `repeat(${Math.min(embedProviders.length || 1, 4)}, 1fr)`,
                  gap: '12px',
                  marginBottom: '20px',
                }}
              >
                {(embedProviders.length ? embedProviders : [String(embeddingType || '')]).filter(Boolean).map((provider) => (
                  <button
                    key={provider}
                    onClick={() => setEmbeddingType(String(provider).toLowerCase())}
                    style={{
                      padding: '12px',
                      background:
                        String(embeddingType || '').toLowerCase() === String(provider).toLowerCase()
                          ? 'rgba(var(--accent-rgb), 0.1)'
                          : 'var(--bg-elev2)',
                      border:
                        String(embeddingType || '').toLowerCase() === String(provider).toLowerCase()
                          ? '2px solid var(--accent)'
                          : '1px solid var(--line)',
                      borderRadius: '8px',
                      cursor: 'pointer',
                      textAlign: 'center',
                      transition: 'all 0.2s ease',
                    }}
                  >
                    {(() => {
                      const s = describeEmbeddingProviderStrategy(String(provider));
                      return (
                        <>
                    <div
                      style={{
                        fontSize: '12px',
                        fontWeight: 600,
                        color:
                          String(embeddingType || '').toLowerCase() === String(provider).toLowerCase()
                            ? 'var(--accent)'
                            : 'var(--fg)',
                      }}
                    >
                      {String(provider)}
                    </div>
                          <div style={{ fontSize: '10px', color: 'var(--fg-muted)', marginTop: '4px' }}>{s.detail}</div>
                        </>
                      );
                    })()}
                  </button>
                ))}
              </div>
            )}

            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginBottom: '20px' }}>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Backend
                  <TooltipIcon name="EMBEDDING_BACKEND" />
                </label>
                <select
                  data-testid="embedding-backend"
                  value={embeddingBackend}
                  onChange={(e) => setEmbeddingBackend(e.target.value as any)}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                  }}
                >
                  <option value="deterministic">deterministic (tests/offline)</option>
                  <option value="provider">provider (real embeddings)</option>
                </select>
              </div>
              <div className="input-group" style={{ display: 'flex', alignItems: 'center', gap: '10px', paddingTop: '28px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={autoSetDimensions}
                    onChange={(e) => setAutoSetDimensions(e.target.checked)}
                  />
                  <span style={{ fontSize: '13px', color: 'var(--fg)' }}>Auto-set dimensions</span>
                  <TooltipIcon name="EMBEDDING_AUTO_SET_DIMENSIONS" />
                </label>
              </div>
              <div className="input-group" />
            </div>

            {/* Model + dimensions */}
            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '20px' }}>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Model
                  <TooltipIcon name="EMBEDDING_MODEL" />
                </label>
                <select
                  value={currentModel}
                  onChange={(e) => setCurrentModel(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                  }}
                >
                  {providerEmbedModels.length ? (
                    providerEmbedModels.map((m) => (
                      <option key={m.model} value={m.model}>
                        {m.model}
                      </option>
                    ))
                  ) : (
                    <option value={currentModel}>{currentModel || 'No models found for provider'}</option>
                  )}
                </select>
              </div>

              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Dimensions
                  <TooltipIcon name="EMBEDDING_DIM" />
                </label>
                <input
                  type="number"
                  value={embeddingDim}
                  onChange={(e) => setEmbeddingDim(parseInt(e.target.value || '0', 10))}
                  min={128}
                  max={4096}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                  }}
                />
              </div>

              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Batch size
                  <TooltipIcon name="EMBEDDING_BATCH_SIZE" />
                </label>
                <input
                  type="number"
                  value={embeddingBatchSize}
                  onChange={(e) => setEmbeddingBatchSize(parseInt(e.target.value || '0', 10))}
                  min={1}
                  max={256}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                  }}
                />
              </div>
            </div>

            <details style={{ marginTop: '18px' }}>
              <summary style={{ cursor: 'pointer', fontSize: '13px', fontWeight: 600, color: 'var(--fg)' }}>
                Advanced embedding settings
              </summary>
              <div style={{ marginTop: '12px' }}>
                <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginBottom: '16px' }}>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Input truncation
                      <TooltipIcon name="EMBEDDING_INPUT_TRUNCATION" />
                    </label>
                    <select
                      data-testid="embedding-input-truncation"
                      value={embeddingInputTruncation}
                      onChange={(e) => setEmbeddingInputTruncation(e.target.value as any)}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                      }}
                    >
                      <option value="truncate_end">truncate_end</option>
                      <option value="truncate_middle">truncate_middle</option>
                      <option value="error">error</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Text prefix
                      <TooltipIcon name="EMBEDDING_TEXT_PREFIX" />
                    </label>
                    <input
                      data-testid="embedding-text-prefix"
                      type="text"
                      value={embedTextPrefix}
                      onChange={(e) => setEmbedTextPrefix(e.target.value)}
                      placeholder=""
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Text suffix
                      <TooltipIcon name="EMBEDDING_TEXT_SUFFIX" />
                    </label>
                    <input
                      data-testid="embedding-text-suffix"
                      type="text"
                      value={embedTextSuffix}
                      onChange={(e) => setEmbedTextSuffix(e.target.value)}
                      placeholder=""
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                      }}
                    />
                  </div>
                </div>

                <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginBottom: '16px' }}>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Contextual embeddings
                      <TooltipIcon name="EMBEDDING_CONTEXTUAL_CHUNK_EMBEDDINGS" />
                    </label>
                    <select
                      data-testid="embedding-contextual-chunk-embeddings"
                      value={contextualChunkEmbeddings}
                      onChange={(e) => setContextualChunkEmbeddings(e.target.value as any)}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                      }}
                    >
                      <option value="off">off</option>
                      <option value="prepend_context">prepend_context</option>
                      <option value="late_chunking_local_only">late_chunking_local_only (local only)</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Late chunking max doc tokens
                      <TooltipIcon name="EMBEDDING_LATE_CHUNKING_MAX_DOC_TOKENS" />
                    </label>
                    <input
                      data-testid="embedding-late-chunking-max-doc-tokens"
                      type="number"
                      value={lateChunkingMaxDocTokens}
                      onChange={(e) => setLateChunkingMaxDocTokens(parseInt(e.target.value || '0', 10))}
                      min={512}
                      max={65536}
                      disabled={String(contextualChunkEmbeddings).toLowerCase() !== 'late_chunking_local_only'}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: String(contextualChunkEmbeddings).toLowerCase() === 'late_chunking_local_only' ? 1 : 0.6,
                      }}
                    />
                  </div>
                  <div className="input-group" />
                </div>

                <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px' }}>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Max tokens
                      <TooltipIcon name="EMBEDDING_MAX_TOKENS" />
                    </label>
                    <input
                      type="number"
                      value={embeddingMaxTokens}
                      onChange={(e) => setEmbeddingMaxTokens(parseInt(e.target.value || '0', 10))}
                      min={512}
                      max={8192}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
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
                      onChange={(e) => setEmbeddingTimeout(parseInt(e.target.value || '0', 10))}
                      min={5}
                      max={120}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Max retries
                      <TooltipIcon name="EMBEDDING_RETRY_MAX" />
                    </label>
                    <input
                      type="number"
                      value={embeddingRetryMax}
                      onChange={(e) => setEmbeddingRetryMax(parseInt(e.target.value || '0', 10))}
                      min={1}
                      max={5}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                      }}
                    />
                  </div>
                </div>
                <div style={{ marginTop: '16px' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={embeddingCacheEnabled === 1}
                      onChange={(e) => setEmbeddingCacheEnabled(e.target.checked ? 1 : 0)}
                    />
                    <span style={{ fontSize: '13px', color: 'var(--fg)' }}>Enable embedding cache</span>
                    <TooltipIcon name="EMBEDDING_CACHE_ENABLED" />
                  </label>
                </div>
              </div>
            </details>
          </div>
        )}

        {/* CHUNKING */}
        {selectedComponent === 'chunking' && (
          <div>
            <h4
              style={{
                fontSize: '14px',
                fontWeight: 600,
                color: 'var(--fg)',
                marginBottom: '16px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              🧩 Chunking Configuration
              <TooltipIcon name="CHUNKING_STRATEGY" />
            </h4>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '20px' }}>
              {CHUNKING_STRATEGIES.map((strat) => (
                <button
                  key={strat.id}
                  onClick={() => setChunkingStrategy(strat.id)}
                  style={{
                    padding: '16px',
                    background:
                      String(chunkingStrategy || '').toLowerCase() === strat.id
                        ? 'rgba(var(--accent-rgb), 0.1)'
                        : 'var(--bg-elev2)',
                    border:
                      String(chunkingStrategy || '').toLowerCase() === strat.id ? '2px solid var(--accent)' : '1px solid var(--line)',
                    borderRadius: '8px',
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'all 0.2s ease',
                  }}
                >
                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--fg)', marginBottom: '4px' }}>{strat.label}</div>
                  <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>{strat.description}</div>
                </button>
              ))}
            </div>

            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px' }}>
              {usesTokenChunking ? (
                <>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Target tokens
                      <TooltipIcon name="TARGET_TOKENS" />
                    </label>
                    <input
                      data-testid="chunking-target-tokens"
                      type="number"
                      value={targetTokens}
                      onChange={(e) => setTargetTokens(parseInt(e.target.value || '0', 10))}
                      min={64}
                      max={8192}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Overlap tokens
                      <TooltipIcon name="OVERLAP_TOKENS" />
                    </label>
                    <input
                      data-testid="chunking-overlap-tokens"
                      type="number"
                      value={overlapTokens}
                      onChange={(e) => setOverlapTokens(parseInt(e.target.value || '0', 10))}
                      min={0}
                      max={2048}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      AST overlap lines
                      <TooltipIcon name="AST_OVERLAP_LINES" />
                    </label>
                    <input
                      type="number"
                      value={astOverlapLines}
                      onChange={(e) => setAstOverlapLines(parseInt(e.target.value || '0', 10))}
                      min={0}
                      max={100}
                      disabled
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: 0.6,
                      }}
                    />
                  </div>
                </>
              ) : (
                <>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Chunk size (chars)
                      <TooltipIcon name="CHUNK_SIZE" />
                    </label>
                    <input
                      data-testid="chunking-chunk-size"
                      type="number"
                      value={chunkSize}
                      onChange={(e) => setChunkSize(parseInt(e.target.value || '0', 10))}
                      min={200}
                      max={5000}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Chunk overlap (chars)
                      <TooltipIcon name="CHUNK_OVERLAP" />
                    </label>
                    <input
                      type="number"
                      value={chunkOverlap}
                      onChange={(e) => setChunkOverlap(parseInt(e.target.value || '0', 10))}
                      min={0}
                      max={1000}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      AST overlap lines
                      <TooltipIcon name="AST_OVERLAP_LINES" />
                    </label>
                    <input
                      type="number"
                      value={astOverlapLines}
                      onChange={(e) => setAstOverlapLines(parseInt(e.target.value || '0', 10))}
                      min={0}
                      max={100}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                      }}
                    />
                  </div>
                </>
              )}
            </div>

            {(chunkingStrategyNorm === 'recursive' || chunkingStrategyNorm === 'markdown') && (
              <div style={{ marginTop: '16px' }}>
                <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
                  Recursive splitting uses the separator list in priority order. Use <code>\\n</code> for newlines. An empty line represents the hard fallback.
                </div>
                <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px' }}>
                  <div className="input-group" style={{ gridColumn: 'span 2' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Separators (one per line)
                      <TooltipIcon name="SEPARATORS" />
                    </label>
                    <textarea
                      data-testid="chunking-separators"
                      value={separatorsText}
                      onChange={(e) => updateSeparatorsFromText(e.target.value)}
                      rows={5}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '12px',
                        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace',
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Keep separators
                      <TooltipIcon name="SEPARATOR_KEEP" />
                    </label>
                    <select
                      value={separatorKeep}
                      onChange={(e) => setSeparatorKeep(e.target.value as any)}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                      }}
                    >
                      <option value="suffix">Suffix</option>
                      <option value="prefix">Prefix</option>
                      <option value="none">None</option>
                    </select>
                    <div style={{ marginTop: '12px' }}>
                      <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                        Max recursion depth
                        <TooltipIcon name="RECURSIVE_MAX_DEPTH" />
                      </label>
                      <input
                        type="number"
                        value={recursiveMaxDepth}
                        onChange={(e) => setRecursiveMaxDepth(parseInt(e.target.value || '0', 10))}
                        min={1}
                        max={50}
                        style={{
                          width: '100%',
                          padding: '10px 12px',
                          background: 'var(--input-bg)',
                          border: '1px solid var(--line)',
                          borderRadius: '6px',
                          color: 'var(--fg)',
                          fontSize: '13px',
                        }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}

            {chunkingStrategyNorm === 'markdown' && (
              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginTop: '16px' }}>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    Max heading level
                    <TooltipIcon name="MARKDOWN_MAX_HEADING_LEVEL" />
                  </label>
                  <input
                    type="number"
                    value={markdownMaxHeadingLevel}
                    onChange={(e) => setMarkdownMaxHeadingLevel(parseInt(e.target.value || '0', 10))}
                    min={1}
                    max={6}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                    }}
                  />
                </div>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', marginTop: '28px' }}>
                    <input
                      type="checkbox"
                      checked={markdownIncludeCodeFences}
                      onChange={(e) => setMarkdownIncludeCodeFences(e.target.checked)}
                    />
                    Include code fences
                    <TooltipIcon name="MARKDOWN_INCLUDE_CODE_FENCES" />
                  </label>
                </div>
                <div className="input-group" />
              </div>
            )}

            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginTop: '16px' }}>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Max chunk tokens
                  <TooltipIcon name="MAX_CHUNK_TOKENS" />
                </label>
                <input
                  type="number"
                  value={maxChunkTokens}
                  onChange={(e) => setMaxChunkTokens(parseInt(e.target.value || '0', 10))}
                  min={100}
                  max={32000}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                  }}
                />
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Min chunk chars
                  <TooltipIcon name="MIN_CHUNK_CHARS" />
                </label>
                <input
                  type="number"
                  value={minChunkChars}
                  onChange={(e) => setMinChunkChars(parseInt(e.target.value || '0', 10))}
                  min={10}
                  max={500}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                  }}
                />
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Max file size (bytes)
                  <TooltipIcon name="MAX_INDEXABLE_FILE_SIZE" />
                </label>
                <input
                  type="number"
                  value={maxIndexableFileSize}
                  onChange={(e) => setMaxIndexableFileSize(parseInt(e.target.value || '0', 10))}
                  min={10000}
                  max={2000000000}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                  }}
                />
              </div>
            </div>

            <div style={{ marginTop: '16px' }}>
              <div style={{ display: 'flex', gap: '18px', flexWrap: 'wrap' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={emitChunkOrdinal}
                    onChange={(e) => setEmitChunkOrdinal(e.target.checked)}
                  />
                  <span style={{ fontSize: '13px', color: 'var(--fg)' }}>Emit chunk ordinal</span>
                  <TooltipIcon name="EMIT_CHUNK_ORDINAL" />
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={emitParentDocId}
                    onChange={(e) => setEmitParentDocId(e.target.checked)}
                  />
                  <span style={{ fontSize: '13px', color: 'var(--fg)' }}>Emit parent doc id</span>
                  <TooltipIcon name="EMIT_PARENT_DOC_ID" />
                </label>
              </div>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                <input type="checkbox" checked={preserveImports === 1} onChange={(e) => setPreserveImports(e.target.checked ? 1 : 0)} />
                <span style={{ fontSize: '13px', color: 'var(--fg)' }}>Preserve imports in chunks</span>
                <TooltipIcon name="PRESERVE_IMPORTS" />
              </label>
              <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginLeft: '24px', marginTop: '4px' }}>
                Keeps import statements near the top of each chunk for better code understanding.
              </div>
            </div>
          </div>
        )}

        {/* TOKENIZER + VOCAB */}
        {selectedComponent === 'bm25' && (
          <div>
            <h4
              style={{
                fontSize: '14px',
                fontWeight: 600,
                color: 'var(--fg)',
                marginBottom: '16px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              📝 Tokenization
              <TooltipIcon name="BM25_TOKENIZER" />
            </h4>

            <div
              style={{
                padding: '14px 16px',
                background: 'var(--bg-elev2)',
                borderRadius: '8px',
                border: '1px solid var(--line)',
                marginBottom: '16px',
              }}
            >
              <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)', marginBottom: '10px' }}>
                Chunk & Embedding Tokenizer
              </div>
              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px' }}>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    Strategy
                    <TooltipIcon name="TOKENIZATION_STRATEGY" />
                  </label>
                  <select
                    data-testid="tokenization-strategy"
                    value={tokenizationStrategy}
                    onChange={(e) => setTokenizationStrategy(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                    }}
                  >
                    <option value="tiktoken">tiktoken</option>
                    <option value="whitespace">whitespace</option>
                    <option value="huggingface">huggingface</option>
                  </select>
                </div>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    tiktoken encoding
                    <TooltipIcon name="TOKENIZATION_TIKTOKEN_ENCODING" />
                  </label>
                  <input
                    type="text"
                    value={tiktokenEncoding}
                    onChange={(e) => setTiktokenEncoding(e.target.value)}
                    placeholder="o200k_base"
                    disabled={String(tokenizationStrategy).toLowerCase() !== 'tiktoken'}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      opacity: String(tokenizationStrategy).toLowerCase() === 'tiktoken' ? 1 : 0.6,
                    }}
                  />
                </div>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    HF tokenizer name
                    <TooltipIcon name="TOKENIZATION_HF_TOKENIZER_NAME" />
                  </label>
                  <input
                    type="text"
                    value={hfTokenizerName}
                    onChange={(e) => setHfTokenizerName(e.target.value)}
                    placeholder="gpt2"
                    disabled={String(tokenizationStrategy).toLowerCase() !== 'huggingface'}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      opacity: String(tokenizationStrategy).toLowerCase() === 'huggingface' ? 1 : 0.6,
                    }}
                  />
                </div>
              </div>
              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginTop: '14px' }}>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                    <input type="checkbox" checked={normalizeUnicode} onChange={(e) => setNormalizeUnicode(e.target.checked)} />
                    Normalize Unicode (NFKC)
                    <TooltipIcon name="TOKENIZATION_NORMALIZE_UNICODE" />
                  </label>
                </div>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                    <input type="checkbox" checked={lowercaseTokenizer} onChange={(e) => setLowercaseTokenizer(e.target.checked)} />
                    Lowercase
                    <TooltipIcon name="TOKENIZATION_LOWERCASE" />
                  </label>
                </div>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                    <input type="checkbox" checked={tokenEstimateOnly} onChange={(e) => setTokenEstimateOnly(e.target.checked)} />
                    Estimate-only (fast)
                    <TooltipIcon name="TOKENIZATION_ESTIMATE_ONLY" />
                  </label>
                </div>
              </div>
              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginTop: '14px' }}>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    Max tokens per chunk (hard)
                    <TooltipIcon name="TOKENIZATION_MAX_TOKENS_PER_CHUNK_HARD" />
                  </label>
                  <input
                    type="number"
                    value={maxTokensPerChunkHard}
                    onChange={(e) => setMaxTokensPerChunkHard(parseInt(e.target.value || '0', 10))}
                    min={256}
                    max={65536}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                    }}
                  />
                </div>
                <div className="input-group" />
                <div className="input-group" />
              </div>
            </div>

            <div
              style={{
                padding: '14px 16px',
                background: 'var(--bg-elev2)',
                borderRadius: '8px',
                border: '1px solid var(--line)',
                marginBottom: '16px',
              }}
            >
              <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)', marginBottom: '10px' }}>
                Large-file indexing safety
              </div>
              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px' }}>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    Max file size (MB)
                    <TooltipIcon name="INDEX_MAX_FILE_SIZE_MB" />
                  </label>
                  <input
                    type="number"
                    value={indexMaxFileSizeMb}
                    onChange={(e) => setIndexMaxFileSizeMb(parseInt(e.target.value || '0', 10))}
                    min={1}
                    max={1024}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                    }}
                  />
                </div>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    Large file mode
                    <TooltipIcon name="LARGE_FILE_MODE" />
                  </label>
                  <select
                    data-testid="large-file-mode"
                    value={largeFileMode}
                    onChange={(e) => setLargeFileMode(e.target.value as any)}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                    }}
                  >
                    <option value="stream">stream</option>
                    <option value="read_all">read_all</option>
                  </select>
                </div>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    Stream block chars
                    <TooltipIcon name="LARGE_FILE_STREAM_CHUNK_CHARS" />
                  </label>
                  <input
                    type="number"
                    value={largeFileStreamChunkChars}
                    onChange={(e) => setLargeFileStreamChunkChars(parseInt(e.target.value || '0', 10))}
                    min={100000}
                    max={50000000}
                    disabled={largeFileMode !== 'stream'}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      opacity: largeFileMode === 'stream' ? 1 : 0.6,
                    }}
                  />
                </div>
              </div>
              <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--fg-muted)' }}>
                Streaming mode ingests large <code>.txt</code>/<code>.md</code> files in bounded blocks to avoid loading the entire file into RAM.
              </div>
            </div>

            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px' }}>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Postgres FTS tokenizer
                  <TooltipIcon name="BM25_TOKENIZER" />
                </label>
                <select
                  value={bm25Tokenizer}
                  onChange={(e) => setBm25Tokenizer(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                  }}
                >
                  <option value="stemmer">Stemmer</option>
                  <option value="lowercase">Lowercase</option>
                  <option value="whitespace">Whitespace</option>
                </select>
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Stemmer language
                  <TooltipIcon name="BM25_STEMMER_LANG" />
                </label>
                <input
                  type="text"
                  value={bm25StemmerLang}
                  onChange={(e) => setBm25StemmerLang(e.target.value)}
                  placeholder="english"
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                  }}
                />
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Stopwords language
                  <TooltipIcon name="BM25_STOPWORDS_LANG" />
                </label>
                <input
                  type="text"
                  value={bm25StopwordsLang}
                  onChange={(e) => setBm25StopwordsLang(e.target.value)}
                  placeholder="en"
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                  }}
                />
              </div>
            </div>

            <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--fg-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <strong style={{ color: 'var(--fg)' }}>Resolved:</strong> {resolvedTokenizerDesc}
            </div>

            <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--fg-muted)' }}>
              Vocabulary Preview reads from Postgres built-in FTS (<code>chunks.tsv</code>). If you switch sparse retrieval to <code>pg_search_bm25</code>, this preview may not reflect the active BM25 index.
            </div>

            <details open={vocabExpanded} onToggle={(e) => setVocabExpanded((e.target as HTMLDetailsElement).open)} style={{ marginTop: '20px' }}>
              <summary style={{ cursor: 'pointer', fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>
                🔍 Vocabulary Preview
                <TooltipIcon name="BM25_VOCAB_PREVIEW" />
              </summary>

              <div
                style={{
                  marginTop: '12px',
                  padding: '16px',
                  background: 'var(--bg-elev2)',
                  borderRadius: '8px',
                  border: '1px solid var(--line)',
                }}
              >
                <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap' }}>
                  <label style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
                    Top N:
                    <input
                      type="number"
                      value={vocabTopN}
                      onChange={(e) => setVocabTopN(Math.max(10, Math.min(500, parseInt(e.target.value || '50', 10))))}
                      min={10}
                      max={500}
                      style={{
                        width: '80px',
                        marginLeft: '8px',
                        padding: '4px 8px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '4px',
                        color: 'var(--fg)',
                        fontSize: '12px',
                      }}
                    />
                  </label>
                  <button
                    onClick={loadVocabPreview}
                    disabled={vocabLoading || !String(activeRepo || '').trim()}
                    style={{
                      padding: '6px 12px',
                      fontSize: '12px',
                      background: 'var(--accent)',
                      color: 'var(--accent-contrast)',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: vocabLoading ? 'wait' : 'pointer',
                      opacity: vocabLoading ? 0.7 : 1,
                    }}
                  >
                    {vocabLoading ? 'Loading…' : 'Load Vocabulary'}
                  </button>
                </div>

                {vocabPreview.length > 0 ? (
                  <>
                    <div
                      style={{
                        maxHeight: '280px',
                        overflowY: 'auto',
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))',
                        gap: '6px',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '11px',
                      }}
                    >
                      {vocabPreview.map((item, idx) => (
                        <div
                          key={`${item.term}-${idx}`}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            padding: '6px 8px',
                            background: 'var(--bg)',
                            borderRadius: '6px',
                            border: '1px solid var(--line)',
                          }}
                        >
                          <span style={{ color: 'var(--fg)', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.term}</span>
                          <span style={{ color: 'var(--fg-muted)', marginLeft: '10px' }}>{item.doc_count}</span>
                        </div>
                      ))}
                    </div>
                    <div style={{ marginTop: '10px', fontSize: '11px', color: 'var(--fg-muted)', display: 'flex', justifyContent: 'space-between' }}>
                      <span>Tokenizer: {bm25Tokenizer || '—'}</span>
                      <span>
                        Showing {vocabPreview.length} of {vocabTotal || '—'} terms
                      </span>
                    </div>
                  </>
                ) : (
                  <div style={{ fontSize: '12px', color: 'var(--fg-muted)', textAlign: 'center', padding: '20px' }}>
                    Click “Load Vocabulary” to inspect tokenized terms.
                  </div>
                )}
              </div>
            </details>
          </div>
        )}

        {/* GRAPH + OPTIONS */}
        {selectedComponent === 'enrichment' && (
          <div>
            <h4
              style={{
                fontSize: '14px',
                fontWeight: 600,
                color: 'var(--fg)',
                marginBottom: '16px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              🧠 Graph Build & Index Options
              <TooltipIcon name="GRAPH_SEARCH_ENABLED" />
            </h4>

            <div style={{ display: 'grid', gap: '16px' }}>
              <div
                style={{
                  padding: '16px',
                  background: 'var(--bg-elev2)',
                  borderRadius: '8px',
                  border: graphIndexingEnabled ? '2px solid var(--accent)' : '1px solid var(--line)',
                }}
              >
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input
                    data-testid="graph-indexing-enabled"
                    type="checkbox"
                    checked={graphIndexingEnabled}
                    onChange={(e) => setGraphIndexingEnabled(e.target.checked)}
                    style={{ width: '18px', height: '18px' }}
                  />
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Build graph during indexing</div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                      When enabled, indexing also extracts entities/relationships into Neo4j for GraphRAG.
                    </div>
                  </div>
                </label>
              </div>

              <div
                style={{
                  padding: '16px',
                  background: 'var(--bg-elev2)',
                  borderRadius: '8px',
                  border: graphIndexingEnabled && lexicalGraphEnabled ? '2px solid var(--accent)' : '1px solid var(--line)',
                  opacity: graphIndexingEnabled ? 1 : 0.6,
                }}
              >
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input
                    data-testid="graph-lexical-enabled"
                    type="checkbox"
                    checked={lexicalGraphEnabled}
                    onChange={(e) => setLexicalGraphEnabled(e.target.checked)}
                    disabled={!graphIndexingEnabled}
                    style={{ width: '18px', height: '18px' }}
                  />
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Build lexical chunk graph</div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                      Creates Document/Chunk nodes + NEXT_CHUNK edges for chunk-based GraphRAG.
                    </div>
                  </div>
                </label>
              </div>

              <div
                style={{
                  padding: '16px',
                  background: 'var(--bg-elev2)',
                  borderRadius: '8px',
                  border: storeChunkEmbeddings ? '1px solid var(--line)' : '1px solid var(--line)',
                  opacity: graphIndexingEnabled && lexicalGraphEnabled ? 1 : 0.6,
                }}
              >
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input
                    data-testid="graph-store-chunk-embeddings"
                    type="checkbox"
                    checked={storeChunkEmbeddings}
                    onChange={(e) => setStoreChunkEmbeddings(e.target.checked)}
                    disabled={!graphIndexingEnabled || !lexicalGraphEnabled}
                    style={{ width: '18px', height: '18px' }}
                  />
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Store chunk embeddings in Neo4j</div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                      Enables Neo4j native vector index over Chunk nodes (requires dense embeddings).
                    </div>
                  </div>
                </label>
                {skipDense === 1 && storeChunkEmbeddings && (
                  <div
                    style={{
                      marginTop: '10px',
                      padding: '8px 12px',
                      background: 'rgba(var(--warn-rgb), 0.1)',
                      borderRadius: '6px',
                      color: 'var(--warn)',
                      fontSize: '11px',
                    }}
                  >
                    skip_dense=1 disables embeddings. Re-index with dense enabled to populate Neo4j vectors.
                  </div>
                )}
              </div>

              <div
                style={{
                  padding: '16px',
                  background: 'var(--bg-elev2)',
                  borderRadius: '8px',
                  border: semanticKgEnabled ? '2px solid rgba(var(--accent-rgb), 0.6)' : '1px solid var(--line)',
                  opacity: graphIndexingEnabled && lexicalGraphEnabled ? 1 : 0.6,
                }}
              >
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input
                    data-testid="semantic-kg-enabled"
                    type="checkbox"
                    checked={semanticKgEnabled}
                    onChange={(e) => setSemanticKgEnabled(e.target.checked)}
                    disabled={!graphIndexingEnabled || !lexicalGraphEnabled}
                    style={{ width: '18px', height: '18px' }}
                  />
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Semantic KG (concepts + relations)</div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                      Extracts concept entities + related_to edges and links them to chunk_ids for graph expansion.
                    </div>
                  </div>
                </label>

                {semanticKgEnabled && (
                  <div style={{ marginTop: '12px', display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
                    <div className="input-group">
                      <label style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '6px' }}>Mode</label>
                      <select
                        data-testid="semantic-kg-mode"
                        value={semanticKgMode}
                        onChange={(e) => setSemanticKgMode(e.target.value as any)}
                        style={{ width: '100%' }}
                      >
                        <option value="heuristic">Heuristic</option>
                        <option value="llm">LLM</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '6px' }}>Max chunks</label>
                      <input
                        data-testid="semantic-kg-max-chunks"
                        type="number"
                        min={0}
                        max={100000}
                        value={semanticKgMaxChunks}
                        onChange={(e) => setSemanticKgMaxChunks(parseInt(e.target.value || '0', 10))}
                        style={{ width: '100%' }}
                      />
                    </div>
                    <div className="input-group">
                      <label style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '6px' }}>Max concepts / chunk</label>
                      <input
                        data-testid="semantic-kg-max-concepts"
                        type="number"
                        min={0}
                        max={50}
                        value={semanticKgMaxConcepts}
                        onChange={(e) => setSemanticKgMaxConcepts(parseInt(e.target.value || '0', 10))}
                        style={{ width: '100%' }}
                      />
                    </div>
                  </div>
                )}
              </div>

              <div
                style={{
                  padding: '16px',
                  background: 'var(--bg-elev2)',
                  borderRadius: '8px',
                  border: skipDense === 1 ? '2px solid var(--warn)' : '1px solid var(--line)',
                }}
              >
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input type="checkbox" checked={skipDense === 1} onChange={(e) => setSkipDense(e.target.checked ? 1 : 0)} style={{ width: '18px', height: '18px' }} />
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Skip dense vectors</div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                      Useful for graph-only/sparse-only indexing runs (fast, no embeddings).
                    </div>
                  </div>
                  <TooltipIcon name="SKIP_DENSE" />
                </label>
                {skipDense === 1 && (
                  <div style={{ marginTop: '10px', padding: '8px 12px', background: 'rgba(var(--warn-rgb), 0.1)', borderRadius: '6px', color: 'var(--warn)', fontSize: '11px' }}>
                    Vector search will not work until you re-index with dense enabled.
                  </div>
                )}
              </div>

              <div
                style={{
                  padding: '16px',
                  background: 'var(--bg-elev2)',
                  borderRadius: '8px',
                  border: '1px solid var(--line)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Parquet ingestion (bounded)</div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                      Prevents huge Parquet files from dominating memory/time during indexing.
                    </div>
                  </div>
                  <TooltipIcon name="PARQUET_EXTRACT_MAX_ROWS" />
                </div>

                <div style={{ marginTop: '12px', display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '14px' }}>
                  <div className="input-group">
                    <label style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                      Max rows
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={200000}
                      value={parquetExtractMaxRows}
                      onChange={(e) => setParquetExtractMaxRows(parseInt(e.target.value || '0', 10))}
                      style={{ width: '100%' }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                      Max chars
                    </label>
                    <input
                      type="number"
                      min={10_000}
                      max={50_000_000}
                      value={parquetExtractMaxChars}
                      onChange={(e) => setParquetExtractMaxChars(parseInt(e.target.value || '0', 10))}
                      style={{ width: '100%' }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                      Max cell chars
                    </label>
                    <input
                      type="number"
                      min={100}
                      max={200_000}
                      value={parquetExtractMaxCellChars}
                      onChange={(e) => setParquetExtractMaxCellChars(parseInt(e.target.value || '0', 10))}
                      style={{ width: '100%' }}
                    />
                  </div>
                </div>

                <div style={{ marginTop: '12px', display: 'flex', gap: '18px', flexWrap: 'wrap' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={parquetExtractTextColumnsOnly === 1}
                      onChange={(e) => setParquetExtractTextColumnsOnly(e.target.checked ? 1 : 0)}
                    />
                    <span style={{ fontSize: '12px', color: 'var(--fg)' }}>Text columns only</span>
                    <TooltipIcon name="PARQUET_EXTRACT_TEXT_COLUMNS_ONLY" />
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={parquetExtractIncludeColumnNames === 1}
                      onChange={(e) => setParquetExtractIncludeColumnNames(e.target.checked ? 1 : 0)}
                    />
                    <span style={{ fontSize: '12px', color: 'var(--fg)' }}>Include column names</span>
                    <TooltipIcon name="PARQUET_EXTRACT_INCLUDE_COLUMN_NAMES" />
                  </label>
                </div>
              </div>
            </div>

            <details style={{ marginTop: '18px' }}>
              <summary style={{ cursor: 'pointer', fontSize: '13px', fontWeight: 600, color: 'var(--fg)' }}>
                Advanced chunking controls
              </summary>
              <div style={{ marginTop: '12px' }}>
                <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px' }}>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Greedy fallback target
                      <TooltipIcon name="GREEDY_FALLBACK_TARGET" />
                    </label>
                    <input
                      type="number"
                      value={greedyFallbackTarget}
                      onChange={(e) => setGreedyFallbackTarget(parseInt(e.target.value || '0', 10))}
                      min={200}
                      max={2000}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                      }}
                    />
                  </div>
                </div>
              </div>
            </details>
          </div>
        )}
      </div>

      {/* Index stats panel */}
      <div
        style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          marginBottom: '24px',
        }}
      >
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
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '16px' }}>📊</span>
            <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--fg)' }}>Index Stats</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                void loadStats();
                void refreshStatus();
              }}
              style={{
                padding: '4px 8px',
                fontSize: '11px',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                borderRadius: '6px',
                color: 'var(--fg-muted)',
                cursor: 'pointer',
              }}
            >
              ↻ Refresh
            </button>
          </div>
          <span style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>{statsExpanded ? '▼' : '▶'}</span>
        </button>

        {statsExpanded && (
          <div style={{ padding: '0 16px 16px' }}>
            {statsLoading ? (
              <div style={{ color: 'var(--fg-muted)', fontSize: '12px', padding: '8px 0' }}>Loading…</div>
            ) : indexStats ? (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
                  gap: '12px',
                }}
              >
                {[
                  { label: 'Files', value: String(indexStats.total_files ?? 0), icon: '📄' },
                  { label: 'Chunks', value: String(indexStats.total_chunks ?? 0), icon: '📦' },
                  { label: 'Tokens', value: String(indexStats.total_tokens ?? 0), icon: '🔤' },
                  { label: 'Embedding provider', value: indexStats.embedding_provider || '—', icon: '🏷️' },
                  { label: 'Embedding model', value: indexStats.embedding_model || '—', icon: '🔢' },
                  { label: 'Dimensions', value: indexStats.embedding_dimensions ? `${indexStats.embedding_dimensions}d` : '—', icon: '📐' },
                  { label: 'Last indexed', value: indexStats.last_indexed ? new Date(String(indexStats.last_indexed)).toLocaleString() : '—', icon: '🕒' },
                ].map((item) => (
                  <div
                    key={item.label}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '10px',
                      padding: '10px',
                      background: 'var(--bg)',
                      borderRadius: '10px',
                      border: '1px solid var(--line)',
                    }}
                  >
                    <span style={{ fontSize: '20px' }}>{item.icon}</span>
                    <div>
                      <div style={{ fontSize: '14px', fontWeight: 800, color: 'var(--fg)' }}>{item.value}</div>
                      <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>{item.label}</div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ color: 'var(--fg-muted)', fontSize: '12px' }}>No stats available for this corpus yet.</div>
            )}
          </div>
        )}
      </div>

      {/* Action panel (Index now + terminal slide-down) */}
      <div
        style={{
          background: 'linear-gradient(135deg, var(--bg) 0%, var(--bg-elev1) 100%)',
          border: '1px solid var(--line)',
          borderRadius: '12px',
          padding: '20px',
          marginBottom: '24px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: isIndexing ? '16px' : 0, flexWrap: 'wrap' }}>
          {isIndexing ? (
            <>
              <button
                onClick={handleStopIndex}
                style={{
                  padding: '12px 24px',
                  fontSize: '14px',
                  fontWeight: 700,
                  background: 'var(--error)',
                  color: 'white',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: 'pointer',
                }}
              >
                Stop Indexing
              </button>
              <div style={{ flex: 1, minWidth: '260px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontSize: '12px' }}>
                  <span style={{ color: 'var(--fg)' }}>{progress.status}</span>
                  <span style={{ color: 'var(--accent)', fontWeight: 800 }}>{progress.current}%</span>
                </div>
                <div style={{ height: '6px', background: 'var(--line)', borderRadius: '3px', overflow: 'hidden' }}>
                  <div
                    style={{
                      width: `${progress.current}%`,
                      height: '100%',
                      background: 'linear-gradient(90deg, var(--accent), var(--link))',
                      borderRadius: '3px',
                      transition: 'width 0.3s ease',
                    }}
                  />
                </div>
              </div>
            </>
          ) : (
            <>
              <button
                onClick={handleStartIndex}
                data-testid="index-now-button"
                disabled={!canIndex || estimateLoading}
                aria-busy={estimateLoading}
                style={{
                  padding: '12px 32px',
                  fontSize: '14px',
                  fontWeight: 800,
                  background: canIndex && !estimateLoading ? 'var(--accent)' : 'var(--bg-elev2)',
                  color: canIndex && !estimateLoading ? 'var(--accent-contrast)' : 'var(--fg-muted)',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: canIndex && !estimateLoading ? 'pointer' : 'not-allowed',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}
              >
                <span>🚀</span>
                {estimateLoading ? 'Estimating…' : 'Index Now'}
              </button>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--fg-muted)' }}>
                <input type="checkbox" checked={forceReindex} onChange={(e) => setForceReindex(e.target.checked)} />
                Force reindex
              </label>
              <button
                onClick={() => setTerminalVisible(!terminalVisible)}
                style={{
                  padding: '10px 14px',
                  background: 'var(--bg-elev2)',
                  color: 'var(--fg-muted)',
                  border: '1px solid var(--line)',
                  borderRadius: '8px',
                  fontSize: '13px',
                  cursor: 'pointer',
                }}
              >
                {terminalVisible ? '✕ Hide Logs' : '🪵 Show Logs'}
              </button>
              <button
                onClick={handleDeleteIndex}
                disabled={!String(activeRepo || '').trim()}
                style={{
                  padding: '10px 14px',
                  background: 'transparent',
                  color: 'var(--err)',
                  border: '1px solid var(--err)',
                  borderRadius: '8px',
                  fontSize: '13px',
                  cursor: 'pointer',
                }}
                title="Deletes embeddings, FTS, chunks, and graph for this corpus"
              >
                🗑 Delete index
              </button>
            </>
          )}
        </div>

        {!isIndexing && indexEstimate ? (
          <div
            data-testid="index-estimate-summary"
            style={{
              marginTop: '10px',
              fontSize: '12px',
              color: 'var(--fg-muted)',
              fontFamily: "'SF Mono', monospace",
            }}
          >
            Est: {indexEstimate.embedding_cost_usd == null ? 'N/A' : formatCurrency(Number(indexEstimate.embedding_cost_usd || 0))} •{' '}
            {indexEstimate.estimated_seconds_low != null && indexEstimate.estimated_seconds_high != null
              ? `${formatDuration(Number(indexEstimate.estimated_seconds_low) * 1000)}–${formatDuration(
                  Number(indexEstimate.estimated_seconds_high) * 1000
                )}`
              : 'N/A'}{' '}
            • {formatNumber(Number(indexEstimate.total_files || 0))} files • {formatBytes(Number(indexEstimate.total_size_bytes || 0))}
          </div>
        ) : null}

        {/* Live terminal - slide down with cubic-bezier */}
        <div
          style={{
            maxHeight: terminalVisible ? '400px' : '0',
            opacity: terminalVisible ? 1 : 0,
            overflow: 'hidden',
            transition: 'max-height 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease',
            marginTop: terminalVisible ? '16px' : '0',
          }}
        >
          <LiveTerminal ref={terminalRef} id="indexing_terminal" title="Indexing Output" initialContent={['Ready for indexing...']} />
        </div>
      </div>
    </div>
  );
}
