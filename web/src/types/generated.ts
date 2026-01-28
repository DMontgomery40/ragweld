/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

/**
 * Chunk summary builder filtering configuration.
 */
export interface ChunkSummaryConfig {
  /**
   * Directories to skip when building chunk_summaries
   */
  exclude_dirs?: string[];
  /**
   * File patterns/extensions to skip
   */
  exclude_patterns?: string[];
  /**
   * Keywords that, when present in code, skip the chunk
   */
  exclude_keywords?: string[];
  /**
   * Max code snippet length in semantic chunk_summaries
   */
  code_snippet_length?: number;
  /**
   * Max symbols to include per chunk_summary
   */
  max_symbols?: number;
  /**
   * Max API routes to include per chunk_summary
   */
  max_routes?: number;
  /**
   * Max length for purpose field in chunk_summaries
   */
  purpose_max_length?: number;
  /**
   * Quick tips shown in chunk_summaries builder UI
   */
  quick_tips?: string[];
}
/**
 * Code chunking configuration.
 */
export interface ChunkingConfig {
  /**
   * Target chunk size (non-whitespace chars)
   */
  chunk_size?: number;
  /**
   * Overlap between chunks
   */
  chunk_overlap?: number;
  /**
   * Overlap lines for AST chunking
   */
  ast_overlap_lines?: number;
  /**
   * Max file size to index (bytes) - files larger than this are skipped
   */
  max_indexable_file_size?: number;
  /**
   * Maximum tokens per chunk - chunks exceeding this are split recursively
   */
  max_chunk_tokens?: number;
  /**
   * Minimum chunk size
   */
  min_chunk_chars?: number;
  /**
   * Target size for greedy chunking
   */
  greedy_fallback_target?: number;
  /**
   * Chunking strategy
   */
  chunking_strategy?: string;
  /**
   * Include imports in chunks
   */
  preserve_imports?: number;
}
/**
 * Docker infrastructure configuration.
 */
export interface DockerConfig {
  /**
   * Docker socket URL (e.g., unix:///var/run/docker.sock). Leave empty for auto-detection.
   */
  docker_host?: string;
  /**
   * Timeout for Docker status check (seconds)
   */
  docker_status_timeout?: number;
  /**
   * Timeout for Docker container list (seconds)
   */
  docker_container_list_timeout?: number;
  /**
   * Timeout for Docker container actions (start/stop/restart)
   */
  docker_container_action_timeout?: number;
  /**
   * Timeout for Docker infrastructure up command (seconds)
   */
  docker_infra_up_timeout?: number;
  /**
   * Timeout for Docker infrastructure down command (seconds)
   */
  docker_infra_down_timeout?: number;
  /**
   * Default number of log lines to tail from containers
   */
  docker_logs_tail?: number;
  /**
   * Include timestamps in Docker logs (1=yes, 0=no)
   */
  docker_logs_timestamps?: number;
  /**
   * Port for dev frontend (Vite)
   */
  dev_frontend_port?: number;
  /**
   * Port for dev backend (Uvicorn)
   */
  dev_backend_port?: number;
  /**
   * Timeout for dev stack restart operations (seconds)
   */
  dev_stack_restart_timeout?: number;
}
/**
 * Embedding generation and caching configuration.
 */
export interface EmbeddingConfig {
  /**
   * Embedding provider (dynamic - validated against models.json at runtime)
   */
  embedding_type?: string;
  /**
   * OpenAI embedding model
   */
  embedding_model?: string;
  /**
   * Embedding dimensions
   */
  embedding_dim?: number;
  /**
   * Voyage embedding model
   */
  voyage_model?: string;
  /**
   * Local SentenceTransformer model
   */
  embedding_model_local?: string;
  /**
   * Batch size for embedding generation
   */
  embedding_batch_size?: number;
  /**
   * Max tokens per embedding chunk
   */
  embedding_max_tokens?: number;
  /**
   * Enable embedding cache
   */
  embedding_cache_enabled?: number;
  /**
   * Embedding API timeout (seconds)
   */
  embedding_timeout?: number;
  /**
   * Max retries for embedding API
   */
  embedding_retry_max?: number;
}
/**
 * Code enrichment and chunk_summary generation configuration.
 */
export interface EnrichmentConfig {
  /**
   * Enable chunk_summary enrichment by default
   */
  chunk_summaries_enrich_default?: number;
  /**
   * Max chunk_summaries to generate
   */
  chunk_summaries_max?: number;
  /**
   * Enable chunk enrichment
   */
  enrich_code_chunks?: number;
  /**
   * Min chars for enrichment
   */
  enrich_min_chars?: number;
  /**
   * Max chars for enrichment prompt
   */
  enrich_max_chars?: number;
  /**
   * Enrichment timeout (seconds)
   */
  enrich_timeout?: number;
}
/**
 * Evaluation dataset configuration.
 */
export interface EvaluationConfig {
  /**
   * Golden evaluation dataset path
   */
  golden_path?: string;
  /**
   * Baseline results path
   */
  baseline_path?: string;
  /**
   * Multi-query variants for evaluation
   */
  eval_multi_m?: number;
}
/**
 * Configuration for tri-brid fusion of vector + sparse + graph results.
 */
export interface FusionConfig {
  /**
   * Fusion method: 'rrf' (Reciprocal Rank Fusion) or 'weighted' (score-based)
   */
  method?: "rrf" | "weighted";
  /**
   * Weight for vector search results (pgvector)
   */
  vector_weight?: number;
  /**
   * Weight for sparse BM25/FTS search results
   */
  sparse_weight?: number;
  /**
   * Weight for graph search results (Neo4j)
   */
  graph_weight?: number;
  /**
   * RRF smoothing constant (higher = more weight to top ranks)
   */
  rrf_k?: number;
  /**
   * Normalize scores to [0,1] before fusion
   */
  normalize_scores?: boolean;
}
/**
 * LLM generation configuration.
 */
export interface GenerationConfig {
  /**
   * Primary generation model
   */
  gen_model?: string;
  /**
   * Generation temperature
   */
  gen_temperature?: number;
  /**
   * Max tokens for generation
   */
  gen_max_tokens?: number;
  /**
   * Nucleus sampling threshold
   */
  gen_top_p?: number;
  /**
   * Generation timeout (seconds)
   */
  gen_timeout?: number;
  /**
   * Max retries for generation
   */
  gen_retry_max?: number;
  /**
   * Model for code enrichment
   */
  enrich_model?: string;
  /**
   * Enrichment backend
   */
  enrich_backend?: string;
  /**
   * Disable code enrichment
   */
  enrich_disabled?: number;
  /**
   * Context window for Ollama
   */
  ollama_num_ctx?: number;
  /**
   * CLI generation model
   */
  gen_model_cli?: string;
  /**
   * Ollama generation model
   */
  gen_model_ollama?: string;
  /**
   * HTTP transport generation model override
   */
  gen_model_http?: string;
  /**
   * MCP transport generation model override
   */
  gen_model_mcp?: string;
  /**
   * Ollama enrichment model
   */
  enrich_model_ollama?: string;
  /**
   * Ollama API URL
   */
  ollama_url?: string;
  /**
   * OpenAI API base URL override (for proxies)
   */
  openai_base_url?: string;
  /**
   * Maximum total time to wait for a local (Ollama) generation request to complete (seconds)
   */
  ollama_request_timeout?: number;
  /**
   * Maximum idle time allowed between streamed chunks from local (Ollama) during generation (seconds)
   */
  ollama_stream_idle_timeout?: number;
}
/**
 * Configuration for Neo4j graph storage and traversal.
 */
export interface GraphStorageConfig {
  /**
   * Neo4j connection URI (bolt:// or neo4j://)
   */
  neo4j_uri?: string;
  /**
   * Neo4j username
   */
  neo4j_user?: string;
  /**
   * Neo4j password (recommend using environment variable)
   */
  neo4j_password?: string;
  /**
   * Neo4j database name
   */
  neo4j_database?: string;
  /**
   * Maximum traversal hops for graph search
   */
  max_hops?: number;
  /**
   * Include community detection in graph analysis
   */
  include_communities?: boolean;
  /**
   * Community detection algorithm
   */
  community_algorithm?: "louvain" | "label_propagation";
  /**
   * Entity types to extract and store in graph
   */
  entity_types?: string[];
  /**
   * Relationship types to extract
   */
  relationship_types?: string[];
  /**
   * Number of results from graph traversal
   */
  graph_search_top_k?: number;
}
/**
 * Context hydration configuration.
 */
export interface HydrationConfig {
  /**
   * Context hydration mode
   */
  hydration_mode?: string;
  /**
   * Max characters to hydrate
   */
  hydration_max_chars?: number;
}
/**
 * Indexing and vector storage configuration.
 */
export interface IndexingConfig {
  /**
   * PostgreSQL pgvector URL
   */
  postgres_url?: string;
  /**
   * pgvector table name template
   */
  table_name?: string;
  /**
   * Collection suffix for multi-index scenarios
   */
  collection_suffix?: string;
  /**
   * Fallback repository path if not found in repos.json
   */
  repo_path?: string;
  /**
   * Batch size for indexing
   */
  indexing_batch_size?: number;
  /**
   * Parallel workers for indexing
   */
  indexing_workers?: number;
  /**
   * BM25 tokenizer type
   */
  bm25_tokenizer?: string;
  /**
   * Stemmer language
   */
  bm25_stemmer_lang?: string;
  /**
   * Stopwords language code
   */
  bm25_stopwords_lang?: string;
  /**
   * Excluded file extensions (comma-separated)
   */
  index_excluded_exts?: string;
  /**
   * Max file size to index (MB)
   */
  index_max_file_size_mb?: number;
  /**
   * Skip dense vector indexing
   */
  skip_dense?: number;
  /**
   * Base output directory
   */
  out_dir_base?: string;
  /**
   * Override for OUT_DIR_BASE if specified
   */
  rag_out_base?: string;
  /**
   * Repository configuration file
   */
  repos_file?: string;
}
/**
 * Discriminative keywords configuration.
 */
export interface KeywordsConfig {
  /**
   * Max discriminative keywords per repo
   */
  keywords_max_per_repo?: number;
  /**
   * Min frequency for keyword
   */
  keywords_min_freq?: number;
  /**
   * Score boost for keyword matches
   */
  keywords_boost?: number;
  /**
   * Auto-generate keywords
   */
  keywords_auto_generate?: number;
  /**
   * Hours between keyword refresh
   */
  keywords_refresh_hours?: number;
}
/**
 * Layer-specific scoring bonuses with intent-aware matrix.
 *
 * The base bonuses are additive percentages (e.g., 0.15 = +15%).
 * They are converted downstream to multiplicative factors.
 */
export interface LayerBonusConfig {
  /**
   * Bonus for GUI/front-end layers
   */
  gui?: number;
  /**
   * Bonus for retrieval/API layers
   */
  retrieval?: number;
  /**
   * Bonus for indexing/ingestion layers
   */
  indexer?: number;
  /**
   * Penalty for vendor/third-party code (negative values apply a penalty)
   */
  vendor_penalty?: number;
  /**
   * Bonus for recently modified files
   */
  freshness_bonus?: number;
  /**
   * Intent-to-layer bonus matrix. Keys are query intents, values are layer->multiplier maps.
   */
  intent_matrix?: {
    [k: string]: {
      [k: string]: number;
    };
  };
}
/**
 * Reranking configuration for result refinement.
 */
export interface RerankingConfig {
  /**
   * Reranker mode: 'cloud' (Cohere/Voyage API), 'local' (HuggingFace cross-encoder), 'learning' (TRIBRID cross-encoder-tribrid), 'none' (disabled)
   */
  reranker_mode?: string;
  /**
   * Cloud reranker provider when mode=cloud (cohere, voyage, jina)
   */
  reranker_cloud_provider?: string;
  /**
   * Cloud reranker model name when mode=cloud (Cohere: rerank-v3.5)
   */
  reranker_cloud_model?: string;
  /**
   * Local HuggingFace cross-encoder model when mode=local
   */
  reranker_local_model?: string;
  /**
   * Blend weight for reranker scores
   */
  tribrid_reranker_alpha?: number;
  /**
   * Number of candidates to rerank (local/learning mode)
   */
  tribrid_reranker_topn?: number;
  /**
   * Number of candidates to rerank (cloud mode)
   */
  reranker_cloud_top_n?: number;
  /**
   * Reranker batch size
   */
  tribrid_reranker_batch?: number;
  /**
   * Max token length for reranker
   */
  tribrid_reranker_maxlen?: number;
  /**
   * Hot-reload on model change
   */
  tribrid_reranker_reload_on_change?: number;
  /**
   * Reload check period (seconds)
   */
  tribrid_reranker_reload_period_sec?: number;
  /**
   * Reranker API timeout (seconds)
   */
  reranker_timeout?: number;
  /**
   * Snippet chars for reranking input
   */
  rerank_input_snippet_chars?: number;
  /**
   * Allow transformers remote code for HF rerankers that require it
   */
  transformers_trust_remote_code?: number;
}
/**
 * Configuration for retrieval and search parameters.
 */
export interface RetrievalConfig {
  /**
   * RRF rank smoothing constant (higher = more weight to top ranks)
   */
  rrf_k_div?: number;
  /**
   * Number of final results to return in LangGraph pipeline
   */
  langgraph_final_k?: number;
  /**
   * Maximum number of query rewrites for multi-query expansion
   */
  max_query_rewrites?: number;
  /**
   * Maximum number of query rewrites for LangGraph pipeline
   */
  langgraph_max_query_rewrites?: number;
  /**
   * Confidence threshold for fallback retrieval strategies
   */
  fallback_confidence?: number;
  /**
   * Default top-k for search results
   */
  final_k?: number;
  /**
   * Top-k for evaluation runs
   */
  eval_final_k?: number;
  /**
   * Confidence threshold for top-1
   */
  conf_top1?: number;
  /**
   * Confidence threshold for avg top-5
   */
  conf_avg5?: number;
  /**
   * Minimum confidence threshold
   */
  conf_any?: number;
  /**
   * Enable multi-query in eval
   */
  eval_multi?: number;
  /**
   * Enable synonym expansion
   */
  query_expansion_enabled?: number;
  /**
   * Weight for BM25 in hybrid search
   */
  bm25_weight?: number;
  /**
   * BM25 term frequency saturation parameter (higher = more weight to term frequency)
   */
  bm25_k1?: number;
  /**
   * BM25 length normalization (0=no penalty, 1=full penalty, 0.3-0.5 recommended for code)
   */
  bm25_b?: number;
  /**
   * Weight for vector search
   */
  vector_weight?: number;
  /**
   * Enable chunk_summary-based retrieval
   */
  chunk_summary_search_enabled?: number;
  /**
   * Query variants for multi-query
   */
  multi_query_m?: number;
  /**
   * Enable semantic synonym expansion
   */
  use_semantic_synonyms?: number;
  /**
   * Custom path to semantic_synonyms.json (default: data/semantic_synonyms.json)
   */
  tribrid_synonyms_path?: string;
  /**
   * Top-K for dense vector search
   */
  topk_dense?: number;
  /**
   * Top-K for sparse BM25 search
   */
  topk_sparse?: number;
  /**
   * Result hydration mode
   */
  hydration_mode?: string;
  /**
   * Max characters for result hydration
   */
  hydration_max_chars?: number;
}
/**
 * Configuration for result scoring and boosting.
 */
export interface ScoringConfig {
  /**
   * Bonus score for chunks matched via chunk_summary-based retrieval
   */
  chunk_summary_bonus?: number;
  /**
   * Score multiplier when filename exactly matches query terms
   */
  filename_boost_exact?: number;
  /**
   * Score multiplier when path components match query terms
   */
  filename_boost_partial?: number;
  /**
   * Vendor code preference
   */
  vendor_mode?: string;
  /**
   * Comma-separated path prefixes to boost
   */
  path_boosts?: string;
}
/**
 * System prompts for LLM interactions - affects RAG pipeline behavior.
 *
 * These prompts control how LLMs behave during query processing, code analysis,
 * and result generation. Changes here can significantly impact RAG accuracy.
 */
export interface SystemPromptsConfig {
  /**
   * Main conversational AI system prompt for answering codebase questions
   */
  main_rag_chat?: string;
  /**
   * Generate query variants for better recall in hybrid search
   */
  query_expansion?: string;
  /**
   * Optimize user query for code search - expand CamelCase, include API nouns
   */
  query_rewrite?: string;
  /**
   * Generate JSON summaries for code chunks during indexing
   */
  semantic_chunk_summaries?: string;
  /**
   * Extract metadata from code chunks during indexing
   */
  code_enrichment?: string;
  /**
   * Analyze eval regressions with skeptical approach - avoid false explanations
   */
  eval_analysis?: string;
  /**
   * Lightweight chunk_summary generation prompt for faster indexing
   */
  lightweight_chunk_summaries?: string;
}
/**
 * Observability and tracing configuration.
 */
export interface TracingConfig {
  /**
   * Enable distributed tracing
   */
  tracing_enabled?: number;
  /**
   * Trace sampling rate (0.0-1.0)
   */
  trace_sampling_rate?: number;
  /**
   * Prometheus metrics port
   */
  prometheus_port?: number;
  /**
   * Enable metrics collection
   */
  metrics_enabled?: number;
  /**
   * Include resolved alerts
   */
  alert_include_resolved?: number;
  /**
   * Alert webhook timeout (seconds)
   */
  alert_webhook_timeout?: number;
  /**
   * Logging level
   */
  log_level?: string;
  /**
   * Tracing backend mode
   */
  tracing_mode?: string;
  /**
   * Auto-enable LangSmith tracing
   */
  trace_auto_ls?: number;
  /**
   * Number of traces to retain
   */
  trace_retention?: number;
  /**
   * Query log file path
   */
  tribrid_log_path?: string;
  /**
   * Alert severities to notify
   */
  alert_notify_severities?: string;
  /**
   * LangChain/LangSmith API endpoint
   */
  langchain_endpoint?: string;
  /**
   * LangChain project name
   */
  langchain_project?: string;
  /**
   * Enable LangChain v2 tracing
   */
  langchain_tracing_v2?: number;
  /**
   * LangTrace API host
   */
  langtrace_api_host?: string;
  /**
   * LangTrace project ID
   */
  langtrace_project_id?: string;
}
/**
 * Reranker training configuration.
 */
export interface TrainingConfig {
  /**
   * Training epochs for reranker
   */
  reranker_train_epochs?: number;
  /**
   * Training batch size
   */
  reranker_train_batch?: number;
  /**
   * Learning rate
   */
  reranker_train_lr?: number;
  /**
   * Warmup steps ratio
   */
  reranker_warmup_ratio?: number;
  /**
   * Min triplets for training
   */
  triplets_min_count?: number;
  /**
   * Triplet mining mode
   */
  triplets_mine_mode?: string;
  /**
   * Reranker model path
   */
  tribrid_reranker_model_path?: string;
  /**
   * Triplet mining mode
   */
  tribrid_reranker_mine_mode?: string;
  /**
   * Reset triplets file before mining
   */
  tribrid_reranker_mine_reset?: number;
  /**
   * Training triplets file path
   */
  tribrid_triplets_path?: string;
}
/**
 * TRIBRID RAG Engine tunable configuration parameters
 */
export interface TRIBRIDConfig {
  retrieval?: RetrievalConfig;
  scoring?: ScoringConfig;
  layer_bonus?: LayerBonusConfig;
  embedding?: EmbeddingConfig;
  chunking?: ChunkingConfig;
  indexing?: IndexingConfig;
  graph_storage?: GraphStorageConfig;
  fusion?: FusionConfig;
  reranking?: RerankingConfig;
  generation?: GenerationConfig;
  enrichment?: EnrichmentConfig;
  chunk_summaries?: ChunkSummaryConfig;
  keywords?: KeywordsConfig;
  tracing?: TracingConfig;
  training?: TrainingConfig;
  ui?: UIConfig;
  hydration?: HydrationConfig;
  evaluation?: EvaluationConfig;
  system_prompts?: SystemPromptsConfig;
  docker?: DockerConfig;
  [k: string]: unknown;
}
/**
 * User interface configuration.
 */
export interface UIConfig {
  /**
   * Enable streaming responses
   */
  chat_streaming_enabled?: number;
  /**
   * Max chat history messages
   */
  chat_history_max?: number;
  /**
   * Include reasoning/thinking in streamed responses when supported by model
   */
  chat_stream_include_thinking?: number;
  /**
   * Show confidence badge on chat answers
   */
  chat_show_confidence?: number;
  /**
   * Show citations list on chat answers
   */
  chat_show_citations?: number;
  /**
   * Show routing trace panel by default
   */
  chat_show_trace?: number;
  /**
   * Default model for chat if not specified in request
   */
  chat_default_model?: string;
  /**
   * Streaming response timeout in seconds
   */
  chat_stream_timeout?: number;
  /**
   * Max thinking tokens for Anthropic extended thinking
   */
  chat_thinking_budget_tokens?: number;
  /**
   * Embedded editor port
   */
  editor_port?: number;
  /**
   * Default Grafana dashboard UID
   */
  grafana_dashboard_uid?: string;
  /**
   * Grafana dashboard slug
   */
  grafana_dashboard_slug?: string;
  /**
   * Grafana base URL
   */
  grafana_base_url?: string;
  /**
   * Grafana authentication mode
   */
  grafana_auth_mode?: string;
  /**
   * Enable Grafana embedding
   */
  grafana_embed_enabled?: number;
  /**
   * Grafana kiosk mode
   */
  grafana_kiosk?: string;
  /**
   * Grafana organization ID
   */
  grafana_org_id?: number;
  /**
   * Grafana refresh interval
   */
  grafana_refresh?: string;
  /**
   * Editor bind mode
   */
  editor_bind?: string;
  /**
   * Enable editor embedding
   */
  editor_embed_enabled?: number;
  /**
   * Enable embedded editor
   */
  editor_enabled?: number;
  /**
   * Editor Docker image
   */
  editor_image?: string;
  /**
   * UI theme mode
   */
  theme_mode?: string;
  /**
   * Auto-open browser on start
   */
  open_browser?: number;
  /**
   * Runtime environment mode (development uses localhost, production uses deployed URLs)
   */
  runtime_mode?: "development" | "production";
}
