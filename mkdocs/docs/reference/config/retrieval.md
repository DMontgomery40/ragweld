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

**Total parameters**: 30

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `retrieval.bm25_weight` | `BM25_WEIGHT` | `float` | `0.3` | ≥ 0.0, ≤ 1.0 | Weight for BM25 in hybrid search |
| `retrieval.chunk_summary_search_enabled` | `CHUNK_SUMMARY_SEARCH_ENABLED` | `bool` | `true` | — | Enable chunk_summary-based retrieval |
| `retrieval.conf_any` | `CONF_ANY` | `float` | `0.55` | ≥ 0.0, ≤ 1.0 | Minimum confidence threshold |
| `retrieval.conf_avg5` | `CONF_AVG5` | `float` | `0.55` | ≥ 0.0, ≤ 1.0 | Confidence threshold for avg top-5 |
| `retrieval.conf_top1` | `CONF_TOP1` | `float` | `0.62` | ≥ 0.0, ≤ 1.0 | Confidence threshold for top-1 |
| `retrieval.dedup_by` | — | `Literal["chunk_id", "file_path"]` | `"chunk_id"` | allowed="chunk_id", "file_path" | Dedup key for final results. |
| `retrieval.enable_mmr` | — | `bool` | `false` | — | Enable MMR diversification when embeddings are available. |
| `retrieval.eval_final_k` | `EVAL_FINAL_K` | `int` | `5` | ≥ 1, ≤ 50 | Top-k for evaluation runs |
| `retrieval.eval_multi` | `EVAL_MULTI` | `bool` | `true` | — | Enable multi-query in eval |
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
| `retrieval.query_expansion_enabled` | `QUERY_EXPANSION_ENABLED` | `bool` | `true` | — | Enable synonym expansion |
| `retrieval.rrf_k_div` | `RRF_K_DIV` | `int` | `60` | ≥ 1, ≤ 200 | RRF rank smoothing constant (higher = more weight to top ranks) |
| `retrieval.topk_dense` | `TOPK_DENSE` | `int` | `75` | ≥ 10, ≤ 200 | Top-K for dense vector search |
| `retrieval.topk_sparse` | `TOPK_SPARSE` | `int` | `75` | ≥ 10, ≤ 200 | Top-K for sparse BM25 search |
| `retrieval.tribrid_synonyms_path` | `TRIBRID_SYNONYMS_PATH` | `str` | `""` | — | Custom path to semantic_synonyms.json (default: data/semantic_synonyms.json) |
| `retrieval.use_semantic_synonyms` | `USE_SEMANTIC_SYNONYMS` | `bool` | `true` | — | Enable semantic synonym expansion |
| `retrieval.vector_weight` | `VECTOR_WEIGHT` | `float` | `0.7` | ≥ 0.0, ≤ 1.0 | Weight for vector search |

### Details (glossary)

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

    Enables a separate retrieval path over generated chunk summaries, so the system can match intent-level language even when the query does not contain exact identifiers. This usually improves recall for architectural or behavioral questions, but only if summaries were generated during indexing and kept in sync with source updates. Turning it on adds another retrieval pass, so latency and token/compute cost can rise slightly depending on your backend. Best practice is to enable it with careful score balancing so summary matches expand candidate recall without replacing strong exact matches.

    **Badges**:
    - Recall feature

    **Links**:
    - [cAST: Structural chunking for code RAG (arXiv 2025)](https://arxiv.org/abs/2506.15655)
    - [LangChain MultiVector Retriever](https://python.langchain.com/docs/how_to/multi_vector/)
    - [Qdrant hybrid query concepts](https://qdrant.tech/documentation/concepts/hybrid-queries/)
    - [LangChain retriever concepts](https://python.langchain.com/docs/concepts/retrievers/)

??? info "`retrieval.conf_any` (`CONF_ANY`) — Confidence Any"
    **Category**: `general`

    Safety-net confidence gate: proceed when at least one candidate clears this threshold, even if aggregate gates fail. It is designed to reduce false abstentions when retrieval returns one strong hit plus several weak ones, which is common in sparse or highly specific technical queries. Setting it too low increases hallucination risk by allowing weak singleton matches; setting it too high cancels its rescue value and causes unnecessary rewrites or no-answer outcomes. Tune it using failure analysis that separates true misses from ranking noise.

    **Badges**:
    - Safety gate

    **Links**:
    - [QuCo-RAG uncertainty-aware retrieval (arXiv 2025)](https://arxiv.org/abs/2512.19134)
    - [Elasticsearch min_score parameter](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-search.html#search-api-min-score)
    - [LangChain multi-query retrieval](https://python.langchain.com/docs/how_to/multi_query/)
    - [Scikit-learn threshold tuning](https://scikit-learn.org/stable/modules/classification_threshold.html)

??? info "`retrieval.conf_avg5` (`CONF_AVG5`) — Confidence Avg-5"
    **Category**: `general`

    Average confidence over the top five candidates, used as a stability gate before accepting retrieval or triggering rewrite loops. Compared with top-1 thresholds, this metric is less sensitive to one lucky match and better reflects whether the candidate set is broadly usable for grounded generation. Raising it improves answer reliability but increases rewrite frequency and cost; lowering it reduces retries but can pass low-coherence sets into generation. Use it as your main control for balancing relevance quality against latency and token spend.

    **Badges**:
    - Retry controller

    **Links**:
    - [SAGE adaptive query rewriting (arXiv 2025)](https://arxiv.org/abs/2506.19783)
    - [LangChain multi-query retrieval](https://python.langchain.com/docs/how_to/multi_query/)
    - [Elasticsearch min_score parameter](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-search.html#search-api-min-score)
    - [Weaviate hybrid retrieval](https://docs.weaviate.io/weaviate/search/hybrid)

??? info "`retrieval.conf_top1` (`CONF_TOP1`) — Confidence Top-1"
    **Category**: `general`

    Primary acceptance gate for the best-ranked candidate. If the top result exceeds this threshold, the system can short-circuit additional rewrite or expansion steps, reducing latency and cost. Lower values increase answer rate but make the system more likely to trust brittle single hits; higher values enforce stricter precision and can over-trigger retries. The best operating point depends on your tolerance for false positives versus abstentions, so tune with labeled evals rather than intuition.

    **Badges**:
    - Precision gate

    **Links**:
    - [LLM confidence calibration via perturbation stability (arXiv 2025)](https://arxiv.org/abs/2505.21772)
    - [Elasticsearch min_score parameter](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-search.html#search-api-min-score)
    - [LangChain retriever concepts](https://python.langchain.com/docs/concepts/retrievers/)
    - [Scikit-learn threshold tuning](https://scikit-learn.org/stable/modules/classification_threshold.html)

??? info "`retrieval.eval_final_k` (`EVAL_FINAL_K`) — Eval Final‑K"
    **Category**: `evaluation`

    Defines how many top retrieved items count toward success during evaluation metrics like Hit@K. Lower values enforce strict precision and expose ranking weaknesses, while higher values emphasize recall and can hide poor ordering if the answer appears late. Keep this aligned with your production retrieval depth so offline metrics predict real behavior. When tuning, inspect both aggregate Hit@K and position-sensitive metrics so you do not optimize for lenient success criteria alone.

    **Badges**:
    - Metric sensitivity

    **Links**:
    - [What to Retrieve for RAG Code Gen (arXiv)](https://arxiv.org/abs/2503.20589)
    - [ir-measures Metrics](https://ir-measur.es/en/latest/measures.html)
    - [pytrec_eval](https://github.com/cvangysel/pytrec_eval)
    - [TREC](https://trec.nist.gov/)

??? info "`retrieval.eval_multi` (`EVAL_MULTI`) — Eval Multi‑Query"
    **Category**: `evaluation`

    Controls whether evaluation uses multi-query expansion, where one prompt is rewritten into several retrieval queries to improve recall under wording variation. Enable this when production also uses multi-query, otherwise eval results can be overly optimistic or pessimistic compared with real traffic. The gain usually comes from broader evidence discovery, but cost and latency scale with rewrite count and dedup work. Measure marginal benefit per extra rewrite and stop when added queries no longer improve quality.

    **Badges**:
    - Recall expansion

    **Links**:
    - [MA-RAG Multi-Agent Retrieval (arXiv)](https://arxiv.org/abs/2505.20096)
    - [LangChain MultiQueryRetriever](https://python.langchain.com/docs/how_to/MultiQueryRetriever/)
    - [LangChain Retrieval Concepts](https://python.langchain.com/docs/concepts/retrieval/)
    - [LlamaIndex Retriever Guide](https://docs.llamaindex.ai/en/stable/module_guides/querying/retriever/)

??? info "`retrieval.fallback_confidence` (`FALLBACK_CONFIDENCE`) — Fallback Confidence"
    **Category**: `retrieval`

    Sets the confidence cutoff that decides when first-pass retrieval is accepted versus when fallback strategies are triggered. Typical fallbacks include query rewrites, broader candidate pools, alternate retrievers, or graph traversal expansion. Higher thresholds increase recovery attempts and usually quality, but also increase cost and latency; lower thresholds preserve speed but tolerate weaker evidence. Calibrate this value on held-out failures and monitor how often fallbacks improve answers versus creating unnecessary retries.

    **Badges**:
    - Fallback policy

    **Links**:
    - [Agentic RAG Survey (arXiv)](https://arxiv.org/abs/2507.09477)
    - [TruLens Evaluation](https://www.trulens.org/component_guides/evaluation/)
    - [Ragas Metrics](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/)
    - [LangChain Retrieval Concepts](https://python.langchain.com/docs/concepts/retrieval/)

??? info "`retrieval.final_k` (`FINAL_K`) — Final Top‑K"
    **Category**: `general`

    Sets how many results survive final fusion and reranking before response generation or UI display. Larger values increase recall and diversity but can dilute evidence quality and consume more context budget; smaller values improve focus and latency but risk dropping key context. Tune this together with reranker quality and chunk size so returned sets remain both relevant and compact. In practice, this parameter strongly influences answer stability because it controls the evidence frontier given to the model.

    **Badges**:
    - Returned context depth

    **Links**:
    - [What to Retrieve for RAG Code Gen (arXiv)](https://arxiv.org/abs/2503.20589)
    - [ir-measures Metrics](https://ir-measur.es/en/latest/measures.html)
    - [Elasticsearch Search size](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-search.html#search-api-param-size)
    - [Azure Search Result Count](https://learn.microsoft.com/en-us/azure/search/search-pagination-page-layout#number-of-results-in-the-response)

??? info "`retrieval.langgraph_final_k` (`LANGGRAPH_FINAL_K`) — LangGraph Final K"
    **Category**: `general`

    Sets how many retrieved candidates are retained after fusion or reranking before final answer synthesis in a LangGraph-style workflow. This parameter directly balances recall against context noise and token cost: larger values preserve more potentially useful evidence, while smaller values reduce latency and hallucination surface from marginal passages. Effective tuning depends on corpus redundancy and reranker quality, so evaluate with answer-level metrics rather than retrieval-only metrics. Keep this aligned with model context limits and downstream prompt design to avoid passing excess low-value text. In multi-stage graphs, final_k should be considered with earlier retrieval breadth settings.

    **Badges**:
    - Candidate depth

    **Links**:
    - [ImpRAG: Importance-Aware Retrieval-Augmented Generation](https://arxiv.org/abs/2506.02279)
    - [LangGraph Documentation](https://docs.langchain.com/langgraph)
    - [LangGraph Low-Level Concepts](https://langchain-ai.github.io/langgraph/concepts/low_level/)
    - [Cohere Rerank Overview](https://docs.cohere.com/docs/rerank-overview)

??? info "`retrieval.langgraph_max_query_rewrites` (`LANGGRAPH_MAX_QUERY_REWRITES`) — LangGraph Max Query Rewrites"
    **Category**: `general`

    Limits how many alternate query rewrites are generated inside the LangGraph answer path. Additional rewrites can significantly improve recall on ambiguous or underspecified user questions by exploring lexical variants and sub-intents, but each rewrite adds model calls, retrieval fan-out, and dedup work. Set this based on latency budget and observed marginal gain per rewrite, not on a fixed preference for larger numbers. Practical deployments combine a moderate cap with early-stop heuristics when rewrites become near-duplicates. This keeps retrieval expansion useful instead of turning into cost-heavy redundancy.

    **Badges**:
    - Latency vs recall

    **Links**:
    - [RL-QR: Reinforcement Learning for Query Rewriting in RAG](https://arxiv.org/abs/2507.23242)
    - [LangGraph Documentation](https://docs.langchain.com/langgraph)
    - [LangGraph Low-Level Concepts](https://langchain-ai.github.io/langgraph/concepts/low_level/)
    - [Cohere Rerank Overview](https://docs.cohere.com/docs/rerank-overview)

??? info "`retrieval.max_query_rewrites` (`MAX_QUERY_REWRITES`) — Multi‑Query Rewrites"
    **Category**: `general`

    Sets how many alternative query phrasings are generated before retrieval. Each rewrite typically executes the full retrieval stack (sparse/vector/graph + fusion), so increasing this value can recover documents missed by the original wording but grows latency and token cost almost linearly. In practice, treat it as a recall budget: start low, measure unique-relevant-document gain per extra rewrite, and stop when marginal gain flattens. Keep the original query in the candidate set to prevent rewrite drift, and pair this with reranking so noisy rewrites do not dominate final context selection.

    **Badges**:
    - Better recall
    - Higher cost

    **Links**:
    - [Annotation-Free RL Query Rewriting via Verifiable Search Reward (arXiv 2025)](https://arxiv.org/abs/2507.23242)
    - [LangChain MultiQuery Retriever](https://python.langchain.com/docs/how_to/MultiQueryRetriever/)
    - [Haystack Query Expansion Cookbook](https://haystack.deepset.ai/cookbook/query-expansion)
    - [Elasticsearch Reciprocal Rank Fusion](https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html)

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

    Enables generation of additional query variants (rewrites, paraphrases, or decomposition prompts) before retrieval. This can significantly improve recall on underspecified or ambiguous user questions by increasing lexical and semantic coverage, especially in heterogeneous code-and-doc corpora. The tradeoff is extra latency, more candidate noise, and higher token or API cost if expansions are not constrained. Production tuning usually combines expansion with caps on variant count, deduplication, and reranker gating so recall gains do not overwhelm precision.

    **Links**:
    - [Query Suggestion for Retrieval-Augmented Generation (arXiv 2026)](https://arxiv.org/abs/2601.08105)
    - [SAGE: Learning Query Rewriting for LLM-based Search (arXiv 2025)](https://arxiv.org/abs/2506.19783)
    - [LangChain MultiQueryRetriever](https://python.langchain.com/docs/how_to/MultiQueryRetriever/)
    - [Elasticsearch Synonyms and Query Expansion](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-with-synonyms.html)

??? info "`retrieval.rrf_k_div` (`RRF_K_DIV`) — Reciprocal Rank Fusion (K)"
    **Category**: `retrieval`

    `RRF_K_DIV` is the Reciprocal Rank Fusion smoothing constant in the fusion formula `score += 1 / (k + rank)`, and it governs how aggressively top-ranked items dominate the merged ranking. Lower values make the fusion more top-heavy and sensitive to rank-1/2 positions from individual retrievers, while higher values flatten contributions so deeper-ranked hits still influence final order. In implementation, this is a calibration parameter for hybrid retrieval behavior: tune it with representative queries and compare recall, top-k precision, and downstream answer grounding, because an overly small k can overfit to one retriever and an overly large k can dilute strong top signals.

    **Links**:
    - [Exp4Fuse: Online Learning for Robust Search Result Fusion with Modified RRF (arXiv)](https://arxiv.org/abs/2506.04760)
    - [Elasticsearch Reciprocal Rank Fusion (RRF)](https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html)
    - [Azure AI Search Hybrid Search Ranking (RRF)](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking)
    - [Weaviate Hybrid Search Concepts](https://docs.weaviate.io/weaviate/concepts/search/hybrid-search)

??? info "`retrieval.topk_dense` (`TOPK_DENSE`) — Top‑K Dense"
    **Category**: `retrieval`

    TOPK_DENSE sets how many semantic candidates are pulled from the dense index before fusion. In practice, this controls the recall ceiling for meaning-based matches: if it is too low, relevant chunks can be dropped before reranking ever sees them; if it is too high, latency and downstream rerank cost grow quickly. Tune it against your corpus distribution and query mix by tracking recall@k, answer grounding rate, and p95 latency together, not in isolation. A common pattern is to increase TOPK_DENSE when user questions are abstract or paraphrased, then counterbalance compute by tightening reranker depth or pruning thresholds later in the pipeline.

    **Badges**:
    - Affects latency
    - Semantic matches

    **Links**:
    - [Topo-RAG: Retrieval-Augmented Generation with Topology-Aware Retrieval (arXiv 2026)](https://arxiv.org/abs/2601.10215)
    - [Qdrant Hybrid Queries](https://qdrant.tech/documentation/concepts/hybrid-queries/)
    - [Qdrant Query Points API (limit and retrieval controls)](https://api.qdrant.tech/master/api-reference/search/query-points)
    - [Elasticsearch Reciprocal Rank Fusion (RRF)](https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html)

??? info "`retrieval.topk_sparse` (`TOPK_SPARSE`) — Top‑K Sparse"
    **Category**: `retrieval`

    TOPK_SPARSE sets how many lexical candidates are retrieved from sparse scoring (BM25-style) before hybrid fusion. This value is critical for exact-match behavior such as identifiers, SKU-like tokens, config names, and error strings that dense embeddings can blur. If TOPK_SPARSE is too low, precision may look good while recall silently collapses on keyword-heavy workloads; if too high, you can over-admit noisy boilerplate and increase rerank pressure. Evaluate it jointly with tokenizer configuration and fusion weights so sparse evidence remains a strong but not dominant signal.

    **Badges**:
    - Affects latency
    - Keyword matches

    **Links**:
    - [Hybrid Retrieval for Multilingual RAG Systems (arXiv 2025)](https://arxiv.org/abs/2512.12694)
    - [Elasticsearch BM25 Similarity](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-modules-similarity.html)
    - [OpenSearch Hybrid Query DSL](https://docs.opensearch.org/latest/query-dsl/compound/hybrid/)
    - [Elasticsearch Reciprocal Rank Fusion (RRF)](https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html)

??? info "`retrieval.tribrid_synonyms_path` (`TRIBRID_SYNONYMS_PATH`) — Synonyms File Path"
    **Category**: `general`

    Path to the synonyms dictionary used for controlled query expansion and lexical normalization. This file can materially change retrieval behavior, especially for domain acronyms, aliases, and product-specific terminology that embeddings may underrepresent. Keep the synonym set versioned and scoped: broad global replacements can hurt precision by over-expanding ambiguous terms. Treat updates as relevance experiments, not static configuration, and validate with representative query buckets before rollout.

    **Badges**:
    - Optional override

    **Links**:
    - [Generative Query Expansion with Multilingual LLMs (arXiv 2025)](https://arxiv.org/abs/2511.19325)
    - [Elasticsearch Synonym Token Filter](https://www.elastic.co/docs/reference/text-analysis/analysis-synonym-tokenfilter)
    - [OpenSearch Synonym Token Filter](https://docs.opensearch.org/latest/analyzers/token-filters/synonym/)
    - [PostgreSQL Text Search Dictionaries and Synonym Support](https://www.postgresql.org/docs/current/textsearch-features.html)

??? info "`retrieval.use_semantic_synonyms` (`USE_SEMANTIC_SYNONYMS`) — Semantic Synonyms Expansion"
    **Category**: `general`

    Enables semantic synonym expansion before retrieval so user queries can match equivalent terminology, abbreviations, and team-specific phrasing beyond exact token overlap. This typically improves recall on natural-language prompts and cross-team vocabulary mismatches, especially when users ask with informal wording while documents use canonical terms. The tradeoff is expansion noise: broad or poorly curated synonym sets can pull in marginally related chunks and lower precision. Enable this with a controlled synonym dictionary, monitor zero-hit reduction and false-positive rates, and pair with reranking so expanded candidates are rescored instead of accepted blindly.

    **Links**:
    - [TCDE: Textual Conceptual Drift Estimation for Query Expansion (arXiv 2025)](https://arxiv.org/abs/2512.17164)
    - [Elasticsearch Search with Synonyms](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-with-synonyms.html)
    - [OpenSearch Synonyms](https://docs.opensearch.org/latest/search-plugins/searching-data/synonyms/)
    - [Lucene SynonymGraphFilter](https://lucene.apache.org/core/9_11_1/analysis/common/org/apache/lucene/analysis/synonym/SynonymGraphFilter.html)

??? info "`retrieval.vector_weight` (`VECTOR_WEIGHT`) — Vector Weight (Hybrid Fusion)"
    **Category**: `retrieval`

    Relative influence of dense semantic scores during hybrid fusion. Raising vector weight helps when user wording differs from document wording (paraphrases, alias-heavy language, conceptual queries), while lowering it helps when exact identifiers and lexical precision matter more (error codes, symbol names, strict API strings). This is not an isolated knob: optimal weight depends on BM25 configuration, candidate pool sizes, and reranker behavior. Tune weight on a fixed benchmark set and inspect failure cases; if dense-heavy tuning introduces topical but non-specific hits, reduce vector weight or increase lexical/reranker influence.

    **Badges**:
    - Advanced RAG tuning
    - Pairs with BM25_WEIGHT

    **Links**:
    - [BAR-RAG: Adaptive Hybrid Retrieval Weighting (arXiv 2026)](https://arxiv.org/abs/2602.03689)
    - [Weaviate Hybrid Search (alpha weighting)](https://weaviate.io/developers/weaviate/search/hybrid)
    - [OpenSearch Hybrid Search](https://docs.opensearch.org/latest/search-plugins/hybrid-search/)
    - [Elasticsearch Reciprocal Rank Fusion (RRF)](https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html)
