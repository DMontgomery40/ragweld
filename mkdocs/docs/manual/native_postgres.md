# Native Postgres (macOS) + pgvector

ragweld defaults to running Postgres in Docker (via `docker-compose.yml`). On Apple Silicon, you may prefer a **host-installed Postgres** to reduce container overhead and improve indexing/search latency.

This repo supports that workflow via:

```bash
./start.sh --native-postgres
```

!!! important "Compatibility"
    `--native-postgres` works with the local backend and with the Docker backend/observability stack. When Docker is involved, containers connect to your host Postgres via `host.docker.internal`.

## 1) Stop Docker Postgres (if it’s running)

If you previously started the stack without `--native-postgres`, Docker may still be holding port 5432:

```bash
docker stop tribrid-postgres || true
```

## 2) Install Postgres + pgvector

One working option on macOS is Homebrew:

```bash
brew install postgresql@16 pgvector
brew services start postgresql@16
```

Verify you can connect:

```bash
psql -d postgres -c "select version();"
```

## 3) Create the database (if needed)

By default, `.env.example` uses:

- `POSTGRES_DB=tribrid_rag`
- `POSTGRES_USER=postgres`
- `POSTGRES_PASSWORD=postgres`

Create the DB if it doesn’t exist:

```bash
psql -d postgres -c "create database tribrid_rag;"
```

## 4) Ensure pgvector is available

ragweld will run `CREATE EXTENSION IF NOT EXISTS vector;` at startup, but Postgres must have pgvector installed.

You can verify manually:

```bash
psql -d tribrid_rag -c "create extension if not exists vector;"
psql -d tribrid_rag -c "select extname from pg_extension where extname = 'vector';"
```

## 5) Configure `.env`

Edit `.env` so the backend connects to your native Postgres:

```bash
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=tribrid_rag
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
```

## 6) Start ragweld using native Postgres

```bash
./start.sh --native-postgres
```

Then confirm readiness:

```bash
curl -sS "http://127.0.0.1:8012/api/ready" | jq .
```

