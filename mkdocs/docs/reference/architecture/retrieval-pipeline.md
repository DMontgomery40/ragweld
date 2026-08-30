# Retrieval pipeline

!!! info "Generated page"
    Node labels are the real configuration keys and defaults from `server/models/tribrid_config_model.py`;
    module paths are checked to exist when this page is generated. Tune values in the config UI or
    `tribrid_config.json`; corpus-scoped overrides apply per corpus.

The three legs (dense and sparse from Qdrant generations, graph from the Neo4j lexical graph) are fused with
weighted RRF, boosted, deduplicated, optionally reranked, gated on confidence and hydrated before generation
through the LiteLLM gateway. Every value shown is the shipped default.

```mermaid
flowchart TB
    subgraph s_in["Request"]
    q["Query\nPOST /api/search, /api/chat/stream, /api/answer"]
    cache["Semantic cache (server/retrieval/cache.py)\nenabled=False\nmode=read_write\nsimilarity_threshold_search=0.9\nsimilarity_threshold_chat=0.95\nttl_seconds_search=900\nmax_entries=5000"]
    expand["Query expansion\nquery_expansion_enabled=True\nmulti_query_m=4\nmax_query_rewrites=2\nuse_semantic_synonyms=True"]
    end
    subgraph s_legs["Three retrieval legs"]
    embed["Embedder (server/indexing/embedder.py)\nembedding_backend=deterministic\nembedding_type=openai\nembedding_model=text-embedding-3-large\nembedding_dim=3072"]
    dense["Dense leg -> Qdrant dense generation\nenabled=True\ntop_k=50\nmin_score_vector=0.0"]
    sparse["Sparse leg -> Qdrant sparse generation (BM25)\nenabled=True\ntop_k=50\nbm25_k1=1.2\nbm25_b=0.4\nmin_score_sparse=0.0"]
    graph["Graph leg -> Neo4j (Document/Chunk lexical graph)\nenabled=True\nmode=chunk\nmax_hops=2\ntop_k=30\nchunk_neighbor_window=1\ninclude_communities=True\nmin_score_graph=0.0"]
    end
    subgraph s_stores["Stores"]
    qdrant["Qdrant (server/retrieval/qdrant_store.py)\nurl=http://127.0.0.1:56333"]
    pg["Postgres chunk rows + generation manifests\npostgres_url=postgresql://postgres:postgres@localhost:5432/tribrid_rag"]
    neo4j["Neo4j (server/db/neo4j.py)\nneo4j_uri=bolt://localhost:7687\nneo4j_database_mode=shared\ncommunity_algorithm=louvain"]
    end
    subgraph s_fuse["Fusion and shaping (server/retrieval/fusion.py)"]
    fusion["Weighted RRF fusion\nvector_weight=0.4\nsparse_weight=0.3\ngraph_weight=0.3\nrrf_k=60\n"]
    boost["Scoring boosts (server/retrieval/scoring_boosts.py)\nchunk_summary_bonus=0.08\nfilename_boost_exact=1.5\nfilename_boost_partial=1.2\nvendor_mode=prefer_first_party\ngui=0.15\nretrieval=0.15\nindexer=0.15\nvendor_penalty=-0.1\nfreshness_bonus=0.05"]
    shape["Dedup / MMR / neighbours\ndedup_by=chunk_id\nmax_chunks_per_file=3\nneighbor_window=1\nenable_mmr=False\nmmr_lambda=0.7\nchunk_summary_search_enabled=True"]
    end
    subgraph s_rerank["Reranking (server/retrieval/rerank.py, gateway_reranker.py)"]
    rerank["Reranker\nreranker_mode=none\nreranker_cloud_provider=litellm\nreranker_cloud_model=openai.gpt-4.1-nano\nreranker_cloud_top_n=50\ntribrid_reranker_alpha=0.7\ntribrid_reranker_topn=50\nreranker_timeout=10"]
    end
    subgraph s_out["Answer"]
    conf["Confidence gate\nconf_top1=0.62\nconf_avg5=0.55\nconf_any=0.55\nfallback_confidence=0.55\nfinal_k=10\neval_final_k=5"]
    hydrate["Hydration\nhydration_mode=lazy\nhydration_max_chars=2000"]
    gen["Generation via LiteLLM gateway (server/services/answer_service.py)\ngen_model=ragweld-local\ngen_max_tokens=512\ngen_temperature=0.0"]
    trace["Trace + cost accounting\nserver/services/traces.py -> Tempo / Langfuse"]
    end
    q --> cache
    cache --> expand
    expand --> embed
    expand --> sparse
    expand --> graph
    embed --> dense
    dense --> qdrant
    sparse --> qdrant
    graph --> neo4j
    qdrant --> pg
    neo4j --> pg
    dense --> fusion
    sparse --> fusion
    graph --> fusion
    fusion --> boost
    boost --> shape
    shape --> rerank
    rerank --> conf
    conf --> hydrate
    hydrate --> gen
    gen --> trace
    gen --> cache
```

## Every knob on the path

### `semantic_cache`

| Field | Default | What it does |
|---|---|---|
| `enabled` | `False` | Enable semantic cache reads/writes. |
| `mode` | `read_write` | Cache mode when enabled. |
| `max_entries` | `5000` | Maximum cache rows to retain per scope/endpoint. |
| `min_query_chars` | `3` | Minimum query length before cache is eligible. |
| `similarity_threshold_search` | `0.9` | Minimum cosine similarity for semantic search cache hits. |
| `similarity_threshold_answer` | `0.93` | Minimum cosine similarity for semantic answer cache hits. |
| `similarity_threshold_chat` | `0.95` | Minimum cosine similarity for semantic chat cache hits. |
| `ttl_seconds_search` | `900` | TTL in seconds for search cache entries. |
| `ttl_seconds_answer` | `1800` | TTL in seconds for answer cache entries. |
| `ttl_seconds_chat` | `600` | TTL in seconds for chat cache entries. |
| `chat_history_window` | `6` | Number of prior conversation turns included in chat cache fingerprint. |
| `bypass_if_images` | `True` | Bypass chat generation cache when images are attached. |
| `max_temperature_for_write` | `0.5` | Skip generation-cache writes when temperature exceeds this value. |

### `retrieval`

| Field | Default | What it does |
|---|---|---|
| `max_query_rewrites` | `2` | Maximum number of query rewrites for multi-query expansion |
| `langgraph_max_query_rewrites` | `2` | Maximum number of query rewrites for LangGraph pipeline |
| `fallback_confidence` | `0.55` | Confidence threshold for fallback retrieval strategies |
| `final_k` | `10` | Default top-k for search results |
| `eval_final_k` | `5` | Final-k used only by the evaluation flow (server/api/eval.py); the live retrieval pipeline uses retrieval.final_k. Distinct knob, not a duplicate. |
| `conf_top1` | `0.62` | Confidence threshold for top-1 |
| `conf_avg5` | `0.55` | Confidence threshold for avg top-5 |
| `conf_any` | `0.55` | Minimum confidence threshold |
| `eval_multi` | `True` | Enable multi-query in eval |
| `query_expansion_enabled` | `True` | Enable synonym expansion |
| `chunk_summary_search_enabled` | `True` | Enable chunk_summary-based retrieval |
| `max_chunks_per_file` | `3` | Max chunks to return per file_path (document-aware result shaping). |
| `dedup_by` | `chunk_id` | Dedup key for final results. |
| `neighbor_window` | `1` | Include adjacent chunks by ordinal for coherence (requires chunk_ordinal metadata). |
| `min_score_vector` | `0.0` | Minimum score threshold for vector leg results (0 disables). |
| `min_score_sparse` | `0.0` | Minimum score threshold for sparse leg results (0 disables). Note: sparse scores are engine-dependent (FTS vs BM25). |
| `min_score_graph` | `0.0` | Minimum score threshold for graph leg results (0 disables). |
| `enable_mmr` | `False` | Enable MMR diversification when embeddings are available. |
| `mmr_lambda` | `0.7` | MMR lambda (1=query relevance only, 0=diversity only). |
| `multi_query_m` | `4` | Query variants for multi-query |
| `use_semantic_synonyms` | `True` | Enable semantic synonym expansion |
| `tribrid_synonyms_path` | `` | Custom path to semantic_synonyms.json (default: data/semantic_synonyms.json) |
| `hydration_mode` | `lazy` | Result hydration mode |
| `hydration_max_chars` | `2000` | Max characters for result hydration |

### `embedding`

| Field | Default | What it does |
|---|---|---|
| `embedding_backend` | `deterministic` | Embedding execution backend. 'deterministic' is offline/test-friendly; 'provider' calls real providers. |
| `embedding_type` | `openai` | Embedding provider (dynamic - validated against models.json at runtime) |
| `embedding_model` | `text-embedding-3-large` | OpenAI embedding model |
| `embedding_dim` | `3072` | Embedding dimensions |
| `auto_set_dimensions` | `True` | When true, the UI auto-syncs embedding_dim from data/models.json when model changes. |
| `input_truncation` | `truncate_end` | What to do when text exceeds embedding/token limits. |
| `embed_text_prefix` | `` | Prefix added before chunk text prior to embedding (stable document context). |
| `embed_text_suffix` | `` | Suffix added after chunk text prior to embedding. |
| `contextual_chunk_embeddings` | `off` | Contextual chunk embedding mode. 'late_chunking_local_only' requires local/HF provider backend. |
| `late_chunking_max_doc_tokens` | `8192` | Max tokens per document segment for local late chunking. |
| `voyage_model` | `voyage-code-3` | Voyage embedding model |
| `embedding_model_local` | `BAAI/bge-small-en-v1.5` | Local SentenceTransformer model |
| `embedding_model_mlx` | `mlx-community/all-MiniLM-L6-v2-4bit` | MLX-optimized embedding model (used when embedding_type=mlx) |
| `embedding_batch_size` | `64` | Batch size for embedding generation |
| `embedding_max_tokens` | `8000` | Max tokens per embedding chunk |
| `embedding_cache_enabled` | `True` | Enable embedding cache |
| `embedding_timeout` | `30` | Embedding API timeout (seconds) |
| `embedding_retry_max` | `3` | Max retries for embedding API |

### `vector_search`

| Field | Default | What it does |
|---|---|---|
| `enabled` | `True` | Enable the dense vector (Qdrant) leg in tri-brid retrieval |
| `top_k` | `50` | Number of results to retrieve from vector search |
| `similarity_threshold` | `0.0` | Minimum similarity score threshold (0 = no threshold) |

### `sparse_search`

| Field | Default | What it does |
|---|---|---|
| `enabled` | `True` | Enable the sparse (Qdrant/bm25) leg in tri-brid retrieval |
| `top_k` | `50` | Number of results to retrieve from the sparse leg |
| `bm25_k1` | `1.2` | BM25 term-frequency saturation for the Qdrant/bm25 sparse vectors (higher = more weight to term frequency). Part of the sparse index contract (re-index on change). |
| `bm25_b` | `0.4` | BM25 length normalization for the Qdrant/bm25 sparse vectors (0 = no penalty, 1 = full penalty). Part of the sparse index contract (re-index on change). |

### `graph_search`

| Field | Default | What it does |
|---|---|---|
| `mode` | `chunk` | Graph retrieval mode. 'chunk' uses lexical chunk nodes + Neo4j vector index; 'entity' uses the legacy code-entity graph. |
| `enabled` | `True` | Enable graph search in tri-brid retrieval |
| `chunk_neighbor_window` | `1` | When mode='chunk', include up to N adjacent chunks (NEXT_CHUNK) around each seed hit |
| `chunk_seed_overfetch_multiplier` | `10` | When mode='chunk' and Neo4j uses a shared database, overfetch seed hits before filtering by corpus_id |
| `chunk_entity_expansion_enabled` | `True` | When mode='chunk', expand from seed chunks via Entity graph (IN_CHUNK links) to find related chunks |
| `chunk_entity_expansion_weight` | `0.8` | Blend weight for entity-expansion scores relative to seed chunk scores (mode='chunk') |
| `max_hops` | `2` | Maximum graph traversal hops |
| `include_communities` | `True` | Include community-based expansion in graph search |
| `top_k` | `30` | Number of results to retrieve from graph search |

### `graph_storage`

| Field | Default | What it does |
|---|---|---|
| `neo4j_uri` | `bolt://localhost:7687` | Neo4j connection URI (bolt:// or neo4j://) |
| `neo4j_user` | `neo4j` | Neo4j username |
| `neo4j_database` | `neo4j` | Neo4j database name |
| `neo4j_database_mode` | `shared` | Database isolation mode: 'shared' uses a single Neo4j database (Community-compatible), 'per_corpus' uses a separate Neo4j database per corpus (Enterprise multi-database). |
| `neo4j_database_prefix` | `tribrid_` | Prefix for per-corpus Neo4j database names when neo4j_database_mode='per_corpus'. |
| `neo4j_auto_create_databases` | `True` | Automatically create per-corpus Neo4j databases when missing (Enterprise). |
| `max_hops` | `2` | Maximum traversal hops for graph search |
| `include_communities` | `True` | Include community detection in graph analysis |
| `community_algorithm` | `louvain` | Community detection algorithm |
| `entity_types` | `['function', 'class', 'module', 'variable', 'import']` | Entity types to extract and store in graph |
| `relationship_types` | `['calls', 'imports', 'inherits', 'contains', 'references']` | Relationship types to extract |
| `graph_search_top_k` | `30` | Number of results from graph traversal |

### `fusion`

| Field | Default | What it does |
|---|---|---|
| `method` | `rrf` | Fusion method: 'rrf' (Reciprocal Rank Fusion) or 'weighted' (score-based) |
| `vector_weight` | `0.4` | Weight for vector search results (Qdrant dense) |
| `sparse_weight` | `0.3` | Weight for sparse (Qdrant/bm25) search results |
| `graph_weight` | `0.3` | Weight for graph search results (Neo4j) |
| `rrf_k` | `60` | RRF smoothing constant (higher = more weight to top ranks) |
| `normalize_scores` | `True` | Normalize scores to [0,1] before fusion |

### `scoring`

| Field | Default | What it does |
|---|---|---|
| `chunk_summary_bonus` | `0.08` | Bonus score for chunks matched via chunk_summary-based retrieval |
| `filename_boost_exact` | `1.5` | Score multiplier when filename exactly matches query terms |
| `filename_boost_partial` | `1.2` | Score multiplier when path components match query terms |
| `vendor_mode` | `prefer_first_party` | Vendor code preference |
| `path_boosts` | `/gui,/server,/indexer,/retrieval` | Comma-separated path prefixes to boost |

### `layer_bonus`

| Field | Default | What it does |
|---|---|---|
| `gui` | `0.15` | Bonus for GUI/front-end layers |
| `retrieval` | `0.15` | Bonus for retrieval/API layers |
| `indexer` | `0.15` | Bonus for indexing/ingestion layers |
| `vendor_penalty` | `-0.1` | Penalty for vendor/third-party code (negative values apply a penalty) |
| `freshness_bonus` | `0.05` | Bonus for recently modified files |
| `intent_matrix` | `{'gui': {'gui': 1.2, 'web': 1.2, 'server': 0.9, 'retrieva...` | Intent-to-layer bonus matrix. Keys are query intents, values are layer->multiplier maps. |

### `reranking`

| Field | Default | What it does |
|---|---|---|
| `reranker_mode` | `none` | Reranker mode: 'cloud' (LiteLLM gateway alias or Cohere API), 'learning' (MLX Qwen3 LoRA learning reranker), 'none' (disabled). Stale values such as 'local'/'hf' fail validation and must be migrated. |
| `reranker_cloud_provider` | `litellm` | Cloud reranker provider when mode=cloud: 'litellm' scores candidates listwise through a LiteLLM gateway alias (no local model, no extra credential); 'cohere' calls the Cohere rerank API (COHERE_API_KEY). |
| `reranker_cloud_model` | `openai.gpt-4.1-nano` | Cloud reranker model when mode=cloud: a LiteLLM gateway alias for provider 'litellm' (a cheap non-reasoning instruct model is ideal), or a Cohere rerank model id for provider 'cohere'. |
| `tribrid_reranker_alpha` | `0.7` | Blend weight for reranker scores |
| `tribrid_reranker_topn` | `50` | Number of candidates to rerank (learning mode) |
| `reranker_cloud_top_n` | `50` | Number of candidates to rerank (cloud mode) |
| `tribrid_reranker_batch` | `16` | Reranker batch size |
| `tribrid_reranker_maxlen` | `512` | Max token length for reranker |
| `tribrid_reranker_reload_on_change` | `False` | Hot-reload on model change |
| `tribrid_reranker_reload_period_sec` | `60` | Reload check period (seconds) |
| `reranker_timeout` | `10` | Reranker API timeout (seconds) |
| `rerank_input_snippet_chars` | `700` | Snippet chars for reranking input |

### `hydration`

| Field | Default | What it does |
|---|---|---|
| `hydration_mode` | `lazy` | Context hydration mode |
| `hydration_max_chars` | `2000` | Max characters to hydrate |

### `generation`

| Field | Default | What it does |
|---|---|---|
| `gen_model` | `ragweld-local` | Primary LiteLLM model alias |
| `gen_temperature` | `0.0` | Generation temperature |
| `gen_max_tokens` | `512` | Max tokens for generation |
| `gen_top_p` | `1.0` | Nucleus sampling threshold |
| `gen_timeout` | `600` | Generation timeout in seconds for non-chat generation calls (eval analysis, synthetic data); sized for single-stream CPU serving of the local model |
| `enrich_model` | `ragweld-local` | LiteLLM alias for code enrichment |
| `enrich_disabled` | `False` | Disable code enrichment |
| `gen_model_cli` | `` | Optional LiteLLM alias for CLI requests |
| `gen_model_http` | `` | HTTP transport generation model override |
| `gen_model_mcp` | `` | MCP transport generation model override |
