# How advanced RAG engines handle legacy engineering schematics — research and a ragweld design (2026-08-29)

Operator ask: "research how advanced RAG engines do old NASA schematics, because that is what
we're supposed to do here." This note records what the current literature and shipped systems
actually do, what ragweld has today, and the design that follows. Sources are at the end.

## 1. What ragweld has today (measured, not assumed)

- **Chat input is multimodal**: `ImageAttachment`s → `chat.multimodal` limits → a vision alias
  (production `gpt-5.6-terra`); semantic cache bypasses on images.
- **Ingestion is layout-aware, text-only**: Docling `DocumentConverter()` with default options
  (layout, TableFormer tables, OCR) → `iterate_items()` → text chunks; page geometry is kept as
  `ChunkProvenance` and the viewer renders the page and boxes the cited region.
- **Retrieval is text-only**: `bge-small` dense + BM25 sparse (Qdrant generations) + Neo4j lexical
  graph (+ the new AST code graph for code corpora). No figure chunks, no picture descriptions, no
  image embeddings, no page-image leg. A figure in the Apollo mission report is retrievable only
  through whatever text sits near it.

## 2. What the evidence says

### 2.1 Page-image retrieval (ColPali family) is not the answer on its own for degraded legacy scans

- Los Alamos (DocEng '25) compared ColQwen2 (7B, ViDoRe SOTA at the time) against an OCR→text
  pipeline on **DocDeg**: 4,196 DOE/OSTI technical documents hand-labelled into four degradation
  levels. The OCR pipeline with a strong VLM OCR (Llama 3.2 90B) **won at every degradation level**
  — NDCG@5 0.547 vs 0.324 on clean digital pages, **0.487 vs 0.235 on severely degraded scans** —
  and even Nougat OCR beat ColQwen on levels 1–3. Multi-vector page retrieval was also slower at
  query time and did not generalise to unseen technical documents without fine-tuning.
- ViDoRe leaders keep improving (Nemotron ColEmbed V2 8B: 63.42 NDCG@10 on ViDoRe V3, CC BY 4.0;
  3B/4B/8B; ~773 vectors/page, 5.9 TB per 1M pages in fp16, 512-d projections keep ~96%), but the
  benchmarks are clean PDFs. Treat page-image late interaction as a **complementary leg**, gated
  by our own eval, not as the primary retriever.

### 2.2 The system that actually solved legacy engineering archives is layout-aware OCR + hybrid text retrieval

**BLUEPRINT** (Oak Ridge National Laboratory, Feb 2026) — 770k legacy engineering files (drawings,
schematics, policies, procedures; PDF/TIFF/CAD; inconsistent metadata; scans with skew and
bleed-through). Deployed pipeline:

1. **Modality router**: zero-shot CLIP "drawing vs document" + cheap heuristics (border strength,
   edge density, long straight lines, CAD extensions), fit with logistic regression → 97.7% recall.
2. **Vision path (drawings)**: YOLOv8-S detects the canonical regions of a drawing — *drawing
   number, data/title block, parts list, revisions block* (89.5% mAP@0.5:0.95, 5 ms/image) → **VLM
   OCR restricted to those crops** (Llama-4, 8-bit) with field-aware prompts → schema-validated
   identifiers (DWG, part, facility, revision).
3. **Text path (documents)**: LLM classification (policy/procedure/other), EasyOCR with native text
   fallback, normalised text → Nemotron text embeddings.
4. **Unified index**: one vector space fusing the text embedding with a layout/region feature
   vector; **hybrid BM25 + dense** with per-query z-score fusion; a lightweight reranker that
   promotes region-consistent hits and penalises revision/modality mismatches.

Results on 375 expert queries (150 drawing-centric, 150 document-centric, 75 cross-modal):
nDCG@3 **0.626**, Success@3 **0.715**, vs the best full-page VLM baseline (Llama-4-Scout 17B)
0.519 / 0.607 — **+10 points absolute**, while being ~7× faster (9.5 s/file vs 64 s). The decisive
ablation: **full-page OCR is nearly useless on drawings** (Tesseract full-page nDCG@3 0.208) while
**region-restricted OCR** recovers 0.532 (predicted boxes) and 0.699 (oracle boxes) with VLM OCR.
Their stated future work: relation graphs between components and cross-document linkage.

### 2.3 Frontier VLMs still fail at the things schematics are made of

**Enginuity** (Jun 2026; U.S. military service manuals, 2,056 diagram–parts-table pairs, six
diagram types including wiring/electrical and hydraulic): GPT-5.2, Claude Opus 4.7, Gemma 4 and
Qwen3-VL-32B reach Recall@all 0.61–0.87 on identifying called-out parts but **Token F1 of only
0.03–0.18** on describing them; consistent failures on callout→table grounding, domain vocabulary
(NSN/CAGE codes), connectivity tracing and cross-sheet references. Their working recipe: layout
analysis → figure↔table page mapping → **200 DPI rasterisation** → frontier VLM for structured
table extraction (98.7% item accuracy where conventional OCR was "unacceptable").

### 2.4 Granularity, hybrids and graphs (ACL 2026 survey)

- **Element-level retrieval** (tables, charts, figures, regions) beats page-level for questions
  that target a figure or table; page-level is cheaper for general comprehension.
- **Image+text hybrid** beats image-only; fuse with rank fusion (RRF/Borda) or confidence weights.
- **Graph-based enhancements** that work: layout graphs (spatial relations), entity graphs
  (cross-modal entity alignment), inter-page links — stored in a graph database.
- Open problems named explicitly: scanned/degraded documents with OCR errors, structured
  extraction of tables/charts/diagrams, cross-page and cross-document reasoning.
- **Region grounding** for late-interaction retrievers exists (patch→region relevance propagation
  over Docling-style blocks; +15–22% region F1, <50 ms/query) — i.e. a page-image leg can still
  hand the viewer a bounding box.

### 2.5 Tooling that fits the locked stack

- **Docling enrichments**: `do_picture_classification`, `do_picture_description` with
  `PictureDescriptionApiOptions(url=<OpenAI-compatible endpoint>)` — i.e. **our LiteLLM gateway
  and vision alias** — plus `generate_picture_images=True`, `images_scale`; descriptions land as
  `PictureItem` annotations and flow into chunking.
- **Qdrant** supports ColPali-style multivectors natively (`multivector_config`, MaxSim; binary
  quantisation + rescoring halves search time); the Visual RAG Toolkit adds training-free pooling
  and two-stage (pooled prefetch → full MaxSim) search, and supports **ColSmol-500M** for CPU
  deployments; ColSmol-256M scores 80.1 on ViDoRe v1 and runs on CPU/ONNX.
- VLM OCR for vintage scans: olmOCR (75.5% on olmOCR-Bench; ~$176 per million pages on an L40S)
  and Mistral OCR are the credible open/hosted options; both beat Marker/Tesseract on degraded
  typewritten pages.

## 3. What this means for ragweld (design)

The literature converges on a **hybrid, element-level, layout-aware** architecture; ragweld already
has the fusion, the Qdrant generations, the Neo4j lane, the provenance model and the viewer. The
missing pieces are ingestion-side.

### Phase 1 — figures and title blocks become first-class chunks (highest payoff, all locked stack)
- Docling `PdfPipelineOptions`: `generate_picture_images=True`, `images_scale=2` (≈200 DPI),
  `do_picture_classification=True`, `do_picture_description=True` via
  `PictureDescriptionApiOptions` pointed at LiteLLM's vision alias, with a **schematic-aware prompt**
  (component list, labels/callouts, connections, drawing number/sheet/revision, units).
- Each `PictureItem` → a **figure chunk**: description + OCR'd callouts, `ChunkProvenance` with
  page and bbox (the viewer already boxes regions), `kind=figure|table|drawing`.
- **Region-restricted OCR** for title blocks / drawing numbers / parts lists (BLUEPRINT's biggest
  single win): start with Docling layout blocks as the regions; a YOLO detector only if the
  Apollo corpus shows the blocks are missed.
- Cost control: the index estimate must count figures × vision calls (the estimator already
  itemises semantic-KG LLM cost; add a `figure_description` line).
- Config: `indexing.figures.{enabled, describe, classify, images_scale, prompt_profile}` — typed,
  per-corpus, off by default for code corpora.

### Phase 2 — a page-image leg, gated by our own eval
- Fourth retrieval leg: ColSmol-500M (CPU, ONNX) multivectors in a Qdrant multivector generation
  with pooled prefetch + MaxSim rescoring; fused through the existing RRF with its own weight.
  Upgrade path to Nemotron ColEmbed if a GPU appears. Keep it **off** unless the eval below shows
  it lifts drawing-centric queries — the LANL result says it may not on degraded scans.
- Patch→region grounding to feed the viewer a bbox for image-leg hits.

### Phase 3 — schematic graph in Neo4j
- From the structured figure descriptions, extract *component → connection → sheet/cross-ref*
  relations into the GraphRAG contract (entity types `component`, `signal`, `sheet`; relations
  `connects_to`, `references_sheet`, `part_of`), anchored IN_CHUNK exactly like the code graph.
  This is BLUEPRINT's stated future work and the survey's graph-based enhancement; ragweld already
  has the write path and the entity-mode graph leg.

### Eval first (non-negotiable per repo rules)
- Corpus: Apollo **LM Systems Handbook LM-5..LM-9** (29 MB, 1969, scanned schematics, ALSJ), the
  **LEM GN&C Study Guide** (panel diagrams) and the **AOH LM-10 Vol I** — real, public, degraded.
- Queries: BLUEPRINT's split — drawing-centric ("which breaker feeds the S-band transceiver"),
  document-centric, cross-modal ("procedure and the schematic it references"); graded 0/1/2.
- Metrics: nDCG@3 / Success@3 (BLUEPRINT), plus degradation buckets (DocDeg levels 0–3).
- Baseline is today's text-only pipeline; each phase must beat it on drawing-centric queries.

### Hardware note
pve1 has only an Intel Iris Xe iGPU (no NVIDIA); LXC100 is 16 vCPU / 24 GiB, CPU-only. Phase 1 needs no local model (vision calls go through the gateway). Phase 2
is CPU-feasible only with ColSmol-class models; anything ColQwen/Nemotron-sized needs a GPU.

## Sources

- BLUEPRINT — Rebuilding a Legacy: Multimodal Retrieval for Complex Engineering Drawings and Documents (ORNL, Feb 2026): https://arxiv.org/abs/2602.13345
- Lost in OCR Translation? Vision-Based Approaches to Robust Document Retrieval (LANL, DocEng '25): https://arxiv.org/abs/2505.05666
- Enginuity: A Dataset and Benchmark for Vision-Language Understanding of Engineering Diagrams (Jun 2026): https://arxiv.org/abs/2606.03410
- Scaling Beyond Context: A Survey of Multimodal RAG for Document Understanding (ACL 2026): https://arxiv.org/abs/2510.15253
- Spatially-Grounded Document Retrieval via Patch-to-Region Relevance Propagation: https://arxiv.org/abs/2512.02660
- Nemotron ColEmbed V2 (ViDoRe V3 leader, Feb 2026): https://arxiv.org/abs/2602.03992
- Visual RAG Toolkit: training-free pooling and multi-stage search: https://arxiv.org/abs/2602.12510
- ColPali (ICLR 2025): https://arxiv.org/abs/2407.01449 · ColSmol-500M / 256M: https://huggingface.co/vidore/colSmol-500M
- Qdrant + ColPali: https://qdrant.tech/blog/qdrant-colpali/ · Multi-vector search: https://qdrant.tech/course/multi-vector-search/module-1/multi-vector-in-qdrant/
- Docling enrichments (picture classification/description, remote API options): https://docling-project.github.io/docling/usage/enrichments/
- olmOCR (AI2): https://arxiv.org/abs/2502.18443 · olmOCR 2: https://arxiv.org/abs/2510.19817 · Mistral OCR: https://mistral.ai/news/mistral-ocr/
- Apollo Lunar Module documentation with scanned schematics (ALSJ): https://www.apollojournals.org/alsj/alsj-LMdocs.html · NASA NTRS: https://ntrs.nasa.gov/
