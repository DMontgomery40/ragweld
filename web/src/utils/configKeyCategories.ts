// Deterministic display grouping for the flat env-style config snapshot that
// eval runs capture (TriBridConfig.to_flat_dict keys). Presentation-only: the
// wire payload stays untouched; this maps each key to a labeled category and
// an honest "can this change what retrieval/answers return" tier so the
// drill-down stops rendering 290 keys as one flat "OTHER" list.

export type ConfigKeyTier = 'response' | 'operational';

export interface ConfigKeyCategory {
  category: string;
  tier: ConfigKeyTier;
}

// Ordered rules: first match wins. Anchored prefixes / exact names only —
// no fuzzy guessing; anything unmatched lands in "Other" (response tier so a
// new retrieval knob is never silently filed as ignorable).
const RULES: Array<{ test: RegExp; category: string; tier: ConfigKeyTier }> = [
  // --- UI / workbench presentation (checked before broader prefixes) ---
  { test: /^CHAT_SHOW_/, category: 'UI & Workbench', tier: 'operational' },
  { test: /^LEARNING_RERANKER_(VISUALIZER|STUDIO|DOCKVIEW|LAYOUT|LOGS_RENDERER|SHOW_SETUP)/, category: 'UI & Workbench', tier: 'operational' },
  { test: /^(THEME_MODE|OPEN_BROWSER|EDITOR_)/, category: 'UI & Workbench', tier: 'operational' },

  // --- Observability / alerting / cost ---
  { test: /^(GRAFANA_|ALERT|ALLOY_|TEMPO_|LOKI_|MIMIR_|PYROSCOPE_|FARO_|LANGFUSE_|OPENCOST_|OTEL_|OTLP_|TRACE_|TRACING_|METRICS_ENABLED$|LOG_LEVEL$|TRIBRID_LOG_PATH$|COST_TRACKING_)/, category: 'Observability & Alerts', tier: 'operational' },

  // --- Data stores / runtime wiring ---
  { test: /^(POSTGRES_|NEO4J_URI$|NEO4J_USER$|NEO4J_DATABASE$|DOCKER_|MCP_|DEV_|RUNTIME_MODE$|ESTIMATED_TOKENS_PER_SECOND_LOCAL$)/, category: 'Infra & Data Stores', tier: 'operational' },

  // --- Training (shapes future models, not this run's answers) ---
  { test: /^(LEARNING_RERANKER_|RAGWELD_AGENT_|RERANKER_TRAIN_|TRIPLETS_|TRIBRID_TRIPLETS_PATH$|TRIBRID_RERANKER_MINE_)/, category: 'Training & Mining', tier: 'operational' },

  // --- Response-affecting ---
  { test: /^BM25_/, category: 'Sparse (BM25)', tier: 'response' },
  { test: /^GRAPH_/, category: 'Graph Search', tier: 'response' },
  { test: /^(EMBEDDING_|VOYAGE_MODEL$)/, category: 'Embedding', tier: 'response' },
  { test: /^(RERANKER_|RERANK_|TRIBRID_RERANKER_)/, category: 'Reranking', tier: 'response' },
  { test: /^(CHUNKING_|CHUNK_SIZE$|CHUNK_OVERLAP$|MAX_CHUNK_TOKENS$|MIN_CHUNK_CHARS$|AST_OVERLAP_LINES$|PRESERVE_IMPORTS$|INDEXING_|INDEX_|MAX_INDEXABLE_FILE_SIZE$|PARQUET_|ENRICH_|CHUNK_SUMMARIES_)/, category: 'Chunking & Indexing', tier: 'response' },
  { test: /^(GEN_|CHAT_)/, category: 'Generation & Chat', tier: 'response' },
  { test: /^PROMPT_/, category: 'Prompts', tier: 'response' },
  { test: /^SEMANTIC_CACHE_/, category: 'Semantic Cache', tier: 'response' },
  { test: /^(KEYWORDS_|USE_SEMANTIC_SYNONYMS$|TRIBRID_SYNONYMS_PATH$)/, category: 'Keywords & Synonyms', tier: 'response' },
  { test: /^(EVAL_|RAGAS_|PROMPTFOO_|BASELINE_PATH$)/, category: 'Evaluation', tier: 'response' },
  { test: /^(FUSION_|RRF_K_DIV$|VECTOR_WEIGHT$|FINAL_K$|LANGGRAPH_|MAX_QUERY_REWRITES$|MQ_REWRITES$|MULTI_QUERY_M$|FALLBACK_CONFIDENCE$|CONF_(TOP1|AVG5|ANY)$|SKIP_DENSE$|TOPK_(DENSE|SPARSE)$|GREEDY_FALLBACK_TARGET$|QUERY_EXPANSION_|HYDRATION_|PATH_BOOSTS$|FILENAME_BOOST_|FRESHNESS_BONUS$|LAYER_BONUS_|LAYER_INTENT_MATRIX$|CHUNK_SUMMARY_BONUS$|CHUNK_SUMMARY_SEARCH_ENABLED$|VENDOR_(MODE|PENALTY)$)/, category: 'Retrieval & Fusion', tier: 'response' },
];

export function categorizeConfigKey(key: string): ConfigKeyCategory {
  const upper = String(key || '').toUpperCase();
  for (const rule of RULES) {
    if (rule.test.test(upper)) return { category: rule.category, tier: rule.tier };
  }
  return { category: 'Other', tier: 'response' };
}

// Display order within each tier.
export const RESPONSE_CATEGORY_ORDER = [
  'Retrieval & Fusion',
  'Sparse (BM25)',
  'Graph Search',
  'Embedding',
  'Reranking',
  'Semantic Cache',
  'Chunking & Indexing',
  'Keywords & Synonyms',
  'Generation & Chat',
  'Prompts',
  'Evaluation',
  'Other',
];

export const OPERATIONAL_CATEGORY_ORDER = [
  'Training & Mining',
  'Observability & Alerts',
  'UI & Workbench',
  'Infra & Data Stores',
];

// Categories whose changes genuinely cannot alter what a retrieval/eval run
// returns. Deliberately excludes 'Infra & Data Stores': pointing at a
// different Postgres/Neo4j can change the corpus itself, so those diffs must
// not be waved off.
export const RESULT_SAFE_CATEGORIES = new Set([
  'Training & Mining',
  'Observability & Alerts',
  'UI & Workbench',
]);

export function isResultSafeKey(key: string): boolean {
  const { category, tier } = categorizeConfigKey(key);
  return tier === 'operational' && RESULT_SAFE_CATEGORIES.has(category);
}
