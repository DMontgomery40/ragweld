<div class="grid chunk_summaries" markdown>

-   :material-information:{ .lg .middle } **Glossary**

    ---

    Key terms from data/glossary.json

-   :material-database:{ .lg .middle } **Infrastructure Terms**

    ---

    Postgres pgvector URL, Neo4j URI, Table names

-   :material-magnify:{ .lg .middle } **Retrieval Terms**

    ---

    vector_k, fusion weights, chunk_summaries

</div>

!!! note "Information"
    The complete glossary is sourced from data/glossary.json. UI tooltips derive from this file.

!!! tip "Pro Tip"
    Use glossary terms in UI via the TooltipIcon component to keep definitions consistent.

!!! warning "Note"
    Do not duplicate glossary definitions in UI code—use the source file for single source of truth.

??? note "Collapsible: Example terms"

    Selected entries from data/glossary.json are shown below.


| Term | Key | Definition |
|------|-----|------------|
| PostgreSQL pgvector URL | POSTGRES_URL | Connection URL for PostgreSQL with pgvector extension. Format: postgresql://user:pass@host:port/db |
| Neo4j Connection URI | NEO4J_URI | Connection URI for Neo4j. Format: bolt://host:7687 or neo4j://host:7687 |
| Active Repository | REPO | Logical repository name for routing and indexing (repo_id / corpus_id) |
| Table Name | TABLE_NAME | Optional override for pgvector table name, defaults to code_chunks_{REPO} |


```mermaid
flowchart LR
    data_glossary[data/glossary.json] --> UI_Tooltip[TooltipIcon]
    UI_Tooltip --> Frontend[Help text & Glossary tab]
```


=== "Python"
    ```python
    # (1) Load glossary JSON
    import json
    with open('data/glossary.json') as f:
        g = json.load(f)
    print(g['terms'][0]['term'])
    ```

=== "curl"
    ```bash
    # (1) Serve glossary via endpoint
    curl http://localhost:8000/glossary
    ```

=== "TypeScript"
    ```typescript
    import glossary from '../data/glossary.json'
    // (1) Render TooltipIcon with definition
    <TooltipIcon term={glossary.terms[0]} />
    ```


1. The glossary is the authoritative source for tooltips and UI help


- [x] Use glossary terms in UI components
- [x] Keep data/glossary.json updated when adding terms


??? note "Collapsible: Adding a glossary term"

    1. Add the term to data/glossary.json with key and definition
    2. Commit and deploy
    3. UI will surface term via TooltipIcon automatically

