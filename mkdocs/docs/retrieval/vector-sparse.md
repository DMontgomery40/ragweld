# Vector + Sparse Retrieval

<div class="grid chunk_summaries" markdown>

-   :material-vector-polyline:{ .lg .middle } **Dense Semantics**

    ---

    Embeddings capture meaning beyond exact tokens.

-   :material-format-quote-close:{ .lg .middle } **Keyword Precision**

    ---

    BM25 excels at exact identifiers, error codes, and file names.

-   :material-merge:{ .lg .middle } **Hybrid Strength**

    ---

    Combining both improves recall and precision across query types.

</div>

[Get started](../index.md){ .md-button .md-button--primary }
[Configuration](../configuration.md){ .md-button }
[API](../api.md){ .md-button }

!!! tip "Tune Weights"
    Set `retrieval.vector_weight` vs `retrieval.bm25_weight` (and/or `fusion.*_weight`) based on corpus characteristics.

!!! note "Top-K Budget"
    Keep `topk_dense` and `topk_sparse` high enough that `final_k` always has good candidates.

!!! warning "Embedding Mismatch"
    Changing embedding model/dimensions requires full reindexing.

| Field | Default | Notes |
|-------|---------|-------|
| `vector_search.top_k` | 50 | Candidate set size for dense |
| `sparse_search.top_k` | 50 | Candidate set size for BM25 |
| `retrieval.final_k` | 10 | Returned results after fusion |
