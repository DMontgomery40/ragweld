# Quickstart

<div class="grid chunk_summaries" markdown>

-   :material-play-circle:{ .lg .middle } **Start the stack**

    ---

    Bring up Postgres + Neo4j + API + UI with one command.

-   :material-heart-pulse:{ .lg .middle } **Verify readiness**

    ---

    Confirm `/api/ready` is green before indexing or querying.

-   :material-database-arrow-up:{ .lg .middle } **Index your first corpus**

    ---

    Index a folder on disk into chunks/embeddings (and optional graph context).

-   :material-magnify:{ .lg .middle } **Search**

    ---

    Run tri-brid retrieval (`vector + sparse + graph`) and inspect results before moving into eval/tracing workflows.

</div>

[User manual](index.md){ .md-button .md-button--primary }
[UI tour](ui.md){ .md-button }
[API reference](../api.md){ .md-button }

!!! tip "Default dev URLs"
    - **UI**: `http://127.0.0.1:5173/web`
    - **API**: `http://127.0.0.1:8012/api`

!!! note "Ports are configurable"
    `./start.sh` honors `BACKEND_PORT` and `FRONTEND_PORT`. If you change ports, update your curl examples accordingly.

    Environment variables you export in your shell **win over `.env`**: `start.sh` snapshots every exported variable before sourcing `.env` and restores that exact snapshot afterwards, so `.env` only fills in the keys you did not already set. A caller-provided `BACKEND_PORT=59999` therefore survives even a `.env` that hardcodes `BACKEND_PORT` for the deployed default.

!!! tip "If a port override seems ignored"
    - Confirm the variable is actually **exported** (`BACKEND_PORT=59999 ./start.sh` or `export BACKEND_PORT=59999` first) — unexported shell variables are not visible to the script.
    - Check `/api/health` on the port you expected: the backend logs the `--port` value it was launched with.
    - If you're not sure what the effective value was, run `./start.sh --check` and read the rendered port in its output.


## 1) Start everything

From the repo root:

```bash
./start.sh
```

Optional: add observability (Prometheus/Grafana/Loki) if you’re going to tune or benchmark:

```bash
./start.sh --with-observability
```

Advanced: on Apple Silicon, you can run Postgres natively (skip Docker postgres) for lower overhead:

```bash
./start.sh --native-postgres
```

See [Native Postgres (macOS)](native_postgres.md) for setup steps.

## 2) Verify the API is ready

```bash
curl -sS "http://127.0.0.1:8012/api/ready" | jq .
curl -sS "http://127.0.0.1:8012/api/health" | jq .
```

If readiness is failing, jump to [Troubleshooting](troubleshooting.md).

## 3) Confirm provider keys (optional but recommended)

ragweld can run without every provider key, but many features (cloud embeddings, generation, cloud reranking) require the gateway to have an upstream configured.

```bash
curl -sS "http://127.0.0.1:58012/api/secrets/check?keys=LITELLM_API_KEY" | jq .
```

This checks the **app's gateway client key** (`LITELLM_API_KEY`) — presence only, never the value, and never upstream-provider readiness. Upstream provider keys (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, …) live **only** in the gateway's private `infra/litellm.env` (copy it from `infra/litellm.env.example`; `disabled` is not a working key) and are deliberately never loaded into the app process, so they are not registered secret checks.

You can also see this in the UI at **Admin → Dependencies**.

## 4) Index your first corpus

Pick a folder on disk and a stable corpus id (lowercase slug).

=== "curl"
    ```bash
    BASE="http://127.0.0.1:8012/api"

    curl -sS -X POST "$BASE/index" \
      -H "Content-Type: application/json" \
      -d '{
        "corpus_id": "demo",
        "repo_path": "/absolute/path/to/your/project",
        "force_reindex": false
      }' | jq .
    ```

=== "Python"
    ```python
    import httpx

    BASE = "http://127.0.0.1:8012/api"
    req = {
        "corpus_id": "demo",
        "repo_path": "/absolute/path/to/your/project",
        "force_reindex": False,
    }
    httpx.post(f"{BASE}/index", json=req, timeout=30).raise_for_status()
    ```

!!! warning "Graph is optional"
    If you haven’t configured Neo4j (or you want faster bring-up), you can still index and search using the Postgres-backed legs. Graph retrieval will degrade gracefully when unavailable.

## 5) Watch indexing progress

```bash
curl -sS "http://127.0.0.1:8012/api/index/demo/status" | jq .
```

When status becomes `complete`, you’re ready to search.

## 6) Search

=== "curl"
    ```bash
    BASE="http://127.0.0.1:8012/api"

    curl -sS -X POST "$BASE/search" \
      -H "Content-Type: application/json" \
      -d '{
        "corpus_id": "demo",
        "query": "Where is indexing started in the backend?",
        "top_k": 8
      }' | jq '.matches | length'
    ```

=== "Python"
    ```python
    import httpx

    BASE = "http://127.0.0.1:8012/api"
    payload = {"corpus_id": "demo", "query": "Where is indexing started?", "top_k": 8}
    res = httpx.post(f"{BASE}/search", json=payload, timeout=30).json()
    print([(m["file_path"], m["score"]) for m in res.get("matches", [])])
    ```

## Next steps

- Learn what a **corpus** really means: [Corpus vs repo_id](../guides/corpus.md)
- Understand the retrieval legs and tuning knobs: [Searching & answering](search.md)
- Use the UI effectively: [UI tour](ui.md)

