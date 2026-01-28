# Model Configuration

TriBridRAG supports multiple LLM providers for embedding and generation.

## Models Endpoint

All available models are served from `/api/models`:

```bash
curl http://localhost:8000/api/models | jq length
# Returns: 95+ models
```

## Embedding Models

```json
{
  "embedding": {
    "provider": "openai",
    "model": "text-embedding-3-large",
    "dimensions": 3072
  }
}
```

### Available Providers

| Provider | Models |
|----------|--------|
| OpenAI | text-embedding-3-small, text-embedding-3-large |
| Voyage | voyage-code-3, voyage-3-lite |
| Cohere | embed-v4, embed-multilingual-v3 |
| Local | sentence-transformers/* |

## Generation Models

```json
{
  "generation": {
    "gen_model": "gpt-5",
    "gen_temperature": 0.0,
    "gen_max_tokens": 2048
  }
}
```

## Reranker Models

```json
{
  "reranking": {
    "reranker_mode": "local",
    "reranker_local_model": "cross-encoder/ms-marco-MiniLM-L-12-v2"
  }
}
```

!!! tip "Use the Hook"
    In the frontend, always use `useModels('GEN')` or `useEmbeddingModels()` hooks to get model lists. Never hardcode.
