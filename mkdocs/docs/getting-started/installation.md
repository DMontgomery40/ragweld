# Installation

Detailed installation instructions for TriBridRAG.

## System Requirements

- **Python**: 3.10 or higher
- **PostgreSQL**: 14+ with pgvector extension
- **Neo4j**: 5.x (optional, for graph search)
- **Memory**: 8GB+ recommended

## Database Setup

### PostgreSQL with pgvector

```bash
# Install pgvector extension
CREATE EXTENSION vector;

# Create tables (handled automatically by the indexer)
```

### Neo4j (Optional)

```bash
# Using Docker
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:5
```

## Environment Variables

Create a `.env` file:

```bash
# Database
POSTGRES_URL=postgresql://user:pass@localhost:5432/tribrid
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# API Keys
OPENAI_API_KEY=sk-...
```

## Verify Installation

```bash
# Check config loads
python -c "from server.models.tribrid_config_model import TriBridConfigRoot; print('OK')"

# Run health check
curl http://localhost:8000/api/health
```
