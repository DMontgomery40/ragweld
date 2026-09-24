# Config reference: `system_one`

<div class="grid chunk_summaries" markdown>

-   :material-tune:{ .lg .middle } **Enterprise tuning surface**

    ---

    Defaults + constraints are rendered directly from Pydantic.

-   :material-key-outline:{ .lg .middle } **Env keys when available**

    ---

    Many fields have an env-style alias (from `TriBridConfig.to_flat_dict()`).

-   :material-tooltip-text:{ .lg .middle } **Tooltip-level guidance**

    ---

    If a matching glossary entry exists, you’ll see deeper tuning notes.

</div>

[Config reference](index.md){ .md-button .md-button--primary }
[Config API & workflow](../../configuration.md){ .md-button }
[Glossary](../../glossary.md){ .md-button }

**Total parameters**: 7

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `system_one.laya_base_url` | — | `str` | `"http://127.0.0.1:58180"` | min_length=1 | API root of the self-hosted laya-serve used when provider='laya'. |
| `system_one.max_concurrency` | — | `int` | `16` | ≥ 1, ≤ 64 | Concurrent System One requests one caller (a rerank, a synthetic run) keeps in flight. TypeSafe allows 1,200 requests per minute per key. |
| `system_one.max_retries` | — | `int` | `3` | ≥ 0, ≤ 8 | Retries after a 408, 429 or 5xx (including 529 Overloaded) or a connection failure; 0 disables. |
| `system_one.model` | — | `str` | `"jev-latest"` | min_length=1 | Model named in every request. TypeSafe needs a Jev model id (jev-latest). laya-serve honours a checkpoint name (english, multilingual, typed-decisions) and routes any other value by language. |
| `system_one.provider` | — | `Literal["typesafe", "laya"]` | `"typesafe"` | allowed="typesafe", "laya" | System One backend: 'typesafe' calls TypeSafe's hosted Jev (TYPESAFE_API_KEY); 'laya' calls a self-hosted laya-serve (offline, no credential). Both speak POST /v1/systemone. |
| `system_one.timeout_s` | — | `float` | `30.0` | ≥ 1.0, ≤ 120.0 | Total budget per System One call in seconds, including retries after 408/429/5xx. |
| `system_one.typesafe_base_url` | — | `str` | `"https://api.typesafe.ai"` | min_length=1 | API root of the TypeSafe endpoint used when provider='typesafe'. |
