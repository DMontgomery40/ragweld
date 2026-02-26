# Config reference: `layer_bonus`

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

**Total parameters**: 6

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `layer_bonus.freshness_bonus` | `FRESHNESS_BONUS` | `float` | `0.05` | ≥ 0.0, ≤ 0.3 | Bonus for recently modified files |
| `layer_bonus.gui` | `LAYER_BONUS_GUI` | `float` | `0.15` | ≥ 0.0, ≤ 0.5 | Bonus for GUI/front-end layers |
| `layer_bonus.indexer` | `LAYER_BONUS_INDEXER` | `float` | `0.15` | ≥ 0.0, ≤ 0.5 | Bonus for indexing/ingestion layers |
| `layer_bonus.intent_matrix` | `LAYER_INTENT_MATRIX` | `dict[str, dict[str, float]]` | `{"gui": {"gui": 1.2, "web": 1.2, "server": 0.9, "retrieval": 0.8, "indexer": 0.8}, "retrieval": {"retrieval": 1.3, "server": 1.15, "common": 1.1, "web": 0.7, "gui": 0.6}, "indexer": {"indexer": 1.3, "retrieval": 1.15, "common": 1.1, "web": 0.7, "gui": 0.6}, "eval": {"eval": 1.3, "retrieval": 1.15, "server": 1.1, "web": 0.8, "gui": 0.7}, "infra": {"infra": 1.3, "scripts": 1.15, "server": 1.1, "web": 0.9}, "server": {"server": 1.3, "retrieval": 1.15, "common": 1.1, "web": 0.7, "gui": 0.6}}` | — | Intent-to-layer bonus matrix. Keys are query intents, values are layer->multiplier maps. |
| `layer_bonus.retrieval` | `LAYER_BONUS_RETRIEVAL` | `float` | `0.15` | ≥ 0.0, ≤ 0.5 | Bonus for retrieval/API layers |
| `layer_bonus.vendor_penalty` | `VENDOR_PENALTY` | `float` | `-0.1` | ≥ -0.5, ≤ 0.0 | Penalty for vendor/third-party code (negative values apply a penalty) |

### Details (glossary)

??? info "`layer_bonus.freshness_bonus` (`FRESHNESS_BONUS`) — Freshness Bonus"
    **Category**: `general`

    Score boost applied to recently modified files during reranking, prioritizing newer code over stale code. Based on file modification time (mtime). Files modified in the last N days receive the full bonus, with linear decay over time. Useful for prioritizing recent work, active features, and current implementation patterns. Typical range: 0.0 (disabled) to 0.10 (strong recency bias).

    Sweet spot: 0.03-0.06 for subtle freshness preference. Use 0.06-0.10 for strong recency bias when your codebase changes rapidly and recent code is more likely relevant. Use 0.0 to disable entirely for stable codebases where age doesn't correlate with relevance. The bonus decays linearly from full value (files modified <7 days ago) to zero (files modified >90 days ago).

    Example: With 0.05 bonus, a file modified yesterday gets +0.05, a file modified 30 days ago gets +0.025, a file modified 90+ days ago gets 0. Freshness helps when users ask "how do we currently handle X?" - emphasizes recent implementations over legacy code. Trade-off: May deprioritize well-tested stable code in favor of recent changes.

    • Range: 0.0-0.10 (typical)
    • Disabled: 0.0 (age-agnostic ranking)
    • Subtle: 0.03-0.05
    • Balanced: 0.05-0.06 (recommended for active repos)
    • Strong recency: 0.08-0.10
    • Decay window: Full bonus at 0-7 days, linear decay to 90 days
    • Trade-off: Recent code vs battle-tested stable code

    **Badges**:
    - Advanced RAG tuning
    - Time-based ranking

    **Links**:
    - [Freshness in Ranking](https://en.wikipedia.org/wiki/Freshness_(search_engine))
    - [Temporal Relevance](https://en.wikipedia.org/wiki/Temporal_information_retrieval)
    - [Recency Bias](https://en.wikipedia.org/wiki/Recency_bias)

??? info "`layer_bonus.gui` (`LAYER_BONUS_GUI`) — Layer Bonus (GUI)"
    **Category**: `ui`

    Score boost applied to chunks from GUI/frontend layers when query intent is classified as UI-related. Part of the multi-layer architecture routing system. When users ask "how does the settings page work?" or "where is the login button?", chunks from directories like frontend/, components/, views/ receive this additive bonus during reranking. Higher values (0.08-0.15) strongly bias toward frontend code. Lower values (0.03-0.06) provide subtle guidance.

    Sweet spot: 0.06-0.10 for production systems with clear frontend/backend separation. Use 0.10-0.15 for strict layer routing when your architecture is well-organized and layer detection is accurate. Use 0.03-0.06 for loose guidance when layer boundaries are fuzzy. This bonus is only applied when intent classification detects UI/frontend intent from the query.

    Works with repos.json layer_bonuses configuration, which maps intent types to directory patterns. Example: "ui" intent boosts frontend/, components/, views/. Combine with LAYER_BONUS_RETRIEVAL for multi-tier architectures (API, service, data layers). Intent detection uses keyword matching and optional LLM classification.

    • Range: 0.03-0.15 (typical)
    • Subtle guidance: 0.03-0.06
    • Balanced: 0.06-0.10 (recommended)
    • Strong routing: 0.10-0.15
    • Applied: Only when query intent = UI/frontend
    • Requires: repos.json layer_bonuses configuration

    **Badges**:
    - Advanced RAG tuning
    - Multi-layer architectures

    **Links**:
    - [Architecture-Aware Retrieval](https://arxiv.org/abs/2312.10997)

??? info "`layer_bonus.intent_matrix` (`LAYER_INTENT_MATRIX`) — Intent Matrix (Advanced)"
    **Category**: `general`

    Advanced JSON map that biases results toward specific architectural layers based on the detected intent of the query.

    Structure: { intent: { layer: multiplier } }

    When a query is classified as an intent (e.g., gui, retrieval, indexer), the corresponding row multiplies layer bonuses for matching files/directories. Values > 1.0 boost that layer for the intent; values < 1.0 penalize. This is “soft routing” for monorepos: UI questions should drift toward web/gui, indexing questions toward indexer, etc.

    Start conservative. Large multipliers can overpower actual relevance and produce confidently-wrong results.

    • Format: JSON object of objects (numbers only)
    • Multipliers: 1.0 = neutral, > 1.0 boost, < 1.0 penalize
    • Typical range: 0.6–1.3
    • Debugging: if results feel “stuck” in one layer, reduce the highest multipliers
    • Related knobs: Layer Bonus (GUI/Retrieval), Vendor Penalty, Freshness Bonus

    **Badges**:
    - Advanced RAG tuning
    - Multi-layer architectures

    **Links**:
    - [Architecture-Aware Retrieval](https://arxiv.org/abs/2312.10997)
    - [Multitier Architecture](https://en.wikipedia.org/wiki/Multitier_architecture)

??? info "`layer_bonus.retrieval` (`LAYER_BONUS_RETRIEVAL`) — Layer Bonus (Retrieval)"
    **Category**: `evaluation`

    Score boost applied to chunks from backend/API/service layers when query intent is classified as retrieval or data-related. Complements LAYER_BONUS_GUI for multi-tier architecture routing. When users ask "how do we fetch user data?" or "where is the search API?", chunks from api/, services/, models/, controllers/ receive this bonus during reranking. Helps route queries to the right architectural layer.

    Sweet spot: 0.06-0.10 for production systems. Use 0.10-0.15 for strong backend routing when API layer is clearly separated. Use 0.03-0.06 for subtle hints when boundaries are less clear. This bonus applies when intent detection identifies backend/API/data queries via keywords like "fetch", "query", "API", "endpoint", "database".

    Configure layer patterns in repos.json layer_bonuses: map "retrieval" intent to api/, routes/, controllers/, services/, etc. The intent classifier examines query terms and (optionally) uses an LLM to categorize intent. Multiple bonuses can apply simultaneously - a query about "user profile API" might trigger both LAYER_BONUS_GUI and LAYER_BONUS_RETRIEVAL.

    • Range: 0.03-0.15 (typical)
    • Subtle guidance: 0.03-0.06
    • Balanced: 0.06-0.10 (recommended)
    • Strong routing: 0.10-0.15
    • Applied: When query intent = API/backend/retrieval/data
    • Requires: repos.json layer_bonuses with retrieval intent mapping

    **Badges**:
    - Advanced RAG tuning
    - Multi-layer architectures

    **Links**:
    - [Multi-Tier Architectures](https://en.wikipedia.org/wiki/Multitier_architecture)

??? info "`layer_bonus.vendor_penalty` (`VENDOR_PENALTY`) — Vendor Penalty"
    **Category**: `general`

    Score penalty (negative bonus) applied to third-party library code (node_modules, vendor/, site-packages/, etc.) during reranking when VENDOR_MODE is set to prefer_first_party. Helps prioritize your application code over external dependencies. Typical range: -0.05 to -0.12. Higher penalties (more negative) push library code down the rankings more aggressively.

    Sweet spot: -0.08 to -0.10 for production systems. Use -0.10 to -0.12 for strong first-party preference when you want library code only as fallback. Use -0.05 to -0.08 for moderate preference when library examples are sometimes helpful. Set to 0.0 to disable vendor detection entirely (all code ranked equally).

    Vendor detection matches common patterns: node_modules/, vendor/, .venv/, site-packages/, bower_components/, Pods/, third_party/. The penalty is applied during final reranking after hybrid fusion. Pair with path boosts in repos.json to further prioritize your core application directories. Most users want to understand THEIR code first, then library internals.

    • Range: -0.12 to 0.0 (negative = penalty)
    • No penalty: 0.0 (rank libraries equally)
    • Moderate preference: -0.05 to -0.08
    • Balanced: -0.08 to -0.10 (recommended)
    • Strong first-party: -0.10 to -0.12
    • Opposite mode: Set VENDOR_MODE=prefer_vendor to boost libraries instead

    **Badges**:
    - Advanced RAG tuning
    - Code priority control

    **Links**:
    - [Path Patterns](https://github.com/github/gitignore)
    - [First-Party vs Third-Party](https://en.wikipedia.org/wiki/First-party_and_third-party_sources)
