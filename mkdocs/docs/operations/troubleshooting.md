# Troubleshooting

Common issues and solutions.

## Search Returns 0 Results

**Symptoms:** `/api/search` returns empty matches.

**Possible Causes:**

1. Index not built
2. Wrong collection name
3. Database connection issues

**Solutions:**

```bash
# Check if chunks exist
curl http://localhost:8000/api/health/detailed

# Verify collection
psql -c "SELECT count(*) FROM chunks"
```

## Slow Search Performance

**Symptoms:** Searches take >1 second.

**Solutions:**

1. Check HNSW index exists
2. Reduce `topk_dense` and `topk_sparse`
3. Tune `ef_search` parameter

## TypeScript Types Out of Sync

**Symptoms:** Frontend type errors.

**Solution:**

```bash
# Regenerate types
python3.10 -c "from pydantic2ts import generate_typescript_defs; generate_typescript_defs('server.models.tribrid_config_model', 'web/src/types/generated.ts')"

# Validate
python scripts/validate_types.py
```

## Neo4j Connection Failed

**Symptoms:** Graph search returns errors.

**Solutions:**

1. Check Neo4j is running
2. Verify credentials in config
3. Set `graph_search.enabled: false` to disable
