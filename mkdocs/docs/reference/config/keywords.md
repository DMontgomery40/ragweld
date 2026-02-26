# Config reference: `keywords`

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

**Total parameters**: 5

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `keywords.keywords_auto_generate` | `KEYWORDS_AUTO_GENERATE` | `int` | `1` | ≥ 0, ≤ 1 | Auto-generate keywords |
| `keywords.keywords_boost` | `KEYWORDS_BOOST` | `float` | `1.3` | ≥ 1.0, ≤ 3.0 | Score boost for keyword matches |
| `keywords.keywords_max_per_repo` | `KEYWORDS_MAX_PER_REPO` | `int` | `50` | ≥ 10, ≤ 500 | Max discriminative keywords per repo |
| `keywords.keywords_min_freq` | `KEYWORDS_MIN_FREQ` | `int` | `3` | ≥ 1, ≤ 10 | Min frequency for keyword |
| `keywords.keywords_refresh_hours` | `KEYWORDS_REFRESH_HOURS` | `int` | `24` | ≥ 1, ≤ 168 | Hours between keyword refresh |

### Details (glossary)

??? info "`keywords.keywords_auto_generate` (`KEYWORDS_AUTO_GENERATE`) — Auto-Generate Keywords"
    **Category**: `general`

    Automatically extract repository keywords from code and documentation during indexing (1=yes, 0=no). When enabled, the system analyzes class names, function names, docstrings, and comments to build a keyword set for routing. This supplements manually-defined keywords in repos.json. Auto-generation is useful for new repos or when you don't know what routing keywords to use. Disable if you prefer full manual control via repos.json.

    Recommended: 1 for automatic keyword discovery, 0 for strict manual control.

    **Badges**:
    - Multi-repo feature
    - Complements manual keywords

??? info "`keywords.keywords_boost` (`KEYWORDS_BOOST`) — Keywords Boost"
    **Category**: `general`

    Score boost multiplier applied to search results that match corpus keywords. Higher values (1.5-2.0) strongly favor keyword matches, lower values (1.1-1.3) provide mild preference. The boost is multiplied with the base retrieval score. Recommended: 1.3 for balanced keyword preference.

    Sweet spot: 1.3 for balanced systems. Use 1.1-1.2 for mild keyword preference (keyword matches slightly favored). Use 1.5-2.0 when keywords are highly reliable indicators of relevance. Use 2.5+ only when keywords are definitive relevance signals.

    • Range: 1.0-3.0 (typical: 1.1-2.0)
    • Mild boost: 1.1-1.2 (slight preference)
    • Balanced: 1.3 (recommended)
    • Strong boost: 1.5-2.0 (strong preference)
    • Effect: Higher = more weight to keyword matches
    • Symptom too low: Keyword matches undervalued
    • Symptom too high: Keyword matches dominate, other signals ignored

    **Badges**:
    - Scoring

    **Links**:
    - [Score Boosting](https://en.wikipedia.org/wiki/Relevance_(information_retrieval))
    - [TF-IDF Scoring](https://en.wikipedia.org/wiki/Tf%E2%80%93idf)
    - [Keyword Extraction](https://github.com/airKlizz/CustomizedTFIDF)

??? info "`keywords.keywords_max_per_repo` (`KEYWORDS_MAX_PER_REPO`) — Keywords Max Per Repo"
    **Category**: `general`

    Maximum number of repository-specific keywords to extract and store for query routing in multi-repo setups. Higher values (100-200) capture more routing signals but increase memory and may introduce noise. Lower values (20-50) keep routing focused on core concepts. Keywords are extracted from code, docs, and enrichment metadata. Used by the router to determine which repositories are most relevant for a given query.

    Recommended: 50-100 for most repos, 150-200 for large multi-domain codebases, 20-30 for focused microservices.

    **Badges**:
    - Multi-repo only
    - Auto-generated

??? info "`keywords.keywords_min_freq` (`KEYWORDS_MIN_FREQ`) — Keywords Min Frequency"
    **Category**: `general`

    Minimum term frequency required for a keyword to be included. Terms must appear at least this many times in the corpus to be considered. Higher values (5-10) ensure keywords are common enough to be meaningful, lower values (1-3) allow rare but distinctive terms. Recommended: 3 for balanced filtering.

    Sweet spot: 3 for most corpora. Use 1-2 when you want to include rare but distinctive terms (e.g., unique function names). Use 5-7 when you want only common, well-established keywords. Use 10+ only for very large corpora.

    • Range: 1-10 (typical: 2-5)
    • Rare terms: 1-2 (include distinctive rare terms)
    • Balanced: 3 (recommended)
    • Common terms: 5-7 (only well-established keywords)
    • Effect: Higher = fewer keywords, more common terms only
    • Symptom too low: Rare, potentially noisy keywords included
    • Symptom too high: Important distinctive keywords filtered out

    **Badges**:
    - Keyword Extraction

    **Links**:
    - [TF-IDF Keyword Extraction](https://github.com/tonifuc3m/document_selection_tfidf)
    - [Term Frequency](https://en.wikipedia.org/wiki/Tf%E2%80%93idf)
    - [Keyword Extraction](https://github.com/MOoTawaty/TF-IDF-keywords-extraction)

??? info "`keywords.keywords_refresh_hours` (`KEYWORDS_REFRESH_HOURS`) — Keywords Refresh (Hours)"
    **Category**: `general`

    How often (in hours) to regenerate repository keywords from code for improved query routing. Lower values keep keywords fresh but increase indexing overhead. Typical: 24-168 hours (1-7 days).

    **Links**:
    - [Keyword Extraction](https://en.wikipedia.org/wiki/Keyword_extraction)
