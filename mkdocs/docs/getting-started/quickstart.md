# Quick Start

Get TriBridRAG running in minutes.

## Prerequisites

- Python 3.10+
- PostgreSQL with pgvector extension
- Neo4j (optional, for graph search)

## Installation

```bash
# Clone the repository
git clone https://github.com/DMontgomery40/tribrid-rag.git
cd tribrid-rag

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .
```

## Configuration

Copy the example configuration:

```bash
cp tribrid_config.example.json tribrid_config.json
```

Edit `tribrid_config.json` to configure:

- Database connections (PostgreSQL, Neo4j)
- Embedding model (OpenAI, local)
- Fusion weights

## Start the Server

```bash
python -m server.main
```

The API will be available at `http://localhost:8000`.

## Next Steps

- [Installation Guide](installation.md) - Detailed setup
- [Configuration](../configuration/settings.md) - All configuration options
