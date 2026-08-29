# Figure Chunks (Multimodal Ingestion Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Figures, charts and drawings inside Docling-converted documents become retrievable, citable chunks with structured metadata and a viewer-boxable region, driven by a per-corpus config section and a vision alias through the LiteLLM gateway.

**Architecture:** Docling's own picture classification and API-based picture description are switched on from a new `indexing.figures` config section; a ragweld picture serializer renders each described figure as prose at its position in the markdown and keeps the structured JSON aside; the existing source map → chunker → `stamp_provenance` path then produces figure chunks with page/bbox provenance and `metadata.figure`, with no new chunk kind and no retrieval changes.

**Tech Stack:** Python 3.12, Pydantic v2, Docling 2.81 / docling-core 2.70 (`PdfPipelineOptions`, `PictureDescriptionApiOptions`, `MarkdownDocSerializer`), LiteLLM gateway (OpenAI-compatible `/chat/completions`), pypdfium2, pytest, FastAPI, React/TypeScript (`generated.ts`).

**Spec:** `docs/superpowers/specs/2026-08-29-figure-chunks-design.md` (research: `docs/exec-plans/active/multimodal-schematics-research-2026-08-29.md`)

## Global Constraints

- **Execution location (CLAUDE.md hard rule):** no tests, builds, Docling, models or services on the Mac. Every `pytest`, `ruff`, `generate_types.py`, `validate_types.py`, `check_banned.py` in this plan runs on LXC100 in a throwaway worktree: `su -s /bin/bash ragweld -c "git -C /opt/ragweld fetch --quiet origin main && git -C /opt/ragweld worktree add --detach /tmp/fable-figs origin/main"`, edited files copied in, `cd /tmp/fable-figs && PYTHONPATH=/tmp/fable-figs /opt/ragweld/.venv/bin/python -m pytest …`. Create the worktree **as `ragweld`** (root-created ones cannot be removed by the service user). Commits are made from a Mac worktree off `origin/main` and pushed; the Mac checkout is source-editing only.
- **Coordination:** before touching `server/api/index.py` or `server/indexing/text_extractors.py`, append a dated lane entry to `~/.codex/projects/-Users-davidmontgomery-ragweld/memory/agent-lanes-2026-08-29.md`; grep that file for `INDEX RUN ACTIVE` and check every corpus's `runs/latest.status` before any `systemctl restart ragweld.service`.
- **Zero-mocked tests** (`.claude/rules/testing.md`): no `monkeypatch`, `unittest.mock`, Playwright route interception. Real Docling objects, real PDFs, real gateway calls for the integration test. Real Apollo questions in evals — never `test`/`hello`.
- **Pydantic first:** new tunables are `Field`s with constraints in `server/models/tribrid_config_model.py`; every field gets a glossary term in `data/glossary.json` **and** the byte-identical mirror `web/public/glossary.json`; `uv run scripts/generate_types.py` regenerates `web/src/types/generated.ts`; `uv run scripts/validate_types.py` must pass.
- **Defaults from the spec:** `enabled=False`, `describe=True`, `classify=True`, `vision_model="z-ai.glm-5.3-flash"`, `prompt_profile="technical_figure"`, `images_scale=2.0` (1.0–4.0), `min_area_fraction=0.02` (0–1), `skip_classes=["logo","signature","icon"]`, `max_figures_per_file=200` (≥0), `max_completion_tokens=600` (64–4000), `concurrency=4` (1–16), `timeout_s=90` (5–600).
- **Scope:** PDF (and image) inputs only in this phase — Docling's enrichment pipeline options apply to the PDF pipeline; DOCX/PPTX/HTML keep today's text-only conversion.
- **Commits:** conventional commits, one per task, with the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.

---

## File map

| File | Responsibility |
|---|---|
| `server/models/tribrid_config_model.py` | `IndexingFiguresConfig` section; `figures` field on `IndexingConfig` |
| `server/models/index.py` | `FigureAnnotation` (persisted in chunk metadata); `IndexEstimate` figure fields |
| `server/indexing/figure_prompts.py` (new) | Prompt profiles and the JSON reply schema as code constants; `parse_figure_reply` |
| `server/indexing/figure_serializer.py` (new) | `RagweldPictureSerializer`: figure block markdown + `figures_by_ref` |
| `server/indexing/text_extractors.py` | Converter options from config; `SourceSpan.figure`; figure counters on `ExtractedDocument` |
| `server/indexing/provenance.py` | `stamp_provenance` copies figure metadata and `chunk_kind` |
| `server/api/index.py` | Threads the corpus-scoped `figures` config into extraction; alias validation at run start; figure counters in run log; estimate cost line |
| `web/src/components/RAG/IndexingSubtab.tsx` | Figure cost line in the estimate summary |
| `data/glossary.json`, `web/public/glossary.json` | Terms for the new fields |
| `tests/fixtures/pdf_builder.py`, `tests/fixtures/acceptance_corpus_docs/apollo11_figure_pages.pdf` (new) | Real two-page Apollo figure fixture |
| `tests/unit/test_indexing_figures_config.py`, `tests/unit/test_figure_prompts.py`, `tests/unit/test_figure_serializer.py`, `tests/unit/test_figure_provenance.py`, `tests/unit/test_figure_extraction_options.py`, `tests/unit/test_index_estimate_figures.py` (new) | Unit tests |
| `tests/integration/test_figure_description_live.py` (new) | One real figure through the gateway alias on LXC100 |
| `data/eval_datasets/nasa-apollo-11-figures.json` (new, via the eval lane's own format) | Figure-targeted eval set |

---

### Task 0: Lane coordination and LXC100 test worktree

**Files:**
- Modify: `~/.codex/projects/-Users-davidmontgomery-ragweld/memory/agent-lanes-2026-08-29.md` (append)

**Interfaces:**
- Produces: the throwaway worktree `/tmp/fable-figs` on LXC100 used by every later "Run:" step.

- [ ] **Step 1: Announce the lane**

Append to the lane note:

```
## Fable-1 <HH:MM> UTC — figure chunks (Phase 1) starting
Files I will edit: server/models/tribrid_config_model.py (new IndexingFiguresConfig only),
server/models/index.py (FigureAnnotation, IndexEstimate fields), server/indexing/text_extractors.py,
server/indexing/provenance.py, server/api/index.py (extraction call site, estimate, run log),
web/src/components/RAG/IndexingSubtab.tsx (one cost line), glossary + mirror, new files under
server/indexing/figure_*.py and tests. Say here if you are in any of these.
```

- [ ] **Step 2: Create the LXC100 worktree as the service user**

Run (from the Mac):
```bash
ssh -i ~/.ssh/proxmox_portable_backup_ed25519 -o BatchMode=yes root@192.168.68.171 \
  "pct exec 100 -- su -s /bin/bash ragweld -c 'git -C /opt/ragweld fetch --quiet origin main && git -C /opt/ragweld worktree add --detach /tmp/fable-figs origin/main && cd /tmp/fable-figs && git rev-parse --short HEAD'"
```
Expected: prints the origin/main SHA; `/tmp/fable-figs` exists and is owned by `ragweld`.

- [ ] **Step 3: Define the sync helper used by every later task**

Save on the Mac as `/private/tmp/claude-501/-Users-davidmontgomery-ragweld/160bcb83-5626-4925-af05-7639482a8b58/scratchpad/sync_figs.sh`:

```bash
#!/usr/bin/env bash
# usage: sync_figs.sh <mac-worktree> <relative paths...>   copies files into /tmp/fable-figs on LXC100
set -euo pipefail
WT="$1"; shift
K=~/.ssh/proxmox_portable_backup_ed25519; H=root@192.168.68.171
for rel in "$@"; do
  scp -q -i "$K" -o BatchMode=yes "$WT/$rel" "$H:/tmp/_sync_file"
  ssh -i "$K" -o BatchMode=yes "$H" "pct push 100 /tmp/_sync_file /tmp/_sync_file >/dev/null 2>&1; pct exec 100 -- bash -lc 'install -o ragweld -g ragweld -D /tmp/_sync_file /tmp/fable-figs/$rel'"
done
```

Run: `chmod +x sync_figs.sh` — Expected: no output.

- [ ] **Step 4: Create the Mac source worktree for this feature**

Run:
```bash
cd /Users/davidmontgomery/ragweld && git fetch --quiet origin main && \
git worktree add --detach /private/tmp/claude-501/-Users-davidmontgomery-ragweld/160bcb83-5626-4925-af05-7639482a8b58/scratchpad/wt-figs origin/main
```
Expected: `HEAD is now at <sha>`. All edits below happen in that worktree (`$WT`); commits are made there and pushed with `git push origin HEAD:main` after each task's LXC100 test run is green.

---

### Task 1: `IndexingFiguresConfig` section, glossary, generated types

**Files:**
- Modify: `server/models/tribrid_config_model.py` (add class before `class IndexingConfig(BaseModel):` at ~line 4399; add field inside `IndexingConfig`)
- Modify: `data/glossary.json`, `web/public/glossary.json`
- Modify (generated): `web/src/types/generated.ts`
- Test: `tests/unit/test_indexing_figures_config.py`

**Interfaces:**
- Produces: `IndexingFiguresConfig` with the fields/constraints listed in Global Constraints; `TriBridConfig().indexing.figures`; `ChunkFigurePromptProfile = Literal["technical_figure", "schematic"]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_indexing_figures_config.py
"""indexing.figures is a typed, per-corpus tunable with the spec's defaults and constraints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.models.tribrid_config_model import IndexingFiguresConfig, TriBridConfig

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_defaults_match_the_spec() -> None:
    f = TriBridConfig().indexing.figures
    assert f.enabled is False
    assert f.describe is True and f.classify is True
    assert f.vision_model == "z-ai.glm-5.3-flash"
    assert f.prompt_profile == "technical_figure"
    assert f.images_scale == 2.0
    assert f.min_area_fraction == 0.02
    assert f.skip_classes == ["logo", "signature", "icon"]
    assert f.max_figures_per_file == 200
    assert f.max_completion_tokens == 600
    assert f.concurrency == 4
    assert f.timeout_s == 90


@pytest.mark.parametrize(
    "field, bad",
    [
        ("images_scale", 0.5), ("images_scale", 4.5),
        ("min_area_fraction", -0.1), ("min_area_fraction", 1.5),
        ("max_figures_per_file", -1),
        ("max_completion_tokens", 10), ("max_completion_tokens", 5000),
        ("concurrency", 0), ("concurrency", 17),
        ("timeout_s", 1), ("timeout_s", 601),
        ("prompt_profile", "poetry"),
    ],
)
def test_constraints_are_contract(field: str, bad: object) -> None:
    with pytest.raises(ValidationError):
        IndexingFiguresConfig(**{field: bad})


def test_round_trips_through_json_and_scoped_merge() -> None:
    cfg = TriBridConfig()
    payload = cfg.model_dump(mode="json")
    payload["indexing"]["figures"]["enabled"] = True
    payload["indexing"]["figures"]["vision_model"] = "google.gemini-3.7-flash"
    again = TriBridConfig.model_validate(payload)
    assert again.indexing.figures.enabled is True
    assert again.indexing.figures.vision_model == "google.gemini-3.7-flash"


def test_every_field_has_a_glossary_term_in_both_copies() -> None:
    keys = {f"FIGURES_{name.upper()}" for name in IndexingFiguresConfig.model_fields}
    for rel in ("data/glossary.json", "web/public/glossary.json"):
        terms = {t.get("key") for t in json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))["terms"]}
        missing = sorted(keys - terms)
        assert not missing, f"{rel} lacks glossary terms: {missing}"
    assert (REPO_ROOT / "data/glossary.json").read_bytes() == (REPO_ROOT / "web/public/glossary.json").read_bytes()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./sync_figs.sh $WT tests/unit/test_indexing_figures_config.py && ssh … "pct exec 100 -- bash -lc 'cd /tmp/fable-figs && PYTHONPATH=/tmp/fable-figs /opt/ragweld/.venv/bin/python -m pytest -q --no-cov -p no:cacheprovider tests/unit/test_indexing_figures_config.py'"`
Expected: FAIL — `ImportError: cannot import name 'IndexingFiguresConfig'`.

- [ ] **Step 3: Add the config section**

In `server/models/tribrid_config_model.py`, immediately before `class IndexingConfig(BaseModel):`:

```python
ChunkFigurePromptProfile = Literal["technical_figure", "schematic"]


class IndexingFiguresConfig(BaseModel):
    """Figure/chart/drawing description during indexing (Docling picture enrichment via the gateway)."""

    enabled: bool = Field(
        default=False,
        description="Describe and classify figures inside Docling-converted PDFs so they become retrievable chunks",
    )
    describe: bool = Field(
        default=True,
        description="Send each figure to the vision alias for a structured description",
    )
    classify: bool = Field(
        default=True,
        description="Run Docling's local figure classifier (chart, diagram, logo, photo) before describing",
    )
    vision_model: str = Field(
        default="z-ai.glm-5.3-flash",
        description="Gateway alias used to describe figures; must be vision-capable in the model catalog",
    )
    prompt_profile: ChunkFigurePromptProfile = Field(
        default="technical_figure",
        description="Prompt template for figure descriptions: technical figures or engineering schematics",
    )
    images_scale: float = Field(
        default=2.0,
        ge=1.0,
        le=4.0,
        description="Docling raster scale for figure crops (2.0 is about 144 DPI)",
    )
    min_area_fraction: float = Field(
        default=0.02,
        ge=0.0,
        le=1.0,
        description="Skip figures smaller than this fraction of the page area (icons, logos)",
    )
    skip_classes: list[str] = Field(
        default_factory=lambda: ["logo", "signature", "icon"],
        description="Classifier classes that are never sent for description",
    )
    max_figures_per_file: int = Field(
        default=200,
        ge=0,
        description="Cap on described figures per document; the rest keep caption-only text",
    )
    max_completion_tokens: int = Field(
        default=600,
        ge=64,
        le=4000,
        description="Output token budget per figure description",
    )
    concurrency: int = Field(
        default=4,
        ge=1,
        le=16,
        description="Parallel vision calls while converting one document",
    )
    timeout_s: int = Field(
        default=90,
        ge=5,
        le=600,
        description="Per-figure vision call timeout in seconds",
    )
```

Inside `IndexingConfig`, after the last existing field (`estimated_tokens_per_second_local`), add:

```python
    figures: IndexingFiguresConfig = Field(default_factory=IndexingFiguresConfig)
```

- [ ] **Step 4: Add the eleven glossary terms and mirror the file**

Run (on the Mac, source editing) from `$WT`:

```bash
/Users/davidmontgomery/ragweld/.venv/bin/python - <<'EOF'
import json, shutil
from pathlib import Path
g = Path("data/glossary.json"); data = json.loads(g.read_text(encoding="utf-8")); terms = data["terms"]
template = next(t for t in terms if t.get("key") == "BUILD_CODE_GRAPH")
defs = {
 "ENABLED": ("Figures Enabled", "Turns on figure/chart/drawing description during indexing for this corpus. Docling detects picture regions on each page, optionally classifies them, and sends each one to the configured vision alias; the description becomes a retrievable chunk anchored to the figure's page and bounding box so citations can box it in the viewer. Off by default because it spends vision calls; the index estimate shows the cost before a run."),
 "DESCRIBE": ("Figures Describe", "Whether each detected figure is sent to the vision alias for a structured description (summary, labels, components, connections, values, references). Turn off to keep only captions and classification."),
 "CLASSIFY": ("Figures Classify", "Runs Docling's local figure classifier before description so logos, signatures and icons can be skipped and the figure kind (chart, diagram, photo) is recorded on the chunk."),
 "VISION_MODEL": ("Figures Vision Model", "Gateway alias that describes figures at index time. Must be a catalog alias flagged as vision-capable; the run refuses to start otherwise. Defaults to the cheap GLM 5.3 Flash alias; point hard scanned schematics at a stronger vision model per corpus."),
 "PROMPT_PROFILE": ("Figures Prompt Profile", "Prompt template for figure descriptions. 'technical_figure' covers charts, diagrams and photos in reports; 'schematic' adds drawing number, sheet, revision, connector and unit conventions for engineering drawings."),
 "IMAGES_SCALE": ("Figures Image Scale", "Raster scale Docling uses for figure crops sent to the vision model (1.0 = 72 DPI; 2.0 ≈ 144 DPI). Higher reads small callouts better at higher token cost."),
 "MIN_AREA_FRACTION": ("Figures Min Area Fraction", "Figures smaller than this fraction of the page area are not described (icons, logos, decorative marks)."),
 "SKIP_CLASSES": ("Figures Skip Classes", "Classifier classes that are never described, e.g. logo, signature, icon."),
 "MAX_FIGURES_PER_FILE": ("Figures Max Per File", "Hard cap on described figures per document; figures beyond the cap keep caption-only text and are counted as skipped in the run summary."),
 "MAX_COMPLETION_TOKENS": ("Figures Max Completion Tokens", "Output token budget for one figure description."),
 "CONCURRENCY": ("Figures Concurrency", "How many vision calls run in parallel while converting one document."),
 "TIMEOUT_S": ("Figures Timeout", "Seconds to wait for one vision call before the figure falls back to caption-only text."),
}
for suffix, (term, definition) in defs.items():
    key = f"FIGURES_{suffix}"
    if any(t.get("key") == key for t in terms):
        continue
    entry = {k: template[k] for k in template}
    entry.update({"term": term, "key": key, "definition": definition, "related": ["FIGURES_ENABLED"] if suffix != "ENABLED" else ["FIGURES_VISION_MODEL", "FIGURES_PROMPT_PROFILE"], "links": [], "badges": [], "category": "indexing"})
    terms.append(entry)
g.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
shutil.copyfile(g, "web/public/glossary.json"); print("glossary updated + mirrored")
EOF
```

- [ ] **Step 5: Regenerate and validate types on LXC100**

Run: sync `server/models/tribrid_config_model.py data/glossary.json web/public/glossary.json` then on LXC100 in `/tmp/fable-figs`: `PYTHONPATH=/tmp/fable-figs /opt/ragweld/.venv/bin/python scripts/generate_types.py && PYTHONPATH=/tmp/fable-figs /opt/ragweld/.venv/bin/python scripts/validate_types.py`
Expected: `✓ Types are in sync`. Copy the regenerated `web/src/types/generated.ts` back into `$WT` (`pct pull 100 /tmp/fable-figs/web/src/types/generated.ts /tmp/generated.ts` then `scp`).

- [ ] **Step 6: Run the tests to verify they pass**

Run: the Step 2 command.
Expected: 15 passed.

- [ ] **Step 7: Commit and push**

```bash
cd $WT && git add server/models/tribrid_config_model.py data/glossary.json web/public/glossary.json web/src/types/generated.ts tests/unit/test_indexing_figures_config.py
git commit -m "feat(config): add indexing.figures section for figure description at index time

Per-corpus tunables for Docling picture enrichment through the gateway: enabled,
describe, classify, vision_model (default z-ai.glm-5.3-flash), prompt_profile,
images_scale, min_area_fraction, skip_classes, max_figures_per_file,
max_completion_tokens, concurrency, timeout_s. Glossary terms and generated types.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git fetch origin main && git rebase origin/main && git push origin HEAD:main
```

---

### Task 2: `FigureAnnotation` model, prompt profiles and reply parser

**Files:**
- Modify: `server/models/index.py` (add `FigureAnnotation` next to `ChunkProvenance`)
- Create: `server/indexing/figure_prompts.py`
- Test: `tests/unit/test_figure_prompts.py`

**Interfaces:**
- Produces: `FigureAnnotation(kind: Literal[...]="other", summary: str, labels: list[str], components: list[str], connections: list[str], values: list[str], references: list[str])`; `FIGURE_PROMPTS: dict[str, str]` keyed by profile; `parse_figure_reply(text: str) -> FigureAnnotation` (never raises; non-JSON → summary=text); `figure_block_markdown(caption: str, cls: str | None, fig: FigureAnnotation | None) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_figure_prompts.py
"""Vision replies parse into FigureAnnotation; malformed replies degrade, never raise."""

from __future__ import annotations

import json

from server.indexing.figure_prompts import FIGURE_PROMPTS, figure_block_markdown, parse_figure_reply
from server.models.index import FigureAnnotation


def test_prompts_exist_for_both_profiles_and_forbid_invention() -> None:
    assert set(FIGURE_PROMPTS) == {"technical_figure", "schematic"}
    for text in FIGURE_PROMPTS.values():
        assert "JSON" in text and "do not invent" in text.lower()
        for key in ("summary", "labels", "components", "connections", "values", "references", "kind"):
            assert f'"{key}"' in text
    assert "drawing number" in FIGURE_PROMPTS["schematic"].lower()


def test_parse_valid_reply() -> None:
    reply = json.dumps({
        "kind": "chart",
        "summary": "Command module cabin pressure during entry, falling from 5.0 to 4.6 psia.",
        "labels": ["CABIN PRESSURE, PSIA", "TIME, SEC"],
        "components": [], "connections": [],
        "values": ["5.0 psia", "4.6 psia"],
        "references": ["Figure 5-12"],
    })
    fig = parse_figure_reply(reply)
    assert fig.kind == "chart" and fig.values == ["5.0 psia", "4.6 psia"]
    assert fig.references == ["Figure 5-12"]


def test_parse_reply_wrapped_in_fences_and_unknown_kind() -> None:
    fig = parse_figure_reply('```json\n{"kind": "hologram", "summary": "x", "labels": ["A"]}\n```')
    assert fig.kind == "other" and fig.summary == "x" and fig.labels == ["A"]


def test_non_json_reply_becomes_summary() -> None:
    fig = parse_figure_reply("A photograph of the lunar module ascent stage on the pad.")
    assert fig.summary == "A photograph of the lunar module ascent stage on the pad."
    assert fig.labels == [] and fig.kind == "other"


def test_empty_reply_is_empty_annotation() -> None:
    assert parse_figure_reply("") == FigureAnnotation()


def test_block_markdown_is_prose_only_and_omits_empty_parts() -> None:
    fig = FigureAnnotation(kind="diagram", summary="Fuel cell flow.", labels=["H2", "O2"], values=[])
    block = figure_block_markdown("Figure 4-1. Fuel cell", "diagram", fig)
    assert block.startswith("Figure (diagram): Figure 4-1. Fuel cell")
    assert "Fuel cell flow." in block and "Labels: H2, O2" in block
    assert "Values:" not in block and "{" not in block
    assert figure_block_markdown("", None, None) == ""
    assert figure_block_markdown("Figure 2", None, None) == "Figure: Figure 2"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: sync the test and `pytest -q tests/unit/test_figure_prompts.py` on LXC100.
Expected: FAIL — `ModuleNotFoundError: server.indexing.figure_prompts`.

- [ ] **Step 3: Add `FigureAnnotation` to `server/models/index.py`**

Directly after `class ChunkProvenance(BaseModel):` block:

```python
FigureKind = Literal["diagram", "chart", "schematic", "photo", "table", "drawing", "other"]


class FigureAnnotation(BaseModel):
    """Structured description of one figure, produced by the vision alias at index time.

    Persisted in ``Chunk.metadata["figure"]`` so callouts and part numbers are searchable
    verbatim and a later schematic graph can consume ``components``/``connections``.
    """

    kind: FigureKind = Field(default="other", description="Figure kind as judged by the vision model")
    summary: str = Field(default="", description="Dense prose description; this is what gets embedded")
    labels: list[str] = Field(default_factory=list, description="Legible callouts, axis labels, legend entries, part numbers")
    components: list[str] = Field(default_factory=list, description="Named parts or entities depicted")
    connections: list[str] = Field(default_factory=list, description="'A -> B' relations stated or drawn")
    values: list[str] = Field(default_factory=list, description="Numbers with units as printed")
    references: list[str] = Field(default_factory=list, description="Sheet/figure/table/section cross-references printed on the figure")
```

(`Literal` and `Field` are already imported in that module.)

- [ ] **Step 4: Create `server/indexing/figure_prompts.py`**

```python
"""Prompt profiles and reply parsing for figure description at index time.

The prompts and the reply schema are code, not configuration: they are protocol invariants
between ragweld and the vision alias. Operators choose a profile via
``indexing.figures.prompt_profile``.
"""

from __future__ import annotations

import json
import re
from typing import Any, get_args

from server.models.index import FigureAnnotation, FigureKind

_SCHEMA = (
    'Return ONLY a JSON object with these keys: "kind" (one of diagram, chart, schematic, photo, '
    'table, drawing, other), "summary" (2-6 sentences of dense prose: what the figure shows and '
    'what it establishes), "labels" (every legible callout, axis label, legend entry or part number, '
    'transcribed exactly), "components" (named parts or entities depicted), "connections" '
    '("A -> B" relations that are drawn or stated), "values" (numbers with units exactly as printed), '
    '"references" (sheet, figure, table or section cross-references printed on the figure). '
    "Transcribe text exactly; do not invent values; leave a list empty when nothing is visible."
)

FIGURE_PROMPTS: dict[str, str] = {
    "technical_figure": (
        "You are describing one figure from a technical report so that an engineer can find it by "
        "searching for what it shows. " + _SCHEMA
    ),
    "schematic": (
        "You are describing one engineering drawing or schematic (electrical, hydraulic, mechanical, "
        "panel layout). Read the title block: put the drawing number, sheet, and revision into "
        '"references"; put connector, pin, signal and part designators into "labels"; put every '
        'drawn connection into "connections" as "A -> B"; keep units exactly as printed. ' + _SCHEMA
    ),
}

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_VALID_KINDS: frozenset[str] = frozenset(get_args(FigureKind))


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def parse_figure_reply(text: str) -> FigureAnnotation:
    """Parse a vision reply into a FigureAnnotation; anything unparseable becomes the summary."""
    raw = (text or "").strip()
    if not raw:
        return FigureAnnotation()
    candidate = raw
    m = _FENCE_RE.search(raw)
    if m:
        candidate = m.group(1)
    elif not raw.startswith("{"):
        start, end = raw.find("{"), raw.rfind("}")
        candidate = raw[start : end + 1] if start >= 0 and end > start else ""
    data: Any = None
    if candidate:
        try:
            data = json.loads(candidate)
        except ValueError:
            data = None
    if not isinstance(data, dict):
        return FigureAnnotation(summary=raw)
    kind = str(data.get("kind") or "other").strip().lower()
    return FigureAnnotation(
        kind=kind if kind in _VALID_KINDS else "other",  # type: ignore[arg-type]
        summary=str(data.get("summary") or "").strip(),
        labels=_string_list(data.get("labels")),
        components=_string_list(data.get("components")),
        connections=_string_list(data.get("connections")),
        values=_string_list(data.get("values")),
        references=_string_list(data.get("references")),
    )


def figure_block_markdown(caption: str, cls: str | None, fig: FigureAnnotation | None) -> str:
    """Prose-only markdown for one figure; the JSON never enters the embedded text."""
    caption = (caption or "").strip()
    head = f"Figure ({cls}): {caption}" if cls else f"Figure: {caption}"
    if not caption and (fig is None or not fig.summary):
        return ""
    parts: list[str] = [head.rstrip(": ").rstrip()]
    if fig is not None:
        if fig.summary:
            parts.append(fig.summary.strip())
        for name, items in (("Labels", fig.labels), ("Components", fig.components), ("Connections", fig.connections), ("Values", fig.values), ("References", fig.references)):
            if items:
                parts.append(f"{name}: " + ", ".join(items))
    return "\n".join(parts)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: sync `server/models/index.py server/indexing/figure_prompts.py` + test; `pytest -q tests/unit/test_figure_prompts.py`.
Expected: 6 passed.

- [ ] **Step 6: Commit and push**

```bash
git add server/models/index.py server/indexing/figure_prompts.py tests/unit/test_figure_prompts.py
git commit -m "feat(indexing): FigureAnnotation model, figure prompt profiles and reply parser

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git fetch origin main && git rebase origin/main && git push origin HEAD:main
```

---

### Task 3: Real Apollo figure fixture

**Files:**
- Create: `tests/fixtures/acceptance_corpus_docs/apollo11_figure_pages.pdf`
- Modify: `tests/fixtures/pdf_builder.py` (add `APOLLO_FIGURE_FIXTURE` path constant and `apollo_figure_pages()` reader)

**Interfaces:**
- Produces: a ≤ 1.5 MB two-page PDF cut from `A11_MissionReport.pdf` where Docling's layout model yields at least one `PictureItem` with `prov`; `apollo_figure_pages() -> Path`.

- [ ] **Step 1: Find two consecutive pages Docling sees as containing a picture (on LXC100)**

Run on LXC100 (`/tmp/fable-figs`, service venv):

```python
# /tmp/find_figure_pages.py
import sys
import pypdfium2 as pdfium
from docling.document_converter import DocumentConverter
from docling_core.types.doc import PictureItem

src = "/srv/ragweld/corpora/nasa-apollo-11/A11_MissionReport.pdf"
pdf = pdfium.PdfDocument(src)
conv = DocumentConverter()
for start in range(20, 120, 2):  # skip front matter; probe pairs of pages
    out = pdfium.PdfDocument.new()
    out.import_pages(pdf, [start, start + 1])
    out.save("/tmp/_probe.pdf")
    doc = conv.convert("/tmp/_probe.pdf").document
    pics = [p for p, _ in doc.iterate_items() if isinstance(p, PictureItem) and p.prov]
    if pics:
        print("pages", start + 1, start + 2, "pictures", len(pics), "bbox", pics[0].prov[0].bbox)
        break
```
Run: `PYTHONPATH=/tmp/fable-figs /opt/ragweld/.venv/bin/python /tmp/find_figure_pages.py`
Expected: one line naming a page pair and ≥1 picture. If the first probe finds nothing before page 120, widen the range to 300 and rerun.

- [ ] **Step 2: Cut the fixture and check its size**

Run on LXC100 (replace `P` with the 0-based start page from Step 1):
```bash
/opt/ragweld/.venv/bin/python - <<'EOF'
import pypdfium2 as pdfium
P = <start-index>
pdf = pdfium.PdfDocument("/srv/ragweld/corpora/nasa-apollo-11/A11_MissionReport.pdf")
out = pdfium.PdfDocument.new(); out.import_pages(pdf, [P, P + 1]); out.save("/tmp/apollo11_figure_pages.pdf")
EOF
ls -la /tmp/apollo11_figure_pages.pdf
```
Expected: file under 1.5 MB (scanned pages at the report's native resolution are ~150–400 KB each). Pull it to the Mac worktree: `pct pull 100 /tmp/apollo11_figure_pages.pdf /tmp/apollo11_figure_pages.pdf` then `scp` into `$WT/tests/fixtures/acceptance_corpus_docs/apollo11_figure_pages.pdf`.

- [ ] **Step 3: Add the fixture accessor**

Append to `tests/fixtures/pdf_builder.py`:

```python
# Two consecutive scanned pages of the Apollo 11 Mission Report (NASA, public domain) on which
# Docling's layout model detects at least one figure. Used by the figure-chunk tests.
APOLLO_FIGURE_FIXTURE = Path(__file__).resolve().parent / "acceptance_corpus_docs" / "apollo11_figure_pages.pdf"


def apollo_figure_pages() -> Path:
    if not APOLLO_FIGURE_FIXTURE.exists():
        raise FileNotFoundError(f"missing fixture {APOLLO_FIGURE_FIXTURE}")
    return APOLLO_FIGURE_FIXTURE
```

- [ ] **Step 4: Commit and push**

```bash
git add tests/fixtures/pdf_builder.py tests/fixtures/acceptance_corpus_docs/apollo11_figure_pages.pdf
git commit -m "test(fixtures): two scanned Apollo 11 report pages with a detected figure

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git fetch origin main && git rebase origin/main && git push origin HEAD:main
```

---

### Task 4: `RagweldPictureSerializer`

**Files:**
- Create: `server/indexing/figure_serializer.py`
- Test: `tests/unit/test_figure_serializer.py`

**Interfaces:**
- Consumes: `parse_figure_reply`, `figure_block_markdown`, `FigureAnnotation` (Task 2); the fixture (Task 3).
- Produces: `RagweldPictureSerializer` (subclass of `docling_core.transforms.serializer.markdown.MarkdownPictureSerializer`) with `figures_by_ref: dict[str, FigureAnnotation]` and `classes_by_ref: dict[str, str]`; `make_markdown_serializer(doc) -> MarkdownDocSerializer` returning a doc serializer wired with one picture serializer instance (accessible as `serializer.picture_serializer`).

- [ ] **Step 1: Verify the docling-core API names on LXC100 before writing code**

Run: `PYTHONPATH=/tmp/fable-figs /opt/ragweld/.venv/bin/python -c "from docling_core.transforms.serializer.base import create_ser_result; from docling_core.transforms.serializer.markdown import MarkdownDocSerializer, MarkdownPictureSerializer, MarkdownParams; from docling_core.types.doc.document import DescriptionAnnotation, PictureClassificationData, PictureClassificationClass, PictureItem; print('ok')"`
Expected: `ok`. (If `create_ser_result` is missing, use `SerializationResult(text=..., spans=[...])` from `docling_core.transforms.serializer.base` — check `MarkdownPictureSerializer.serialize` in the installed source for the exact constructor and mirror it.)

- [ ] **Step 2: Write the failing tests**

```python
# tests/unit/test_figure_serializer.py
"""Described figures serialize as prose at the picture's position; JSON stays out of the text."""

from __future__ import annotations

import json

import pytest
from docling.document_converter import DocumentConverter
from docling_core.types.doc import PictureItem
from docling_core.types.doc.document import DescriptionAnnotation, PictureClassificationClass, PictureClassificationData

from server.indexing.figure_serializer import RagweldPictureSerializer, make_markdown_serializer
from tests.fixtures.pdf_builder import apollo_figure_pages

REPLY = json.dumps({
    "kind": "chart",
    "summary": "Spacecraft altitude versus time during the descent orbit insertion burn.",
    "labels": ["ALTITUDE, FEET", "TIME, MIN"],
    "components": ["descent engine"],
    "connections": [],
    "values": ["50 000 ft"],
    "references": ["Figure 6-3"],
})


@pytest.fixture(scope="module")
def converted():
    doc = DocumentConverter().convert(str(apollo_figure_pages())).document
    pictures = [p for p, _ in doc.iterate_items() if isinstance(p, PictureItem) and p.prov]
    assert pictures, "fixture must contain at least one detected picture"
    return doc, pictures


def test_described_picture_serializes_as_prose_block(converted) -> None:
    doc, pictures = converted
    pic = pictures[0]
    pic.annotations.append(PictureClassificationData(provenance="test", predicted_classes=[PictureClassificationClass(class_name="chart", confidence=0.9)]))
    pic.annotations.append(DescriptionAnnotation(text=REPLY, provenance="test"))

    serializer = make_markdown_serializer(doc)
    full = serializer.serialize().text
    part = serializer.serialize(item=pic).text

    assert part.startswith("Figure (chart):")
    assert "Spacecraft altitude versus time" in part
    assert "Labels: ALTITUDE, FEET, TIME, MIN" in part
    assert "References: Figure 6-3" in part
    assert "{" not in part and '"summary"' not in part
    assert part in full, "the per-item serialization must be findable verbatim in the whole document"
    picture_serializer = serializer.picture_serializer
    assert isinstance(picture_serializer, RagweldPictureSerializer)
    assert picture_serializer.figures_by_ref[pic.self_ref].values == ["50 000 ft"]
    assert picture_serializer.classes_by_ref[pic.self_ref] == "chart"


def test_undescribed_picture_serializes_exactly_as_docling_would(converted) -> None:
    from docling_core.transforms.serializer.markdown import MarkdownDocSerializer

    doc, pictures = converted
    pic = pictures[-1]
    pic.annotations = [a for a in pic.annotations if not isinstance(a, DescriptionAnnotation)]
    ours = make_markdown_serializer(doc).serialize(item=pic).text
    theirs = MarkdownDocSerializer(doc=doc).serialize(item=pic).text
    assert ours == theirs


def test_non_json_description_becomes_summary(converted) -> None:
    doc, pictures = converted
    pic = pictures[0]
    pic.annotations = [a for a in pic.annotations if not isinstance(a, DescriptionAnnotation)]
    pic.annotations.append(DescriptionAnnotation(text="A scanned line drawing of the lunar module landing gear.", provenance="test"))
    serializer = make_markdown_serializer(doc)
    part = serializer.serialize(item=pic).text
    assert "A scanned line drawing of the lunar module landing gear." in part
    assert serializer.picture_serializer.figures_by_ref[pic.self_ref].labels == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: sync + `pytest -q tests/unit/test_figure_serializer.py`.
Expected: FAIL — `ModuleNotFoundError: server.indexing.figure_serializer`. (Docling conversion of two scanned pages takes 20–90 s on LXC100's CPU; that is expected.)

- [ ] **Step 4: Implement the serializer**

```python
# server/indexing/figure_serializer.py
"""Markdown serialization of described figures.

Docling's own picture serializer emits captions, raw annotation text and an image placeholder.
Ragweld's variant renders the vision reply as prose (``figure_block_markdown``) at the
picture's position and keeps the parsed ``FigureAnnotation`` aside, keyed by ``self_ref``, so
the extractor's source map can attach it to the chunk that lands on that text.

One serializer instance is used for both the whole-document serialization and the per-item
calls made by ``_build_source_map``; the per-item text is therefore findable verbatim in the
whole text, which is what the source map relies on.
"""

from __future__ import annotations

from typing import Any

from docling_core.transforms.serializer.base import create_ser_result
from docling_core.transforms.serializer.markdown import (
    MarkdownDocSerializer,
    MarkdownParams,
    MarkdownPictureSerializer,
)
from docling_core.types.doc.document import (
    DescriptionAnnotation,
    DoclingDocument,
    PictureClassificationData,
    PictureItem,
)

from server.indexing.figure_prompts import figure_block_markdown, parse_figure_reply
from server.models.index import FigureAnnotation


class RagweldPictureSerializer(MarkdownPictureSerializer):
    """Prose for described pictures; Docling's default output for everything else."""

    def __init__(self) -> None:
        super().__init__()
        self.figures_by_ref: dict[str, FigureAnnotation] = {}
        self.classes_by_ref: dict[str, str] = {}

    def serialize(self, *, item: PictureItem, doc_serializer: Any, doc: DoclingDocument, **kwargs: Any):  # type: ignore[override]
        description: DescriptionAnnotation | None = None
        cls: str | None = None
        for ann in item.get_annotations():
            if isinstance(ann, DescriptionAnnotation) and description is None:
                description = ann
            elif isinstance(ann, PictureClassificationData) and ann.predicted_classes and cls is None:
                cls = ann.predicted_classes[0].class_name.replace("_", " ")
        if cls is not None:
            self.classes_by_ref[item.self_ref] = cls
        if description is None:
            return super().serialize(item=item, doc_serializer=doc_serializer, doc=doc, **kwargs)

        fig = parse_figure_reply(description.text)
        self.figures_by_ref[item.self_ref] = fig
        caption = doc_serializer.serialize_captions(item=item, **kwargs).text
        params = MarkdownParams(**kwargs)
        block = figure_block_markdown(caption, cls, fig)
        placeholder = params.image_placeholder if params.image_placeholder else ""
        text = "\n\n".join(p for p in (block, placeholder) if p)
        return create_ser_result(text=text, span_source=item)


def make_markdown_serializer(doc: DoclingDocument) -> MarkdownDocSerializer:
    """A Docling markdown serializer whose picture serializer records figure annotations."""
    return MarkdownDocSerializer(doc=doc, picture_serializer=RagweldPictureSerializer())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: sync + `pytest -q tests/unit/test_figure_serializer.py`.
Expected: 3 passed. If `test_undescribed_picture_serializes_exactly_as_docling_would` fails on the image placeholder, compare `MarkdownPictureSerializer.serialize` in the installed docling-core and mirror its exact composition (caption, legacy annotations, image part) for the undescribed path — the contract is byte-equality with Docling when no description exists.

- [ ] **Step 6: Commit and push**

```bash
git add server/indexing/figure_serializer.py tests/unit/test_figure_serializer.py
git commit -m "feat(indexing): ragweld picture serializer renders figure descriptions as prose

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git fetch origin main && git rebase origin/main && git push origin HEAD:main
```

---

### Task 5: Source map and provenance carry the figure

**Files:**
- Modify: `server/indexing/text_extractors.py` (`SourceSpan`, `ExtractedDocument`, `_build_source_map`, `_read_with_docling`)
- Modify: `server/indexing/provenance.py` (`stamp_provenance`)
- Test: `tests/unit/test_figure_provenance.py`

**Interfaces:**
- Consumes: `make_markdown_serializer` (Task 4).
- Produces: `SourceSpan.figure: FigureAnnotation | None`, `SourceSpan.figure_class: str | None`; `ExtractedDocument.figures_described: int`, `figures_failed: int`, `figures_skipped: int`; `stamp_provenance(chunks, *, extraction, spans)` also sets `chunk.metadata["figure"]` (model dump), `chunk.metadata["figure_class"]`, and `chunk.metadata["chunk_kind"] = "figure"` when figure-span characters cover ≥ 50% of the chunk; `_read_with_docling(path, *, serializer_factory=make_markdown_serializer)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_figure_provenance.py
"""A described figure's chunk carries its region, the parsed JSON and a figure chunk kind."""

from __future__ import annotations

import json

import pytest
from docling.document_converter import DocumentConverter
from docling_core.types.doc import PictureItem
from docling_core.types.doc.document import DescriptionAnnotation

from server.indexing.chunker import Chunker
from server.indexing.figure_serializer import make_markdown_serializer
from server.indexing.provenance import stamp_provenance
from server.indexing.text_extractors import ExtractedDocument, SourceSpan, _build_source_map
from server.models.index import Chunk, PageRegion
from server.models.tribrid_config_model import TriBridConfig
from tests.fixtures.pdf_builder import apollo_figure_pages

REPLY = json.dumps({"kind": "drawing", "summary": "Landing gear strut and footpad with the lunar surface sensing probe.", "labels": ["PROBE", "FOOTPAD"], "components": ["strut", "footpad"], "connections": ["strut -> footpad"], "values": [], "references": []})


@pytest.fixture(scope="module")
def described_doc():
    doc = DocumentConverter().convert(str(apollo_figure_pages())).document
    pic = next(p for p, _ in doc.iterate_items() if isinstance(p, PictureItem) and p.prov)
    pic.annotations.append(DescriptionAnnotation(text=REPLY, provenance="test"))
    serializer = make_markdown_serializer(doc)
    full = serializer.serialize().text
    spans, unlocated = _build_source_map(doc, serializer, full)
    return doc, pic, full, spans, unlocated


def test_source_map_attaches_the_figure_to_the_pictures_span(described_doc) -> None:
    doc, pic, full, spans, unlocated = described_doc
    figure_spans = [s for s in spans if s.figure is not None]
    assert len(figure_spans) == len(pic.prov)
    span = figure_spans[0]
    assert span.figure.components == ["strut", "footpad"]
    assert full[span.char_start:span.char_end].startswith("Figure")
    assert span.region.page == pic.prov[0].page_no
    assert 0.0 <= span.region.left < span.region.right <= 1.0
    assert unlocated == 0


def test_stamp_provenance_marks_the_figure_chunk(described_doc) -> None:
    doc, pic, full, spans, _ = described_doc
    figure_span = next(s for s in spans if s.figure is not None)
    cfg = TriBridConfig()
    chunks = Chunker(cfg.chunking).chunk_document(file_path="apollo11_figure_pages.pdf", content=full, language=None)  # noqa: E501 — use the real chunker entry point; adjust name to Chunker's public method if it differs
    stamp_provenance(chunks, extraction="docling", spans=spans)
    figure_chunks = [c for c in chunks if c.metadata.get("chunk_kind") == "figure"]
    assert figure_chunks, "the chunk holding the figure block must be a figure chunk"
    chunk = figure_chunks[0]
    assert chunk.metadata["figure"]["labels"] == ["PROBE", "FOOTPAD"]
    assert chunk.provenance is not None and figure_span.region in chunk.provenance.regions
    text_chunks = [c for c in chunks if c.metadata.get("chunk_kind") != "figure"]
    assert all("figure" not in c.metadata for c in text_chunks)


def test_a_chunk_that_only_brushes_a_figure_stays_a_text_chunk() -> None:
    region = PageRegion(page=1, left=0.1, top=0.1, right=0.9, bottom=0.5)
    fig_text = "Figure: A\nshort."
    prose = "x" * 400
    full = prose + "\n" + fig_text
    spans = (SourceSpan(char_start=len(prose) + 1, char_end=len(full), region=region, figure=__import__("server.models.index", fromlist=["FigureAnnotation"]).FigureAnnotation(summary="short.")),)
    chunk = Chunk(chunk_id="f:1-1:0", content=full, file_path="f", start_line=1, end_line=1, metadata={"char_start": 0, "char_end": len(full)})
    stamp_provenance([chunk], extraction="docling", spans=spans)
    assert chunk.provenance is not None and chunk.provenance.regions == [region]
    assert chunk.metadata.get("chunk_kind") != "figure" and "figure" not in chunk.metadata


def test_extracted_document_counts_default_to_zero() -> None:
    doc = ExtractedDocument(text="x", extraction="direct", kind="text")
    assert (doc.figures_described, doc.figures_failed, doc.figures_skipped) == (0, 0, 0)
```

Before syncing, replace the `Chunker(...).chunk_document(...)` call with the chunker's real entry point: run `grep -n "def chunk" server/indexing/chunker.py` and use the public method that takes `(file_path, content, language)` and returns `list[Chunk]` with `metadata.char_start/char_end` set (the one `server/api/index.py` calls before `stamp_provenance`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: sync + `pytest -q tests/unit/test_figure_provenance.py`.
Expected: FAIL — `TypeError: SourceSpan.__init__() got an unexpected keyword argument 'figure'` / `AttributeError: figures_described`.

- [ ] **Step 3: Extend `SourceSpan`, `ExtractedDocument`, the source map and the reader**

In `server/indexing/text_extractors.py`:

```python
from server.models.index import DocumentKind, ExtractionMethod, FigureAnnotation, PageRegion
```

```python
@dataclass(frozen=True)
class SourceSpan:
    """One Docling layout item located in the serialized markdown: [char_start, char_end)."""

    char_start: int
    char_end: int
    region: PageRegion
    figure: FigureAnnotation | None = None
    figure_class: str | None = None


@dataclass(frozen=True)
class ExtractedDocument:
    """Extracted text plus the provenance needed to point a chunk back at its source."""

    text: str
    extraction: ExtractionMethod
    kind: DocumentKind
    spans: tuple[SourceSpan, ...] = ()
    unlocated_items: int = 0
    figures_described: int = 0
    figures_failed: int = 0
    figures_skipped: int = 0
```

In `_build_source_map`, after computing `end`/`cursor` and before the `for prov in item.prov:` loop:

```python
        figures = getattr(getattr(serializer, "picture_serializer", None), "figures_by_ref", {})
        classes = getattr(getattr(serializer, "picture_serializer", None), "classes_by_ref", {})
        figure = figures.get(getattr(item, "self_ref", ""))
        figure_class = classes.get(getattr(item, "self_ref", ""))
```
and pass them into every `SourceSpan(...)` built in that loop: `figure=figure, figure_class=figure_class`.

In `_read_with_docling`, replace `MarkdownDocSerializer(doc=doc)` with the factory and count figures:

```python
def _read_with_docling(path: Path, *, converter: Any | None = None) -> ExtractedDocument | None:
    """Convert a rich document to markdown via Docling with a page/bbox source map.

    ``converter`` lets the indexer pass a converter configured for figure enrichment
    (Task 6); the default is the plain cached converter.
    """
    try:
        from docling_core.types.doc import PictureItem
        from docling_core.types.doc.document import DescriptionAnnotation

        from server.indexing.figure_serializer import make_markdown_serializer

        result = (converter or _docling_converter()).convert(str(path))
        doc = result.document
        serializer = make_markdown_serializer(doc)
        full = str(serializer.serialize().text or "")
    except Exception:
        return None
    if not full.strip():
        return None
    spans, unlocated = _build_source_map(doc, serializer, full)
    pictures = [p for p, _ in doc.iterate_items() if isinstance(p, PictureItem)]
    described = sum(1 for p in pictures if any(isinstance(a, DescriptionAnnotation) for a in p.get_annotations()))
    return ExtractedDocument(
        text=full,
        extraction="docling",
        kind=document_kind_for_path(path),
        spans=spans,
        unlocated_items=unlocated,
        figures_described=described,
        figures_skipped=max(0, len(pictures) - described),
    )
```
(`figures_failed` is set by Task 6, which knows whether description was requested.)

- [ ] **Step 4: Extend `stamp_provenance`**

Replace the loop body in `server/indexing/provenance.py`:

```python
    starts = [span.char_start for span in spans]
    for chunk in chunks:
        raw_start = chunk.metadata.get("char_start")
        raw_end = chunk.metadata.get("char_end")
        regions: list[PageRegion] = []
        overlapping: list[SourceSpan] = []
        if isinstance(raw_start, int) and isinstance(raw_end, int):
            overlapping = spans_for_span(spans, starts, raw_start, raw_end)
            regions = [span.region for span in overlapping]
        pages = [region.page for region in regions]
        chunk.provenance = ChunkProvenance(
            extraction=extraction,
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            regions=regions,
        )
        figure_spans = [span for span in overlapping if span.figure is not None]
        if not figure_spans or not isinstance(raw_start, int) or not isinstance(raw_end, int):
            continue
        covered = sum(
            max(0, min(span.char_end, raw_end) - max(span.char_start, raw_start)) for span in figure_spans
        )
        chunk_len = max(1, raw_end - raw_start)
        if covered * 2 >= chunk_len:
            first = figure_spans[0]
            chunk.metadata["figure"] = first.figure.model_dump(mode="json")
            if first.figure_class:
                chunk.metadata["figure_class"] = first.figure_class
            chunk.metadata["chunk_kind"] = "figure"
```

and add, above `regions_for_span`:

```python
def spans_for_span(
    spans: Sequence[SourceSpan], starts: Sequence[int], char_start: int, char_end: int
) -> list[SourceSpan]:
    """Every source span overlapping [char_start, char_end), in reading order."""
    if not spans or char_end <= char_start:
        return []
    hi = bisect_left(starts, char_end)
    found: list[SourceSpan] = []
    index = hi - 1
    while index >= 0 and spans[index].char_end > char_start:
        found.append(spans[index])
        index -= 1
    found.reverse()
    return found


def regions_for_span(
    spans: Sequence[SourceSpan], starts: Sequence[int], char_start: int, char_end: int
) -> list[PageRegion]:
    """Regions of every source span overlapping [char_start, char_end), in reading order."""
    return [span.region for span in spans_for_span(spans, starts, char_start, char_end)]
```

- [ ] **Step 5: Run the new tests and the existing provenance/extractor suites**

Run: sync `server/indexing/text_extractors.py server/indexing/provenance.py` + test; `pytest -q tests/unit/test_figure_provenance.py tests/unit/test_provenance.py tests/unit/test_text_extractors.py tests/unit/test_document_models.py`.
Expected: all pass; the pre-existing suites must stay byte-for-byte green (no figure annotations ⇒ identical output).

- [ ] **Step 6: Commit and push**

```bash
git add server/indexing/text_extractors.py server/indexing/provenance.py tests/unit/test_figure_provenance.py
git commit -m "feat(indexing): source map and provenance carry figure annotations onto chunks

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git fetch origin main && git rebase origin/main && git push origin HEAD:main
```

---

### Task 6: Converter options from config, gateway route, run wiring

**Files:**
- Modify: `server/indexing/text_extractors.py` (`build_figure_pipeline_options`, `docling_converter_for`, `extract_text_for_path(..., figures=, gateway=)`)
- Modify: `server/api/index.py` (`_resolve_figure_route`, `_extract_text_for_index_sync/_extract_text_for_index` thread `figures`/`gateway`; start-of-run validation; run-log counters)
- Test: `tests/unit/test_figure_extraction_options.py`

**Interfaces:**
- Consumes: `IndexingFiguresConfig` (Task 1), `FIGURE_PROMPTS` (Task 2), `select_provider_route` (`server/chat/provider_router.py`, returns `ProviderRoute(kind, provider_name, base_url, model, api_key)`).
- Produces: `FigureGateway(base_url: str, api_key: str, model: str)` (frozen dataclass in `text_extractors.py`); `build_figure_pipeline_options(figures: IndexingFiguresConfig, gateway: FigureGateway | None) -> PdfPipelineOptions`; `docling_converter_for(figures, gateway) -> DocumentConverter` (cached per options signature); `extract_text_for_path(path, *, figures=None, gateway=None, …)`; in `index.py`: `_resolve_figure_route(cfg) -> FigureGateway` (raises `HTTPException(409, …)` when the alias is not routable or not `supports_vision`), and a run-log line `figures described=… failed=… skipped=…`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_figure_extraction_options.py
"""Config becomes Docling pipeline options exactly; disabled config keeps the plain converter."""

from __future__ import annotations

from docling.datamodel.pipeline_options import PdfPipelineOptions, PictureDescriptionApiOptions

from server.indexing.text_extractors import (
    FigureGateway,
    _docling_converter,
    build_figure_pipeline_options,
    docling_converter_for,
)
from server.models.tribrid_config_model import IndexingFiguresConfig


def test_disabled_config_uses_the_plain_cached_converter() -> None:
    figures = IndexingFiguresConfig(enabled=False)
    assert docling_converter_for(figures, None) is _docling_converter()


def test_enabled_config_maps_every_field_onto_pipeline_options() -> None:
    figures = IndexingFiguresConfig(
        enabled=True, describe=True, classify=True, vision_model="z-ai.glm-5.3-flash",
        prompt_profile="schematic", images_scale=3.0, min_area_fraction=0.05,
        skip_classes=["logo"], max_completion_tokens=800, concurrency=2, timeout_s=45,
    )
    gateway = FigureGateway(base_url="http://127.0.0.1:54000/v1", api_key="sk-test", model="z-ai.glm-5.3-flash")
    opts = build_figure_pipeline_options(figures, gateway)
    assert isinstance(opts, PdfPipelineOptions)
    assert opts.generate_picture_images is True and opts.images_scale == 3.0
    assert opts.do_picture_classification is True and opts.do_picture_description is True
    assert opts.enable_remote_services is True
    api = opts.picture_description_options
    assert isinstance(api, PictureDescriptionApiOptions)
    assert api.url == "http://127.0.0.1:54000/v1/chat/completions"
    assert api.headers["Authorization"] == "Bearer sk-test"
    assert api.params["model"] == "z-ai.glm-5.3-flash"
    assert api.params["max_completion_tokens"] == 800
    assert api.params["response_format"] == {"type": "json_object"}
    assert api.timeout == 45 and api.concurrency == 2
    assert api.picture_area_threshold == 0.05
    assert api.classification_deny == ["logo"]
    assert "drawing number" in api.prompt.lower()


def test_describe_off_still_classifies_without_remote_services() -> None:
    figures = IndexingFiguresConfig(enabled=True, describe=False, classify=True)
    opts = build_figure_pipeline_options(figures, None)
    assert opts.do_picture_classification is True and opts.do_picture_description is False
    assert opts.enable_remote_services is False


def test_converters_are_cached_per_options_signature() -> None:
    a = IndexingFiguresConfig(enabled=True, describe=False)
    b = IndexingFiguresConfig(enabled=True, describe=False)
    c = IndexingFiguresConfig(enabled=True, describe=False, images_scale=1.5)
    assert docling_converter_for(a, None) is docling_converter_for(b, None)
    assert docling_converter_for(a, None) is not docling_converter_for(c, None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: sync + `pytest -q tests/unit/test_figure_extraction_options.py`.
Expected: FAIL — `ImportError: cannot import name 'FigureGateway'`.

- [ ] **Step 3: Implement options, gateway and converter cache in `text_extractors.py`**

Add after `_docling_converter()`:

```python
@dataclass(frozen=True)
class FigureGateway:
    """Resolved LiteLLM route for figure description (URL, key, alias)."""

    base_url: str
    api_key: str
    model: str


def build_figure_pipeline_options(figures: Any, gateway: FigureGateway | None) -> Any:
    """Docling PDF pipeline options for figure classification/description from config."""
    from docling.datamodel.pipeline_options import PdfPipelineOptions, PictureDescriptionApiOptions

    from server.indexing.figure_prompts import FIGURE_PROMPTS

    opts = PdfPipelineOptions()
    opts.generate_picture_images = True
    opts.images_scale = float(figures.images_scale)
    opts.do_picture_classification = bool(figures.classify)
    describe = bool(figures.describe) and gateway is not None
    opts.do_picture_description = describe
    opts.enable_remote_services = describe
    if describe:
        assert gateway is not None
        opts.picture_description_options = PictureDescriptionApiOptions(
            url=f"{gateway.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {gateway.api_key}"},
            params={
                "model": gateway.model,
                "max_completion_tokens": int(figures.max_completion_tokens),
                "response_format": {"type": "json_object"},
            },
            prompt=FIGURE_PROMPTS[str(figures.prompt_profile)],
            timeout=float(figures.timeout_s),
            concurrency=int(figures.concurrency),
            picture_area_threshold=float(figures.min_area_fraction),
            classification_deny=list(figures.skip_classes),
        )
    return opts


_FIGURE_CONVERTERS: dict[str, Any] = {}


def docling_converter_for(figures: Any, gateway: FigureGateway | None) -> Any:
    """The plain cached converter when figures are off; otherwise one converter per options signature."""
    if figures is None or not bool(getattr(figures, "enabled", False)):
        return _docling_converter()
    signature = json.dumps(
        {"figures": figures.model_dump(mode="json"), "gateway": (gateway.base_url, gateway.model) if gateway else None},
        sort_keys=True,
    )
    with _DOCLING_CONVERTER_LOCK:
        converter = _FIGURE_CONVERTERS.get(signature)
        if converter is None:
            from docling.datamodel.base_models import InputFormat
            from docling.document_converter import DocumentConverter, PdfFormatOption

            options = build_figure_pipeline_options(figures, gateway)
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=options),
                    InputFormat.IMAGE: PdfFormatOption(pipeline_options=options),
                }
            )
            _FIGURE_CONVERTERS[signature] = converter
    return converter
```

(add `import json` at the top). Extend `extract_text_for_path` with `figures: Any | None = None, gateway: FigureGateway | None = None` keyword arguments and route the Docling branch through `_read_with_docling(path, converter=docling_converter_for(figures, gateway))`; when `figures` is enabled with `describe=True`, set `figures_failed = figures_skipped` on the returned document only for pictures that were eligible — keep it simple and honest: report `figures_failed = 0` and `figures_skipped = len(pictures) - described` (Docling does not expose per-picture failure reasons; the count of undescribed eligible pictures is what the operator needs), and note this in the run log wording ("undescribed").

- [ ] **Step 4: Resolve the route and thread config through `server/api/index.py`**

Add near `_resolve_semantic_kg_route`:

```python
def _figure_model_spec(alias: str) -> dict[str, Any] | None:
    for m in _load_models_json():
        if str(m.get("gateway_alias") or "").strip() == alias:
            return m
    return None


def _resolve_figure_route(cfg: TriBridConfig) -> FigureGateway | None:
    """Validated gateway route for figure description, or None when figures are off."""
    figures = cfg.indexing.figures
    if not figures.enabled or not figures.describe:
        return None
    alias = str(figures.vision_model or "").strip()
    spec = _figure_model_spec(alias)
    if spec is None or not bool(spec.get("supports_vision")):
        raise HTTPException(
            status_code=409,
            detail=f"indexing.figures.vision_model {alias!r} is not a vision-capable gateway alias in the model catalog",
        )
    try:
        route = select_provider_route(config=cfg, model_override=alias)
    except Exception as exc:  # fail closed with the alias in the message
        raise HTTPException(status_code=409, detail=f"figure vision alias {alias!r} is not routable: {exc}") from exc
    return FigureGateway(base_url=str(route.base_url), api_key=str(route.api_key), model=str(route.model))
```

(import `FigureGateway` from `server.indexing.text_extractors` and `select_provider_route` from `server.chat.provider_router` — the latter is already imported for the semantic-KG route; confirm with `grep -n select_provider_route server/api/index.py`.)

In `start_index`, right after `cfg = await load_scoped_config(repo_id=request.repo_id)`, add `figure_gateway = _resolve_figure_route(cfg)` so an unroutable alias refuses the run before the fence is taken, and pass `figures=cfg.indexing.figures, gateway=figure_gateway` down to `_run_index_body` → `_extract_text_for_index` → `_extract_text_for_index_sync` → `extract_text_for_path` (add the two keyword parameters at each level, defaulting to `None`).

In `_run_index_body`, next to `semantic_entities_total = 0`, add `figures_described_total = 0; figures_undescribed_total = 0`; after each `extracted = await _extract_text_for_index(...)`, add `figures_described_total += extracted.figures_described; figures_undescribed_total += extracted.figures_skipped`; and in the run-log message that prints `entities=… relations=…` append `f"figures_described={figures_described_total} figures_undescribed={figures_undescribed_total} "` when `cfg.indexing.figures.enabled`.

- [ ] **Step 5: Run the tests plus the index-module import and estimate suites**

Run: sync `server/indexing/text_extractors.py server/api/index.py` + test; on LXC100: `PYTHONPATH=/tmp/fable-figs /opt/ragweld/.venv/bin/python -c "import server.api.index" && pytest -q tests/unit/test_figure_extraction_options.py tests/unit/test_figure_provenance.py tests/unit/test_text_extractors.py -k "not live"`.
Expected: all pass.

- [ ] **Step 6: Ruff and repo gates on LXC100**

Run: `PYTHONPATH=/tmp/fable-figs /opt/ragweld/.venv/bin/python -m ruff check server/indexing server/api/index.py server/models tests/unit/test_figure_*.py && PYTHONPATH=/tmp/fable-figs /opt/ragweld/.venv/bin/python scripts/check_banned.py`
Expected: ruff clean on the touched files; `check_banned` shows only the pre-existing `test_chat_usage_propagation.py` monkeypatch violations (not ours) or is clean if Codex has fixed them.

- [ ] **Step 7: Commit and push**

```bash
git add server/indexing/text_extractors.py server/api/index.py tests/unit/test_figure_extraction_options.py
git commit -m "feat(indexing): describe figures through the gateway vision alias during Docling conversion

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git fetch origin main && git rebase origin/main && git push origin HEAD:main
```

---

### Task 7: Estimate cost line and the Indexing tab

**Files:**
- Modify: `server/models/index.py` (`IndexEstimate`: add `estimated_figures: int | None = None`, `figure_description_cost_usd: float | None = None`)
- Modify: `server/api/index.py` (`_estimate_figure_description_cost_usd`, `estimate_index`)
- Modify: `web/src/components/RAG/IndexingSubtab.tsx` (two places: the `costBreakdown` string at ~line 735 and the `Est:` line at ~line 2974)
- Modify (generated): `web/src/types/generated.ts`
- Test: `tests/unit/test_index_estimate_figures.py`

**Interfaces:**
- Consumes: `_figure_model_spec` (Task 6), `pdf_page_sizes` (`server/services/pdf_render.py`).
- Produces: `_estimate_figure_description_cost_usd(*, alias: str, figures: int, max_completion_tokens: int) -> float | None`; `_count_pdf_pages(paths: list[Path]) -> int`; estimate fields above.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_index_estimate_figures.py
"""The estimate itemises figure description when figures are enabled and only then."""

from __future__ import annotations

from pathlib import Path

from server.api.index import _count_pdf_pages, _estimate_figure_description_cost_usd
from server.models.index import IndexEstimate
from tests.fixtures.pdf_builder import apollo_figure_pages


def test_cost_uses_catalog_prices_for_the_alias() -> None:
    cost = _estimate_figure_description_cost_usd(alias="z-ai.glm-5.3-flash", figures=100, max_completion_tokens=600)
    assert cost is not None and cost > 0
    # input 1200 tokens/figure at $0.000075/1k + output 600 at $0.00025/1k, for 100 figures
    assert abs(cost - (100 * (1.2 * 0.000075 + 0.6 * 0.00025))) < 1e-9


def test_cost_is_zero_for_no_figures_and_none_for_unknown_alias() -> None:
    assert _estimate_figure_description_cost_usd(alias="z-ai.glm-5.3-flash", figures=0, max_completion_tokens=600) == 0.0
    assert _estimate_figure_description_cost_usd(alias="nope.not-a-model", figures=5, max_completion_tokens=600) is None


def test_pdf_page_count_reads_real_pages() -> None:
    assert _count_pdf_pages([Path(apollo_figure_pages())]) == 2
    assert _count_pdf_pages([Path("/nonexistent/x.pdf")]) == 0


def test_estimate_model_carries_figure_fields() -> None:
    fields = IndexEstimate.model_fields
    assert "estimated_figures" in fields and "figure_description_cost_usd" in fields
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: sync + `pytest -q tests/unit/test_index_estimate_figures.py`.
Expected: FAIL — `ImportError: cannot import name '_count_pdf_pages'`.

- [ ] **Step 3: Implement the estimate pieces**

In `server/models/index.py`, inside `IndexEstimate` after `semantic_kg_cost_usd`:

```python
    estimated_figures: int | None = Field(default=None, description="Figures expected to be described (exact when known, else pages x 0.6)")
    figure_description_cost_usd: float | None = Field(default=None, description="Vision-call cost to describe figures, from catalog prices")
```

In `server/api/index.py` near `_estimate_semantic_kg_cost_usd`:

```python
_FIGURE_INPUT_TOKENS = 1200  # image at images_scale 2 (~800) + prompt (~400)
_FIGURES_PER_PAGE_HEURISTIC = 0.6


def _estimate_figure_description_cost_usd(*, alias: str, figures: int, max_completion_tokens: int) -> float | None:
    """Vision-call cost for describing ``figures`` pictures with ``alias``, from models.json GEN pricing."""
    count = max(0, int(figures or 0))
    if count <= 0:
        return 0.0
    spec = _figure_model_spec(str(alias or "").strip())
    if not spec or str(spec.get("unit") or "").strip() != "1k_tokens":
        return None
    in_rate = _to_float(spec.get("input_per_1k"))
    out_rate = _to_float(spec.get("output_per_1k"))
    if in_rate is None and out_rate is None:
        return None
    return count * (
        (_FIGURE_INPUT_TOKENS / 1000.0) * float(in_rate or 0.0)
        + (float(max_completion_tokens) / 1000.0) * float(out_rate or 0.0)
    )


def _count_pdf_pages(paths: list[Path]) -> int:
    from server.services.pdf_render import pdf_page_sizes

    total = 0
    for path in paths:
        try:
            total += len(pdf_page_sizes(path))
        except Exception:
            continue
    return total
```

In `estimate_index`, after the semantic-KG cost is computed: collect `pdf_paths = [p for p in indexable file paths if p.suffix.lower() == ".pdf"]` from the already-walked file list, then

```python
    figures_cfg = cfg.indexing.figures
    estimated_figures: int | None = None
    figure_cost: float | None = None
    if figures_cfg.enabled and figures_cfg.describe and pdf_paths:
        pages = _count_pdf_pages(pdf_paths)
        estimated_figures = min(
            int(round(pages * _FIGURES_PER_PAGE_HEURISTIC)),
            int(figures_cfg.max_figures_per_file) * len(pdf_paths),
        )
        figure_cost = _estimate_figure_description_cost_usd(
            alias=figures_cfg.vision_model, figures=estimated_figures, max_completion_tokens=figures_cfg.max_completion_tokens
        )
        assumptions.append(f"figures≈{_FIGURES_PER_PAGE_HEURISTIC} per PDF page; {_FIGURE_INPUT_TOKENS} input tokens per figure")
```
and fold `figure_cost` into `total_cost_usd` (None if any component is None, same rule as the semantic-KG line), passing `estimated_figures=estimated_figures, figure_description_cost_usd=figure_cost` to `IndexEstimate(...)`.

- [ ] **Step 4: Show the line in the Indexing tab**

In `web/src/components/RAG/IndexingSubtab.tsx`, extend the breakdown at ~line 735:

```tsx
        const figureCostUsd = estimate.figure_description_cost_usd;
        const costBreakdown =
          semanticKgCostUsd == null && figureCostUsd == null
            ? null
            : [
                `Embed ${embedCostUsd == null ? 'N/A' : formatCurrency(Number(embedCostUsd || 0))}`,
                semanticKgCostUsd == null ? null : `Semantic KG ${formatCurrency(Number(semanticKgCostUsd || 0))}`,
                figureCostUsd == null
                  ? null
                  : `Figures ${formatCurrency(Number(figureCostUsd || 0))}${estimate.estimated_figures != null ? ` (~${formatNumber(Number(estimate.estimated_figures))})` : ''}`,
              ]
                .filter(Boolean)
                .join(' + ');
```

and in the `Est:` block at ~line 2974 append, after the KG parenthetical:

```tsx
            {indexEstimate.figure_description_cost_usd != null
              ? ` + Figures ${formatCurrency(Number(indexEstimate.figure_description_cost_usd || 0))}`
              : ''}
```

- [ ] **Step 5: Regenerate types, run tests, lint and build on LXC100**

Run: sync all four files; on LXC100: `python scripts/generate_types.py && python scripts/validate_types.py && pytest -q tests/unit/test_index_estimate_figures.py tests/unit -k "index_estimate" && (cd web && npm run lint && npm run build)`.
Expected: types in sync; tests pass; lint and production build succeed. Copy the regenerated `generated.ts` back to `$WT`.

- [ ] **Step 6: Commit and push**

```bash
git add server/models/index.py server/api/index.py web/src/components/RAG/IndexingSubtab.tsx web/src/types/generated.ts tests/unit/test_index_estimate_figures.py
git commit -m "feat(indexing): itemise figure description cost in the index estimate

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git fetch origin main && git rebase origin/main && git push origin HEAD:main
```

---

### Task 8: Live gateway integration test

**Files:**
- Create: `tests/integration/test_figure_description_live.py`

**Interfaces:**
- Consumes: `extract_text_for_path(..., figures=, gateway=)` and `_resolve_figure_route` (Task 6), the fixture (Task 3).

- [ ] **Step 1: Write the test (it only runs where a gateway is configured)**

```python
# tests/integration/test_figure_description_live.py
"""One real Apollo figure through the configured vision alias, end to end into a figure chunk."""

from __future__ import annotations

import os

import pytest

from server.api.index import _resolve_figure_route
from server.indexing.chunker import Chunker
from server.indexing.provenance import stamp_provenance
from server.indexing.text_extractors import extract_text_for_path
from server.models.tribrid_config_model import TriBridConfig
from server.services.config_store import load_config
from tests.fixtures.pdf_builder import apollo_figure_pages

pytestmark = pytest.mark.skipif(
    not os.getenv("RAGWELD_LIVE_GATEWAY"),
    reason="set RAGWELD_LIVE_GATEWAY=1 on LXC100 to run against the real LiteLLM gateway",
)


def test_real_figure_is_described_and_becomes_a_figure_chunk() -> None:
    cfg: TriBridConfig = load_config()
    cfg.indexing.figures.enabled = True
    cfg.indexing.figures.describe = True
    gateway = _resolve_figure_route(cfg)
    assert gateway is not None and gateway.model == cfg.indexing.figures.vision_model

    extracted = extract_text_for_path(apollo_figure_pages(), figures=cfg.indexing.figures, gateway=gateway)
    assert extracted is not None and extracted.figures_described >= 1
    figure_spans = [s for s in extracted.spans if s.figure is not None]
    assert figure_spans and figure_spans[0].figure.summary.strip()

    chunks = Chunker(cfg.chunking).chunk_document(file_path="apollo11_figure_pages.pdf", content=extracted.text, language=None)  # same entry point as Task 5
    stamp_provenance(chunks, extraction=extracted.extraction, spans=extracted.spans)
    figure_chunks = [c for c in chunks if c.metadata.get("chunk_kind") == "figure"]
    assert figure_chunks
    fig = figure_chunks[0].metadata["figure"]
    assert fig["summary"] and figure_chunks[0].provenance and figure_chunks[0].provenance.regions
    # A real Apollo question must be answerable from the description: the fixture's figure text
    # mentions something about the mission; assert the description is not generic boilerplate.
    assert len(fig["summary"].split()) >= 15
```

- [ ] **Step 2: Run it on LXC100 against the real gateway**

Run: sync; on LXC100 (`/tmp/fable-figs`), with the production env sourced the way `start-runtime.sh` does for tests (`set -a; . /etc/ragweld/runtime.env; set +a`): `RAGWELD_LIVE_GATEWAY=1 PYTHONPATH=/tmp/fable-figs /opt/ragweld/.venv/bin/python -m pytest -q --no-cov -p no:cacheprovider tests/integration/test_figure_description_live.py -s`
Expected: 1 passed; one or two vision calls at GLM-5.3-Flash prices. Paste the printed summary into the lane note as evidence.

- [ ] **Step 3: Commit and push**

```bash
git add tests/integration/test_figure_description_live.py
git commit -m "test(integration): describe a real Apollo figure through the gateway alias

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git fetch origin main && git rebase origin/main && git push origin HEAD:main
```

---

### Task 9: Deploy, enable for `nasa-apollo-11`, re-index, evaluate

**Files:**
- Create: `data/eval_datasets/nasa-apollo-11-figures.json` (in the eval lane's dataset format — copy the shape of an existing file in `data/eval_datasets/`)
- Modify: `docs/exec-plans/active/multimodal-schematics-research-2026-08-29.md` (results section)

**Interfaces:**
- Consumes: everything above deployed on LXC100.

- [ ] **Step 1: Deploy (Codex's lane by default)**

Write in the lane note: "Fable-1: figure-chunk slice is on origin/main at `<sha>`; please include it in your next LXC100 deploy, or say 'Fable: deploy it'." If authorised, deploy with the checklist: grep the lane note for `INDEX RUN ACTIVE`; confirm every corpus's `runs/latest.status != "indexing"`; `su -s /bin/bash ragweld -c "git -C /opt/ragweld pull --ff-only origin main"`; render config; write `/etc/ragweld/deployment-commit`; `systemctl restart ragweld`; wait for `/api/ready`; verify `git rev-parse HEAD` equals the marker.

- [ ] **Step 2: Enable figures for the corpus and read the estimate**

Run on LXC100:
```bash
B=http://127.0.0.1:58012/api
curl -fsS -X PATCH -H 'Content-Type: application/json' "$B/config/indexing?corpus_id=nasa-apollo-11" --data '{"figures": {"enabled": true}}' | jq -c '.indexing.figures'
curl -fsS -X POST -H 'Content-Type: application/json' "$B/index/estimate" --data '{"repo_id":"nasa-apollo-11","repo_path":"/srv/ragweld/corpora/nasa-apollo-11"}' | jq -c '{estimated_figures, figure_description_cost_usd, total_cost_usd}'
```
Expected: `enabled: true`; an estimate around 215 figures (359 pages × 0.6) and a cost in cents. Record it in the lane note.

- [ ] **Step 3: Baseline eval before re-indexing**

Author `data/eval_datasets/nasa-apollo-11-figures.json` with 20 real questions answerable only from figures or tables in the report (e.g. "What was the maximum cabin pressure shown during entry?", "Which figure shows the descent orbit insertion altitude profile?", "According to the trajectory figure, at what ground elapsed time did lunar orbit insertion occur?"), each with the page number of the figure as the expected source. Run the eval lane against the current index and save the run id.

- [ ] **Step 4: Re-index with figures on**

Set the lane-note flag (`INDEX RUN ACTIVE … nasa-apollo-11 (figures) since HH:MM UTC`), then `curl -fsS -X POST … "$B/index" --data '{"repo_id":"nasa-apollo-11","repo_path":"/srv/ragweld/corpora/nasa-apollo-11","force_reindex":true}'`; watch `runs/latest` until `complete`; check the run log line `figures_described=… figures_undescribed=…`; clear the flag.

- [ ] **Step 5: Verify figure chunks exist and are retrievable**

Run:
```bash
curl -fsS -X POST -H 'Content-Type: application/json' "$B/search" --data '{"query":"cabin pressure during entry figure","repo_id":"nasa-apollo-11","top_k":5}' | jq -c '.matches[] | {chunk_id, kind: .metadata.chunk_kind, page: .provenance.page_start}'
```
Expected: at least one match with `kind == "figure"` and a page; open it in the viewer through the signed-in app and confirm the box lands on the figure.

- [ ] **Step 6: Re-run the eval and record the verdict**

Run the same eval dataset; compare nDCG@3 / Success@3 on figure questions and on the existing prose dataset. Append a "Phase 1 results" section to the research note with both numbers, the figure counts, and the cost, and push it. Phase 1 passes only if figure questions improve and prose questions do not regress.

---

## Self-review

- **Spec coverage:** §4.1 config → Task 1; §4.3 serializer + reply schema/prompts → Tasks 2, 4; §4.4 provenance/metadata → Task 5; §4.2 extraction options, gateway route, run behaviour (typed 409 at start, counters, caption-only degradation) → Task 6; §4.5 estimate + UI line → Task 7; §7 tests (serializer/provenance unit, config contract, estimate, gateway integration, eval) → Tasks 1–8 and 9; §8 rollout → Task 9. Gap noted: §6 "per-figure failure counted as `figures_failed`" — Docling does not expose per-picture failure reasons, so Task 6 reports `figures_undescribed` (eligible pictures without a description) instead and says so in the log; the spec's intent (never fail the run, count the misses) is preserved.
- **Placeholder scan:** the only deliberate "adjust to the real name" note is the chunker entry point in Tasks 5/8, resolved by a `grep` step before the test is synced.
- **Type consistency:** `FigureAnnotation` (Task 2) is used by Tasks 4–6; `FigureGateway` (Task 6) by Tasks 7–8; `make_markdown_serializer` (Task 4) by Task 5; `_figure_model_spec` (Task 6) by Task 7; `extract_text_for_path(..., figures=, gateway=)` (Task 6) by Task 8. Names match throughout.
