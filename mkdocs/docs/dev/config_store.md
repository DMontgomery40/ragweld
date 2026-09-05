# Config store & caching

<div class="grid chunk_summaries" markdown>

-   :material-content-copy:{ .lg .middle } **Copy-on-read safety**

    ---

    `ConfigStore.get()` now returns a deep Pydantic copy. No shared references are leaked to callers, preventing accidental cross-request mutations.

-   :material-source-repository:{ .lg .middle } **Scoped by corpus (`repo_id`)**

    ---

    Global and per-corpus configs are both exposed. Per-corpus configs are keyed by `repo_id` (the code-path term for corpus id).

-   :material-content-save:{ .lg .middle } **Persist via API**

    ---

    GET returns a snapshot. Changes are not persisted until you POST/PUT back to `/api/config` (global) or the per-corpus endpoint.

-   :material-shield-lock:{ .lg .middle } **Pydantic is the law**

    ---

    Shapes and defaults come from `server/models/tribrid_config_model.py` (`TriBridConfig`). Migrations happen inside the store.

</div>

[Get started](../manual/quickstart.md){ .md-button .md-button--primary }
[Configuration](../configuration.md){ .md-button }
[API](../api.md){ .md-button }

!!! tip "Correct base path in dev"
    All configuration routes are under `/api`. Examples:
    - Global: `http://127.0.0.1:8012/api/config`
    - UI fetch: `fetch("/api/config")`

!!! warning "Anti-pattern: holding live references"
    Don’t hold a config object across awaits or between requests and mutate it in place. From now on, every `get()` call returns a detached deep copy; your mutations won’t affect server state until you explicitly save.

## What changed and why

ragweld now enforces copy-on-read semantics in the server-side config store:

- `ConfigStore.get(repo_id)` returns a deep `model_copy(deep=True)` of `TriBridConfig`.
- The in-memory cache also holds deep copies so subsequent reads never expose mutable shared state.
- `ConfigStore.save(config, repo_id)` writes to persistent storage and updates the cache with a deep copy, returning a deep copy.

This prevents subtle races where a handler mutates a previously returned config object and unintentionally changes server state for concurrent requests.

!!! note "Unit test coverage"
    See `tests/unit/test_config_store.py` for a minimal assertion that repeated `get(None)` calls return detached objects and that mutating one does not affect subsequent reads.

!!! note "Preview reads: `persist=False`"
    `ConfigStore.get(repo_id, persist=False)` resolves a scope through the same upgrade and production-reconciliation rules but writes nothing: no migration persisted, no new corpus seeded from the global template, no cache entry, and no touch of the global template file. Conditional corpus cleanup uses it so *checking* a corpus before deleting it cannot quietly migrate or seed that corpus's stored config; the next ordinary `get()` still performs any pending migration exactly as before. Both paths return a fresh deep copy — a preview can never hand out a live cached snapshot, and it never warms the cache that a later ordinary read would use.

## Snapshot semantics (GET → mutate local → PUT/POST)

```mermaid
flowchart LR
  A["Client"] --> B["GET '/api/config'"]
  B --> C["ConfigStore.get()"]
  C --> D["Return deep copy"]
  D --> E["Client mutates local"]
  E --> F["PUT '/api/config'"]
  F --> G["ConfigStore.save()"]
  G --> H["Persist to Postgres"]
  H --> I["Update in-memory cache (deep copy)"]
  I --> J["Return deep copy"]
```

### Round-trip examples

=== "Python"
```python
import asyncio
import httpx

API = "http://127.0.0.1:8012/api"  # (1)!

async def main() -> None:
    async with httpx.AsyncClient(base_url=API, timeout=30) as client:
        # Read a snapshot (deep copy on the server)
        r = await client.get("/config")
        r.raise_for_status()
        cfg = r.json()

        # Mutate locally (does not affect server until saved)
        cfg["generation"]["gen_model"] = "gpt-4o-mini"  # (2)!

        # Persist the change
        s = await client.put("/config", json=cfg)  # (3)!
        s.raise_for_status()

        # Verify round-trip
        back = (await client.get("/config")).json()
        assert back["generation"]["gen_model"] == "gpt-4o-mini"

if __name__ == "__main__":
    asyncio.run(main())
```

1. Always include `/api` in the base URL in dev.
2. Local mutation is safe; it won’t leak to other requests.
3. Use PUT/POST to persist. The server updates storage and cache, and returns a deep copy.

=== "curl"
```bash
# Read global config (snapshot)
curl -sS "http://127.0.0.1:8012/api/config" | jq .

# Save back a modified config (persist + cache update)
curl -sS -X PUT "http://127.0.0.1:8012/api/config" \
  -H "Content-Type: application/json" \
  -d @config.json | jq .
```

=== "TypeScript"
```ts
// Read (snapshot)
const res = await fetch("/api/config"); // (1)!
const cfg = await res.json();

// Mutate locally
cfg.generation.gen_model = "gpt-4o-mini"; // (2)!

// Save (persist + cache deep copy)
const saved = await fetch("/api/config", {
  method: "PUT", // (3)!
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(cfg),
});
if (!saved.ok) throw new Error("Failed to save config");
```

1. In dev, the UI proxies relative calls to the backend under `/api`.
2. Local mutation is fine; it’s only applied when saved.
3. Use PUT/POST to persist changes.

## Definitions (what these terms mean)

Detached copy
: A deep Pydantic copy (`model_copy(deep=True)`) returned to callers. You can mutate it safely; it won’t change server-held objects unless you save.

Global config
: The default `TriBridConfig` returned when `repo_id=None`. Read via `/api/config`.

Corpus config (per-`repo_id`)
: A `TriBridConfig` layered over the global defaults for a specific corpus. Read via a per-corpus endpoint and written back similarly. In code, corpus id is referred to as `repo_id`.

Cache
: An in-memory map inside the server that stores deep copies of configs to avoid recomputing and to ensure fast reads. The cache never exposes shared mutable references to clients.

## Engineering guidance

- Treat GET responses as immutable snapshots. If you need to change config:
  - Make local edits.
  - Save via PUT/POST.
  - Re-read if you need to observe migrations/default-infills.
- Never stash a config object for reuse across requests; always call `get()` when you start a new operation.
- If you’re not sure, prefer a fresh GET before making a decision that depends on current configuration values.

??? tip "Service-layer pattern (internal)"
    When modifying config inside the backend:

    ```python
    cfg = await store.get(repo_id="docs")
    cfg.generation.gen_model = "gpt-4o-mini"
    await store.save(cfg, repo_id="docs")
    ```

    - `get()` and `save()` both return deep copies.
    - The in-memory cache is also updated with a deep copy.

## Failure modes this avoids

- Cross-request leakage: handler A mutates a shared object and handler B sees it unexpectedly.
- Lost updates: a later read stomps on an unsafely mutated object in memory.
- Heisenbugs tied to the timing/order of operations within async handlers.

!!! success "Safe defaults"
    - Read is cheap and safe: you get a fresh deep copy each time.
    - Write updates storage and cache atomically from the perspective of callers.
    - If you’re not sure, do another GET right after save to lock in what the server will use.

## UI implications

- UI settings panels operate on local snapshots; unsaved changes are not applied to the server.
- Saving settings explicitly triggers a PUT/POST to `/api/config` (global) or the corpus-specific endpoint.
- A page reload discards unsaved local changes (by design).

!!! warning "If your config ‘resets’ on refresh"
    That’s expected when you haven’t saved. Click Save in the settings panel to persist. After saving, a refresh will read the latest server-side copy.

## Where this lives in the code

- Config model and defaults: `server/models/tribrid_config_model.py` (`TriBridConfig`)
