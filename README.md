# TriBridRAG

A tri-brid RAG (Retrieval-Augmented Generation) engine combining vector search, sparse search (BM25), and knowledge graph traversal for superior code understanding.

## Architecture

TriBridRAG uses three complementary retrieval methods:

1. **Vector Search** (pgvector) - Semantic similarity using embeddings
2. **Sparse Search** (PostgreSQL FTS) - Keyword matching with BM25-style ranking
3. **Graph Search** (Neo4j) - Relationship traversal through code entities

Results are fused using Reciprocal Rank Fusion (RRF) or weighted combination, then optionally reranked using a cross-encoder model.

## Corpus-first (not “repo-first”)

TriBridRAG indexes **corpora**: any folder you want to search/GraphRAG over (a git repository, a docs folder, a monorepo subtree, etc.).

- A **corpus** is the unit of isolation for **storage (Postgres)**, **graph (Neo4j)**, and **configuration**.
- The API still uses the field name `repo_id` for backward compatibility; treat it as the **corpus identifier** (stable slug).

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- uv (Python package manager)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/your-org/tribrid-rag.git
cd tribrid-rag
```

2. Copy environment file:
```bash
cp .env.example .env
# Edit .env with your API keys
```

3. Start infrastructure:
```bash
docker compose up -d postgres neo4j grafana
```

4. Install Python dependencies:
```bash
uv sync
```

5. Install frontend dependencies:
```bash
cd web && npm install && cd ..
```

6. Start the backend:
```bash
uv run uvicorn server.main:app --reload --port 8012
```

7. Start the frontend (in another terminal):
```bash
cd web && npm run dev
```

8. Open http://localhost:5173 in your browser

### Create a corpus + index it

You can do this from the UI (Corpus switcher modal) or via the API:

```bash
# 1) Create a corpus (server must be able to see this path)
curl -sS -X POST "http://localhost:8012/api/repos" \
  -H "Content-Type: application/json" \
  -d '{"name":"TriBridRAG","path":"'"$PWD"'","description":"Local checkout"}'

# 2) Start indexing (uses the stored corpus path)
curl -sS -X POST "http://localhost:8012/api/index/start" \
  -H "Content-Type: application/json" \
  -d '{"repo_id":"tribridrag"}'

# 3) Follow status
curl -sS "http://localhost:8012/api/index/tribridrag/status"
```

## Configuration

The main configuration file is `tribrid_config.json`. You can also configure via the web UI under the RAG tab.

### Embedding Providers

- **OpenAI**: `text-embedding-3-small`, `text-embedding-3-large`
- **Voyage**: `voyage-code-2`, `voyage-large-2`
- **Local**: Any sentence-transformers model

### Reranker Modes

- **none**: No reranking (fastest)
- **local**: Pre-trained cross-encoder (ms-marco-MiniLM)
- **trained**: Your fine-tuned model
- **api**: Cohere, Voyage, or Jina reranking API

## Project Structure

```
tribrid-rag/
├── server/          # Python FastAPI backend
│   ├── api/         # REST endpoints
│   ├── db/          # Database clients (Postgres, Neo4j)
│   ├── indexing/    # Chunking, embedding, graph building
│   ├── models/      # Pydantic schemas
│   ├── retrieval/   # Search and fusion logic
│   └── services/    # Business logic
├── web/             # React TypeScript frontend
│   ├── src/
│   │   ├── api/        # API client
│   │   ├── components/ # UI components
│   │   ├── hooks/      # React hooks
│   │   └── stores/     # Zustand state
├── infra/           # Docker and observability configs
├── scripts/         # Development scripts
├── tests/           # Python tests
└── spec/            # YAML specifications
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/repos` | GET/POST | List/create corpora |
| `/api/index` | POST | Start indexing (explicit `repo_path`) |
| `/api/index/start` | POST | Start indexing for an existing corpus (path resolved from `/api/repos`) |
| `/api/index/{repo_id}/status` | GET | Indexing status for a corpus |
| `/api/index/{repo_id}/stats` | GET | Index stats for a corpus |
| `/api/search` | POST | Tri-brid search with fusion |
| `/api/answer` | POST | RAG-powered answer generation |
| `/api/graph/{repo_id}/entities` | GET | List knowledge graph entities for a corpus |
| `/api/config` | GET/PUT | Configuration management (supports `?repo_id=...` for per-corpus config) |
| `/api/eval/run` | POST | Run evaluation suite |

## Development

### Run Tests
```bash
uv run pytest
```

### Type Checking
```bash
uv run mypy server
```

### Linting
```bash
uv run ruff check server
```

### Generate TypeScript Types
```bash
uv run python scripts/generate_types.py
```

## Observability

- **Metrics**: Prometheus at http://localhost:9090
- **Dashboards**: Grafana at http://localhost:3000 (admin/admin)
- **API Docs**: FastAPI at http://localhost:8012/docs

## License

MIT
