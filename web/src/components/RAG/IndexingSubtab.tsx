/**
 * IndexingSubtab (TriBrid) — Restored production-quality layout.
 *
 * Goal:
 * - Keep the *layout* and UX patterns from the legacy IndexingSubtab (cards, panels, advanced details, slide-down terminal)
 * - Wire public config to TriBridConfig and corpus-first state to useRepoStore
 * - No hardcoded model lists (load from /api/models)
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  useAPI,
  useConfig,
  useConfigField,
  useEmbeddingModel,
  useEmbeddingStatus,
  useIndexing,
  useModels,
  useRuntimeCapabilities,
} from '@/hooks';
import { useRepoStore } from '@/stores/useRepoStore';
import { LiveTerminal, type LiveTerminalHandle } from '@/components/LiveTerminal/LiveTerminal';
import { RepositoryConfig } from '@/components/RAG/RepositoryConfig';
import { SyntheticCallout } from '@/components/RAG/SyntheticCallout';
import { ModelPicker } from '@/components/RAG/ModelPicker';
import { ModelPicker as ChatModelPicker } from '@/components/Chat/ModelPicker';
import { PromptLink } from '@/components/ui/PromptLink';
import { EmbeddingMismatchWarning } from '@/components/ui/EmbeddingMismatchWarning';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { confirmDialog } from '@/components/ui/confirmDialog';
import { indexingApi } from '@/api';
import type { ReadyIndexEstimate } from '@/api/indexing';
import { formatBytes, formatCurrency, formatDuration, formatNumber } from '@/utils/formatters';
import { NumberField } from '@/components/ui/NumberField';
import type {
  ChatModelInfo,
  ChatModelsResponse,
  GraphIndexingConfig,
  GraphSchemaProposal,
  GraphSchemaProposalFailureResponse,
  IndexRequest,
  IndexRunEvent,
  IndexRunEventPage,
  IndexRunSummary,
  IndexStats,
  IndexStatus,
} from '@/types/generated';
import { describeEmbeddingProviderStrategy } from '@/utils/embeddingStrategy';

type IndexingComponent = 'embedding' | 'chunking' | 'bm25' | 'enrichment' | 'figures';

/**
 * One line per conversion instead of forty.
 *
 * A Docling conversion emits a "still running" heartbeat while it works, so a long PDF buried
 * its real events -- the figure summary among them -- under ~40 identical
 * "Converting A11_MissionReport.pdf: still running (60s...2400s elapsed)" lines. Only the last
 * beat per file carries information (how long it ended up taking), so the earlier ones are
 * folded into it and the line says how many there were.
 */
const HEARTBEAT_RE = /^(?:.*?\b)?Converting (.+?): still running/;

export function collapseHeartbeats(events: IndexRunEvent[]): IndexRunEvent[] {
  const beatsByFile = new Map<string, number>();
  for (const ev of events) {
    const file = HEARTBEAT_RE.exec(String(ev.message || ''))?.[1];
    if (file) beatsByFile.set(file, (beatsByFile.get(file) ?? 0) + 1);
  }
  const seen = new Map<string, number>();
  const out: IndexRunEvent[] = [];
  for (const ev of events) {
    const file = HEARTBEAT_RE.exec(String(ev.message || ''))?.[1];
    if (!file) {
      out.push(ev);
      continue;
    }
    const index = (seen.get(file) ?? 0) + 1;
    seen.set(file, index);
    const total = beatsByFile.get(file) ?? 1;
    if (index < total) continue; // superseded by a later beat for the same file
    out.push(
      total > 1
        ? { ...ev, message: `${String(ev.message || '')} [${total} progress notices]` }
        : ev
    );
  }
  return out;
}

const COMPONENT_CARDS: Array<{
  id: IndexingComponent;
  icon: string;
  label: string;
  description: string;
}> = [
  { id: 'embedding', icon: '🔢', label: 'Embedding', description: 'Provider, model, dimensions, batching' },
  { id: 'chunking', icon: '🧩', label: 'Chunking', description: 'Strategy, size, overlap, limits' },
  { id: 'bm25', icon: '📝', label: 'Tokenization', description: 'Chunk tokenizer + Qdrant/BM25 sparse stemming + large-file mode' },
  { id: 'enrichment', icon: '🧠', label: 'Graph & Enrichment', description: 'Graph build, dense-vector skip, enrichment prompts' },
  { id: 'figures', icon: '🖼️', label: 'Figures & Vision', description: 'Describe charts, diagrams, drawings via the gateway' },
];

const INDEXING_COMPONENT_IDS = new Set<string>(COMPONENT_CARDS.map((card) => card.id));

function isIndexingComponent(value: string | null): value is IndexingComponent {
  return value !== null && INDEXING_COMPONENT_IDS.has(value);
}

/**
 * A duration in ms for `formatDuration`, rounded.
 *
 * `formatDuration` prints sub-second values verbatim, so a phase of 0.148833... seconds
 * rendered as "148.83333333333334ms" in the estimate dialog. The phases are estimates to one
 * or two significant figures; printing fourteen decimals of one is noise.
 */
function durationMs(seconds: number): number {
  return Math.round(Number(seconds) * 1000);
}

/**
 * Currency for a figure-description cost, which is genuinely sub-cent: one figure at the
 * vision alias runs about $0.0007, and `Intl` currency (two decimals) prints that as
 * "$0.00" — the exact misleading zero the Python `_estimate_figures` guard exists to avoid,
 * reintroduced at the display layer. At or above one cent this is ordinary `formatCurrency`;
 * below it, show at least three significant figures (trailing zeros trimmed) so the number
 * the estimate produced is not rounded away. Shared `formatCurrency` is left untouched.
 */
function formatFigureCostUsd(amount: number): string {
  const value = Number(amount) || 0;
  if (value >= 0.01 || value <= 0) return formatCurrency(value);
  const digits = Math.min(10, -Math.floor(Math.log10(value)) + 2);
  const fixed = value.toFixed(digits).replace(/0+$/, '').replace(/\.$/, '');
  return `$${fixed}`;
}

/**
 * The operator-readable reason inside an API error.
 *
 * An axios rejection's own `message` is "Request failed with status code 422", which names
 * nothing the operator can act on; the actionable sentence ("repo_path not found: data/recall")
 * is in the response body's `detail`, either as a string or as a typed detail object.
 */
function errorDetail(error: unknown): string {
  const body = (error as { response?: { data?: unknown } } | null)?.response?.data;
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail.trim();
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message.trim();
  }
  if (error instanceof Error && error.message.trim()) return error.message.trim();
  return 'unknown error';
}

// Status polling cadence. Fast enough to follow a live run, slow enough that an idle tab
// is not a request generator.
const INDEX_POLL_ACTIVE_MS = 3000;
const INDEX_POLL_IDLE_MS = 30000;

const FALLBACK_CHUNKING_STRATEGIES = [
  { id: 'fixed_tokens', label: 'Fixed tokens', description: 'Token-window chunking (best default for text corpora)' },
  { id: 'recursive', label: 'Recursive', description: 'Separator-based chunking packed by token target (docs/transcripts)' },
  { id: 'markdown', label: 'Markdown', description: 'Split by headings then pack by tokens (docs/notes)' },
  { id: 'sentence', label: 'Sentence', description: 'Sentence boundaries packed by tokens (prose)' },
  { id: 'qa_blocks', label: 'Q/A blocks', description: 'Detect Q:/A: blocks then pack by tokens (interviews/dumps)' },
  { id: 'greedy', label: 'Greedy', description: 'Legacy fixed-char fallback using the greedy target size' },
  { id: 'fixed_chars', label: 'Fixed chars', description: 'Character windowing with overlap (fallback, legacy)' },
  { id: 'ast', label: 'AST-aware', description: 'Preserve functions/blocks (best for code)' },
  { id: 'hybrid', label: 'Hybrid', description: 'AST with fallback behavior' },
];

/**
 * Mirrors `IndexingFiguresConfig.skip_classes` (server/models/tribrid_config_model.py).
 * Module-level so the array identity is stable: `useConfigField` memoizes on its default
 * value, and the skip-classes text field re-syncs off that memo.
 */
const FIGURES_SKIP_CLASSES_DEFAULT: string[] = ['logo', 'signature', 'icon'];

/**
 * Trim, drop blanks and de-duplicate a comma-separated class list.
 *
 * Entries are lower-cased: Docling's classifier emits lower-case class names and the skip
 * is matched against them, so "Logo" and "logo" are the same rule and must collapse rather
 * than persist as two entries of which only one can ever match.
 */
function parseSkipClasses(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const entry of raw.split(',')) {
    const value = entry.trim().toLowerCase();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

export function IndexingSubtab() {
  const schemaProposalReasoningId = useId();
  const { api } = useAPI();
  const { config, flushPendingPatches } = useConfig();
  const { capabilities: runtimeCapabilities } = useRuntimeCapabilities();
  const { activeRepo, repos, loadRepos, setActiveRepo } = useRepoStore();
  const {
    fetchStatus: fetchIndexStatus,
    fetchStats: fetchIndexStats,
    startAndStream,
    stopIndex,
  } = useIndexing();

  // Terminal ref (slide-down UI)
  const terminalRef = useRef<LiveTerminalHandle>(null);

  // UI state. The selected card is addressable as `?component=<id>` so a global-search hit
  // (or a shared link) can open the card a setting actually lives on. It is a one-shot
  // navigation aid, so it is CONSUMED: applied, then stripped from the URL. Left in place it
  // becomes sticky global state that outranks the operator -- `RAGTab` unmounts this subtab
  // on every subtab change and `useSubtab` copies the whole query string forward, so a
  // surviving `component=` reopens its card on every return, and survives reload and
  // sharing. Read reactively rather than at mount only, because the param can also arrive
  // while this component is already on screen.
  const location = useLocation();
  const navigate = useNavigate();
  const componentParam = useMemo(
    () => new URLSearchParams(location.search || '').get('component'),
    [location.search]
  );
  const [selectedComponent, setSelectedComponent] = useState<IndexingComponent>(
    isIndexingComponent(componentParam) ? componentParam : 'embedding'
  );

  // `/rag` renders native in the Dock (`dockCatalog.ts`), where `location` is the synthetic
  // `{ key: 'dock' }` one `DockView` passes to `<Routes location=...>`. Navigating from there
  // would move the real browser URL out from under the page behind the dock, which is the
  // same hazard `useSubtab` guards. Docked, the param still selects the card; it just is not
  // rewritten -- and a docked URL is neither shared nor reloaded, so nothing sticks.
  const isDockContext = (location as { key?: string })?.key === 'dock';
  // A docked location's synthetic URL cannot be rewritten, so `component=` cannot be
  // stripped after it is read there. This latches consumption instead, so the param is
  // applied once and a later return to a docked `/rag` never reopens the card it named.
  const componentConsumedRef = useRef(false);

  useEffect(() => {
    if (componentParam === null) return;
    if (isDockContext) {
      if (componentConsumedRef.current) return;
      componentConsumedRef.current = true;
      if (isIndexingComponent(componentParam)) setSelectedComponent(componentParam);
      return;
    }
    if (isIndexingComponent(componentParam)) setSelectedComponent(componentParam);
    // Stripped whether or not it named a real card, so a typo cannot stick either.
    // `replace` keeps the consumed link out of the back stack.
    const next = new URLSearchParams(location.search || '');
    next.delete('component');
    const search = next.toString();
    navigate({ pathname: location.pathname, search: search ? `?${search}` : '' }, { replace: true });
  }, [componentParam, isDockContext, location.pathname, location.search, navigate]);
  const [isIndexing, setIsIndexing] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 100, status: 'Ready' });
  const [terminalVisible, setTerminalVisible] = useState(false);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  // Only a measured estimate is ever stored: indexingApi.estimate cannot return anything
  // else, and the narrow type stops a future edit putting a warming payload in here.
  const [indexEstimate, setIndexEstimate] = useState<ReadyIndexEstimate | null>(null);
  const [graphSchemaProposal, setGraphSchemaProposal] = useState<GraphSchemaProposal | null>(null);
  const [graphSchemaLoading, setGraphSchemaLoading] = useState(false);
  const [graphSchemaError, setGraphSchemaError] = useState<{ message: string; operatorHint: string } | null>(null);
  const graphSchemaRequestRef = useRef<AbortController | null>(null);
  const [graphOverrideReason, setGraphOverrideReason] = useState('');
  const [estimateLoading, setEstimateLoading] = useState(false);
  const [estimateWarmup, setEstimateWarmup] = useState('');

  // Job options
  const [forceReindex, setForceReindex] = useState(false);
  const [pathOverride, setPathOverride] = useState('');

  // Config fields (TriBridConfig-backed)
  const [embeddingType, setEmbeddingType] = useConfigField<string>('embedding.embedding_type', '');
  // (embedding model per-provider fields now managed by useEmbeddingModel hook)
  const [embeddingDim, setEmbeddingDim] = useConfigField<number>('embedding.embedding_dim', 0);
  const [embeddingBatchSize, setEmbeddingBatchSize] = useConfigField<number>('embedding.embedding_batch_size', 0);
  const [embeddingMaxTokens, setEmbeddingMaxTokens] = useConfigField<number>('embedding.embedding_max_tokens', 0);
  const [embeddingCacheEnabled, setEmbeddingCacheEnabled] = useConfigField<boolean>('embedding.embedding_cache_enabled', true);
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
  const [preserveImports, setPreserveImports] = useConfigField<boolean>('chunking.preserve_imports', true);
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
  const [parquetExtractTextColumnsOnly, setParquetExtractTextColumnsOnly] = useConfigField<boolean>(
    'indexing.parquet_extract_text_columns_only',
    true
  );
  const [parquetExtractIncludeColumnNames, setParquetExtractIncludeColumnNames] = useConfigField<boolean>(
    'indexing.parquet_extract_include_column_names',
    true
  );

  const [skipDense, setSkipDense] = useConfigField<boolean>('indexing.skip_dense', false);
  const [graphIndexingEnabled, setGraphIndexingEnabled] = useConfigField<boolean>('graph_indexing.enabled', true);
  const [lexicalGraphEnabled, setLexicalGraphEnabled] = useConfigField<boolean>('graph_indexing.build_lexical_graph', true);
  const [buildCodeGraph, setBuildCodeGraph] = useConfigField<boolean>('graph_indexing.build_code_graph', false);
  const [semanticKgMaxChunks, setSemanticKgMaxChunks] = useConfigField<number>('graph_indexing.semantic_kg_max_chunks', 40000);
  const [semanticKgLlmModel, setSemanticKgLlmModel] = useConfigField<string>('graph_indexing.semantic_kg_llm_model', '');
  const [semanticKgReasoningEffort, setSemanticKgReasoningEffort] = useConfigField<
    'minimal' | 'low' | 'medium' | 'high' | 'xhigh'
  >('graph_indexing.semantic_kg_reasoning_effort', 'medium');
  const [semanticKgTimeoutS, setSemanticKgTimeoutS] = useConfigField<number>('graph_indexing.semantic_kg_llm_timeout_s', 90);
  const [schemaProposalReasoningEffort, setSchemaProposalReasoningEffort] = useConfigField<
    NonNullable<GraphIndexingConfig['schema_proposal_reasoning_effort']>
  >('graph_indexing.schema_proposal_reasoning_effort', 'low');
  const [schemaProposalTimeoutS, setSchemaProposalTimeoutS] = useConfigField<number>(
    'graph_indexing.schema_proposal_timeout_s', 60,
  );
  const [schemaProposalMaxOutputTokens, setSchemaProposalMaxOutputTokens] = useConfigField<number>(
    'graph_indexing.schema_proposal_max_output_tokens', 16384,
  );
  const [astContainsWeight, setAstContainsWeight] = useConfigField<number>('graph_indexing.ast_contains_weight', 1);
  const [astInheritsWeight, setAstInheritsWeight] = useConfigField<number>('graph_indexing.ast_inherits_weight', 1);
  const [astImportsWeight, setAstImportsWeight] = useConfigField<number>('graph_indexing.ast_imports_weight', 1);
  const [astCallsWeight, setAstCallsWeight] = useConfigField<number>('graph_indexing.ast_calls_weight', 1);

  // Figure description (indexing.figures.*). Nested paths: `useConfigField` reads the dotted
  // path off the loaded config and writes `{ figures: { <field>: value } }` into the `indexing`
  // section, which the store and `_deep_merge_dicts` on the server both merge in depth.
  const [figuresEnabled, setFiguresEnabled] = useConfigField<boolean>('indexing.figures.enabled', false);
  const [figuresDescribe, setFiguresDescribe] = useConfigField<boolean>('indexing.figures.describe', true);
  const [figuresClassify, setFiguresClassify] = useConfigField<boolean>('indexing.figures.classify', true);
  const [figuresVisionModel, setFiguresVisionModel] = useConfigField<string>('indexing.figures.vision_model', 'z-ai.glm-5.3-flash');
  const [figuresPromptProfile, setFiguresPromptProfile] = useConfigField<'technical_figure' | 'schematic'>(
    'indexing.figures.prompt_profile',
    'technical_figure'
  );
  const [figuresImagesScale, setFiguresImagesScale] = useConfigField<number>('indexing.figures.images_scale', 2.0);
  const [figuresMinAreaFraction, setFiguresMinAreaFraction] = useConfigField<number>(
    'indexing.figures.min_area_fraction',
    0.02
  );
  const [figuresSkipClasses, setFiguresSkipClasses] = useConfigField<string[]>(
    'indexing.figures.skip_classes',
    FIGURES_SKIP_CLASSES_DEFAULT
  );
  const [figuresMaxCompletionTokens, setFiguresMaxCompletionTokens] = useConfigField<number>(
    'indexing.figures.max_completion_tokens',
    2500
  );
  const [figuresConcurrency, setFiguresConcurrency] = useConfigField<number>('indexing.figures.concurrency', 4);
  const [figuresTimeoutS, setFiguresTimeoutS] = useConfigField<number>('indexing.figures.timeout_s', 90);

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

  // Only vision-capable gateway aliases can describe figures; the run refuses to start
  // otherwise (HTTP 409 figure_vision_alias), so the picker offers nothing else.
  const visionModels = useMemo(
    () => generationModels.filter((model) => Boolean(model.supports_vision)),
    [generationModels]
  );
  const figuresVisionAliasWarning = useMemo(() => {
    if (!figuresEnabled) return '';
    if (generationModels.length === 0) return '';
    if (visionModels.length === 0) {
      return 'No vision-capable alias is available from LiteLLM. Add one to the model catalog before indexing figures.';
    }
    const alias = String(figuresVisionModel || '').trim();
    if (!alias) return 'Choose a vision-capable alias: figure description has no gateway default.';
    if (visionModels.some((model) => String(model.id || '').trim() === alias)) return '';
    if (generationModels.some((model) => String(model.id || '').trim() === alias)) {
      return `Alias '${alias}' is not flagged vision-capable in the model catalog; indexing will refuse to start.`;
    }
    return `Alias '${alias}' is not available from LiteLLM.`;
  }, [figuresEnabled, figuresVisionModel, generationModels, visionModels]);

  // Comma-separated editing buffer for `indexing.figures.skip_classes`: the operator types a
  // raw string, the config keeps the parsed list. Re-seeded only when the persisted list stops
  // matching what the buffer parses to (config load, corpus switch), so typing is never fought.
  const [skipClassesText, setSkipClassesText] = useState<string>(() => (figuresSkipClasses || []).join(', '));
  const skipClassesTextRef = useRef<string>(skipClassesText);
  useEffect(() => {
    const persisted = JSON.stringify(figuresSkipClasses || []);
    if (JSON.stringify(parseSkipClasses(skipClassesTextRef.current)) === persisted) return;
    const next = (figuresSkipClasses || []).join(', ');
    skipClassesTextRef.current = next;
    setSkipClassesText(next);
  }, [figuresSkipClasses]);
  const onSkipClassesChange = useCallback(
    (raw: string) => {
      skipClassesTextRef.current = raw;
      setSkipClassesText(raw);
      setFiguresSkipClasses(parseSkipClasses(raw));
    },
    [setFiguresSkipClasses]
  );

  // (Models loaded via useModels hook below — no manual state needed)

  // Index stats + status
  const [_indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  // A run adopted from the server because it was started outside this tab (API, another
  // operator, a schedule). Progress, current file and events are mirrored by polling.
  const [foreignRun, setForeignRun] = useState(false);
  const foreignRunIdRef = useRef<string>('');
  const foreignEventsSeenRef = useRef(0);
  const localRunRef = useRef(false);
  const localRunIdRef = useRef<string>('');
  const isIndexingRef = useRef(false);
  const [latestRun, setLatestRun] = useState<IndexRunSummary | null>(null);
  const [latestRunEvents, setLatestRunEvents] = useState<IndexRunEvent[]>([]);
  const [latestRunEventTotal, setLatestRunEventTotal] = useState(0);
  const [indexStats, setIndexStats] = useState<IndexStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsExpanded, setStatsExpanded] = useState(false);
  const activeRepoRef = useRef<string>('');
  const statusRequestSeq = useRef(0);
  const statsRequestSeq = useRef(0);
  const statusAbortRef = useRef<AbortController | null>(null);
  const statsAbortRef = useRef<AbortController | null>(null);


  // One corpus source of truth across subtabs. `if (!repos.length)` meant the list was
  // fetched once and then never again, so this tab and Data Quality -- which asks the same
  // store on its own schedule -- could show different corpora, and the drive caught a deleted
  // test corpus still listed on one of them. Asking on entry makes the list belong to the view
  // the operator is looking at; the store drops a call that is already in flight.
  useEffect(() => {
    void loadRepos();
  }, [loadRepos]);

  // Resolve selected corpus path from store
  const activeCorpus = useMemo(() => {
    const id = (activeRepo || '').trim();
    if (!id) return undefined;
    return repos.find(r => r.corpus_id === id || r.slug === id || r.name === id);
  }, [activeRepo, repos]);

  const graphCorpusIsInternal = Boolean(activeCorpus?.internal);
  const graphPolicyLabel = graphCorpusIsInternal
    ? 'Excluded internal corpus'
    : !graphIndexingEnabled
      ? 'Graph disabled'
      : buildCodeGraph
        ? 'Code AST graph'
        : 'Semantic entity graph';
  const semanticGraphActive = !graphCorpusIsInternal && graphIndexingEnabled && !buildCodeGraph;

  const resolvedPath = useMemo(() => String(activeCorpus?.path || ''), [activeCorpus]);
  const effectivePath = useMemo(() => (pathOverride.trim() ? pathOverride.trim() : resolvedPath), [pathOverride, resolvedPath]);

  // The phases the API measured, printed as they are. Deriving the embedding leg by
  // subtracting the others from the range's midpoint made it disagree with the range beside
  // it -- the midpoint of a x0.6/x1.9 band is 1.25x the run, so the embed line came out a
  // quarter of a run too long and could exceed the range's own lower bound.
  const estimateTimeBreakdown = useMemo(() => {
    if (!indexEstimate) return '';
    const embedSeconds = indexEstimate.estimated_seconds_embedding;
    const kgSeconds = indexEstimate.estimated_seconds_semantic_kg;
    const figureSeconds = indexEstimate.estimated_seconds_figures;
    const overheadSeconds = indexEstimate.estimated_seconds_overhead;
    if (embedSeconds == null) return '';
    return [
      `Embed ~${formatDuration(durationMs(Number(embedSeconds)))}`,
      kgSeconds == null ? null : `KG ~${formatDuration(durationMs(Number(kgSeconds)))}`,
      figureSeconds == null ? null : `Figures ~${formatDuration(durationMs(Number(figureSeconds)))}`,
      overheadSeconds == null ? null : `startup ~${formatDuration(durationMs(Number(overheadSeconds)))}`,
    ]
      .filter(Boolean)
      .join(' + ');
  }, [indexEstimate]);

  // Invalidate displayed and in-flight proposals when their sampling/configuration
  // context changes. The API independently validates the authoritative fingerprint.
  const graphSchemaContextKey = JSON.stringify([
    activeRepo, effectivePath, graphCorpusIsInternal,
    config?.graph_indexing, config?.chunking, config?.tokenization, config?.indexing,
  ]);
  useEffect(() => {
    graphSchemaRequestRef.current?.abort();
    graphSchemaRequestRef.current = null;
    setIndexEstimate(null);
    setGraphSchemaProposal(null);
    setGraphSchemaError(null);
    setGraphSchemaLoading(false);
    return () => {
      graphSchemaRequestRef.current?.abort();
      graphSchemaRequestRef.current = null;
    };
  }, [graphSchemaContextKey]);

  useEffect(() => {
    activeRepoRef.current = String(activeRepo || '').trim();
  }, [activeRepo]);

  useEffect(() => {
    return () => {
      statusAbortRef.current?.abort();
      statsAbortRef.current?.abort();
    };
  }, []);

  // Derived model field (based on provider) — via shared hook
  const { currentModel, setCurrentModel, tooltipKey: modelTooltipKey } = useEmbeddingModel();

  // Embedding model catalog (via useModels hook)
  const {
    providers: embedProviders,
    getModelsForProvider: getEmbedModelsForProvider,
    loading: modelsLoading,
    error: modelsError,
    findModel: findEmbedModel,
  } = useModels('EMB', { selectionRole: 'embedding_provider' });
  const { status: embeddingStatus } = useEmbeddingStatus();
  const runtimeEmbeddingProviders = useMemo(
    () =>
      (runtimeCapabilities?.embedding?.providers || [])
        .map((provider) => String(provider.provider || '').trim().toLowerCase())
        .filter(Boolean),
    [runtimeCapabilities]
  );
  const chunkingStrategies = useMemo(
    () =>
      runtimeCapabilities?.chunking?.strategies?.length
        ? runtimeCapabilities.chunking.strategies
        : FALLBACK_CHUNKING_STRATEGIES,
    [runtimeCapabilities]
  );

  const normalizedEmbeddingType = useMemo(
    () => String(embeddingType || '').trim().toLowerCase(),
    [embeddingType]
  );
  const supportedRuntimeProvider = useMemo(
    () => {
      const knownProviders = runtimeEmbeddingProviders.length
        ? runtimeEmbeddingProviders
        : (embedProviders || []).map((provider) => String(provider || '').trim().toLowerCase()).filter(Boolean);
      return knownProviders.includes(normalizedEmbeddingType);
    },
    [embedProviders, normalizedEmbeddingType, runtimeEmbeddingProviders]
  );
  const visibleEmbedProviders = useMemo(() => {
    if (!runtimeEmbeddingProviders.length) return embedProviders;
    const filtered = (embedProviders || []).filter((p) =>
      runtimeEmbeddingProviders.includes(String(p || '').trim().toLowerCase())
    );
    if (!filtered.length) return embedProviders;
    if (normalizedEmbeddingType && !filtered.some((p) => String(p).toLowerCase() === normalizedEmbeddingType)) {
      return [normalizedEmbeddingType, ...filtered];
    }
    return filtered;
  }, [embedProviders, normalizedEmbeddingType, runtimeEmbeddingProviders]);
  const hasIndexedCorpus = useMemo(() => {
    if (!embeddingStatus) return false;
    return Boolean(embeddingStatus.hasIndex && Number(embeddingStatus.totalChunks || 0) > 0);
  }, [embeddingStatus]);
  const contractLocked = useMemo(
    () => hasIndexedCorpus && !isIndexing && !forceReindex,
    [forceReindex, hasIndexedCorpus, isIndexing]
  );

  // Auto-select first model when provider changes and current model is not valid
  const providerEmbedModels = useMemo(() => {
    return getEmbedModelsForProvider(embeddingType);
  }, [getEmbedModelsForProvider, embeddingType]);

  useEffect(() => {
    if (contractLocked) return;
    if (!providerEmbedModels.length) return;
    const existing = String(currentModel || '').trim();
    if (existing && providerEmbedModels.some(m => m.model === existing)) return;
    setCurrentModel(providerEmbedModels[0].model);
  }, [contractLocked, currentModel, providerEmbedModels, setCurrentModel]);

  // If selected model has known dimensions, keep embedding_dim aligned (no hardcoded dims)
  useEffect(() => {
    if (contractLocked) return;
    const hit = findEmbedModel(embeddingType, currentModel);
    const dims = hit?.dimensions;
    if (autoSetDimensions && typeof dims === 'number' && dims > 0 && embeddingDim !== dims) {
      setEmbeddingDim(dims);
    }
  }, [autoSetDimensions, contractLocked, currentModel, embeddingDim, embeddingType, findEmbedModel, setEmbeddingDim]);

  // Resolved tokenizer description (UX-only helper)
  const resolvedTokenizerDesc = useMemo(() => {
    const tok = String(bm25Tokenizer || '').toLowerCase();
    if (!tok) return '—';
    if (tok === 'stemmer') {
      const lang = bm25StemmerLang || '—';
      return `Stemmer (${lang})`;
    }
    if (tok === 'whitespace') return 'Whitespace-ish (no stemming)';
    if (tok === 'lowercase') return 'Lowercase (no stemming)';
    return tok;
  }, [bm25Tokenizer, bm25StemmerLang]);

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

  const tokenizationCompatibility = useMemo(() => {
    if (skipDense) return { ok: true as const, message: '' };
    if (String(embeddingBackend || '').toLowerCase() !== 'provider') return { ok: true as const, message: '' };
    const provider = normalizedEmbeddingType;
    const strategy = String(tokenizationStrategy || '').trim().toLowerCase();
    const required =
      (runtimeCapabilities?.embedding?.providers || [])
        .find((item) => String(item.provider || '').trim().toLowerCase() === provider)
        ?.tokenizer_strategies || [];
    if (!required.length) return { ok: true as const, message: '' };
    if (required.includes(strategy)) return { ok: true as const, message: '' };
    return {
      ok: false as const,
      message: `embedding_type=${provider} requires tokenization.strategy=${required.join(' or ')}`,
    };
  }, [embeddingBackend, normalizedEmbeddingType, runtimeCapabilities, skipDense, tokenizationStrategy]);

  const indexBlockingReason = useMemo(() => {
    const semanticAlias = String(semanticKgLlmModel || '').trim();
    if (
      semanticGraphActive
      && semanticAlias
      && !generationModels.some((model) => String(model.id || '').trim() === semanticAlias)
    ) {
      return `Semantic KG alias '${semanticAlias}' is not available from LiteLLM.`;
    }
    if (!skipDense && String(embeddingBackend || '').toLowerCase() === 'provider' && !supportedRuntimeProvider) {
      return `Embedding provider '${normalizedEmbeddingType}' is not supported by the current backend runtime.`;
    }
    if (!tokenizationCompatibility.ok) {
      return tokenizationCompatibility.message;
    }
    if (embeddingStatus?.isMismatched && !forceReindex) {
      return 'Embedding/sparse contract does not match the existing index. Enable Force reindex to migrate.';
    }
    return '';
  }, [
    embeddingBackend,
    embeddingStatus?.isMismatched,
    forceReindex,
    normalizedEmbeddingType,
    generationModels,
    semanticGraphActive,
    semanticKgLlmModel,
    skipDense,
    supportedRuntimeProvider,
    tokenizationCompatibility,
  ]);

  // Two real config keys govern one behaviour -- chunking.max_indexable_file_size (bytes) and
  // indexing.index_max_file_size_mb (MB) -- and the indexer skips a file that exceeds EITHER,
  // i.e. the smaller wins. Both fields carry this line so an operator editing one is never
  // left guessing whether the other follows.
  // The vision alias sat next to an embedding model that shows its catalog price while
  // showing none of its own. Same catalog fields, same shape of line -- what the run will be
  // charged per 1k tokens, from the row behind the alias.
  // Which documents lost figures, from the run's own per-document events. The end-of-run
  // total ("figures_failed=10") named no document, so there was nowhere to look; the
  // extractor records counts per document, so that is the granularity offered here.
  const figureOutcomes = useMemo(() => {
    const rows: Array<{ file: string; described: number; failed: number; undescribed: number }> = [];
    for (const ev of latestRunEvents) {
      const meta = (ev.meta ?? {}) as Record<string, unknown>;
      if (meta.kind !== 'figure_outcome') continue;
      const file = String(meta.file || '').trim();
      if (!file) continue;
      rows.push({
        file,
        described: Number(meta.described ?? 0),
        failed: Number(meta.failed ?? 0),
        undescribed: Number(meta.undescribed ?? 0),
      });
    }
    return rows;
  }, [latestRunEvents]);

  const figureFailureCount = useMemo(
    () => figureOutcomes.reduce((sum, row) => sum + row.failed, 0),
    [figureOutcomes]
  );

  const visionAliasPricing = useMemo(() => {
    const alias = String(figuresVisionModel || '').trim();
    if (!alias) return '';
    const model = visionModels.find((m) => String(m.id || '').trim() === alias);
    if (!model) return '';
    const input = model.input_per_1k;
    const output = model.output_per_1k;
    if (input == null && output == null) return 'No catalog price for this alias.';
    return `Cost: $${Number(input ?? 0).toFixed(5)}/1k in · $${Number(output ?? 0).toFixed(5)}/1k out`;
  }, [figuresVisionModel, visionModels]);

  const effectiveFileSizeLimit = useMemo(() => {
    const bytesLimit = Math.max(0, Number(maxIndexableFileSize) || 0);
    const mbLimit = Math.max(0, Number(indexMaxFileSizeMb) || 0) * 1024 * 1024;
    const effective = Math.min(bytesLimit, mbLimit);
    const source = bytesLimit <= mbLimit ? 'Chunking' : 'Indexing';
    return `Files above ${formatBytes(effective)} are skipped — the smaller of the two ceilings wins (currently ${source}).`;
  }, [indexMaxFileSizeMb, maxIndexableFileSize]);

  const canIndex = useMemo(() => {
    const rid = String(activeRepo || '').trim();
    const pathOk = Boolean(effectivePath && effectivePath.trim());
    const schemaReady = !semanticGraphActive || Boolean(graphSchemaProposal);
    return Boolean(rid && pathOk && schemaReady && !isIndexing && !indexBlockingReason);
  }, [activeRepo, effectivePath, graphSchemaProposal, indexBlockingReason, isIndexing, semanticGraphActive]);

  const refreshStatus = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid) {
      setIndexStatus(null);
      return;
    }
    const seq = ++statusRequestSeq.current;
    statusAbortRef.current?.abort();
    const controller = new AbortController();
    statusAbortRef.current = controller;
    try {
      const data = await fetchIndexStatus(rid, { signal: controller.signal, quiet: true });
      if (seq !== statusRequestSeq.current) return;
      if (activeRepoRef.current !== rid) return;
      setIndexStatus(data);
    } catch (e) {
      if ((e as Error)?.name === 'AbortError') return;
    }
  }, [activeRepo, fetchIndexStatus]);

  const loadStats = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid) {
      setIndexStats(null);
      return;
    }
    const seq = ++statsRequestSeq.current;
    statsAbortRef.current?.abort();
    const controller = new AbortController();
    statsAbortRef.current = controller;
    setStatsLoading(true);
    try {
      const data = await fetchIndexStats(rid, { signal: controller.signal, quiet: true });
      if (seq !== statsRequestSeq.current) return;
      if (activeRepoRef.current !== rid) return;
      setIndexStats(data);
    } catch (e) {
      if ((e as Error)?.name === 'AbortError') return;
      setIndexStats(null);
    } finally {
      if (seq === statsRequestSeq.current && activeRepoRef.current === rid) {
        setStatsLoading(false);
      }
    }
  }, [activeRepo, fetchIndexStats]);

  const resetTerminal = useCallback((title: string) => {
    const t = terminalRef.current;
    t?.show();
    t?.clear();
    t?.setTitle(title);
  }, []);

  const adoptLocalRun = useCallback(
    async (rid: string, runId: string) => {
      try {
        const latestResp = await fetch(api(`index/${encodeURIComponent(rid)}/runs/latest`));
        if (!latestResp.ok) return;
        const latest: IndexRunSummary = await latestResp.json();
        if (String(latest.run_id || '') !== runId || localRunIdRef.current !== runId) return;
        setLatestRun(latest);
      } catch {
        // the stream keeps the terminal truthful; the panel adopts the run on the next line
      }
    },
    [api]
  );

  const loadLatestRunReplay = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid || isIndexingRef.current) {
      return;
    }
    try {
      const latestResp = await fetch(api(`index/${encodeURIComponent(rid)}/runs/latest`));
      if (!latestResp.ok) {
        setLatestRun(null);
        setLatestRunEvents([]);
        return;
      }
      const latest: IndexRunSummary = await latestResp.json();
      setLatestRun(latest);

      const eventsResp = await fetch(
        api(`index/${encodeURIComponent(rid)}/runs/${encodeURIComponent(String(latest.run_id || ''))}/events?limit=500`)
      );
      if (!eventsResp.ok) {
        setLatestRunEvents([]);
        return;
      }
      const page: IndexRunEventPage = await eventsResp.json();
      const events: IndexRunEvent[] = Array.isArray(page.events) ? page.events : [];
      setLatestRunEvents(events);
      setLatestRunEventTotal(Number(page.total ?? events.length));

      if (events.length > 0) {
        resetTerminal(`Indexing Output (${String(latest.run_id || '').slice(0, 12)})`);
        for (const ev of collapseHeartbeats(events)) {
          const msg = String(ev.message || '').trim();
          if (!msg) continue;
          if (ev.type === 'error') {
            terminalRef.current?.appendLine(`\x1b[31m${msg}\x1b[0m`);
            continue;
          }
          if (ev.type === 'warning') {
            terminalRef.current?.appendLine(`\x1b[33m${msg}\x1b[0m`);
            continue;
          }
          if (ev.type === 'complete') {
            terminalRef.current?.appendLine(`\x1b[32m${msg}\x1b[0m`);
            continue;
          }
          terminalRef.current?.appendLine(msg);
        }
      }
      if (latest.status === 'error') {
        setTerminalVisible(true);
      }
    } catch {
      // best effort only
    }
  }, [activeRepo, api, resetTerminal]);

  useEffect(() => {
    isIndexingRef.current = isIndexing;
  }, [isIndexing]);

  useEffect(() => {
    void refreshStatus();
    void loadStats();
    void loadLatestRunReplay();
  }, [refreshStatus, loadStats, loadLatestRunReplay]);

  // Poll the corpus status so a run started anywhere (API, another operator, a schedule)
  // shows up here exactly like one started from this tab: progress bar, current file,
  // replayed + live events, Stop button, Start disabled. Without this the tab only knew
  // about runs it had started itself.
  useEffect(() => {
    const rid = String(activeRepo || '').trim();
    if (!rid) return;
    let cancelled = false;
    const appendEvents = (events: IndexRunEvent[]) => {
      const fresh = events.slice(foreignEventsSeenRef.current);
      for (const ev of fresh) {
        const msg = String(ev.message || '').trim();
        if (!msg) continue;
        if (ev.type === 'error') terminalRef.current?.appendLine(`\x1b[31m${msg}\x1b[0m`);
        else if (ev.type === 'warning') terminalRef.current?.appendLine(`\x1b[33m${msg}\x1b[0m`);
        else if (ev.type === 'complete') terminalRef.current?.appendLine(`\x1b[32m${msg}\x1b[0m`);
        else terminalRef.current?.appendLine(msg);
      }
      foreignEventsSeenRef.current = events.length;
    };
    // Returns whether a run is live, which decides how soon to look again.
    const tick = async (): Promise<boolean> => {
      if (localRunRef.current) return true; // this tab's own stream owns the UI
      let data: IndexStatus | null = null;
      try {
        data = await fetchIndexStatus(rid, { quiet: true });
      } catch {
        return false;
      }
      if (cancelled || activeRepoRef.current !== rid || !data) return false;
      setIndexStatus(data);
      if (data.status === 'indexing') {
        // A single-file corpus reports progress 1.0 while its file is still converting; never
        // show 100% for a run that has not finished.
        const pct = Math.min(99, Math.max(0, Math.round(Number(data.progress || 0) * 100)));
        const file = String(data.current_file || '').trim();
        setIsIndexing(true);
        setForeignRun(true);
        setProgress({ current: pct, total: 100, status: file ? `Indexing ${file}` : 'Indexing…' });
        try {
          const latestResp = await fetch(api(`index/${encodeURIComponent(rid)}/runs/latest`));
          if (!latestResp.ok) return true;
          const latest: IndexRunSummary = await latestResp.json();
          const runId = String(latest.run_id || '');
          if (!runId) return true;
          if (runId !== foreignRunIdRef.current) {
            foreignRunIdRef.current = runId;
            foreignEventsSeenRef.current = 0;
            setLatestRun(latest);
            setTerminalVisible(true);
            resetTerminal(`Indexing: ${rid} (run ${runId.slice(0, 12)}, started outside this tab)`);
          }
          const eventsResp = await fetch(
            api(`index/${encodeURIComponent(rid)}/runs/${encodeURIComponent(runId)}/events?limit=500`)
          );
          if (!eventsResp.ok) return true;
          const page: IndexRunEventPage = await eventsResp.json();
          const events: IndexRunEvent[] = Array.isArray(page.events) ? page.events : [];
          if (cancelled) return true;
          appendEvents(events);
          setLatestRunEvents(events);
          setLatestRunEventTotal(Number(page.total ?? events.length));
        } catch {
          // best effort only
        }
        return true;
      } else if (foreignRunIdRef.current) {
        // The adopted run ended while we were watching it.
        foreignRunIdRef.current = '';
        foreignEventsSeenRef.current = 0;
        setForeignRun(false);
        setIsIndexing(false);
        isIndexingRef.current = false;
        setProgress(
          data.status === 'complete'
            ? { current: 100, total: 100, status: 'Complete' }
            : data.status === 'error'
              ? { current: 0, total: 100, status: `Error: ${String(data.error || '')}` }
              : { current: 0, total: 100, status: 'Cancelled' }
        );
        void loadStats();
        void loadLatestRunReplay();
      }
      return false;
    };
    // A fixed 3 s interval kept asking about a run that reached a terminal state hours ago:
    // 307 requests to /api/index/* in 13 minutes on an idle tab. The tab still has to notice a
    // run started elsewhere, so idle backs off rather than stopping: one poll every 30 s when
    // nothing is running, 3 s while a run is live.
    let timer: number | undefined;
    const loop = async () => {
      const live = await tick();
      if (cancelled) return;
      timer = window.setTimeout(() => void loop(), live ? INDEX_POLL_ACTIVE_MS : INDEX_POLL_IDLE_MS);
    };
    void loop();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
      if (foreignRunIdRef.current) {
        foreignRunIdRef.current = '';
        foreignEventsSeenRef.current = 0;
        setForeignRun(false);
        setIsIndexing(false);
      }
    };
  }, [activeRepo, api, fetchIndexStatus, loadLatestRunReplay, loadStats, resetTerminal]);

  const handleStopIndex = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid) return;
    try {
      const stopped = await stopIndex(rid, { terminalId: 'indexing_terminal' });
      setIsIndexing(false);
      if (stopped.status === 'complete') {
        // The stop landed after the generation manifest was committed: the run is
        // complete and the new index is live; only best-effort retirement was cut short.
        setProgress((prev) => ({ ...prev, status: 'Complete', current: 100, total: 100 }));
        terminalRef.current?.appendLine(`\x1b[32m✓ Stop arrived after the commit: the new index is live\x1b[0m`);
      } else {
        setProgress((prev) => ({ ...prev, status: 'Cancelled' }));
        terminalRef.current?.appendLine(`\x1b[33m⚠ Indexing cancelled by user\x1b[0m`);
      }
      await loadStats();
      await refreshStatus();
      await loadLatestRunReplay();
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to cancel indexing';
      setErrorBanner(msg);
      terminalRef.current?.appendLine(`\x1b[31mFailed to cancel: ${msg}\x1b[0m`);
    }
  }, [activeRepo, loadLatestRunReplay, loadStats, refreshStatus, stopIndex]);

  const handleGenerateGraphSchema = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid || !semanticGraphActive) return;
    graphSchemaRequestRef.current?.abort();
    const controller = new AbortController();
    graphSchemaRequestRef.current = controller;
    setGraphSchemaLoading(true);
    setGraphSchemaError(null);
    try {
      await flushPendingPatches();
      if (controller.signal.aborted || graphSchemaRequestRef.current !== controller) return;
      const proposal = await indexingApi.proposeGraphSchema(
        rid,
        { force_refresh: false },
        { signal: controller.signal, timeoutMs: (schemaProposalTimeoutS + 10) * 1000 },
      );
      if (controller.signal.aborted || graphSchemaRequestRef.current !== controller) return;
      setGraphSchemaProposal(proposal);
    } catch (error) {
      if (controller.signal.aborted || graphSchemaRequestRef.current !== controller) return;
      const hint = axios.isAxiosError<GraphSchemaProposalFailureResponse>(error)
        ? error.response?.data?.detail?.operator_hint
        : undefined;
      setGraphSchemaProposal(null);
      setGraphSchemaError({
        message: errorDetail(error),
        operatorHint: typeof hint === 'string' ? hint : '',
      });
    } finally {
      if (graphSchemaRequestRef.current === controller) {
        graphSchemaRequestRef.current = null;
        setGraphSchemaLoading(false);
      }
    }
  }, [activeRepo, flushPendingPatches, schemaProposalTimeoutS, semanticGraphActive]);

  const handleStartIndex = useCallback(async (requestedGraphOverrideReason?: string) => {
    const rid = String(activeRepo || '').trim();
    const auditedOverrideReason = String(requestedGraphOverrideReason || '').trim();
    if (!rid) {
      setErrorBanner('No corpus is selected. Pick one in the corpus selector before indexing.');
      return;
    }
    if (!effectivePath.trim()) {
      // The path comes from the corpus registry, so an empty one means the registry has not
      // loaded or does not hold this corpus. Returning quietly here is what made Index Now
      // look dead: no dialog, no error, no toast.
      setErrorBanner(
        `No source path resolved for "${rid}". The corpus registry has no path for it — ` +
          'reload the corpus list, or set the path override below.'
      );
      return;
    }

    try {
      // Flush any pending debounced config patches so the backend reads
      // up-to-date settings when it loads scoped config for this index run.
      await flushPendingPatches();

      const approvedSchemaHash =
        graphSchemaProposal?.schema_hash ??
        (auditedOverrideReason ? latestRun?.graph_metadata?.schema_hash ?? null : null);
      if (semanticGraphActive && !approvedSchemaHash) {
        setErrorBanner('Generate and review the current graph schema before semantic indexing.');
        return;
      }

      const body: IndexRequest = {
        corpus_id: rid,
        repo_path: effectivePath,
        force_reindex: Boolean(forceReindex),
        approved_graph_schema_hash: approvedSchemaHash,
        graph_empty_override_reason: auditedOverrideReason || null,
      };

      setErrorBanner(null);
      setEstimateLoading(true);
      let estimate: ReadyIndexEstimate;
      try {
        // Waiting out a cold or under-sampled estimator lives in the api layer, so this
        // component cannot receive a payload with no numbers in it.
        estimate = await indexingApi.estimate(body, {
          // Only reached while warming: an insufficient sample throws instead of waiting.
          onWaiting: (pending) =>
            setEstimateWarmup(
              `Preparing the estimator (about ${Math.max(
                1,
                Math.ceil(Number(pending.warmup_seconds_remaining ?? 0))
              )}s)…`
            ),
        });
        setIndexEstimate(estimate);
      } catch (e) {
        // The estimate IS the consent gate: it is the only place the operator sees the file
        // count, the chunk count and what the run will cost before it spends anything. A run
        // that starts without it is a run nobody agreed to, so a failed estimate stops here
        // and says why.
        // The estimate samples the corpus through the real tokenizer, which loads its model
        // on first use in a fresh API process -- so the first estimate after a restart can
        // outrun the client's 30s timeout even though nothing is wrong. Blocking is still
        // right (no run without consent), but the operator has to be told to try again.
        const timedOut =
          (e as { code?: string } | null)?.code === 'ECONNABORTED' ||
          /timeout/i.test(e instanceof Error ? e.message : '');
        setErrorBanner(
          `Index estimate failed for "${rid}" (${effectivePath}): ` +
            `${errorDetail(e)}. Indexing was not started.` +
            (timedOut
              ? ' The first estimate after a service restart is slow because the tokenizer loads on first use — click Index Now again.'
              : '')
        );
        return;
      } finally {
        setEstimateLoading(false);
        setEstimateWarmup('');
      }

      // Scope for the dialog copy. The estimate is always present here -- a failed one
      // returned above rather than falling through to the run.
      {
        const totalCostUsd = estimate.total_cost_usd ?? estimate.embedding_cost_usd;
        const embedCostUsd = estimate.embedding_cost_usd;
        const semanticKgCostUsd = estimate.semantic_kg_cost_usd;
        const figureCostUsd = estimate.figure_description_cost_usd;
        const cost = totalCostUsd == null ? 'N/A' : formatCurrency(Number(totalCostUsd || 0));
        const costBreakdown =
          semanticKgCostUsd == null && figureCostUsd == null
            ? null
            : [
                `Embed ${embedCostUsd == null ? 'N/A' : formatCurrency(Number(embedCostUsd || 0))}`,
                semanticKgCostUsd == null ? null : `Semantic KG ${formatCurrency(Number(semanticKgCostUsd || 0))}`,
                figureCostUsd == null
                  ? null
                  : `Figures ≤ ${formatFigureCostUsd(Number(figureCostUsd || 0))}${
                      estimate.estimated_figures != null
                        ? ` (~${formatNumber(Number(estimate.estimated_figures))} figures)`
                        : ''
                    }`,
              ]
                .filter(Boolean)
                .join(' + ');
        // One model, so the range and the breakdown can never contradict each other: the
        // point estimate is the sum of the phases printed beside it, and the range is that
        // same number scaled.
        const pointSeconds = estimate.estimated_seconds;
        const time =
          pointSeconds != null &&
          estimate.estimated_seconds_low != null &&
          estimate.estimated_seconds_high != null
            ? `~${formatDuration(durationMs(Number(pointSeconds)))} (${formatDuration(
                durationMs(Number(estimate.estimated_seconds_low))
              )}–${formatDuration(durationMs(Number(estimate.estimated_seconds_high)))})`
            : 'N/A';
        const semanticKgSeconds = estimate.estimated_seconds_semantic_kg;
        const figureSeconds = estimate.estimated_seconds_figures;
        const embedSeconds = estimate.estimated_seconds_embedding;
        const overheadSeconds = estimate.estimated_seconds_overhead;
        const timeBreakdown = [
          embedSeconds == null ? null : `Embed ~${formatDuration(durationMs(Number(embedSeconds)))}`,
          semanticKgSeconds == null ? null : `Semantic KG ~${formatDuration(durationMs(Number(semanticKgSeconds)))}`,
          figureSeconds == null ? null : `Figures ~${formatDuration(durationMs(Number(figureSeconds)))}`,
          overheadSeconds == null ? null : `startup ~${formatDuration(durationMs(Number(overheadSeconds)))}`,
        ]
          .filter(Boolean)
          .join(' + ');
        const msg = [
          `Index estimate for "${rid}"`,
          `Files: ${formatNumber(Number(estimate.total_files || 0))} • Size: ${formatBytes(
            Number(estimate.total_size_bytes || 0)
          )}`,
          `Tokens (est): ${formatNumber(Number(estimate.estimated_total_tokens || 0))} (${formatNumber(
            Number(estimate.estimated_tokens_low)
          )}–${formatNumber(Number(estimate.estimated_tokens_high))})`,
          `Chunks (est): ${formatNumber(Number(estimate.estimated_total_chunks || 0))} (${formatNumber(
            Number(estimate.estimated_chunks_low)
          )}–${formatNumber(Number(estimate.estimated_chunks_high))})`,
          `Measured by chunking ${formatNumber(Number(estimate.sampled_files))} sampled files in ${formatDuration(
            durationMs(Number(estimate.elapsed_seconds))
          )} • band ±${Math.round(Number(estimate.estimate_relative_error) * 100)}%`,
          `Embedding: ${String(estimate.embedding_provider || '—')}/${String(estimate.embedding_model || '—')} (${
            estimate.embedding_backend
          }, skip_dense=${estimate.skip_dense ? 'yes' : 'no'})`,
          `Cost (est): ${cost} • Time (est): ${time}`,
          ...(costBreakdown ? [`Cost breakdown: ${costBreakdown}`] : []),
          ...(timeBreakdown ? [`Time breakdown (est): ${timeBreakdown}`] : []),
          ...(auditedOverrideReason
            ? [
                'AUDITED ENTITY-SPARSE OVERRIDE: this retry may promote only the complete chunk/vector generation. Graph retrieval remains disabled.',
                `Reason: ${auditedOverrideReason}`,
                'The API accepts this only through an authenticated proxy Remote-User and only when the sole failures are zero entities/semantic relationships after complete extraction.',
              ]
            : []),
          // A run does not add to the live index, it replaces it: the new generation is
          // published on commit and the current one is retired.
          ...(hasIndexedCorpus
            ? [
                forceReindex
                  ? 'This run builds a replacement generation and switches the active index after validation. If you changed embedding or sparse settings, searches may be unavailable until the rebuild succeeds.'
                  : 'On commit this run publishes a new generation and retires the one now serving searches.',
              ]
            : []),
        ].join('\n');

        const proceed = await confirmDialog({
          title: auditedOverrideReason ? 'Retry with audited sparse-graph override?' : 'Start indexing?',
          message: msg,
          confirmLabel: auditedOverrideReason ? 'Re-index without graph retrieval' : 'Start indexing',
          danger: Boolean(auditedOverrideReason),
        });
        if (!proceed) {
          return;
        }
      }

      localRunRef.current = true;
      localRunIdRef.current = '';
      setIsIndexing(true);
      setForeignRun(false);
      // The panel must never show the previous run's id and graph verdict under the new
      // run's badge (Task 8 drive observation D2): drop the replayed run now and adopt the
      // new run as soon as the stream names it.
      setLatestRun(null);
      setLatestRunEvents([]);
      setLatestRunEventTotal(0);
      setProgress({ current: 0, total: 100, status: 'Starting...' });
      setTerminalVisible(true);
      resetTerminal(`Indexing: ${rid}`);

      terminalRef.current?.appendLine(`🚀 Starting indexing for ${rid}`);
      terminalRef.current?.appendLine(`   Provider: ${String(embeddingType || '')}, Model: ${String(currentModel || '')}`);
      terminalRef.current?.appendLine(`   Chunk Size: ${chunkSize}, Strategy: ${chunkingStrategy}`);
      terminalRef.current?.appendLine(`   Graph indexing: ${graphIndexingEnabled ? 'enabled' : 'disabled'} • Skip dense: ${skipDense ? 'yes' : 'no'}`);
      if (auditedOverrideReason) {
        terminalRef.current?.appendLine(`   Audited sparse override requested: ${auditedOverrideReason}`);
      }

      const st = await startAndStream(body, {
        terminalId: 'indexing_terminal',
        onLine: (line) => {
          terminalRef.current?.appendLine(line);
          const started = /run_id=([0-9a-f]{32})/.exec(String(line || ''));
          if (started && started[1] !== localRunIdRef.current) {
            localRunIdRef.current = started[1];
            void adoptLocalRun(rid, started[1]);
          }
        },
        onProgress: (percent, message) => {
          setProgress({ current: percent, total: 100, status: message || `Progress: ${percent}%` });
          terminalRef.current?.updateProgress(percent, message);
        },
        onError: (err) => {
          terminalRef.current?.appendLine(`\x1b[31mERROR: ${err}\x1b[0m`);
          setProgress((prev) => ({ ...prev, status: `Error: ${err}` }));
          localRunRef.current = false;
          setIsIndexing(false);
          void loadLatestRunReplay();
        },
        onComplete: () => {
          terminalRef.current?.updateProgress(100, 'Complete');
          terminalRef.current?.appendLine(`\x1b[32m✓ Indexing complete!\x1b[0m`);
          setProgress({ current: 100, total: 100, status: 'Complete' });
          localRunRef.current = false;
          setIsIndexing(false);
          void loadStats();
          void refreshStatus();
          void loadLatestRunReplay();
        },
        onCancelled: () => {
          terminalRef.current?.appendLine(`\x1b[33m⚠ Indexing cancelled\x1b[0m`);
          setProgress((prev) => ({ ...prev, status: 'Cancelled' }));
          localRunRef.current = false;
          setIsIndexing(false);
          void loadStats();
          void refreshStatus();
          void loadLatestRunReplay();
        },
      });
      setIndexStatus(st);
      if (auditedOverrideReason) setGraphOverrideReason('');
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Indexing failed';
      setErrorBanner(msg);
      terminalRef.current?.appendLine(`\x1b[31mFailed: ${msg}\x1b[0m`);
      localRunRef.current = false;
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
    flushPendingPatches,
    forceReindex,
    graphIndexingEnabled,
    graphSchemaProposal,
    hasIndexedCorpus,
    loadLatestRunReplay,
    loadStats,
    latestRun,
    resetTerminal,
    refreshStatus,
    skipDense,
    startAndStream,
    semanticGraphActive,
  ]);

  const handleSparseGraphOverride = useCallback(async () => {
    const reason = graphOverrideReason.trim();
    if (reason.length < 20) {
      setErrorBanner('Explain the entity-sparse exception in at least 20 visible characters.');
      return;
    }
    await handleStartIndex(reason);
  }, [graphOverrideReason, handleStartIndex]);

  const handleDeleteIndex = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid) return;
    const proceed = await confirmDialog({
      title: 'Delete index',
      message:
        `Permanently delete the index for corpus "${rid}". This removes the stored chunks ` +
        `and chunk summaries, the dense and sparse Qdrant generations, and the Neo4j graph ` +
        `for this corpus. The source documents are not touched. This cannot be undone.`,
      confirmLabel: 'Delete index',
      danger: true,
      requireTyped: { expected: rid, label: `Type the corpus id "${rid}" to confirm deletion` },
    });
    if (!proceed) return;

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
      setLatestRun(null);
      setLatestRunEvents([]);
      await loadStats();
      await refreshStatus();
    } catch (e) {
      setErrorBanner(e instanceof Error ? e.message : 'Delete failed');
    }
  }, [activeRepo, api, loadStats, refreshStatus]);

  const graphRunMetadata = latestRun?.graph_metadata ?? null;
  const graphFailureCodes = Array.isArray(latestRun?.graph_failure_codes)
    ? latestRun.graph_failure_codes
    : [];
  const graphOverrideEligible = Boolean(
    latestRun?.status === 'error' &&
      graphRunMetadata?.policy === 'semantic' &&
      graphFailureCodes.length > 0 &&
      graphFailureCodes.every(
        (code) => code === 'zero_entities' || code === 'zero_semantic_relationships'
      ) &&
      graphRunMetadata.extraction.selected_chunks > 0 &&
      graphRunMetadata.extraction.attempted_chunks === graphRunMetadata.extraction.selected_chunks &&
      graphRunMetadata.extraction.succeeded_chunks === graphRunMetadata.extraction.selected_chunks &&
      graphRunMetadata.extraction.failed_chunks === 0 &&
      graphRunMetadata.extraction.truncated_chunks === 0
  );

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
          Corpus Indexing
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
          Configure how the selected corpus is chunked, embedded, sparse-tokenized, and graph-built. Every
          setting here applies to that corpus only, whatever it holds: documents, email, or code.
        </p>
      </div>

      <SyntheticCallout context="indexing" />

      {errorBanner && (
        <div
          data-testid="index-error-banner"
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

      {(_indexStatus || latestRun) && (
        <div
          style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '12px 14px',
            marginBottom: '16px',
          }}
          data-testid="index-run-status-panel"
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
              {isIndexing ? 'Current run' : 'Last run status'}
            </span>
            <span
              style={{
                fontSize: '11px',
                fontWeight: 800,
                padding: '4px 8px',
                borderRadius: '999px',
                border: '1px solid var(--line)',
                color:
                  (_indexStatus?.status || latestRun?.status) === 'error'
                    ? 'var(--error)'
                    : (_indexStatus?.status || latestRun?.status) === 'complete'
                      ? 'var(--ok)'
                      : (_indexStatus?.status || latestRun?.status) === 'indexing'
                        ? 'var(--link)'
                        : 'var(--fg)',
              }}
              data-testid="index-run-status-pill"
            >
              {String(_indexStatus?.status || latestRun?.status || 'idle')}
            </span>
            {latestRun?.run_id ? (
              <span
                data-testid="index-run-id"
                style={{ fontSize: '11px', color: 'var(--fg-muted)', fontFamily: 'var(--font-mono)' }}
              >
                run_id: {String(latestRun.run_id)}
              </span>
            ) : null}
            {latestRunEvents.length > 0 ? (
              <span data-testid="index-run-event-count" style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
                {latestRunEventTotal > latestRunEvents.length
                  ? `showing the most recent ${formatNumber(latestRunEvents.length)} of ${formatNumber(
                      latestRunEventTotal
                    )} events`
                  : `${formatNumber(latestRunEvents.length)} ${isIndexing ? 'events so far' : 'replayed events'}`}
              </span>
            ) : null}
            {foreignRun ? (
              <span
                data-testid="index-run-foreign-note"
                style={{ fontSize: '11.5px', color: 'var(--fg-muted)' }}
              >
                started outside this tab (API, another operator, or a schedule) — progress mirrored from the server
              </span>
            ) : null}
          </div>


          {graphRunMetadata && (
            <div
              data-testid="index-run-graph-telemetry"
              style={{
                marginTop: '10px',
                padding: '10px 12px',
                borderRadius: '8px',
                border: `1px solid ${latestRun?.graph_promotable === false ? 'var(--error)' : 'var(--line)'}`,
                background: latestRun?.graph_promotable === false ? 'rgba(var(--error-rgb), 0.08)' : 'var(--bg-elev2)',
                fontSize: '12px',
                color: 'var(--fg)',
              }}
            >
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', marginBottom: '8px' }}>
                <strong>Graph generation</strong>
                <span data-testid="index-run-graph-policy">policy: {graphRunMetadata.policy}</span>
                <span
                  data-testid="index-run-graph-verdict"
                  style={{
                    fontWeight: 800,
                    color:
                      latestRun?.graph_promotable === false
                        ? 'var(--error)'
                        : latestRun?.graph_promotable == null
                          ? 'var(--fg-muted)'
                        : graphRunMetadata.partial
                          ? 'var(--warn)'
                          : 'var(--ok)',
                  }}
                >
                  {latestRun?.graph_promotable === false
                    ? 'PROMOTION REFUSED'
                    : latestRun?.graph_promotable == null
                      ? 'PROMOTION NOT EVALUATED'
                    : graphRunMetadata.partial
                      ? 'PARTIAL CHUNK-ONLY OVERRIDE'
                      : 'PROMOTABLE'}
                </span>
              </div>
              {graphRunMetadata.schema_hash ? (
                <div style={{ marginBottom: '6px', color: 'var(--fg-muted)', fontFamily: 'var(--font-mono)', wordBreak: 'break-all' }}>
                  schema: {graphRunMetadata.schema_hash}
                </div>
              ) : null}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(185px, 1fr))',
                  gap: '4px 14px',
                }}
              >
                <span>
                  Chunks: {formatNumber(graphRunMetadata.extraction.selected_chunks)} selected /{' '}
                  {formatNumber(graphRunMetadata.extraction.attempted_chunks)} attempted /{' '}
                  {formatNumber(graphRunMetadata.extraction.succeeded_chunks)} succeeded
                </span>
                <span>
                  Extraction failures: {formatNumber(graphRunMetadata.extraction.failed_chunks)} failed /{' '}
                  {formatNumber(graphRunMetadata.extraction.truncated_chunks)} truncated
                </span>
                <span>Entities extracted: {formatNumber(graphRunMetadata.extraction.extracted_entities)}</span>
                <span>Entities resolved: {formatNumber(graphRunMetadata.resolution.resolved_nodes)}</span>
                <span>Entities merged: {formatNumber(graphRunMetadata.resolution.merged_nodes)}</span>
                <span>
                  Semantic/AST relations: {formatNumber(graphRunMetadata.extraction.semantic_relationships)}
                </span>
                <span>
                  Provenance links: {formatNumber(graphRunMetadata.extraction.from_chunk_relationships)}
                </span>
                <span>
                  Duplicate groups: {formatNumber(graphRunMetadata.resolution.unresolved_duplicate_groups)}
                </span>
                <span>
                  Communities:{' '}
                  {graphRunMetadata.communities
                    ? `${formatNumber(graphRunMetadata.communities.community_count)} (${graphRunMetadata.communities.algorithm})`
                    : 'not run yet'}
                </span>
              </div>
              {graphFailureCodes.length > 0 ? (
                <div data-testid="index-run-graph-failure-codes" style={{ marginTop: '8px', color: 'var(--error)' }}>
                  Failed invariants: {graphFailureCodes.join(', ')}
                </div>
              ) : null}
              {graphRunMetadata.override ? (
                <div data-testid="index-run-graph-override-audit" style={{ marginTop: '8px', color: 'var(--warn)' }}>
                  Override by {graphRunMetadata.override.actor} at {new Date(graphRunMetadata.override.created_at).toLocaleString()}:
                  {' '}{graphRunMetadata.override.reason}
                </div>
              ) : null}
            </div>
          )}

          {graphOverrideEligible && (
            <div
              data-testid="index-run-graph-override"
              style={{
                marginTop: '10px',
                padding: '10px 12px',
                borderRadius: '8px',
                border: '1px solid var(--warn)',
                background: 'rgba(var(--warn-rgb), 0.08)',
              }}
            >
              <div style={{ fontWeight: 700, fontSize: '12px', marginBottom: '6px' }}>
                Authenticated entity-sparse retry
              </div>
              <div style={{ fontSize: '11.5px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
                Available only because the full approved extraction succeeded and found no graph. The retry promotes chunks and vectors only; graph retrieval stays disabled. The proxy identity, reason, timestamp, and telemetry are persisted.
              </div>
              <textarea
                data-testid="index-run-graph-override-reason"
                value={graphOverrideReason}
                onChange={(event) => setGraphOverrideReason(event.target.value)}
                placeholder="Explain why this reviewed corpus is intentionally entity sparse (minimum 20 characters)"
                rows={3}
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  borderRadius: '6px',
                  border: '1px solid var(--line)',
                  background: 'var(--input-bg, var(--card-bg))',
                  color: 'var(--fg)',
                  padding: '8px 10px',
                  resize: 'vertical',
                  marginBottom: '8px',
                }}
              />
              <button
                data-testid="index-run-graph-override-retry"
                disabled={graphOverrideReason.trim().length < 20 || isIndexing}
                onClick={() => void handleSparseGraphOverride()}
                style={{
                  padding: '7px 12px',
                  borderRadius: '6px',
                  border: '1px solid var(--warn)',
                  background: 'transparent',
                  color: 'var(--warn)',
                  cursor: graphOverrideReason.trim().length >= 20 && !isIndexing ? 'pointer' : 'not-allowed',
                  fontWeight: 700,
                }}
              >
                Review override and re-index
              </button>
            </div>
          )}


          {figureOutcomes.length > 0 && (
            <div
              data-testid="index-run-figure-outcomes"
              style={{
                marginTop: '10px',
                padding: '10px 12px',
                borderRadius: '8px',
                // Filtered-out pictures are the configured rules working; only a failed
                // vision call is worth painting as a warning.
                border: `1px solid ${figureFailureCount > 0 ? 'var(--warn)' : 'var(--line)'}`,
                background: figureFailureCount > 0 ? 'rgba(var(--warn-rgb), 0.08)' : 'var(--bg-elev2)',
                fontSize: '12px',
                color: 'var(--fg)',
              }}
            >
              <div style={{ fontWeight: 700, marginBottom: '6px' }}>
                {figureFailureCount > 0
                  ? `Figures this run failed to describe (${formatNumber(figureFailureCount)})`
                  : 'Figures this run filtered out, as configured'}
              </div>
              <ul style={{ margin: 0, paddingLeft: '18px', display: 'grid', gap: '2px' }}>
                {figureOutcomes.map((row) => (
                  <li key={row.file} style={{ fontFamily: 'var(--font-mono)', wordBreak: 'break-all' }}>
                    {row.file} — {formatNumber(row.failed)} failed, {formatNumber(row.undescribed)} filtered out,{' '}
                    {formatNumber(row.described)} described
                  </li>
                ))}
              </ul>
              <div style={{ marginTop: '6px', fontSize: '11.5px', color: 'var(--fg-muted)' }}>
                {figureFailureCount > 0
                  ? '"Failed" means the vision call was made and the gateway returned nothing — check the alias and indexing.figures.max_completion_tokens, then re-run with Force reindex. "Filtered out" means the picture never reached the vision call (indexing.figures.skip_classes, min_area_fraction, or classify).'
                  : 'Nothing failed. These pictures never reached the vision call, by configuration: indexing.figures.skip_classes, min_area_fraction, or classify.'}
              </div>
            </div>
          )}
          {(_indexStatus?.error || latestRun?.error) && (
            <div
              style={{
                marginTop: '10px',
                padding: '10px',
                borderRadius: '8px',
                border: '1px solid var(--error)',
                background: 'rgba(var(--error-rgb), 0.08)',
                color: 'var(--error)',
                fontSize: '12px',
                whiteSpace: 'pre-wrap',
              }}
              data-testid="index-run-error-panel"
            >
              {String(_indexStatus?.error || latestRun?.error || '')}
            </div>
          )}
        </div>
      )}

      {/* Embedding mismatch warning (critical) */}
      <EmbeddingMismatchWarning variant="inline" showActions />
      {contractLocked && (
        <div
          data-testid="index-contract-locked-banner"
          style={{
            marginBottom: '16px',
            padding: '10px 12px',
            borderRadius: '8px',
            border: '1px solid var(--warn)',
            background: 'rgba(255, 170, 0, 0.08)',
            fontSize: '12px',
            color: 'var(--fg)',
          }}
        >
          Index contract is locked for this corpus. Enable <strong>Force reindex</strong> to edit fields that change dense or sparse index contents.
        </div>
      )}

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
      {skipDense && (
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
          // Derived so the row never goes stale when a component card is added.
          gridTemplateColumns: `repeat(${COMPONENT_CARDS.length}, minmax(0, 1fr))`,
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
                color: selectedComponent === comp.id ? 'var(--accent-text)' : 'var(--fg)',
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
            {!supportedRuntimeProvider && String(embeddingBackend || '').toLowerCase() === 'provider' && !skipDense && (
              <div
                style={{
                  padding: '12px',
                  borderRadius: '8px',
                  border: '1px solid var(--warn)',
                  marginBottom: '16px',
                  background: 'rgba(255, 170, 0, 0.08)',
                }}
              >
                <div style={{ color: 'var(--warn)', fontWeight: 700, fontSize: '12px' }}>
                  Unsupported embedding provider for runtime backend
                </div>
                <div style={{ color: 'var(--fg-muted)', fontSize: '12px', marginTop: '4px' }}>
                  Select one of: {(runtimeEmbeddingProviders.length ? runtimeEmbeddingProviders : visibleEmbedProviders).join(', ')}
                </div>
              </div>
            )}

            {/* Provider cards */}
            {modelsLoading ? (
              <div style={{ padding: '20px', textAlign: 'center', color: 'var(--fg-muted)' }}>Loading providers…</div>
            ) : (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: `repeat(${Math.min(visibleEmbedProviders.length || 1, 4)}, 1fr)`,
                  gap: '12px',
                  marginBottom: '20px',
                }}
              >
                {(visibleEmbedProviders.length ? visibleEmbedProviders : [String(embeddingType || '')]).filter(Boolean).map((provider) => (
                  <button
                    key={provider}
                    onClick={() => setEmbeddingType(String(provider).toLowerCase())}
                    disabled={contractLocked}
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
                      cursor: contractLocked ? 'not-allowed' : 'pointer',
                      textAlign: 'center',
                      transition: 'all 0.2s ease',
                      opacity: contractLocked ? 0.6 : 1,
                    }}
                  >
                    {(() => {
                      const s = describeEmbeddingProviderStrategy(String(provider), runtimeCapabilities || undefined);
                      return (
                        <>
                    <div
                      style={{
                        fontSize: '12px',
                        fontWeight: 600,
                        color:
                          String(embeddingType || '').toLowerCase() === String(provider).toLowerCase()
                            ? 'var(--accent-text)'
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
                  disabled={contractLocked}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                    opacity: contractLocked ? 0.6 : 1,
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
                    disabled={contractLocked}
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
                  <ModelPicker
                  componentType="EMB"
                  selectionRole="embedding_provider"
                  provider={embeddingType}
                  value={currentModel}
                  onChange={setCurrentModel}
                  label="Model"
                  tooltipKey={modelTooltipKey}
                  disabled={contractLocked}
                />
              </div>

              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Dimensions
                  <TooltipIcon name="EMBEDDING_DIM" />
                </label>
                <NumberField
                  value={embeddingDim}
                  onCommit={setEmbeddingDim}
                  disabled={contractLocked}
                  min={128}
                  max={4096}
                  step={1}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                    opacity: contractLocked ? 0.6 : 1,
                  }}
                />
              </div>

              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Batch size
                  <TooltipIcon name="EMBEDDING_BATCH_SIZE" />
                </label>
                <NumberField
                  data-testid="embedding-batch-size"
                  value={embeddingBatchSize}
                  onCommit={setEmbeddingBatchSize}
                  min={1}
                  max={256}
                  step={1}
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

            {/* Default-open: these are real corpus tunables. A collapsed-by-default
                panel resets on every reload, so a saved value could never be verified
                against the rendered control after refresh (the exhaustive run reported
                ui_matches=false for suffix/truncation/contextual for exactly this
                reason). Operators can still collapse it for the session. */}
            <details open style={{ marginTop: '18px' }}>
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
                      disabled={contractLocked}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: contractLocked ? 0.6 : 1,
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
                      disabled={contractLocked}
                      placeholder=""
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: contractLocked ? 0.6 : 1,
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
                      disabled={contractLocked}
                      placeholder=""
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: contractLocked ? 0.6 : 1,
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
                      disabled={contractLocked}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: contractLocked ? 0.6 : 1,
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
                    <NumberField
                      data-testid="embedding-late-chunking-max-doc-tokens"
                      value={lateChunkingMaxDocTokens}
                      onCommit={setLateChunkingMaxDocTokens}
                      min={256}
                      max={65536}
                      step={1}
                      disabled={contractLocked || String(contextualChunkEmbeddings).toLowerCase() !== 'late_chunking_local_only'}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: !contractLocked && String(contextualChunkEmbeddings).toLowerCase() === 'late_chunking_local_only' ? 1 : 0.6,
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
                    <NumberField
                      data-testid="embedding-max-tokens"
                      value={embeddingMaxTokens}
                      onCommit={setEmbeddingMaxTokens}
                      min={512}
                      max={8192}
                      step={1}
                      disabled={contractLocked}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: contractLocked ? 0.6 : 1,
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Timeout (s)
                      <TooltipIcon name="EMBEDDING_TIMEOUT" />
                    </label>
                    <NumberField
                      value={embeddingTimeout}
                      onCommit={setEmbeddingTimeout}
                      min={5}
                      max={120}
                      step={1}
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
                    <NumberField
                      value={embeddingRetryMax}
                      onCommit={setEmbeddingRetryMax}
                      min={1}
                      max={5}
                      step={1}
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
                      checked={embeddingCacheEnabled}
                      onChange={(e) => setEmbeddingCacheEnabled(e.target.checked)}
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

            {/* One choice out of nine, so it is a radiogroup: screen readers announce the
                selection, arrow keys move it, and the selected card carries a visible mark
                rather than only a border colour a low-contrast display swallows. */}
            <div
              role="radiogroup"
              aria-label="Chunking strategy"
              data-testid="chunking-strategy-group"
              onKeyDown={(e) => {
                if (contractLocked) return;
                const keys = ['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Home', 'End'];
                if (!keys.includes(e.key)) return;
                e.preventDefault();
                const ids = chunkingStrategies.map((s) => s.id);
                const current = Math.max(0, ids.indexOf(String(chunkingStrategy || '').toLowerCase()));
                const next =
                  e.key === 'Home'
                    ? 0
                    : e.key === 'End'
                      ? ids.length - 1
                      : e.key === 'ArrowRight' || e.key === 'ArrowDown'
                        ? (current + 1) % ids.length
                        : (current - 1 + ids.length) % ids.length;
                setChunkingStrategy(ids[next]);
                const node = e.currentTarget.querySelector<HTMLElement>(`[data-strategy="${ids[next]}"]`);
                node?.focus();
              }}
              style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '20px' }}
            >
              {chunkingStrategies.map((strat) => {
                const selected = String(chunkingStrategy || '').toLowerCase() === strat.id;
                return (
                  <button
                    key={strat.id}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    data-strategy={strat.id}
                    data-testid={`chunking-strategy-${strat.id}`}
                    tabIndex={selected ? 0 : -1}
                    onClick={() => setChunkingStrategy(strat.id)}
                    disabled={contractLocked}
                    style={{
                      padding: '16px',
                      background: selected ? 'rgba(var(--accent-rgb), 0.1)' : 'var(--bg-elev2)',
                      border: selected ? '2px solid var(--accent)' : '1px solid var(--line)',
                      borderRadius: '8px',
                      cursor: contractLocked ? 'not-allowed' : 'pointer',
                      textAlign: 'left',
                      transition: 'all 0.2s ease',
                      opacity: contractLocked ? 0.6 : 1,
                    }}
                  >
                    <div
                      style={{
                        fontSize: '13px',
                        fontWeight: 600,
                        color: selected ? 'var(--accent-text)' : 'var(--fg)',
                        marginBottom: '4px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                      }}
                    >
                      <span aria-hidden="true" style={{ color: selected ? 'var(--accent-text)' : 'var(--fg-muted)' }}>
                        {selected ? '\u25c9' : '\u25cb'}
                      </span>
                      {strat.label}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>{strat.description}</div>
                  </button>
                );
              })}
            </div>

            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px' }}>
              {usesTokenChunking ? (
                <>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Target tokens
                      <TooltipIcon name="TARGET_TOKENS" />
                    </label>
                    <NumberField
                      data-testid="chunking-target-tokens"
                      value={targetTokens}
                      onCommit={setTargetTokens}
                      min={64}
                      max={8192}
                      step={1}
                      disabled={contractLocked}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: contractLocked ? 0.6 : 1,
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Overlap tokens
                      <TooltipIcon name="OVERLAP_TOKENS" />
                    </label>
                    <NumberField
                      data-testid="chunking-overlap-tokens"
                      value={overlapTokens}
                      onCommit={setOverlapTokens}
                      min={0}
                      max={2048}
                      step={1}
                      disabled={contractLocked}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: contractLocked ? 0.6 : 1,
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      AST overlap lines
                      <TooltipIcon name="AST_OVERLAP_LINES" />
                    </label>
                    <NumberField
                      value={astOverlapLines}
                      onCommit={setAstOverlapLines}
                      min={0}
                      max={100}
                      step={1}
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
                    <NumberField
                      data-testid="chunking-chunk-size"
                      value={chunkSize}
                      onCommit={setChunkSize}
                      min={200}
                      max={5000}
                      step={1}
                      disabled={contractLocked}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: contractLocked ? 0.6 : 1,
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Chunk overlap (chars)
                      <TooltipIcon name="CHUNK_OVERLAP" />
                    </label>
                    <NumberField
                      data-testid="chunking-chunk-overlap"
                      value={chunkOverlap}
                      onCommit={setChunkOverlap}
                      min={0}
                      max={1000}
                      step={1}
                      disabled={contractLocked}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: contractLocked ? 0.6 : 1,
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      AST overlap lines
                      <TooltipIcon name="AST_OVERLAP_LINES" />
                    </label>
                    <NumberField
                      value={astOverlapLines}
                      onCommit={setAstOverlapLines}
                      min={0}
                      max={100}
                      step={1}
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
                      disabled={contractLocked}
                      style={{
                        opacity: contractLocked ? 0.6 : 1,
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
                      data-testid="chunking-separator-keep"
                      value={separatorKeep}
                      onChange={(e) => setSeparatorKeep(e.target.value as any)}
                      disabled={contractLocked}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: contractLocked ? 0.6 : 1,
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
                      <NumberField
                        data-testid="chunking-recursive-max-depth"
                        value={recursiveMaxDepth}
                        onCommit={setRecursiveMaxDepth}
                        min={1}
                        max={50}
                        step={1}
                        disabled={contractLocked}
                        style={{
                          width: '100%',
                          padding: '10px 12px',
                          background: 'var(--input-bg)',
                          border: '1px solid var(--line)',
                          borderRadius: '6px',
                          color: 'var(--fg)',
                          fontSize: '13px',
                          opacity: contractLocked ? 0.6 : 1,
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
                  <NumberField
                    data-testid="chunking-markdown-max-heading-level"
                    value={markdownMaxHeadingLevel}
                    onCommit={setMarkdownMaxHeadingLevel}
                    min={1}
                    max={6}
                    step={1}
                    disabled={contractLocked}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      opacity: contractLocked ? 0.6 : 1,
                    }}
                  />
                </div>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', marginTop: '28px' }}>
                    <input
                      data-testid="chunking-markdown-include-code-fences"
                      type="checkbox"
                      checked={markdownIncludeCodeFences}
                      onChange={(e) => setMarkdownIncludeCodeFences(e.target.checked)}
                      disabled={contractLocked}
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
                <NumberField
                  data-testid="chunking-max-chunk-tokens"
                  value={maxChunkTokens}
                  onCommit={setMaxChunkTokens}
                  min={100}
                  max={32000}
                  step={1}
                  disabled={contractLocked}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                    opacity: contractLocked ? 0.6 : 1,
                  }}
                />
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Min chunk chars
                  <TooltipIcon name="MIN_CHUNK_CHARS" />
                </label>
                <NumberField
                  data-testid="chunking-min-chunk-chars"
                  value={minChunkChars}
                  onCommit={setMinChunkChars}
                  min={10}
                  max={500}
                  step={1}
                  disabled={contractLocked}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                    opacity: contractLocked ? 0.6 : 1,
                  }}
                />
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Chunking file-size ceiling (bytes)
                  <TooltipIcon name="MAX_INDEXABLE_FILE_SIZE" />
                </label>
                <NumberField
                  data-testid="chunking-max-indexable-file-size"
                  value={maxIndexableFileSize}
                  onCommit={setMaxIndexableFileSize}
                  min={10000}
                  max={2000000000}
                  step={1}
                  disabled={contractLocked}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                    opacity: contractLocked ? 0.6 : 1,
                  }}
                />
                <div
                  data-testid="chunking-file-size-note"
                  style={{ fontSize: '11.5px', color: 'var(--fg-muted)', marginTop: '6px' }}
                >
                  {effectiveFileSizeLimit}
                </div>
              </div>
            </div>

            <div style={{ marginTop: '16px' }}>
              <div style={{ display: 'flex', gap: '18px', flexWrap: 'wrap' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                  <input
                    data-testid="chunking-emit-chunk-ordinal"
                    type="checkbox"
                    checked={emitChunkOrdinal}
                    onChange={(e) => setEmitChunkOrdinal(e.target.checked)}
                    disabled={contractLocked}
                  />
                  <span style={{ fontSize: '13px', color: 'var(--fg)' }}>Emit chunk ordinal</span>
                  <TooltipIcon name="EMIT_CHUNK_ORDINAL" />
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                  <input
                    data-testid="chunking-emit-parent-doc-id"
                    type="checkbox"
                    checked={emitParentDocId}
                    onChange={(e) => setEmitParentDocId(e.target.checked)}
                    disabled={contractLocked}
                  />
                  <span style={{ fontSize: '13px', color: 'var(--fg)' }}>Emit parent doc id</span>
                  <TooltipIcon name="EMIT_PARENT_DOC_ID" />
                </label>
              </div>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                <input data-testid="chunking-preserve-imports" type="checkbox" checked={preserveImports} onChange={(e) => setPreserveImports(e.target.checked)} disabled={contractLocked} />
                <span style={{ fontSize: '13px', color: 'var(--fg)' }}>Preserve imports in chunks</span>
                <TooltipIcon name="PRESERVE_IMPORTS" />
              </label>
              <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginLeft: '24px', marginTop: '4px' }}>
                Keeps import statements near the top of each chunk for better code understanding.
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
                    <NumberField
                      data-testid="greedy-fallback-target"
                      value={greedyFallbackTarget}
                      onCommit={setGreedyFallbackTarget}
                      min={200}
                      max={2000}
                      step={1}
                      disabled={contractLocked}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        opacity: contractLocked ? 0.6 : 1,
                      }}
                    />
                  </div>
                </div>
              </div>
            </details>
          </div>
        )}

        {/* SPARSE TOKENIZATION */}
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
                    disabled={contractLocked}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      opacity: contractLocked ? 0.6 : 1,
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
                    disabled={contractLocked || String(tokenizationStrategy).toLowerCase() !== 'tiktoken'}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      opacity: contractLocked
                        ? 0.6
                        : String(tokenizationStrategy).toLowerCase() === 'tiktoken'
                          ? 1
                          : 0.6,
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
                    disabled={contractLocked || String(tokenizationStrategy).toLowerCase() !== 'huggingface'}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      opacity: contractLocked
                        ? 0.6
                        : String(tokenizationStrategy).toLowerCase() === 'huggingface'
                          ? 1
                          : 0.6,
                    }}
                  />
                </div>
              </div>
              {!tokenizationCompatibility.ok && (
                <div
                  style={{
                    marginTop: '12px',
                    padding: '10px 12px',
                    borderRadius: '8px',
                    border: '1px solid var(--warn)',
                    background: 'rgba(255, 170, 0, 0.08)',
                    color: 'var(--warn)',
                    fontSize: '12px',
                  }}
                >
                  {tokenizationCompatibility.message}
                </div>
              )}
              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginTop: '14px' }}>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                    <input type="checkbox" checked={normalizeUnicode} onChange={(e) => setNormalizeUnicode(e.target.checked)} disabled={contractLocked} />
                    Normalize Unicode (NFKC)
                    <TooltipIcon name="TOKENIZATION_NORMALIZE_UNICODE" />
                  </label>
                </div>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                    <input type="checkbox" checked={lowercaseTokenizer} onChange={(e) => setLowercaseTokenizer(e.target.checked)} disabled={contractLocked} />
                    Lowercase
                    <TooltipIcon name="TOKENIZATION_LOWERCASE" />
                  </label>
                </div>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                    <input type="checkbox" checked={tokenEstimateOnly} onChange={(e) => setTokenEstimateOnly(e.target.checked)} disabled={contractLocked} />
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
                  <NumberField
                    value={maxTokensPerChunkHard}
                    onCommit={setMaxTokensPerChunkHard}
                    disabled={contractLocked}
                    min={256}
                    max={65536}
                    step={1}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      opacity: contractLocked ? 0.6 : 1,
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
                    Indexing file-size ceiling (MB)
                    <TooltipIcon name="INDEX_MAX_FILE_SIZE_MB" />
                  </label>
                  <NumberField
                    data-testid="tokenization-index-max-file-size-mb"
                    value={indexMaxFileSizeMb}
                    onCommit={setIndexMaxFileSizeMb}
                    min={1}
                    max={1024}
                    step={1}
                    disabled={contractLocked}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      opacity: contractLocked ? 0.6 : 1,
                    }}
                  />
                  <div
                    data-testid="tokenization-file-size-note"
                    style={{ fontSize: '11.5px', color: 'var(--fg-muted)', marginTop: '6px' }}
                  >
                    {effectiveFileSizeLimit}
                  </div>
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
                    disabled={contractLocked}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      opacity: contractLocked ? 0.6 : 1,
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
                  <NumberField
                    data-testid="tokenization-large-file-stream-chunk-chars"
                    value={largeFileStreamChunkChars}
                    onCommit={setLargeFileStreamChunkChars}
                    min={100000}
                    max={50000000}
                    step={1}
                    disabled={contractLocked || largeFileMode !== 'stream'}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      opacity: !contractLocked && largeFileMode === 'stream' ? 1 : 0.6,
                    }}
                  />
                </div>
              </div>
              <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--fg-muted)' }}>
                Streaming mode ingests large <code>.txt</code>/<code>.md</code> files in bounded blocks to avoid loading the entire file into RAM.
              </div>
            </div>

            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '20px' }}>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Sparse stemming (Qdrant/bm25)
                  <TooltipIcon name="BM25_TOKENIZER" />
                </label>
                <select
                  data-testid="sparse-bm25-tokenizer"
                  value={bm25Tokenizer}
                  onChange={(e) => setBm25Tokenizer(e.target.value)}
                  disabled={contractLocked}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                    opacity: contractLocked ? 0.6 : 1,
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
                  data-testid="sparse-bm25-stemmer-lang"
                  type="text"
                  value={bm25StemmerLang}
                  onChange={(e) => setBm25StemmerLang(e.target.value)}
                  disabled={contractLocked}
                  placeholder="english"
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                    opacity: contractLocked ? 0.6 : 1,
                  }}
                />
              </div>
            </div>

            <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--fg-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <strong style={{ color: 'var(--fg)' }}>Resolved:</strong> {resolvedTokenizerDesc}
            </div>
            <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--fg-muted)' }}>
              Sparse vectors are IDF-modified BM25 (<code>Qdrant/bm25</code> via fastembed) stored in Qdrant next to the dense
              vectors. Stemming, language, k1, and b are part of the sparse index contract: changing them requires a re-index.
            </div>

            <div style={{ marginTop: '16px' }}>
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
                    <NumberField
                      data-testid="parquet-extract-max-rows"
                      min={1}
                      max={200000}
                      step={1}
                      value={parquetExtractMaxRows}
                      onCommit={setParquetExtractMaxRows}
                      disabled={contractLocked}
                      style={{ width: '100%', opacity: contractLocked ? 0.6 : 1 }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                      Max chars
                    </label>
                    <NumberField
                      data-testid="parquet-extract-max-chars"
                      min={10_000}
                      max={50_000_000}
                      step={1}
                      value={parquetExtractMaxChars}
                      onCommit={setParquetExtractMaxChars}
                      disabled={contractLocked}
                      style={{ width: '100%', opacity: contractLocked ? 0.6 : 1 }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                      Max cell chars
                    </label>
                    <NumberField
                      data-testid="parquet-extract-max-cell-chars"
                      min={100}
                      max={200_000}
                      step={1}
                      value={parquetExtractMaxCellChars}
                      onCommit={setParquetExtractMaxCellChars}
                      disabled={contractLocked}
                      style={{ width: '100%', opacity: contractLocked ? 0.6 : 1 }}
                    />
                  </div>
                </div>

                <div style={{ marginTop: '12px', display: 'flex', gap: '18px', flexWrap: 'wrap' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                    <input
                      data-testid="parquet-extract-text-columns-only"
                      type="checkbox"
                      checked={parquetExtractTextColumnsOnly}
                      onChange={(e) => setParquetExtractTextColumnsOnly(e.target.checked)}
                      disabled={contractLocked}
                    />
                    <span style={{ fontSize: '12px', color: 'var(--fg)' }}>Text columns only</span>
                    <TooltipIcon name="PARQUET_EXTRACT_TEXT_COLUMNS_ONLY" />
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                    <input
                      data-testid="parquet-extract-include-column-names"
                      type="checkbox"
                      checked={parquetExtractIncludeColumnNames}
                      onChange={(e) => setParquetExtractIncludeColumnNames(e.target.checked)}
                      disabled={contractLocked}
                    />
                    <span style={{ fontSize: '12px', color: 'var(--fg)' }}>Include column names</span>
                    <TooltipIcon name="PARQUET_EXTRACT_INCLUDE_COLUMN_NAMES" />
                  </label>
                </div>
              </div>
            </div>

          </div>
        )}

        {/* GRAPH + ENRICHMENT */}
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
                <label
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    cursor: graphCorpusIsInternal ? 'not-allowed' : 'pointer',
                  }}
                >
                  <input
                    data-testid="graph-indexing-enabled"
                    type="checkbox"
                    checked={graphIndexingEnabled}
                    disabled={graphCorpusIsInternal}
                    onChange={(e) => setGraphIndexingEnabled(e.target.checked)}
                    style={{ width: '18px', height: '18px' }}
                  />
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Build a real graph during indexing</div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                      External documents use semantic extraction by default; code corpora can select the AST policy below.
                    </div>
                  </div>
                </label>
                <div
                  data-testid="graph-policy-badge"
                  style={{
                    display: 'inline-flex',
                    marginTop: 12,
                    borderRadius: 999,
                    padding: '5px 9px',
                    background: graphCorpusIsInternal ? 'rgba(var(--warn-rgb), 0.12)' : 'rgba(var(--accent-rgb), 0.12)',
                    color: graphCorpusIsInternal ? 'var(--warn)' : 'var(--fg)',
                    fontSize: 12,
                    fontWeight: 700,
                  }}
                >
                  {graphPolicyLabel}
                </div>
                {graphCorpusIsInternal ? (
                  <div style={{ marginTop: 8, color: 'var(--fg-muted)', fontSize: 12, lineHeight: 1.45 }}>
                    Runtime-managed corpora are excluded from this graph phase. Their own indexing path remains authoritative.
                  </div>
                ) : null}
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
                    disabled={graphCorpusIsInternal || !graphIndexingEnabled}
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
                  border: buildCodeGraph ? '2px solid rgba(var(--accent-rgb), 0.6)' : '1px solid var(--line)',
                  opacity: graphIndexingEnabled && lexicalGraphEnabled && !graphCorpusIsInternal ? 1 : 0.6,
                }}
              >
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input
                    data-testid="graph-build-code"
                    type="checkbox"
                    checked={buildCodeGraph}
                    onChange={(e) => setBuildCodeGraph(e.target.checked)}
                    disabled={graphCorpusIsInternal || !graphIndexingEnabled || !lexicalGraphEnabled}
                    style={{ width: '18px', height: '18px' }}
                  />
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Use the code AST graph policy</div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                      Select this only for code corpora. Otherwise every enabled external corpus uses semantic entity extraction.
                    </div>
                  </div>
                </label>

                {buildCodeGraph ? (
                  <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
                    {[
                      ['Contains weight', astContainsWeight, setAstContainsWeight],
                      ['Inherits weight', astInheritsWeight, setAstInheritsWeight],
                      ['Imports weight', astImportsWeight, setAstImportsWeight],
                      ['Calls weight', astCallsWeight, setAstCallsWeight],
                    ].map(([label, value, onCommit]) => (
                      <div className="input-group" key={String(label)}>
                        <label>{String(label)}</label>
                        <NumberField
                          min={0}
                          max={1}
                          step={0.05}
                          value={Number(value)}
                          onCommit={onCommit as (next: number) => void}
                        />
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>

              {!buildCodeGraph && !graphCorpusIsInternal && graphIndexingEnabled ? (
                <div
                  data-testid="semantic-graph-settings"
                  style={{
                    padding: 16,
                    background: 'var(--bg-elev2)',
                    borderRadius: 8,
                    border: '2px solid rgba(var(--accent-rgb), 0.6)',
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg)' }}>Semantic extraction policy</div>
                  <div style={{ marginTop: 4, color: 'var(--fg-muted)', fontSize: 11, lineHeight: 1.45 }}>
                    Neo4j GraphRAG structured extraction is required for this external corpus. Failed extraction fails the run; the chunk ceiling refuses a partial graph instead of truncating it.
                  </div>
                  <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
                    <div className="input-group">
                      <label>KG LLM Alias</label>
                      <ChatModelPicker
                        value={semanticKgLlmModel}
                        onChange={setSemanticKgLlmModel}
                        models={generationModels}
                        valueMode="id"
                        allowEmpty
                      />
                    </div>
                    <div className="input-group">
                      <label>Reasoning effort</label>
                      <select
                        data-testid="semantic-kg-reasoning-effort"
                        value={semanticKgReasoningEffort}
                        onChange={(event) => setSemanticKgReasoningEffort(event.target.value as typeof semanticKgReasoningEffort)}
                      >
                        {['minimal', 'low', 'medium', 'high', 'xhigh'].map((effort) => (
                          <option key={effort} value={effort}>{effort}</option>
                        ))}
                      </select>
                    </div>
                    <div className="input-group">
                      <label>Semantic chunk ceiling</label>
                      <NumberField
                        data-testid="semantic-kg-max-chunks"
                        min={1}
                        max={100000}
                        step={1}
                        value={semanticKgMaxChunks}
                        onCommit={setSemanticKgMaxChunks}
                      />
                    </div>
                    <div className="input-group">
                      <label>Per-chunk timeout (seconds)</label>
                      <NumberField
                        data-testid="semantic-kg-timeout"
                        min={5}
                        max={600}
                        step={5}
                        value={semanticKgTimeoutS}
                        onCommit={setSemanticKgTimeoutS}
                      />
                    </div>
                  </div>
                  <div
                    style={{
                      marginTop: 14,
                      paddingTop: 14,
                      borderTop: '1px solid var(--line)',
                      display: 'grid',
                      gap: 10,
                    }}
                  >
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
                      <div className="input-group">
                        <label htmlFor={schemaProposalReasoningId}>Proposal reasoning effort <TooltipIcon name="SCHEMA_PROPOSAL_REASONING_EFFORT" /></label>
                        <select
                          id={schemaProposalReasoningId}
                          data-testid="schema-proposal-reasoning-effort"
                          aria-describedby={`${schemaProposalReasoningId}-help`}
                          value={schemaProposalReasoningEffort}
                          onChange={(event) => setSchemaProposalReasoningEffort(event.target.value as typeof schemaProposalReasoningEffort)}
                        >
                          {['minimal', 'low', 'medium', 'high', 'xhigh'].map((effort) => (
                            <option key={effort} value={effort}>{effort}</option>
                          ))}
                        </select>
                        <div id={`${schemaProposalReasoningId}-help`} style={{ fontSize: 11, color: 'var(--fg-muted)' }}>
                          Higher effort can take longer. KG extraction uses its own reasoning setting.
                        </div>
                      </div>
                      <div className="input-group">
                        <label>Proposal deadline (seconds) <TooltipIcon name="SCHEMA_PROPOSAL_TIMEOUT_S" /></label>
                        <NumberField
                          data-testid="schema-proposal-timeout"
                          min={5}
                          max={80}
                          step={1}
                          value={schemaProposalTimeoutS}
                          onCommit={setSchemaProposalTimeoutS}
                        />
                      </div>
                      <div className="input-group">
                        <label>Proposal output token limit <TooltipIcon name="SCHEMA_PROPOSAL_MAX_OUTPUT_TOKENS" /></label>
                        <NumberField
                          data-testid="schema-proposal-max-output-tokens"
                          min={256}
                          max={32768}
                          step={256}
                          value={schemaProposalMaxOutputTokens}
                          onCommit={setSchemaProposalMaxOutputTokens}
                        />
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        data-testid="generate-graph-schema"
                        onClick={() => void handleGenerateGraphSchema()}
                        disabled={graphSchemaLoading}
                        aria-busy={graphSchemaLoading}
                        style={{
                          padding: '8px 14px',
                          border: '1px solid var(--accent)',
                          borderRadius: 7,
                          background: graphSchemaLoading ? 'var(--bg-elev2)' : 'rgba(var(--accent-rgb), 0.12)',
                          color: graphSchemaLoading ? 'var(--fg-muted)' : 'var(--accent-text)',
                          cursor: graphSchemaLoading ? 'wait' : 'pointer',
                          fontWeight: 750,
                        }}
                      >
                        {graphSchemaLoading
                          ? 'Generating proposed schema…'
                          : graphSchemaProposal
                            ? 'Regenerate proposed schema'
                            : 'Generate proposed schema'}
                      </button>
                      <span style={{ fontSize: 11, color: 'var(--fg-muted)' }}>
                        Samples documents deterministically; bulk extraction starts only after approval.
                      </span>
                    </div>

                    {graphSchemaError ? (
                      <div data-testid="graph-schema-error" role="alert" style={{ color: 'var(--err)', fontSize: 12 }}>
                        <div>{graphSchemaError.message}</div>
                        {graphSchemaError.operatorHint ? <div>{graphSchemaError.operatorHint}</div> : null}
                      </div>
                    ) : null}

                    {graphSchemaProposal ? (
                      <div
                        data-testid="graph-schema-proposal"
                        style={{
                          padding: 12,
                          border: '1px solid rgba(var(--accent-rgb), 0.45)',
                          borderRadius: 7,
                          background: 'var(--bg)',
                          display: 'grid',
                          gap: 9,
                          fontSize: 11,
                        }}
                      >
                        <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--fg)' }}>
                          Proposed closed-world graph contract
                        </div>
                        <div style={{ display: 'grid', gap: 3, color: 'var(--fg-muted)' }}>
                          <span>Model: <strong style={{ color: 'var(--fg)' }}>{graphSchemaProposal.model_alias}</strong></span>
                          <span>Neo4j GraphRAG: {graphSchemaProposal.graphrag_version}</span>
                          <span>
                            Schema hash:{' '}
                            <code data-testid="graph-schema-hash" style={{ overflowWrap: 'anywhere', color: 'var(--fg)' }}>
                              {graphSchemaProposal.schema_hash}
                            </code>
                          </span>
                          <span>Sample recipe: {graphSchemaProposal.sample.recipe}</span>
                          <span>
                            Estimated bulk cost:{' '}
                            {indexEstimate?.semantic_kg_cost_usd == null
                              ? 'measured before the final approval; indexing cannot start without that estimate'
                              : formatCurrency(Number(indexEstimate.semantic_kg_cost_usd))}
                          </span>
                        </div>
                        {[
                          ['Node types & properties', 'node_types'],
                          ['Relationships', 'relationship_types'],
                          ['Directed patterns', 'patterns'],
                          ['Constraints', 'constraints'],
                        ].map(([label, key]) => (
                          <details key={key} data-testid={`graph-schema-${key.replace(/_/g, '-')}`}>
                            <summary style={{ cursor: 'pointer', fontWeight: 750, color: 'var(--fg)' }}>{label}</summary>
                            <pre
                              style={{
                                margin: '7px 0 0',
                                padding: 8,
                                maxHeight: 220,
                                overflow: 'auto',
                                borderRadius: 5,
                                background: 'var(--bg-elev2)',
                                color: 'var(--fg-muted)',
                                whiteSpace: 'pre-wrap',
                                overflowWrap: 'anywhere',
                              }}
                            >
                              {JSON.stringify(
                                (graphSchemaProposal.schema as Record<string, unknown>)[key] ?? [],
                                null,
                                2
                              )}
                            </pre>
                          </details>
                        ))}
                        <details data-testid="graph-schema-sample">
                          <summary style={{ cursor: 'pointer', fontWeight: 750, color: 'var(--fg)' }}>
                            Sample documents & positions ({graphSchemaProposal.sample.chunk_ids.length} chunks)
                          </summary>
                          <ol style={{ margin: '7px 0 0', paddingLeft: 24, color: 'var(--fg-muted)' }}>
                            {graphSchemaProposal.sample.chunk_ids.map((chunkId, index) => (
                              <li key={`${chunkId}:${index}`} style={{ marginBottom: 4, overflowWrap: 'anywhere' }}>
                                <code>{chunkId}</code>
                                <span> · SHA-256 {graphSchemaProposal.sample.chunk_hashes[index]}</span>
                              </li>
                            ))}
                          </ol>
                        </details>
                        <div style={{ color: 'var(--warn)', lineHeight: 1.45 }}>
                          Approval is bound to this exact schema hash, model, GraphRAG version, and source fingerprint.
                          Changing any of them invalidates this review.
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}

              <div
                style={{
                  padding: '16px',
                  background: 'var(--bg-elev2)',
                  borderRadius: '8px',
                  border: skipDense ? '2px solid var(--warn)' : '1px solid var(--line)',
                }}
              >
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input data-testid="graph-skip-dense" type="checkbox" checked={skipDense} onChange={(e) => setSkipDense(e.target.checked)} disabled={contractLocked} style={{ width: '18px', height: '18px' }} />
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Skip dense vectors</div>
                    <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                      Useful for graph-only/sparse-only indexing runs (fast, no embeddings).
                    </div>
                  </div>
                  <TooltipIcon name="SKIP_DENSE" />
                </label>
                {skipDense && (
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
                <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)', marginBottom: '8px' }}>Prompt Templates</div>
                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                  <PromptLink promptKey="code_enrichment">Edit Code Enrichment Prompt</PromptLink>
                  <PromptLink promptKey="lightweight_chunk_summaries">Edit Lightweight Summary Prompt</PromptLink>
                  <PromptLink promptKey="semantic_chunk_summaries">Edit Summary Prompt</PromptLink>
                  <PromptLink promptKey="semantic_kg_extraction">Edit Semantic KG Extraction Prompt</PromptLink>
                </div>
              </div>
            </div>

          </div>
        )}

        {/* FIGURES & VISION */}
        {selectedComponent === 'figures' && (
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
              🖼️ Figures & Vision
              <TooltipIcon name="FIGURES_ENABLED" />
            </h4>

            <div style={{ display: 'grid', gap: '16px' }}>
              <div
                data-testid="figures-card"
                style={{
                  padding: '16px',
                  background: 'var(--bg-elev2)',
                  borderRadius: '8px',
                  border: figuresEnabled ? '2px solid var(--accent)' : '1px solid var(--line)',
                }}
              >
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input
                    data-testid="figures-enabled"
                    type="checkbox"
                    checked={figuresEnabled}
                    onChange={(e) => setFiguresEnabled(e.target.checked)}
                    style={{ width: '18px', height: '18px' }}
                  />
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>
                      Figures — describe charts, diagrams and drawings so they become searchable, citable chunks
                    </div>
                    <div style={{ fontSize: '11.5px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                      Vision calls go through the gateway. Index Now prices them before the run starts.
                    </div>
                  </div>
                  <TooltipIcon name="FIGURES_ENABLED" />
                </label>

                {figuresEnabled && (
                  <div style={{ marginTop: '12px', display: 'grid', gap: '12px' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '12px' }}>
                      <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                        <input
                          data-testid="figures-describe"
                          type="checkbox"
                          checked={figuresDescribe}
                          onChange={(e) => setFiguresDescribe(e.target.checked)}
                          style={{ width: '18px', height: '18px' }}
                        />
                        <span style={{ fontSize: '11.5px', color: 'var(--fg)' }}>Describe with the vision alias</span>
                        <TooltipIcon name="FIGURES_DESCRIBE" />
                      </label>
                      <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                        <input
                          data-testid="figures-classify"
                          type="checkbox"
                          checked={figuresClassify}
                          onChange={(e) => setFiguresClassify(e.target.checked)}
                          style={{ width: '18px', height: '18px' }}
                        />
                        <span style={{ fontSize: '11.5px', color: 'var(--fg)' }}>Classify figures locally first</span>
                        <TooltipIcon name="FIGURES_CLASSIFY" />
                      </label>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', alignItems: 'start' }}>
                      <div className="input-group">
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                          Vision alias
                          <TooltipIcon name="FIGURES_VISION_MODEL" />
                        </label>
                        <ChatModelPicker
                          testId="figures-vision-model"
                          value={figuresVisionModel}
                          onChange={setFiguresVisionModel}
                          models={visionModels}
                          valueMode="id"
                        />
                        {figuresVisionAliasWarning ? (
                          <div
                            data-testid="figures-vision-model-warning"
                            style={{ marginTop: '6px', fontSize: '11.5px', color: 'var(--warn)' }}
                          >
                            {figuresVisionAliasWarning}
                          </div>
                        ) : (
                          <div style={{ marginTop: '6px', fontSize: '11.5px', color: 'var(--fg-muted)' }}>
                            Only vision-capable catalog aliases are listed.
                          </div>
                        )}
                        {visionAliasPricing ? (
                          <div
                            data-testid="figures-vision-model-price"
                            style={{ marginTop: '4px', fontSize: '11.5px', color: 'var(--fg-muted)' }}
                          >
                            {visionAliasPricing}
                          </div>
                        ) : null}
                      </div>
                      <div className="input-group">
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                          Prompt profile
                          <TooltipIcon name="FIGURES_PROMPT_PROFILE" />
                        </label>
                        <select
                          data-testid="figures-prompt-profile"
                          value={figuresPromptProfile}
                          onChange={(e) => setFiguresPromptProfile(e.target.value as 'technical_figure' | 'schematic')}
                          style={{ width: '100%' }}
                        >
                          <option value="technical_figure">Technical figure (charts, diagrams, photos)</option>
                          <option value="schematic">Schematic (engineering drawings)</option>
                        </select>
                      </div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
                      <div className="input-group">
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                          Image scale
                          <TooltipIcon name="FIGURES_IMAGES_SCALE" />
                        </label>
                        <NumberField
                          data-testid="figures-images-scale"
                          min={1}
                          max={4}
                          step={0.5}
                          value={figuresImagesScale}
                          onCommit={setFiguresImagesScale}
                          style={{ width: '100%' }}
                        />
                      </div>
                      <div className="input-group">
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                          Min area fraction
                          <TooltipIcon name="FIGURES_MIN_AREA_FRACTION" />
                        </label>
                        <NumberField
                          data-testid="figures-min-area-fraction"
                          min={0}
                          max={1}
                          step={0.01}
                          value={figuresMinAreaFraction}
                          onCommit={setFiguresMinAreaFraction}
                          style={{ width: '100%' }}
                        />
                      </div>
                      <div className="input-group">
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                          Max completion tokens
                          <TooltipIcon name="FIGURES_MAX_COMPLETION_TOKENS" />
                        </label>
                        <NumberField
                          data-testid="figures-max-completion-tokens"
                          min={64}
                          max={8000}
                          step={1}
                          value={figuresMaxCompletionTokens}
                          onCommit={setFiguresMaxCompletionTokens}
                          style={{ width: '100%' }}
                        />
                      </div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
                      <div className="input-group">
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                          Concurrency
                          <TooltipIcon name="FIGURES_CONCURRENCY" />
                        </label>
                        <NumberField
                          data-testid="figures-concurrency"
                          min={1}
                          max={16}
                          step={1}
                          value={figuresConcurrency}
                          onCommit={setFiguresConcurrency}
                          style={{ width: '100%' }}
                        />
                      </div>
                      <div className="input-group">
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                          Timeout (s)
                          <TooltipIcon name="FIGURES_TIMEOUT_S" />
                        </label>
                        <NumberField
                          data-testid="figures-timeout-s"
                          min={5}
                          max={600}
                          step={1}
                          value={figuresTimeoutS}
                          onCommit={setFiguresTimeoutS}
                          style={{ width: '100%' }}
                        />
                      </div>
                      <div className="input-group">
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                          Skip classes
                          <TooltipIcon name="FIGURES_SKIP_CLASSES" />
                        </label>
                        <input
                          data-testid="figures-skip-classes"
                          type="text"
                          value={skipClassesText}
                          onChange={(e) => onSkipClassesChange(e.target.value)}
                          placeholder="logo, signature, icon"
                          style={{ width: '100%' }}
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
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
        {/* Toggle and Refresh are SIBLING buttons: nesting an interactive
            control inside another (button-in-button or role=button) is
            invalid and steals keyboard activation. */}
        <div
          style={{
            width: '100%',
            padding: '16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '10px',
          }}
        >
          <button
            aria-expanded={statsExpanded}
            onClick={() => setStatsExpanded(!statsExpanded)}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '10px',
              padding: 0,
            }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '16px' }}>📊</span>
              <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--fg)' }}>Index Stats</span>
            </span>
            <span style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>{statsExpanded ? '▼' : '▶'}</span>
          </button>
          <button
            onClick={() => {
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
                  <span style={{ color: 'var(--accent-text)', fontWeight: 800 }}>{progress.current}%</span>
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
                onClick={() => void handleStartIndex()}
                data-testid="index-now-button"
                disabled={!canIndex || estimateLoading || graphSchemaLoading}
                aria-busy={estimateLoading || graphSchemaLoading}
                style={{
                  padding: '12px 32px',
                  fontSize: '14px',
                  fontWeight: 800,
                  background: canIndex && !estimateLoading && !graphSchemaLoading ? 'var(--accent)' : 'var(--bg-elev2)',
                  color: canIndex && !estimateLoading && !graphSchemaLoading ? 'var(--accent-contrast)' : 'var(--fg-muted)',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: canIndex && !estimateLoading && !graphSchemaLoading ? 'pointer' : 'not-allowed',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}
              >
                <span>🚀</span>
                {estimateWarmup
                  ? 'Preparing…'
                  : estimateLoading
                    ? 'Estimating…'
                    : semanticGraphActive
                      ? graphSchemaProposal
                        ? 'Approve schema & index'
                        : 'Generate schema first'
                      : 'Index Now'}
              </button>
              <label
                data-testid="force-reindex-toggle"
                style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '12px', color: 'var(--fg)', maxWidth: '340px' }}
              >
                <input
                  type="checkbox"
                  checked={forceReindex}
                  onChange={(e) => setForceReindex(e.target.checked)}
                  style={{ marginTop: '2px' }}
                />
                <span>
                  <strong style={{ color: 'var(--err)' }}>Force reindex</strong> — allows changes to embedding
                  and sparse index settings. The replacement becomes active after validation. Changed settings
                  may make searches unavailable until the rebuild succeeds.
                </span>
              </label>
              <button
                onClick={() => setTerminalVisible(!terminalVisible)}
                data-testid="indexing-show-logs"
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
                data-testid="delete-index"
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
                title="Deletes the dense and sparse vectors, chunks, documents, and graph for this corpus"
              >
                🗑 Delete index
              </button>
            </>
          )}
        </div>
        {estimateWarmup && (
          <div
            data-testid="index-estimate-warmup"
            style={{ marginTop: '10px', fontSize: '12px', color: 'var(--fg-muted)' }}
          >
            {estimateWarmup}
          </div>
        )}

        {!isIndexing && indexBlockingReason && (
          <div
            style={{
              marginTop: '10px',
              fontSize: '12px',
              color: 'var(--warn)',
            }}
          >
            {indexBlockingReason}
          </div>
        )}

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
            Est:{' '}
            {indexEstimate.total_cost_usd == null
              ? indexEstimate.embedding_cost_usd == null
                ? 'N/A'
                : formatCurrency(Number(indexEstimate.embedding_cost_usd || 0))
              : formatCurrency(Number(indexEstimate.total_cost_usd || 0))}
            {indexEstimate.semantic_kg_cost_usd != null
              ? ` (Embed ${indexEstimate.embedding_cost_usd == null ? 'N/A' : formatCurrency(Number(indexEstimate.embedding_cost_usd || 0))} + KG ${formatCurrency(
                  Number(indexEstimate.semantic_kg_cost_usd || 0)
                )})`
              : ''}
            {indexEstimate.figure_description_cost_usd != null
              ? ` + Figures ≤ ${formatFigureCostUsd(Number(indexEstimate.figure_description_cost_usd || 0))}${
                  indexEstimate.estimated_figures != null
                    ? ` (~${formatNumber(Number(indexEstimate.estimated_figures))} figures)`
                    : ''
                }`
              : ''}
            {' • '}
            {indexEstimate.estimated_seconds_low != null && indexEstimate.estimated_seconds_high != null
              ? `${formatDuration(durationMs(Number(indexEstimate.estimated_seconds_low)))}–${formatDuration(
                  durationMs(Number(indexEstimate.estimated_seconds_high))
                )}`
              : 'N/A'}
            {estimateTimeBreakdown ? ` (${estimateTimeBreakdown})` : ''}
            {' '}
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
