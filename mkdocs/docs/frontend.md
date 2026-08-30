# Frontend Integration and Types

<div class="grid chunk_summaries" markdown>

-   :material-code-json:{ .lg .middle } **Generated Types Only**

    ---

    `web/src/types/generated.ts` is the only source for API interfaces.

-   :material-store:{ .lg .middle } **Zustand Stores**

    ---

    Stores consume generated types; hooks expose typed accessors.

-   :material-react:{ .lg .middle } **Components**

    ---

    Props derive from hooks; no custom interfaces without Pydantic ancestry.

</div>

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

!!! tip "Generate Early"
    Run `uv run scripts/generate_types.py` before starting the frontend. Hot reload relies on correct types.

!!! note "Traceability"
    Every UI element (slider, toggle, input) must map to a Pydantic field. Tooltips come from `data/glossary.json`.

!!! warning "No Hand-Written Interfaces"
    Interfaces like `interface SearchResponse { ... }` are forbidden. Import from `generated.ts`.

## Store and Hook Structure

| File | Purpose |
|------|---------|
| `web/src/stores/useConfigStore.ts` | Holds `TriBridConfig` and patch helpers; records `fieldErrors` keyed by dotted config path from rejected section PATCHes |
| `web/src/hooks/useConfig.ts` | Read/update config |
| `web/src/hooks/useFusion.ts` | Fusion-related derived state |
| `web/src/hooks/useReranker.ts` | Reranker configuration and status |

```mermaid
flowchart TB
    G[generated.ts] --> S[stores]
    S --> H[hooks]
    H --> C[components]
```

## Example Usage

=== "Python"
    ```python
    # Backend reference: see dev/pydantic.md for generation step (1)
    ```

=== "curl"
    ```bash
    # Frontend consumes API; see api.md for routes (2)
    ```

=== "TypeScript"
    ```typescript
    import { TriBridConfig, SearchResponse } from '../web/src/types/generated';

    function useConfig() {
      // typed fetch
      const [cfg, setCfg] = React.useState<TriBridConfig | null>(null);
      React.useEffect(() => { fetch('/api/config').then(r => r.json()).then(setCfg); }, []); // (3)
      return cfg;
    }
    ```

1. Types generation step is mandatory
2. API is the contract; no local mocks of shapes
3. Fetch returns the Pydantic-driven shape of config

!!! success "Tooltip Integration"
    `data/glossary.json` drives hover help via `TooltipIcon` in the UI. Keep term keys stable.

- [x] Use generated types across stores, hooks, and components
- [x] Remove any legacy custom interfaces
- [x] Validate prop chains map back to Pydantic fields

```mermaid
flowchart LR
    Glossary[data/glossary.json] --> Tooltip[TooltipIcon]
    Tooltip --> UI
```

## Numeric inputs: `NumberField`

Every numeric input in the frontend is `web/src/components/ui/NumberField.tsx` — the one place a raw `<input type="number">` is allowed to render. It exists so a config-bound number has one behavior everywhere: raw text while editing, a clamp to the field's Pydantic bounds at commit (blur, Tab, or Enter), then an optimistic local update followed by a debounced, deep-merged `PATCH /api/config/{section}`.

Two props carry the contract:

configPath
:   The full dotted `TriBridConfig` path the field persists to (for example `enrichment.chunk_summaries_max`). When set, the per-field detail of a rejected PATCH — parsed by `web/src/utils/configPatchErrors.ts` into `useConfigStore`'s `fieldErrors` — renders under this exact field as a `role="alert"` message. Omit it for inputs that are not persisted config values (the Storage Calculator, ad-hoc request parameters): they still clamp, there is just nothing to attribute a server error to.

onCommit
:   Receives the clamped number. Clearing the box and blurring restores the last committed value — `NumberField` cannot express "the operator cleared this", so genuinely nullable overrides (Chat's per-conversation Top-K) must not use it.

Two tests enforce the contract instead of trusting review:

- `tests/unit/test_clean_start_defaults.py::test_every_number_field_advertises_its_pydantic_bounds` — every `NumberField`'s advertised min/max must equal the Pydantic `ge`/`le` of the config path it writes (resolved from `configPath` or a `useConfigField<number>` binding). It checks 100+ controls; a `NumberField` with neither marker must be a genuine non-config input.
- `tests/unit/test_clean_start_defaults.py::test_no_config_editor_still_writes_a_raw_number_input` — no frontend source may contain `type="number"` outside `NumberField.tsx`, with one pinned, documented exception (Chat's Top-K override).

The end-to-end behavior (clamped value persisted, raw value never posted, a rejected PATCH reverting its own optimistic edits) is proven against a live stack in `web/tests/e2e/exhaustive/numberfield_migration.spec.ts` — see [Testing](testing.md).

## Theme tokens and text contrast

<div class="grid chunk_summaries" markdown>

-   :material-palette:{ .lg .middle } **Text vs. background split**

    ---

    `--accent` is a button background and border color; `--accent-text` is the text-only variant.

-   :material-check-decagram:{ .lg .middle } **Floors, pinned by a test**

    ---

    Body text >= 7:1 and support text >= 4.5:1 against every composited surface, in both themes.

</div>

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

All GUI color choices live in `web/src/styles/tokens.css`, and the legibility rules that govern them are enforced by a real test (`tests/unit/test_web_tokens_contrast.py`), not by eyeballing. The motivation is concrete: ragweld's operator monitors are low-DPI, and muted grays that look fine on a retina screen collapse into mush there. If you add or change a styled surface, these are the constraints you inherit.

### The token contract

| Token | Role | Rule |
|-------|------|------|
| `--accent` | Button **background** (paired with `--accent-contrast`), borders, active accents | Never use as a `color:` (text) value — its dark-theme value fails the text-contrast floor on its own |
| `--accent-text` | Standalone **text** that wants the accent hue | Lightness-adjusted to clear 4.5:1 against `--bg`, `--bg-elev1`, `--bg-elev2`, and `--panel` in both themes; on the light theme it equals `--accent`, which already passes |
| `--fg` | Body text | >= 7:1 against every composited surface |
| `--fg-muted`, `--link`, `--ok`, `--warn`, `--err` | Support text and status colors | >= 4.5:1 against every composited surface |

### Two rules enforced beyond the tokens

1. **Never dim text with `opacity`.** A muted color tier is the only allowed way to de-emphasize text — an `opacity: 0.6` rule composites a token that passes its own floor down to well below it on screen.
2. **Resting opacity on visible controls >= 0.8.** Disabled and loading states communicate through `cursor`, border, and color, not through a sub-0.8 fade.

The test parses the hex values straight out of `tokens.css` (zero mocks, no hand-copied constants) and computes WCAG 2.x relative luminance and contrast ratios directly, across both theme blocks and all four surfaces text actually paints on. When an edit breaks a floor, the failure names the theme, the token, the surface, and the measured ratio.

!!! tip "Reaching for the accent color in text"
    Reach for `var(--accent-text)` instead of `var(--accent)`. The test also scans every `web/src/**/*.{css,tsx,ts}` file for raw `var(--accent)` used as a `color` value, so the migration stays durable. Note that scan is a heuristic over source text: it cannot see through an intermediate variable or lookup table (a `const accent = ...` re-exported as a text color), so review those by hand when you introduce them.

!!! note "What changed visually (operators)"
    Muted text is slightly brighter in both themes, the light-theme status colors were darkened to clear the 4.5:1 floor, and disabled/loading buttons no longer fade below 0.8 resting opacity. Nothing functional changed — this is a legibility pass, not a feature change.

??? note "Component Inventory"
    - `DockerStatusCard.tsx`, `HealthStatusCard.tsx` show system state
    - `RepoSelector.tsx` binds UI to `corpus_id`
    - `RAGTab.tsx`, `GrafanaTab.tsx`, `AdminTab.tsx` orchestrate panels using typed hooks
