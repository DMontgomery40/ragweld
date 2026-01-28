# Settings Reference

Complete configuration reference for TriBridRAG.

## Configuration File

All settings are in `tribrid_config.json` and validated by the Pydantic model.

## Key Sections

### Retrieval

```json
{
  "retrieval": {
    "rrf_k_div": 60,
    "final_k": 10,
    "topk_dense": 75,
    "topk_sparse": 75
  }
}
```

### Fusion

```json
{
  "fusion": {
    "method": "rrf",
    "vector_weight": 0.4,
    "sparse_weight": 0.3,
    "graph_weight": 0.3,
    "rrf_k": 60
  }
}
```

### Chunking

```json
{
  "chunking": {
    "strategy": "ast",
    "chunk_size": 1000,
    "chunk_overlap": 200
  }
}
```

## Pydantic Validation

All settings are validated at load time:

```python
from server.models.tribrid_config_model import TriBridConfigRoot
import json

config = TriBridConfigRoot(**json.load(open('tribrid_config.json')))
```

## Environment Variables

Settings can also be loaded from environment variables using the flat dict format:

```bash
export FUSION_VECTOR_WEIGHT=0.5
export FUSION_SPARSE_WEIGHT=0.25
export FUSION_GRAPH_WEIGHT=0.25
```
