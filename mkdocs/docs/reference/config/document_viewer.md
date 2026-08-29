# Config reference: `document_viewer`

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

**Total parameters**: 3

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `document_viewer.max_text_bytes` | — | `int` | `5000000` | ≥ 65536, ≤ 50000000 | Largest text/code file the viewer will serve in full |
| `document_viewer.page_render_scale` | — | `float` | `2.0` | ≥ 1.0, ≤ 4.0 | PDF page raster scale for the viewer (1.0 = 72 dpi; 2.0 = 144 dpi) |
| `document_viewer.thumbnail_render_scale` | — | `float` | `0.5` | ≥ 0.25, ≤ 1.0 | PDF page raster scale for citation thumbnails in chat |
