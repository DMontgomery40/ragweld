# Vector Search (pgvector)

pgvector provides fast approximate nearest neighbor search in PostgreSQL.

## Overview

TriBridRAG uses pgvector for dense vector storage and retrieval, enabling semantic similarity search.

## Configuration

```json
{
  "embedding": {
    "provider": "openai",
    "model": "text-embedding-3-large",
    "dimensions": 3072,
    "batch_size": 64
  },
  "indexing": {
    "postgres_url": "postgresql://localhost:5432/tribrid"
  }
}
```

## Index Types

### HNSW (Recommended)

Fast approximate search with good recall:

```sql
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
```

### IVFFlat

Memory-efficient for large datasets:

```sql
CREATE INDEX ON chunks USING ivfflat (embedding vector_cosine_ops);
```

## Best Practices

- Use HNSW for most workloads
- Tune `ef_construction` and `m` parameters
- Monitor index build times for large datasets
