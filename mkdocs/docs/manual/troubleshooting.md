# Troubleshooting (user-focused)

<div class="grid chunk_summaries" markdown>

-   :material-heart-pulse:{ .lg .middle } **Readiness first**

    ---

    If `/api/ready` is red, everything else will be weird.

-   :material-folder-search:{ .lg .middle } **Corpus sanity**

    ---

    “Wrong results” are often “wrong corpus” or “index never completed”.

-   :material-docker:{ .lg .middle } **Infra reality**

    ---

    Postgres/Neo4j must be reachable from the backend environment that’s running.

</div>

[Quickstart](quickstart.md){ .md-button .md-button--primary }
[UI tour](ui.md){ .md-button }
[Deep troubleshooting](../troubleshooting.md){ .md-button }

## Fast checks (do these in order)

=== "curl"
    ```bash
    # 1) Backend reachable?
    curl -sS "http://127.0.0.1:8012/api/health" | jq .

    # 2) Backend ready (DB connectivity)?
    curl -sS "http://127.0.0.1:8012/api/ready" | jq .
    ```

=== "UI"
    1. Open **Dashboard → System Status**
    2. Confirm Postgres + Neo4j status
    3. Confirm “Ready” is green

    The top-bar **Health** pill is a shortcut for the same question: click it for a per-dependency readiness popover (with an operator hint per down dependency) plus a jump to System Status, without navigating away.

## Symptom → likely cause → fix

| Symptom | Likely cause | Fix |
|--------|--------------|-----|
| UI loads but search returns nothing | Corpus not indexed (or wrong corpus) | Index a corpus and wait for `complete` (`/api/index/<corpus>/status`) |
| `/api/ready` fails | DB services not reachable | Start Docker services (`./start.sh`), check Postgres/Neo4j containers |
| Indexing errors on a file | Unsupported encoding or giant binary | Exclude the file type; reindex |
| Search is slow | Large candidate sizes, slow provider calls, graph enabled | Start with `/api/search`, disable graph, reduce top-k; then tune |
| Deleting a corpus returns 409 | A live index run holds the corpus fence | The error names the run and its latest step; stop it (**RAG → Indexing → Stop**) or wait for its lease to lapse, then retry |
| Chat logs header says “Loki unreachable” during a heavy re-index | The Loki readiness probe timed out on a busy box (Loki itself is usually up) | The URL is cached and the log tail retries for up to two minutes, so the header recovers without a reload; if it stays red after the box quiets down, check `/api/loki/status` and your `LOKI_BASE_URL` |

## “My corpus indexed, but results look wrong”

- [ ] Confirm you’re searching the correct `corpus_id`
- [ ] Use `/api/search` and inspect `source` for top matches
- [ ] Try disabling one leg at a time (`include_graph=false`, then `include_sparse=false`, etc.)
- [ ] If you recently changed embedding models/dimensions, do a full reindex (`force_reindex=true`)

??? note "When you need the deeper page"
    The main troubleshooting reference covers deeper failure modes (Docker vs local backend, monitoring, and diagnosis paths). See [Troubleshooting](../troubleshooting.md).

