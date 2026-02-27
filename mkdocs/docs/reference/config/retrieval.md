# Config reference: `retrieval`

<div class="grid chunk_summaries" markdown>

-   :material-tune:{ .lg .middle } **Enterprise tuning surface**

    ---

    Defaults + constraints are rendered directly from Pydantic.

-   :material-key-outline:{ .lg .middle } **Env keys when available**

    ---

    Many fields have an env-style alias (from `TriBridConfig.to_flat_dict()`).

-   :material-tooltip-text:{ .lg .middle } **Tooltip-level guidance**

    ---

    If a matching glossary entry exists, you’ll see deeper tuning notes.

</div>

[Config reference](index.md){ .md-button .md-button--primary }
[Config API & workflow](../../configuration.md){ .md-button }
[Glossary](../../glossary.md){ .md-button }

**Total parameters**: 32

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `retrieval.bm25_b` | `BM25_B` | `float` | `0.4` | ≥ 0.0, ≤ 1.0 | BM25 length normalization (0=no penalty, 1=full penalty, 0.3-0.5 recommended for code) |
| `retrieval.bm25_k1` | `BM25_K1` | `float` | `1.2` | ≥ 0.5, ≤ 3.0 | BM25 term frequency saturation parameter (higher = more weight to term frequency) |
| `retrieval.bm25_weight` | `BM25_WEIGHT` | `float` | `0.3` | ≥ 0.0, ≤ 1.0 | Weight for BM25 in hybrid search |
| `retrieval.chunk_summary_search_enabled` | `CHUNK_SUMMARY_SEARCH_ENABLED` | `int` | `1` | ≥ 0, ≤ 1 | Enable chunk_summary-based retrieval |
| `retrieval.conf_any` | `CONF_ANY` | `float` | `0.55` | ≥ 0.0, ≤ 1.0 | Minimum confidence threshold |
| `retrieval.conf_avg5` | `CONF_AVG5` | `float` | `0.55` | ≥ 0.0, ≤ 1.0 | Confidence threshold for avg top-5 |
| `retrieval.conf_top1` | `CONF_TOP1` | `float` | `0.62` | ≥ 0.0, ≤ 1.0 | Confidence threshold for top-1 |
| `retrieval.dedup_by` | — | `Literal["chunk_id", "file_path"]` | `"chunk_id"` | allowed="chunk_id", "file_path" | Dedup key for final results. |
| `retrieval.enable_mmr` | — | `bool` | `false` | — | Enable MMR diversification when embeddings are available. |
| `retrieval.eval_final_k` | `EVAL_FINAL_K` | `int` | `5` | ≥ 1, ≤ 50 | Top-k for evaluation runs |
| `retrieval.eval_multi` | `EVAL_MULTI` | `int` | `1` | ≥ 0, ≤ 1 | Enable multi-query in eval |
| `retrieval.fallback_confidence` | `FALLBACK_CONFIDENCE` | `float` | `0.55` | ≥ 0.0, ≤ 1.0 | Confidence threshold for fallback retrieval strategies |
| `retrieval.final_k` | `FINAL_K` | `int` | `10` | ≥ 1, ≤ 100 | Default top-k for search results |
| `retrieval.hydration_max_chars` | — | `int` | `2000` | ≥ 500, ≤ 10000 | Max characters for result hydration |
| `retrieval.hydration_mode` | — | `str` | `"lazy"` | pattern=^(lazy\|eager\|none\|off)$ | Result hydration mode |
| `retrieval.langgraph_final_k` | `LANGGRAPH_FINAL_K` | `int` | `20` | ≥ 1, ≤ 100 | Number of final results to return in LangGraph pipeline |
| `retrieval.langgraph_max_query_rewrites` | `LANGGRAPH_MAX_QUERY_REWRITES` | `int` | `2` | ≥ 1, ≤ 10 | Maximum number of query rewrites for LangGraph pipeline |
| `retrieval.max_chunks_per_file` | — | `int` | `3` | ≥ 1, ≤ 50 | Max chunks to return per file_path (document-aware result shaping). |
| `retrieval.max_query_rewrites` | `MAX_QUERY_REWRITES`, `MQ_REWRITES` | `int` | `2` | ≥ 1, ≤ 10 | Maximum number of query rewrites for multi-query expansion |
| `retrieval.min_score_graph` | — | `float` | `0.0` | ≥ 0.0, ≤ 10.0 | Minimum score threshold for graph leg results (0 disables). |
| `retrieval.min_score_sparse` | — | `float` | `0.0` | ≥ 0.0, ≤ 10.0 | Minimum score threshold for sparse leg results (0 disables). Note: sparse scores are engine-dependent (FTS vs BM25). |
| `retrieval.min_score_vector` | — | `float` | `0.0` | ≥ 0.0, ≤ 1.0 | Minimum score threshold for vector leg results (0 disables). |
| `retrieval.mmr_lambda` | — | `float` | `0.7` | ≥ 0.0, ≤ 1.0 | MMR lambda (1=query relevance only, 0=diversity only). |
| `retrieval.multi_query_m` | `MULTI_QUERY_M` | `int` | `4` | ≥ 1, ≤ 10 | Query variants for multi-query |
| `retrieval.neighbor_window` | — | `int` | `1` | ≥ 0, ≤ 10 | Include adjacent chunks by ordinal for coherence (requires chunk_ordinal metadata). |
| `retrieval.query_expansion_enabled` | `QUERY_EXPANSION_ENABLED` | `int` | `1` | ≥ 0, ≤ 1 | Enable synonym expansion |
| `retrieval.rrf_k_div` | `RRF_K_DIV` | `int` | `60` | ≥ 1, ≤ 200 | RRF rank smoothing constant (higher = more weight to top ranks) |
| `retrieval.topk_dense` | `TOPK_DENSE` | `int` | `75` | ≥ 10, ≤ 200 | Top-K for dense vector search |
| `retrieval.topk_sparse` | `TOPK_SPARSE` | `int` | `75` | ≥ 10, ≤ 200 | Top-K for sparse BM25 search |
| `retrieval.tribrid_synonyms_path` | `TRIBRID_SYNONYMS_PATH` | `str` | `""` | — | Custom path to semantic_synonyms.json (default: data/semantic_synonyms.json) |
| `retrieval.use_semantic_synonyms` | `USE_SEMANTIC_SYNONYMS` | `int` | `1` | ≥ 0, ≤ 1 | Enable semantic synonym expansion |
| `retrieval.vector_weight` | `VECTOR_WEIGHT` | `float` | `0.7` | ≥ 0.0, ≤ 1.0 | Weight for vector search |

### Details (glossary)

??? info "`retrieval.bm25_b` (`BM25_B`) — BM25 b (Length Normalization)"
    **Category**: `retrieval`

    BM25 length-normalization parameter. Controls how strongly sparse (keyword) scoring penalizes long chunks compared to short chunks.

    b = 0.0 means no length penalty (a long chunk can score highly simply because it contains more terms). b = 1.0 means full length normalization (long chunks are penalized relative to the average chunk length). For code corpora, moderate values typically work best because chunk lengths are already partially normalized by chunking.

    Tune b when sparse results feel “too long” or “too short”: if long boilerplate chunks dominate, increase b; if large files should remain competitive, decrease b.

    • Range: 0.0–1.0
    • Code sweet spot: 0.3–0.5 (recommended)
    • Lower b: favors longer chunks (higher recall, more noise)
    • Higher b: favors shorter chunks (higher precision, may miss context)
    • Interacts with: BM25_K1 and chunking (CHUNK_SIZE / CHUNK_OVERLAP)

    **Badges**:
    - Advanced RAG tuning
    - Affects keyword search

    **Links**:
    - [Okapi BM25](https://en.wikipedia.org/wiki/Okapi_BM25)

??? info "`retrieval.bm25_k1` (`BM25_K1`) — BM25 k1 (Term Saturation)"
    **Category**: `retrieval`

    BM25 term-frequency saturation parameter. Controls how much repeated occurrences of a query term within the same chunk increase the sparse score.

    Low k1 makes BM25 behave closer to “binary” matching (term present vs. absent). High k1 keeps rewarding repeats, which can overweight boilerplate or very repetitive identifiers.

    For code search, moderate k1 (around 1.0–1.5) usually works well: it rewards chunks that are clearly about the query term without letting repetition dominate.

    • Range: 0.5–3.0
    • Typical: 1.2 (default)
    • Lower k1: repeats matter less (more binary)
    • Higher k1: repeats matter more (can favor verbose/repetitive chunks)
    • Interacts with: BM25_B (length normalization)

    **Badges**:
    - Advanced RAG tuning
    - Affects keyword search

    **Links**:
    - [Okapi BM25](https://en.wikipedia.org/wiki/Okapi_BM25)
    - [Term Frequency](https://en.wikipedia.org/wiki/Term_frequency)

??? info "`retrieval.bm25_weight` (`BM25_WEIGHT`) — BM25 Weight (Hybrid Fusion)"
    **Category**: `retrieval`

    Weight assigned to BM25 (sparse lexical) scores during hybrid search fusion. BM25 excels at exact keyword matches - variable names, function names, error codes, technical terms. Higher weights (0.5-0.7) prioritize keyword precision, favoring exact matches over semantic similarity. Lower weights (0.2-0.4) defer to dense embeddings, better for conceptual queries. The fusion formula is: final_score = (BM25_WEIGHT × bm25_score) + (VECTOR_WEIGHT × dense_score).

    Sweet spot: 0.4-0.5 for balanced hybrid retrieval. Use 0.5-0.6 when users search with specific identifiers (e.g., "getUserById function" or "AuthenticationError exception"). Use 0.3-0.4 for natural language queries (e.g., "how does authentication work?"). The two weights should sum to approximately 1.0 for normalized scoring, though this isn't strictly enforced.

    Symptom of too high: Semantic matches are buried under keyword matches. Symptom of too low: Exact identifier matches rank poorly despite containing query terms. Production systems often A/B test 0.4 vs 0.5 to optimize for their user query patterns. Code search typically needs higher BM25 weight than document search.

    • Range: 0.2-0.7 (typical)
    • Keyword-heavy: 0.5-0.6 (function names, error codes)
    • Balanced: 0.4-0.5 (recommended for mixed queries)
    • Semantic-heavy: 0.3-0.4 (conceptual questions)
    • Should sum with VECTOR_WEIGHT to ~1.0
    • Affects: Hybrid fusion ranking, keyword vs semantic balance

    **Badges**:
    - Advanced RAG tuning
    - Pairs with VECTOR_WEIGHT

    **Links**:
    - [BM25 Algorithm](https://en.wikipedia.org/wiki/Okapi_BM25)
    - [Hybrid Search Overview](https://qdrant.tech/articles/hybrid-search/)
    - [Fusion Strategies in RAG](https://arxiv.org/abs/2402.14734)
    - [Sparse vs Dense Retrieval](https://www.pinecone.io/learn/hybrid-search-intro/)

??? info "`retrieval.chunk_summary_search_enabled` (`CHUNK_SUMMARY_SEARCH_ENABLED`) — Chunk Summary Search"
    **Category**: `retrieval`

    Enable an additional retrieval pass that searches over each chunk’s chunk_summary (LLM-generated metadata such as purpose, key symbols, and keywords) instead of only raw chunk text. This can improve recall for conceptual questions where the exact identifier isn’t in the query.

    If a corpus hasn’t generated chunk summaries yet, enabling this won’t add signal until you (re)index with chunk summaries enabled.

    • Disabled: only raw code/doc text participates in retrieval
    • Enabled: chunk summaries can produce candidate hits (often better for “what does this do?” queries)
    • Cost/latency: can add an extra retrieval step (usually small compared to LLM calls)
    • Interacts with: CHUNK_SUMMARY_BONUS and chunk summary indexing limits

    **Badges**:
    - Improves intent

    **Links**:
    - [Automatic Summarization](https://en.wikipedia.org/wiki/Automatic_summarization)

??? info "`retrieval.conf_any` (`CONF_ANY`) — Confidence Any"
    **Category**: `general`

    Fallback threshold - proceed with retrieval if ANY single result exceeds this score, even if top-1 or avg-5 thresholds aren't met. This prevents the system from giving up when there's at least one decent match. Lower values (0.30-0.40) are more permissive, returning results even with weak confidence. Higher values (0.45-0.50) maintain quality standards. Recommended: 0.35-0.45 as a safety net.

    **Badges**:
    - Safety net

    **Links**:
    - [Fallback Strategies](https://en.wikipedia.org/wiki/Fault_tolerance)
    - [Decision Boundaries](https://en.wikipedia.org/wiki/Decision_boundary)

??? info "`retrieval.conf_avg5` (`CONF_AVG5`) — Confidence Avg-5"
    **Category**: `general`

    Average confidence score of the top-5 results, used as a gate for query rewriting iterations. If avg(top-5) is below this threshold, the system may rewrite the query and try again. Lower values (0.50-0.53) reduce retries, accepting more borderline results. Higher values (0.56-0.60) force more rewrites for higher quality. Recommended: 0.52-0.58 for balanced behavior.

    Sweet spot: 0.52-0.55 for production systems. Use 0.55-0.58 when quality is paramount and you have budget for extra LLM calls (query rewriting). Use 0.50-0.52 for cost-sensitive scenarios or when initial retrieval is already high-quality. This threshold examines the top-5 results as a group - even if top-1 is strong, weak supporting results might trigger a rewrite.

    AVG5 complements TOP1: TOP1 checks the best result, AVG5 checks overall result quality. A query might pass TOP1 (strong top result) but fail AVG5 (weak supporting results), triggering refinement. Conversely, borderline TOP1 with strong AVG5 might proceed. Tune both thresholds together for optimal precision/recall trade-offs.

    • Range: 0.48-0.60 (typical)
    • Cost-sensitive: 0.50-0.52 (fewer retries)
    • Balanced: 0.52-0.55 (recommended)
    • Quality-focused: 0.55-0.58 (more retries)
    • Effect: Higher = more query rewrites, better quality, higher cost
    • Interacts with: CONF_TOP1 (top result threshold), MQ_REWRITES (rewrite budget)

    **Badges**:
    - Advanced RAG tuning
    - Controls retries

    **Links**:
    - [Iterative Refinement](https://en.wikipedia.org/wiki/Iterative_refinement)
    - [Query Reformulation](https://en.wikipedia.org/wiki/Query_reformulation)
    - [Multi-Query RAG](https://arxiv.org/abs/2305.14283)

??? info "`retrieval.conf_top1` (`CONF_TOP1`) — Confidence Top-1"
    **Category**: `general`

    Minimum confidence score (0.0-1.0) required to accept the top-1 result without further processing. If the best result scores above this threshold, it's returned immediately. Lower values (0.55-0.60) produce more answers but risk lower quality. Higher values (0.65-0.70) ensure precision but may trigger unnecessary query rewrites. Recommended: 0.60-0.65 for balanced precision/recall.

    Sweet spot: 0.60-0.65 for production systems. Use 0.65-0.70 when precision is critical and false positives are costly (e.g., production debugging, compliance queries). Use 0.55-0.60 for exploratory search where recall matters more. This threshold gates whether the system accepts the top result or attempts query rewriting for better candidates.

    Confidence is computed from hybrid fusion scores, reranking scores, and score boosting. A score of 0.65 means high confidence that the result is relevant. Below the threshold, the system may rewrite the query (if MQ_REWRITES > 1) and try again. Tune this alongside CONF_AVG5 and CONF_ANY for optimal answer rate vs quality.

    • Range: 0.55-0.75 (typical)
    • Exploratory: 0.55-0.60 (favor recall)
    • Balanced: 0.60-0.65 (recommended)
    • Precision-critical: 0.65-0.70 (favor precision)
    • Effect: Lower = more answers, higher risk; Higher = fewer answers, higher quality
    • Triggers: Query rewriting when below threshold

    **Badges**:
    - Advanced RAG tuning
    - Affects answer rate

    **Links**:
    - [Confidence Thresholds](https://en.wikipedia.org/wiki/Confidence_interval)
    - [Precision-Recall Tradeoff](https://developers.google.com/machine-learning/crash-course/classification/precision-and-recall)
    - [Decision Boundaries](https://en.wikipedia.org/wiki/Decision_boundary)

??? info "`retrieval.eval_final_k` (`EVAL_FINAL_K`) — Eval Final‑K"
    **Category**: `evaluation`

    Number of top results to consider when evaluating Hit@K metrics. If set to 10, eval checks if the expected answer appears in the top 10 results. Lower values (5) test precision, higher values (20) test recall. Should match your production FINAL_K setting for realistic evaluation. Common: 5 (strict), 10 (balanced), 20 (lenient).

    **Links**:
    - [Hit@K Metric](https://en.wikipedia.org/wiki/Evaluation_measures_(information_retrieval)#Precision_at_K)

??? info "`retrieval.eval_multi` (`EVAL_MULTI`) — Eval Multi‑Query"
    **Category**: `evaluation`

    Enable multi-query expansion during evaluation runs (1=yes, 0=no). When enabled, each golden question is rewritten multiple times (per MQ_REWRITES setting) to test recall under query variation. Turning this on makes eval results match production behavior if you use multi-query in prod, but increases eval runtime. Use 1 to measure realistic performance, 0 for faster eval iterations.

    **Badges**:
    - Affects eval time

    **Links**:
    - [Multi-Query RAG](https://arxiv.org/abs/2305.14283)

??? info "`retrieval.fallback_confidence` (`FALLBACK_CONFIDENCE`) — Fallback Confidence"
    **Category**: `retrieval`

    Confidence threshold that decides when to escalate to fallback retrieval strategies (e.g., rewrite the query, broaden candidate pools, or lean on alternative sources) instead of trusting the initial result set.

    Think of it as “how bad is too bad”: if the system’s confidence in the current retrieval is below this, it tries something else; if it’s above, it proceeds without extra work.

    Higher values trigger fallbacks more often (usually better quality, higher latency/cost). Lower values accept more first-pass results (faster, riskier). Tune alongside CONF_TOP1 and CONF_AVG5 so you don’t over-trigger rewrites.

    • Range: 0.0–1.0
    • Typical: 0.50–0.60
    • Default: 0.55
    • Higher: more retries/fallbacks (slower, higher precision)
    • Lower: fewer retries (faster, may answer with weaker evidence)
    • Interacts with: Confidence Top-1, Confidence Avg-5, Multi‑Query Rewrites

    **Badges**:
    - Advanced RAG tuning
    - Controls retries

    **Links**:
    - [Query Reformulation](https://en.wikipedia.org/wiki/Query_reformulation)
    - [Precision and Recall](https://developers.google.com/machine-learning/crash-course/classification/precision-and-recall)

??? info "`retrieval.final_k` (`FINAL_K`) — Final Top‑K"
    **Category**: `general`

    Number of top results to return after hybrid fusion, reranking, and scoring boosts. This is what you get back from search. Higher values (15-30) provide more context but may include noise. Lower values (5-10) are faster and more precise. Default: 10. Recommended: 10 for chat, 20-30 for browsing/exploration.

    **Badges**:
    - Core Setting

    **Links**:
    - [Precision vs Recall](https://en.wikipedia.org/wiki/Precision_and_recall)
    - [Top-K Selection](https://en.wikipedia.org/wiki/Tf%E2%80%93idf#Top-K_retrieval)

??? info "`retrieval.langgraph_final_k` (`LANGGRAPH_FINAL_K`) — LangGraph Final K"
    **Category**: `general`

    Compatibility control for LangGraph-style retrieval flows: target number of candidates passed forward after retrieval/fusion stages. This can differ from primary retrieval final_k when running alternate orchestration paths.

    Tune this to keep evaluation and runtime behavior aligned. If this diverges too far from main retrieval settings, debugging cross-path discrepancies becomes difficult.

    - Higher values: more recall, more downstream latency/cost
    - Lower values: tighter precision, less context diversity

    **Links**:
    - [LangGraph](https://langchain-ai.github.io/langgraph/)

??? info "`retrieval.langgraph_max_query_rewrites` (`LANGGRAPH_MAX_QUERY_REWRITES`) — LangGraph Max Query Rewrites"
    **Category**: `general`

    Number of query rewrites used inside the LangGraph answer pipeline (/answer). Separate from MAX_QUERY_REWRITES used by general multi-query retrieval. Higher values improve recall but increase latency and LLM cost. Typical: 2-4.

    **Badges**:
    - LangGraph only
    - Higher cost

    **Links**:
    - [LangGraph](https://langchain-ai.github.io/langgraph/)
    - [Multi‑Query RAG (paper)](https://arxiv.org/abs/2305.14283)

??? info "`retrieval.max_query_rewrites` (`MAX_QUERY_REWRITES`) — Multi‑Query Rewrites"
    **Category**: `general`

    Number of LLM‑generated query variations. Each variation runs hybrid retrieval; results are merged and reranked. Higher improves recall but increases latency and API cost. Typical: 2–4.

    **Badges**:
    - Better recall
    - Higher cost

    **Links**:
    - [Multi‑Query Retriever](https://python.langchain.com/docs/how_to/MultiQueryRetriever/)
    - [Multi‑Query RAG (paper)](https://arxiv.org/abs/2305.14283)

??? info "`retrieval.multi_query_m` (`MULTI_QUERY_M`) — Multi-Query M (RRF Constant)"
    **Category**: `general`

    Constant "k" parameter in Reciprocal Rank Fusion (RRF) formula used to merge results from multiple query rewrites. RRF formula: score = sum(1 / (k + rank_i)) across all query variants. Higher M values (60-100) compress rank differences, treating top-10 and top-20 results more equally. Lower M values (20-40) emphasize top-ranked results, creating steeper rank penalties.

    Sweet spot: 50-60 for balanced fusion. This is the standard RRF constant used in most production systems. Use 40-50 for more emphasis on top results (good when rewrites are high quality). Use 60-80 for smoother fusion (good when rewrites produce diverse rankings). The parameter is called "M" in code but represents the "k" constant in academic RRF papers.

    RRF fusion happens when MQ_REWRITES > 1: each query variant retrieves results, then RRF merges them by summing reciprocal ranks. Example with M=60: rank-1 result scores 1/61=0.016, rank-10 scores 1/70=0.014. Higher M reduces the gap. This parameter rarely needs tuning - default of 60 works well for most use cases.

    • Standard range: 40-80
    • Emphasize top results: 40-50
    • Balanced: 50-60 (recommended, RRF default)
    • Smooth fusion: 60-80
    • Formula: score = sum(1 / (M + rank)) for each query variant
    • Only matters when: MQ_REWRITES > 1 (multi-query enabled)

    **Badges**:
    - Advanced RAG tuning
    - RRF fusion control

    **Links**:
    - [Reciprocal Rank Fusion Paper](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
    - [RRF in Practice](https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html)
    - [Multi-Query RAG](https://arxiv.org/abs/2305.14283)
    - [Fusion Strategies](https://arxiv.org/abs/2402.14734)

??? info "`retrieval.query_expansion_enabled` (`QUERY_EXPANSION_ENABLED`) — Query Expansion Enabled"
    **Category**: `retrieval`

    Controls whether additional rewritten/expanded query variants are generated and used during retrieval. Expansion can improve recall for underspecified prompts but may add latency and noise.

    Enable when users ask vague natural-language questions and miss relevant identifiers. Disable when exact-query behavior and deterministic latency are more important than recall breadth.

    - Enabled: broader retrieval coverage
    - Disabled: stricter, faster lexical/semantic matching

??? info "`retrieval.rrf_k_div` (`RRF_K_DIV`) — Reciprocal Rank Fusion (K)"
    **Category**: `retrieval`

    RRF smoothing constant used in retrieval fusion: score += 1/(K + rank). Lower K makes top-ranked hits dominate more; higher K flattens rank differences. Default: 60. Allowed range: 1-200 (practical minimum validated as 10). Typical: 30-100.

    **Links**:
    - [RRF Paper](https://www.cs.cmu.edu/~jgc/publication/The_Influence_of_Random_Sampling_on_the_Performance_of_Ensembles.pdf)

??? info "`retrieval.topk_dense` (`TOPK_DENSE`) — Top‑K Dense"
    **Category**: `retrieval`

    Number of candidate results to retrieve from Qdrant vector (semantic) search before hybrid fusion. Higher values (100-150) improve recall for semantic matches but increase query latency and memory usage. Lower values (40-60) are faster but may miss relevant results. Must be >= FINAL_K. Recommended: 75 for balanced performance, 100-120 for high recall scenarios.

    **Badges**:
    - Affects latency
    - Semantic matches

    **Links**:
    - [Vector Similarity Search](https://qdrant.tech/documentation/concepts/search/)
    - [Semantic Search](https://en.wikipedia.org/wiki/Semantic_search)
    - [Top-K Retrieval](https://en.wikipedia.org/wiki/Nearest_neighbor_search#k-nearest_neighbors)

??? info "`retrieval.topk_sparse` (`TOPK_SPARSE`) — Top‑K Sparse"
    **Category**: `retrieval`

    Number of candidate results to retrieve from BM25 keyword (lexical) search before hybrid fusion. Higher values (100-150) improve recall for exact keyword matches (variable names, function names, error codes) but increase latency. Lower values (40-60) are faster but may miss exact matches. Must be >= FINAL_K. Recommended: 75 for balanced performance, 100-120 for keyword-heavy queries.

    **Badges**:
    - Affects latency
    - Keyword matches

    **Links**:
    - [BM25 Algorithm](https://en.wikipedia.org/wiki/Okapi_BM25)
    - [BM25S Library (GitHub)](https://github.com/xhluca/bm25s)

??? info "`retrieval.tribrid_synonyms_path` (`TRIBRID_SYNONYMS_PATH`) — Synonyms File Path"
    **Category**: `general`

    Custom path to the semantic synonyms JSON file. Defaults to data/semantic_synonyms.json if empty. Use this to point to a repository-specific or custom synonym dictionary. The file should contain a JSON object mapping terms to arrays of synonyms (e.g., {"auth": ["authentication", "oauth", "jwt"]}).

    • Default: data/semantic_synonyms.json
    • Example: /path/to/custom_synonyms.json
    • Format: {"term": ["synonym1", "synonym2", ...]}
    • Works with: USE_SEMANTIC_SYNONYMS toggle

    **Badges**:
    - Optional override

??? info "`retrieval.use_semantic_synonyms` (`USE_SEMANTIC_SYNONYMS`) — Semantic Synonyms Expansion"
    **Category**: `general`

    Enables semantic synonym expansion before retrieval so queries can match related concepts, aliases, or variant terminology beyond exact user wording.

    This improves recall for natural-language and cross-team vocabulary differences, but can introduce off-topic drift if synonym lists are too broad. Keep synonym sources curated and domain-specific.

    - Enabled: better conceptual recall
    - Disabled: stricter literal query behavior
    - Pair with: TRIBRID_SYNONYMS_PATH

??? info "`retrieval.vector_weight` (`VECTOR_WEIGHT`) — Vector Weight (Hybrid Fusion)"
    **Category**: `retrieval`

    Weight assigned to dense vector (semantic embedding) scores during hybrid search fusion. Dense embeddings capture semantic meaning and conceptual similarity, excelling at natural language queries and synonym matching. Higher weights (0.5-0.7) prioritize semantic relevance over exact keywords. Lower weights (0.2-0.4) defer to BM25 lexical matching. The fusion formula: final_score = (BM25_WEIGHT × bm25_score) + (VECTOR_WEIGHT × dense_score).

    Sweet spot: 0.5-0.6 for balanced hybrid retrieval. Use 0.6-0.7 when users ask conceptual questions ("how does X work?", "what handles Y?") where synonyms and paraphrasing matter. Use 0.4-0.5 when exact term matching is important alongside semantics. The two weights should sum to approximately 1.0 for normalized scoring.

    Symptom of too high: Exact keyword matches (function names, specific terms) rank below semantic near-matches. Symptom of too low: Conceptually relevant results are buried despite being semantically similar. Most production RAG systems balance 0.5 BM25 with 0.5 vector, then fine-tune based on user feedback and eval metrics.

    • Range: 0.3-0.7 (typical)
    • Semantic-heavy: 0.6-0.7 (conceptual queries, natural language)
    • Balanced: 0.5-0.6 (recommended for mixed queries)
    • Keyword-heavy: 0.3-0.4 (when precision matters)
    • Should sum with BM25_WEIGHT to ~1.0
    • Affects: Hybrid fusion ranking, semantic vs keyword balance

    **Badges**:
    - Advanced RAG tuning
    - Pairs with BM25_WEIGHT

    **Links**:
    - [Dense Embeddings](https://www.sbert.net/docs/pretrained_models.html)
    - [Hybrid Search Explained](https://qdrant.tech/articles/hybrid-search/)
    - [Semantic Search](https://en.wikipedia.org/wiki/Semantic_search)
    - [Embedding Models](https://weaviate.io/blog/how-to-choose-an-embedding-model)
