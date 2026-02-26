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
    Use `/api/docker/{container}/logs` and application logs to pinpoint failures. For DB errors, also inspect Postgres and Neo4j logs.

!!! danger "Data Loss Risk"
    Avoid deleting DB volumes unless you intend a full reset. Back up before destructive actions.

## Symptom → Action

| Symptom | Likely Cause | Action |
|---------|--------------|--------|
| 500 on `/api/search` | DB unavailable | Check `/api/ready`, restart DB containers |
| No results from graph | Neo4j empty or disconnected | Rebuild graph, check credentials |
| Validation error on `/api/config` | Field constraints violated | Adjust values to allowed ranges |
| Slow queries | High `max_hops`, large `top_k` | Reduce hops, tune indexes |

```mermaid
flowchart TB
    Error["Error"] --> Check["/api/ready"]
    Check -->|"ok"| Investigate["Inspect Logs"]
    Check -->|"fail"| Restart["Restart Services"]
    Investigate --> Fix["Config Tune"]
```

=== "Python"
```python
import httpx
print(httpx.get("http://127.0.0.1:8012/api/ready").json())  # readiness
```

=== "curl"
```bash
curl -sS http://127.0.0.1:8012/api/ready | jq .
curl -sS http://127.0.0.1:8012/api/docker/status | jq .
```

=== "TypeScript"
```typescript
await fetch('/api/ready').then(r => r.ok || Promise.reject('Not ready'))
```

- [x] Verify readiness
- [x] Inspect logs
- [x] Reduce search/fusion parameters
- [x] Reindex corpus

??? note "Cache Issues"
    If you suspect stale caches, clear retrieval caches (if enabled) and restart the API to invalidate in-memory state.
