# Tri-Brid Search Architecture

TriBridRAG combines three search modalities for comprehensive code retrieval.

## The Three Legs

### 1. Vector Search (pgvector)

Dense vector embeddings capture semantic meaning:

```python
# Embedding configuration
embedding:
  provider: openai
  model: text-embedding-3-large
  dimensions: 3072
```

### 2. Sparse Search (PostgreSQL FTS)

BM25-based keyword matching for exact terms:

```python
# Sparse search configuration
sparse_search:
  enabled: true
  bm25_k1: 1.5
  bm25_b: 0.75
```

### 3. Graph Search (Neo4j)

Entity relationships and code structure:

```python
# Graph search configuration
graph_storage:
  neo4j_uri: bolt://localhost:7687
  max_hops: 2
  include_communities: true
```

## Fusion Methods

### RRF (Reciprocal Rank Fusion)

Combines rankings without score normalization:

```
score = sum(1 / (k + rank_i)) for each system i
```

### Weighted Fusion

Score-based combination with configurable weights:

```python
fusion:
  method: rrf  # or "weighted"
  vector_weight: 0.4
  sparse_weight: 0.3
  graph_weight: 0.3
  rrf_k: 60
```

!!! note "Weights Auto-Normalize"
    The fusion weights automatically normalize to sum to 1.0.
