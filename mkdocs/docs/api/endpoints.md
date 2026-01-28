# API Endpoints

TriBridRAG exposes a REST API for search and configuration.

## Health Check

```
GET /api/health
```

Returns server status.

## Models

```
GET /api/models
```

Returns all available models.

```
GET /api/models/by-type/{type}
```

Filter by type: `EMB`, `GEN`, `RERANK`

## Search

```
POST /api/search
```

**Request:**
```json
{
  "query": "authentication flow",
  "repo_id": "tribrid",
  "top_k": 10
}
```

**Response:**
```json
{
  "matches": [
    {
      "content": "...",
      "file_path": "server/auth.py",
      "score": 0.85
    }
  ],
  "latency_ms": 120
}
```

## Configuration

```
GET /api/config
```

Returns current configuration.

```
PUT /api/config
```

Update configuration (validated against Pydantic model).
