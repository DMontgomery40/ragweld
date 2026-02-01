# Troubleshooting

<div class="grid chunk_summaries" markdown>

-   :material-bug:{ .lg .middle } **Common Failures**

    ---

    Timeouts, DB connectivity, schema mismatches.

-   :material-shield-alert:{ .lg .middle } **Validation Errors**

    ---

    Pydantic constraints fail fast with precise messages.

-   :material-ambulance:{ .lg .middle } **Recovery**

    ---

    Clear caches, reindex, restart services.

</div>

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

!!! tip "Read the Error"
    Pydantic tells you exactly which field failed validation and why. Fix the config, regenerate types if needed, and retry.

!!! note "Logs"
    Use `/docker/{container}/logs` and application logs to pinpoint failures. For DB errors, also inspect Postgres and Neo4j logs.

!!! warning "Data Loss Risk"
    Avoid deleting DB volumes unless you intend a full reset. Back up before destructive actions.

## Symptom → Action

| Symptom | Likely Cause | Action |
|---------|--------------|--------|
| 500 on `/search` | DB unavailable | Check `/ready`, restart DB containers |
| No results from graph | Neo4j disconnected or empty | Rebuild graph, check credentials |
| Validation error on `/config` patch | Field constraints violated | Adjust values to allowed ranges |
| Slow queries | High `max_hops`, large top_k | Reduce graph hops, tune indexes |

```mermaid
flowchart TB
    Error[Error] --> Check[/ready]
    Check -->|ok| Investigate[Inspect Logs]
    Check -->|fail| Restart[Restart Services]
    Investigate --> Fix[Config Tune]
```

## Useful Commands

=== "Python"
    ```python
    import httpx
    base = "http://localhost:8000"
    print(httpx.get(f"{base}/ready").json())  # readiness
    ```

=== "curl"
    ```bash
    curl -sS http://localhost:8000/ready | jq .
    curl -sS http://localhost:8000/docker/status | jq .
    ```

=== "TypeScript"
    ```typescript
    // Programmatic health checks during E2E tests
    await fetch('/ready').then(r => r.ok || Promise.reject('Not ready'))
    ```

- [x] Verify readiness
- [x] Inspect logs
- [x] Reduce search/fusion parameters
- [x] Reindex corpus

!!! success "Fallback Behavior"
    If one retrieval path fails (e.g., graph), the system continues with vector + sparse. This is expected and logged.

??? note "Cache Issues"
    If you suspect stale cache, clear retrieval caches (if enabled) or include a cache-busting parameter during debugging.
