# Figure chunks: multimodal ingestion Phase 1 — design

Date: 2026-08-29 · Status: approved design, awaiting implementation plan
Research basis: `docs/exec-plans/active/multimodal-schematics-research-2026-08-29.md`

## 1. Goal

Figures, charts, drawings and tables inside rich documents become retrievable and citable. A
question answerable only from a figure in the `nasa-apollo-11` mission report must retrieve the
chunk that describes that figure, and the viewer must box the figure on its page. Today figures
contribute no text to retrieval at all.

Non-goals for this phase: page-image (ColPali-class) retrieval, region-restricted title-block
OCR for scanned schematics, a schematic component graph. Those are Phases 2 and 3 of the
research note and build on the chunk metadata this phase produces.

## 2. Decisions taken

| Decision | Choice | Why |
|---|---|---|
| Target corpus | `nasa-apollo-11` (already indexed, has figures/tables) | Fastest honest verdict; schematic scans come next |
| Figure text | Structured JSON + prose summary from one vision call | Prose for embeddings; JSON for callout search, badges, and Phase 3's graph |
| Vision route | Own alias `indexing.figures.vision_model`, default `z-ai.glm-5.3-flash`; operator may point at any vision-capable alias; if unavailable in an environment, the best Gemini in the catalog (`google.gemini-3.7-flash` today) | Catalog marks GLM-5.3-Flash vision-capable at $0.075/M input tokens; operator preference |
| Architecture | Annotate inside Docling and ride the existing markdown → source map → provenance path | No new chunk kind, no second lane; ~200 lines |

## 3. Architecture

```
PDF/DOCX/PPTX/HTML ──Docling convert──▶ DoclingDocument
                                          │  do_picture_classification (local model)
                                          │  do_picture_description ──▶ LiteLLM gateway ──▶ vision alias
                                          ▼
                     RagweldPictureSerializer (markdown) ──▶ full text with figure blocks in place
                                          │
                     _build_source_map (unchanged) ──▶ SourceSpan(page, bbox, figure=JSON)
                                          │
                     chunker ──▶ stamp_provenance ──▶ Chunk(provenance.regions, metadata.figure)
                                          │
                     embed / BM25 / Neo4j lexical graph (unchanged) ──▶ viewer boxes the figure
```

Everything below the serializer is existing code. The serializer is the only new seam.

## 4. Components

### 4.1 Config — `IndexingFiguresConfig` (new Pydantic section, composed as `TriBridConfig.indexing.figures`)

| Field | Type / default | Meaning |
|---|---|---|
| `enabled` | `bool = False` | Master switch; per-corpus via the existing scoped config |
| `describe` | `bool = True` | Call the vision alias for a description |
| `classify` | `bool = True` | Docling's local figure classifier (chart/diagram/logo/photo…) |
| `vision_model` | `str = "z-ai.glm-5.3-flash"` | Gateway alias; must be `supports_vision` in the catalog |
| `prompt_profile` | `Literal["technical_figure", "schematic"] = "technical_figure"` | Selects the prompt template |
| `images_scale` | `float = 2.0`, `ge=1.0, le=4.0` | Docling raster scale (2.0 ≈ 144 DPI) |
| `min_area_fraction` | `float = 0.02`, `ge=0, le=1` | Skip pictures smaller than this fraction of the page (icons, logos); maps to `picture_area_threshold` |
| `skip_classes` | `list[str] = ["logo", "signature", "icon"]` | Classifier classes never described; maps to `classification_deny` |
| `max_figures_per_file` | `int = 200`, `ge=0` | Hard cap per document; excess figures get caption-only text and a counted skip |
| `max_completion_tokens` | `int = 600`, `ge=64, le=4000` | Per-figure output budget |
| `concurrency` | `int = 4`, `ge=1, le=16` | Parallel vision calls inside one Docling conversion |
| `timeout_s` | `int = 90`, `ge=5, le=600` | Per-call timeout |

Glossary entries for every field (`data/glossary.json` + `web/public/glossary.json` mirror);
`scripts/generate_types.py` regenerates `generated.ts`. `indexing.figures` is a real operator
tunable (cost, quality, model), so it belongs in config per the Pydantic-first rule; the prompt
templates and JSON schema are code, not config.

### 4.2 Extraction — `server/indexing/text_extractors.py`

- `_docling_converter()` becomes `_docling_converter(figures: IndexingFiguresConfig | None)`,
  building `PdfPipelineOptions` when `figures.enabled`: `generate_picture_images=True`,
  `images_scale`, `do_picture_classification=classify`, `do_picture_description=describe`,
  `enable_remote_services=True`, `picture_description_options=PictureDescriptionApiOptions(
  url=<gateway>/v1/chat/completions, headers={Authorization: Bearer <gateway key>},
  params={"model": vision_model, "max_completion_tokens": …, "response_format": {"type":
  "json_object"}}, prompt=<profile prompt>, timeout=timeout_s, concurrency=concurrency,
  picture_area_threshold=min_area_fraction, classification_deny=skip_classes)`. Gateway URL and
  key come from the existing LiteLLM config surface (`chat.litellm`) — no new secret.
- Converters are cached per options signature (one per distinct `figures` config), keeping the
  existing single-converter behaviour for the disabled case.
- `extract_text_for_path(..., figures=...)` threads the section through; the call site in
  `server/api/index.py` passes the corpus-scoped config. No other signature changes.

### 4.3 Serializer — `server/indexing/figure_serializer.py` (new)

`RagweldPictureSerializer(MarkdownPictureSerializer)`:
- For each `PictureItem`, reads its annotations: `PictureClassificationData` (class) and
  `DescriptionAnnotation` (the vision reply). Parses the reply as the JSON schema below; on
  parse failure treats the whole reply as `summary`.
- Emits markdown: a heading-free block `Figure (<class>): <caption>` / `<summary>` /
  `Labels: a, b, c` / `Values: …` / `References: …`, followed by Docling's image placeholder.
  Empty parts are omitted; a figure with no description and no caption emits nothing (as today).
- Records the parsed JSON in a `figures_by_ref: dict[str, FigureAnnotation]` on the serializer
  keyed by `item.self_ref`.
- Used for both the whole-document serialization and the per-item calls in
  `_build_source_map`, so positions stay consistent. `_build_source_map` attaches
  `serializer.figures_by_ref.get(item.self_ref)` to the item's `SourceSpan.figure`.

Vision reply schema (code constant, validated with a small Pydantic model
`FigureAnnotation` in `server/models/index.py` because it is persisted in chunk metadata):

```json
{"kind": "diagram|chart|schematic|photo|table|drawing|other",
 "summary": "dense prose, 2–6 sentences, what the figure shows and what it establishes",
 "labels": ["every legible callout, axis label, legend entry, part number"],
 "components": ["named parts/entities depicted"],
 "connections": ["A -> B relations stated or drawn"],
 "values": ["numbers with units as printed"],
 "references": ["sheet/figure/table/section cross-references printed on the figure"]}
```

Prompt profiles: `technical_figure` (charts, diagrams, photos in technical reports) and
`schematic` (adds drawing number, revision, sheet, connector/pin conventions, units). Both end
with "transcribe labels exactly; do not invent values; leave lists empty when nothing is visible".

### 4.4 Provenance — `server/indexing/provenance.py`, `server/models/index.py`

- `SourceSpan` gains `figure: FigureAnnotation | None = None`.
- `stamp_provenance` copies the figure of the first span whose region overlaps the chunk into
  `chunk.metadata["figure"]` (serialised model dump) and sets `chunk.metadata["chunk_kind"]
  = "figure"` when figure-block characters make up at least half of the chunk's text (a chunk
  that merely brushes a figure keeps the region but stays a text chunk). Text chunks are untouched.
- `ChunkMatch` (search response) already carries provenance; `metadata` passes through, so the
  UI can badge figure hits without a wire change.

### 4.5 Cost — index estimate

`_estimate_figure_description_cost_usd(cfg, total_pages, pictures)` in `server/api/index.py`:
`min(pictures, cap) × (image_tokens_per_figure + prompt_tokens) × input_price +
max_completion_tokens × output_price` using the catalog price for `vision_model`; `pictures`
is the real count when Docling has already parsed the file (cached conversion), else
`total_pages × 0.6` as the heuristic (labelled as such in `assumptions`). `IndexEstimate`
gains `figure_description_cost_usd: float | None` and `estimated_figures: int | None`;
`total_cost_usd` includes it. The Indexing tab's cost table shows the new line.

### 4.6 Run behaviour

- A corpus with `figures.enabled` whose `vision_model` is not routable through the gateway
  fails the run at start with a typed 409 (same shape as the existing index-contract errors),
  not per figure.
- Per-figure failures (timeout, non-JSON, HTTP error) degrade to caption-only text, are counted
  in the run summary (`figures_described`, `figures_failed`, `figures_skipped`) and surfaced in
  the Indexing tab and the run events. They never fail the run.
- Vision calls happen inside Docling's conversion, i.e. inside the existing serialised
  extraction lock; `concurrency` bounds parallel calls per document.

## 5. Data flow (one figure)

1. Docling lays out page 12, finds a picture at bbox B, rasterises it at `images_scale`.
2. Classifier says `diagram`; describer POSTs the PNG + profile prompt to the gateway alias;
   reply is JSON.
3. `RagweldPictureSerializer` emits `Figure (diagram): Figure 3-2. Lunar module ascent stage…`
   + summary + labels at the picture's position in the markdown; stores the JSON by `self_ref`.
4. `_build_source_map` finds that block in the full text → `SourceSpan(page=12, bbox=B,
   figure=JSON)`.
5. The chunker splits the markdown as today; the chunk containing the block gets
   `provenance.regions=[B]`, `metadata.figure=JSON`, `metadata.chunk_kind="figure"`.
6. Embedded (bge-small) and BM25-indexed like any chunk; Neo4j lexical graph unchanged.
7. A query hits the chunk; the viewer opens page 12 and boxes B; the UI shows a figure badge.

## 6. Error handling

| Failure | Behaviour |
|---|---|
| Alias not routable / not vision-capable | Run refused at start, typed error with the alias name |
| Gateway 4xx/5xx or timeout on one figure | Caption-only text; `figures_failed += 1`; run continues |
| Reply is not JSON | Whole reply used as `summary`; `labels` etc. empty; counted as described |
| Figure smaller than `min_area_fraction` or in `skip_classes` | Not sent; `figures_skipped += 1` |
| Over `max_figures_per_file` | Remaining figures caption-only; `figures_skipped += n` |
| Docling picture item without `prov` | Same as today: text kept, no region |

## 7. Testing (zero-mocked, per `.claude/rules/testing.md`)

All tests run on LXC100 in a throwaway worktree, never on the Mac.

1. **Serializer + provenance unit tests** (`tests/unit/test_figure_serializer.py`): convert a
   small real PDF fixture with two figures through Docling with remote services *off*, attach
   real `DescriptionAnnotation`/`PictureClassificationData` objects to the picture items,
   serialize with `RagweldPictureSerializer`, and assert: the figure block appears at the
   picture's position; `_build_source_map` yields a span with the picture's bbox and the parsed
   figure; `stamp_provenance` puts the JSON and `chunk_kind` on the right chunk; text chunks are
   byte-identical to today's output when `figures.enabled=False`.
2. **Config contract tests**: field constraints and defaults; `vision_model` validation against
   the catalog's `supports_vision`.
3. **Estimate tests**: cost line present only when enabled; heuristic vs exact figure counts.
4. **Gateway integration test** (`tests/integration/test_figure_description_live.py`): one real
   figure through the gateway alias; asserts the reply parses to the schema and the chunk
   carries it. Uses a real domain figure (Apollo), never a placeholder image.
5. **Eval**: a figure-targeted `eval_dataset` on `nasa-apollo-11` (questions answerable only from
   figures/tables, e.g. "what was the peak heat-shield temperature shown in the entry
   figure?"); run the existing eval lane before and after; the phase passes only if figure
   questions improve without regressing prose questions (nDCG@3 / Success@3).

## 8. Rollout

1. Land config + extraction + serializer + provenance + estimate with tests (one PR).
2. Deploy; set `indexing.figures.enabled=true` for `nasa-apollo-11` (corpus-scoped); re-index
   (flag the run in the lane note; a few hundred vision calls at GLM-5.3-Flash prices).
3. Run the figure eval; record results in the research note.
4. Only then consider `schematic` profile on the LM Systems Handbook corpus (Phase 1b), and
   Phases 2/3.

## 9. Open items deliberately deferred

- Tables: Docling's TableFormer markdown stays as-is; a vision pass over complex tables
  (Enginuity's finding) is a later toggle.
- Page-level rasterisation for degraded scans and region-restricted OCR: Phase 1b/2.
- Schematic graph in Neo4j: Phase 3, consumes `metadata.figure.connections`.
