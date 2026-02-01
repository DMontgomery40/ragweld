#!/usr/bin/env python3
"""
Docs Autopilot bootstrap for TriBridRAG.

Reads source files for each documentation page, calls OpenAI API
to generate MkDocs pages automatically.

Usage:
    python scripts/docs_ai/bootstrap_docs.py --list
    python scripts/docs_ai/bootstrap_docs.py --dry-run --page index
    python scripts/docs_ai/bootstrap_docs.py --page index --page retrieval/overview
    python scripts/docs_ai/bootstrap_docs.py --all --model gpt-5 --verbosity high --reasoning-effort high
"""
import argparse
import os
import sys
from pathlib import Path
from typing import Optional

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai package not installed. Run: pip install openai")
    sys.exit(1)

# =============================================================================
# SYSTEM PROMPT - TriBridRAG-specific (NO AGRO REFERENCES)
# =============================================================================

SYSTEM_PROMPT = """You are writing documentation for TriBridRAG, a tri-brid RAG engine combining:
- Vector search (pgvector in PostgreSQL)
- Sparse search (PostgreSQL Full-Text Search/BM25)
- Graph search (Neo4j for entity relationships)

WRITING STYLE: Extremely detailed, high-signal, and deeply technical.
- Default to long-form documentation. Avoid shallow summaries.
- Assume the reader wants to operate and extend the system (not just understand it).
- Prefer concrete, copy/paste-able examples over generic prose.

MkDocs theme: Material for MkDocs (v9.7.x).
Reference: https://squidfunk.github.io/mkdocs-material/reference/

KEY ARCHITECTURE POINTS:
1. THREE search legs fused together (hence "tri-brid")
2. Pydantic is THE LAW - all config flows from tribrid_config_model.py
3. TypeScript types are GENERATED from Pydantic (never hand-written)
4. pgvector replaces Qdrant (simpler, same Postgres instance)
5. Neo4j for graph RAG - entities, relationships, communities
6. Fusion methods: RRF (Reciprocal Rank Fusion) or weighted scoring

BANNED TERMS (DO NOT USE):
- "Qdrant" - we use pgvector
- "Redis" - removed from project
- "LangChain" - use LangGraph directly if needed
- "cards" - use "chunk_summaries"
- "AGRO" or "agro" - this is TriBridRAG

MKDOCS MATERIAL FORMATTING (MANDATORY):
- Start every page with a feature grid:
  <div class="grid chunk_summaries" markdown>
  ...
  </div>

- Every page MUST include a "Quick links" block with Material buttons (use at least 3):
  !!! tip "Quick links"
      [:material-sitemap: Architecture](architecture.md){ .md-button }
      [:material-magnify: Retrieval](retrieval/overview.md){ .md-button }
      [:material-cog: Configuration](configuration.md){ .md-button .md-button--primary }

- Use admonitions heavily: !!! note, !!! tip, !!! warning, !!! danger, ??? collapsible "Title"

- Use content tabs for all code and multi-approach content:
  === "Python"
      ```python
      code
      ```
  === "curl"
      ```bash
      code
      ```
  === "TypeScript"
      ```typescript
      code
      ```

- Use code annotations (MkDocs Material annotations) with markers inside comments:
  ```python linenums="1" hl_lines="3 4"
  do_thing()  # (1)!
  ```
  1. Explanation for (1)

- Use data tables for configuration and comparisons.
- Use definition lists for parameters and glossary-like sections.
- Use task lists for checklists.

MERMAID v11 (CRITICAL: AVOID SYNTAX ERRORS):
- NO HTML anywhere in Mermaid (no <br/>, no <b>, no <span>, no entities).
- Prefer simple node IDs (A, B, C, D) and put all human text in labels.
- ALWAYS quote labels that contain spaces, punctuation, or newlines:
  - Good: A["Vector Search\\n(pgvector)"]
  - Bad: A[Vector Search (pgvector)]
- Use \\n for multi-line labels ONLY inside quoted labels.
- If you use edge labels, quote them:
  - Good: A -->|"embed + search"| B
  - Bad: A -->|embed + search| B
- Avoid these error-prone patterns: unescaped quotes, parentheses/brackets inside IDs, markdown inside labels.
- Put classDef lines at the end of the diagram block.
- Include 2-3 diagrams per page (mix flowchart LR, sequenceDiagram, stateDiagram-v2).

OUTPUT FORMAT:
- Output ONLY the markdown content for the page
- Start with a level-1 heading (# Title)
- Do not include YAML frontmatter
- Do not wrap output in code blocks

LINKING + REFERENCE RULES (CRITICAL: BUILD MUST PASS `mkdocs build --strict`):
- Only create relative links to other documentation pages listed in VALID_PAGES.
- NEVER create relative links to repository source files (e.g. `server/models/tribrid_config_model.py`) because MkDocs will treat them as broken.
  - If you need to reference a source file path: format it as inline code: `server/models/tribrid_config_model.py`
  - If you want a clickable link: use an ABSOLUTE GitHub URL:
    `https://github.com/DMontgomery40/tribrid-rag/blob/main/server/models/tribrid_config_model.py`
- When you link to an anchor (e.g. `configuration.md#fusion-config`), the target page MUST contain a heading whose generated anchor matches.
- ALWAYS use lowercase in anchor fragments (e.g. `#frontend`, not `#Frontend`).
"""

# =============================================================================
# VALID_PAGES - Documentation structure for accurate cross-linking
# =============================================================================

VALID_PAGES = """
DOCUMENTATION STRUCTURE - Only link to these pages:

PAGES:
- index.md
- architecture.md
- retrieval/overview.md
- configuration.md
- api.md
- indexing.md
- deploy.md
- glossary.md

REQUIRED STABLE ANCHORS (MUST EXIST EXACTLY AS HEADINGS):
- index.md:
  - ## Source of truth file
  - ## Troubleshooting FAQ
- architecture.md:
  - ## Fusion methods
  - ## pgvector integration
  - ## Graph RAG using Neo4j
- retrieval/overview.md:
  - ## Fusion techniques
- configuration.md:
  - ## Fusion config
  - ## Indexing config
  - ## Embedding config
  - ## Graph storage config
  - ## Reranking
- indexing.md:
  - ## Chunking
- deploy.md:
  - ## Neo4j installation
- glossary.md:
  - ## Frontend

LINKING RULES:
1. Use relative links and EXACT filenames from the list above.
2. DO NOT invent new pages or link to non-existent paths.
3. Prefer deep links into subsections using anchors when helpful.
4. If you include an anchored link, you MUST also ensure the target heading exists (see REQUIRED STABLE ANCHORS).

NESTED PAGE LINKING RULES (CRITICAL):
- For `retrieval/overview.md`:
  - Links to root-level pages MUST be prefixed with `../` (e.g. `../architecture.md`, `../configuration.md`, `../index.md`).
  - NEVER link to `retrieval/overview.md` from inside `retrieval/overview.md` (it would resolve to `retrieval/retrieval/overview.md`).
  - Prefer `#anchor` links for within-page references.
"""

# =============================================================================
# DOC_PAGES - Maps each doc page to source files that inform it
# =============================================================================

DOC_PAGES = {
    "index": {
        "title": "TriBridRAG Docs",
        "output_path": "mkdocs/docs/index.md",
        "source_files": [
            "README.md",
            "AGENTS.md",
            "docker-compose.yml",
            "start.sh",
            "server/models/tribrid_config_model.py",
        ],
        "instruction": """Write the main landing page.

Hard requirements:
1. Be LONG and substantive. This page should feel like a mini-book chapter, not a README.
2. Start with a feature grid (<div class="grid chunk_summaries" markdown>).
3. Include at least 3 Mermaid diagrams:
   - A tri-brid pipeline flowchart (vector + sparse + graph -> fusion -> rerank -> results)
   - A sequence diagram for a typical /search request
   - A state diagram for indexing -> ready -> searching
4. Include a table that maps “What you want to do” to the correct docs page (architecture/retrieval/config/api/indexing/deploy/glossary).
5. Include a “Quick start” section with copy/paste commands and verification steps.
6. Include explicit pointers to the Pydantic source-of-truth file and the generated TypeScript type chain.
   - Refer to the source-of-truth file as inline code, or as an absolute GitHub link (NOT a relative link).
7. Include a section with the exact heading: `## Source of truth file` (this must exist for anchored links).
7. Include an “If this page is too long” collapsible (???) with a short reading path.
8. End with a troubleshooting FAQ (at least 8 items) linking to the right pages/anchors.
""",
    },
    "architecture": {
        "title": "Architecture",
        "output_path": "mkdocs/docs/architecture.md",
        "source_files": [
            "AGENTS.md",
            "server/main.py",
            "server/services/rag.py",
            "server/services/indexing.py",
            "server/retrieval/fusion.py",
            "server/db/postgres.py",
            "server/db/neo4j.py",
        ],
        "instruction": """Write an extremely detailed architecture page.

Hard requirements:
1. Explain the end-to-end dataflow for BOTH indexing and retrieval.
2. Include multiple Mermaid diagrams (flowchart + sequence + state).
3. Include a component table mapping responsibilities to concrete files/modules.
4. Include a “Config is the contract” section that explains the Pydantic -> generated TS derivation chain with examples.
5. Include an “Operational boundaries” section: what is per-corpus, what is global, what is cached, what is persisted.
6. Include failure modes and observability signals (what to check when X fails).

Required stable anchor headings (MUST be exact headings):
- `## Fusion methods`
- `## pgvector integration`
- `## Graph RAG using Neo4j`

CRITICAL:
- If you link to `glossary.md#frontend`, the anchor must be lowercase (`#frontend`).
""",
    },
    "retrieval/overview": {
        "title": "Retrieval Overview",
        "output_path": "mkdocs/docs/retrieval/overview.md",
        "source_files": [
            "server/retrieval/vector.py",
            "server/retrieval/sparse.py",
            "server/retrieval/graph.py",
            "server/retrieval/fusion.py",
            "server/retrieval/rerank.py",
            "server/models/tribrid_config_model.py",
        ],
        "instruction": """Write a deep retrieval overview.

Hard requirements:
1. Explain each retriever leg (vector/sparse/graph) with:
   - What signal it captures
   - Common query types it wins on
   - Cost and latency characteristics
   - Key configuration knobs (as tables)
2. Explain fusion strategies (RRF vs weighted) with worked examples and tables.
3. Explain reranking: when it helps, when it hurts, how to configure it.
4. Include at least 3 Mermaid diagrams (pipeline, detailed fusion, rerank sequence).
5. Include “Debugging relevance” and “Debugging latency” sections with step-by-step checklists.

CRITICAL LINKING RULES FOR THIS PAGE:
- This page lives at `retrieval/overview.md` (inside a subdirectory).
- Links to root-level pages MUST be prefixed with `../`:
  - `../architecture.md`, `../configuration.md`, `../api.md`, `../index.md`, `../indexing.md`, `../deploy.md`, `../glossary.md`
- Prefer `#anchor` links for within-page references.

Required stable anchor headings (MUST be exact headings):
- `## Fusion techniques`
""",
    },
    "configuration": {
        "title": "Configuration",
        "output_path": "mkdocs/docs/configuration.md",
        "source_files": [
            "AGENTS.md",
            "tribrid_config.json",
            "server/models/tribrid_config_model.py",
            "web/src/types/generated.ts",
            "scripts/generate_types.py",
        ],
        "instruction": """Write the configuration reference and mental model.

Hard requirements:
1. Explain “Pydantic is the law” and what that means for users and contributors.
2. Show how defaults/ranges are enforced, and how invalid configs fail (validation).
3. Include BIG tables for the most important config sections (retrieval/fusion/reranking/indexing/graph/embedding/chunking).
4. Include a section on type generation (pydantic2ts) and how the UI consumes generated types.
5. Include common config recipes (as tabs) for different corpora:
   - codebase search
   - docs search
   - mixed repo
6. Include “Anti-patterns” section (what NOT to do) as warnings.

Required stable anchor headings (MUST be exact headings):
- `## Fusion config`
- `## Indexing config`
- `## Embedding config`
- `## Graph storage config`
- `## Reranking`
""",
    },
    "api": {
        "title": "API",
        "output_path": "mkdocs/docs/api.md",
        "source_files": [
            "server/main.py",
            "server/api/search.py",
            "server/api/index.py",
            "server/api/config.py",
            "server/api/models.py",
            "server/api/health.py",
            "spec/backend/api_search.yaml",
            "spec/backend/api_index.yaml",
            "spec/backend/api_config.yaml",
            "spec/backend/api_health.yaml",
        ],
        "instruction": """Write a complete API reference page.

Hard requirements:
1. Enumerate endpoints grouped by domain (health, models, config, indexing, search).
2. For each endpoint: purpose, request schema, response schema, examples in tabs (curl + Python + TypeScript).
3. Include error handling guidance: common failure codes and what they mean.
4. Include performance notes: pagination/top-k, timeouts, reranker costs.
5. Include at least 2 Mermaid diagrams showing request lifecycles (search and indexing).
""",
    },
    "indexing": {
        "title": "Indexing",
        "output_path": "mkdocs/docs/indexing.md",
        "source_files": [
            "server/indexing/loader.py",
            "server/indexing/chunker.py",
            "server/indexing/embedder.py",
            "server/indexing/summarizer.py",
            "server/indexing/graph_builder.py",
            "server/models/tribrid_config_model.py",
        ],
        "instruction": """Write a deep indexing pipeline page.

Hard requirements:
1. Explain the pipeline stages: load -> chunk -> embed -> persist -> graph build -> summarize.
2. Include Mermaid diagrams (pipeline + state + failure-mode flow).
3. Include config tables for chunking/embedding/indexing/graph build.
4. Include “How to reindex safely” section with checklists and warnings.
5. Include troubleshooting section: common causes of missing chunks, bad embeddings, empty graphs.

Required stable anchor headings (MUST be exact headings):
- `## Chunking`

CRITICAL:
- The heading line MUST appear exactly as `## Chunking` (H2) somewhere in the page.
- Do NOT replace it with `### Chunk` or `## Chunking Configuration` or any other variant.
- All chunking-specific content, examples, and config tables must live under `## Chunking`.
""",
    },
    "deploy": {
        "title": "Deployment",
        "output_path": "mkdocs/docs/deploy.md",
        "source_files": [
            "Dockerfile",
            "docker-compose.yml",
            "infra/docker-compose.dev.yml",
            ".env.example",
            "start.sh",
        ],
        "instruction": """Write an operational deployment guide.

Hard requirements:
1. Cover local dev, docker compose, and environment configuration.
2. Include explicit tables for required env vars (from .env.example).
3. Include “Bring-up verification” checklists (health endpoints, DB connections, migrations if any).
4. Include resource sizing guidance (CPU/RAM/disk) for small/medium/large corpora.
5. Include at least 2 Mermaid diagrams (service topology + startup sequence).

Required stable anchor headings (MUST be exact headings):
- `## Neo4j installation`
""",
    },
    "glossary": {
        "title": "Glossary",
        "output_path": "mkdocs/docs/glossary.md",
        "source_files": [
            "AGENTS.md",
            "server/models/tribrid_config_model.py",
            "web/src/modules/tooltips.js",
        ],
        "instruction": """Write a large, practical glossary.

Hard requirements:
1. Define core terms (corpus/repo_id, chunk, embedding, reranker, fusion, RRF, BM25/FTS, pgvector, Neo4j entities/relationships).
2. For each term: definition, “why it matters”, and links to the best section elsewhere.
3. Include a “Config field index” section that maps terms to important Pydantic fields.
4. Use definition lists, tables, and admonitions for pitfalls and gotchas.

CRITICAL LINKING RULE:
- Do NOT create relative links to repo source files (like `server/models/tribrid_config_model.py`).
- If you need a clickable reference, use an absolute GitHub URL (blob/main/...).

Required stable anchor headings (MUST be exact headings):
- `## Frontend`
""",
    },
}


# =============================================================================
# DocBootstrapper class
# =============================================================================

class DocBootstrapper:
    """Generates documentation pages using OpenAI API."""

    def __init__(
        self,
        model: str = "gpt-5",
        max_tokens: int = 32000,
        *,
        verbosity: str = "high",
        reasoning_effort: str = "high",
        max_attempts: int = 2,
    ):
        """Initialize with OpenAI client.

        Args:
            model: OpenAI model to use (default: gpt-5)
            max_tokens: Maximum tokens for response (default: 32000)
            verbosity: GPT-5 text verbosity hint (low|medium|high)
            reasoning_effort: GPT-5 reasoning effort (minimal|low|medium|high)
            max_attempts: Max generation attempts per page (default: 2)
        """
        if not self._is_gpt5_model(model):
            raise ValueError(f"Only GPT-5 models are supported here (got: {model})")

        api_key = os.environ.get("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key) if api_key else None
        self.model = model
        self.max_tokens = max_tokens
        self.verbosity = verbosity
        self.reasoning_effort = reasoning_effort
        self.max_attempts = max_attempts
        self.project_root = Path(__file__).parent.parent.parent

    @staticmethod
    def _is_gpt5_model(model: str) -> bool:
        m = (model or "").strip().lower()
        return m.startswith("gpt-5")

    def _validate_generated_markdown(self, page_key: str, content: str) -> list[str]:
        """Return a list of validation issues for generated markdown."""
        issues: list[str] = []

        # Length heuristics: enforce non-trivial, long-form pages.
        lines = [ln for ln in (content or "").splitlines() if ln.strip()]
        if len(lines) < 180:
            issues.append(f"too short: only {len(lines)} non-empty lines (min 180)")

        # Material bells & whistles.
        if "<div class=\"grid" not in (content or ""):
            issues.append("missing feature grid (<div class=\"grid ...\">)")
        if ".md-button" not in (content or ""):
            issues.append("missing Material buttons (.md-button quick links)")
        if (content or "").count("```mermaid") < 2:
            issues.append("missing mermaid diagrams (need at least 2)")
        if (content or "").count("!!!") < 3:
            issues.append("missing admonitions (need at least 3)")
        if (content or "").count("===") < 3:
            issues.append("missing tabbed sections (need at least 3)")

        # No relative links to repo source files (MkDocs strict breaks on these).
        banned_rel_prefixes = ("server/", "web/", "scripts/", "infra/", "data/", "tests/")
        for pref in banned_rel_prefixes:
            if f"]({pref}" in (content or ""):
                issues.append(f"contains relative link to repo path: ]({pref}...) (must be inline code or GitHub URL)")
                break

        # Nested page linking correctness (MkDocs strict resolves relative to current dir)
        if page_key == "retrieval/overview":
            wrong_root_links = [
                "index.md",
                "architecture.md",
                "configuration.md",
                "api.md",
                "indexing.md",
                "deploy.md",
                "glossary.md",
            ]
            for tgt in wrong_root_links:
                if f"]({tgt}" in (content or ""):
                    issues.append(f"retrieval/overview.md must link to '../{tgt}', not '{tgt}'")
                    break
            if "](retrieval/overview.md" in (content or ""):
                issues.append("retrieval/overview.md must not link to 'retrieval/overview.md' (self-link resolves incorrectly)")

        # Stable anchors required by VALID_PAGES section.
        required_heading_by_page: dict[str, list[str]] = {
            "index": ["## Source of truth file", "## Troubleshooting FAQ"],
            "architecture": ["## Fusion methods", "## pgvector integration", "## Graph RAG using Neo4j"],
            "retrieval/overview": ["## Fusion techniques"],
            "configuration": [
                "## Fusion config",
                "## Indexing config",
                "## Embedding config",
                "## Graph storage config",
                "## Reranking",
            ],
            "indexing": ["## Chunking"],
            "deploy": ["## Neo4j installation"],
            "glossary": ["## Frontend"],
        }
        for heading in required_heading_by_page.get(page_key, []):
            if heading not in (content or ""):
                issues.append(f"missing required heading: {heading!r}")

        return issues

    def _read_source_files(self, source_files: list[str]) -> str:
        """Read and concatenate source files."""
        contents = []
        for file_path in source_files:
            full_path = self.project_root / file_path
            if full_path.exists():
                try:
                    content = full_path.read_text()
                    # Truncate very large files
                    max_chars = 200000 if file_path.endswith("tribrid_config_model.py") else 75000
                    if len(content) > max_chars:
                        content = content[:max_chars] + "\n\n... [truncated] ..."
                    contents.append(f"=== FILE: {file_path} ===\n{content}\n")
                except Exception as e:
                    contents.append(f"=== FILE: {file_path} ===\nError reading: {e}\n")
            else:
                contents.append(f"=== FILE: {file_path} ===\nFile not found\n")
        return "\n".join(contents)

    def generate_page(self, page_key: str, dry_run: bool = False) -> Optional[str]:
        """Generate a single documentation page.

        Args:
            page_key: Key from DOC_PAGES dict
            dry_run: If True, print what would be done without calling API

        Returns:
            Generated markdown content, or None if dry_run
        """
        if page_key not in DOC_PAGES:
            print(f"ERROR: Unknown page key: {page_key}")
            print(f"Available pages: {', '.join(DOC_PAGES.keys())}")
            return None

        page_config = DOC_PAGES[page_key]
        source_content = self._read_source_files(page_config["source_files"])

        user_prompt = f"""Generate documentation for: {page_config['title']}

{VALID_PAGES}

SOURCE FILES:
{source_content}

INSTRUCTIONS:
{page_config['instruction']}
"""

        if dry_run:
            print(f"\n{'='*60}")
            print(f"DRY RUN: {page_key}")
            print(f"{'='*60}")
            print(f"Title: {page_config['title']}")
            print(f"Output: {page_config['output_path']}")
            print(f"Source files: {', '.join(page_config['source_files'])}")
            print(f"Model: {self.model}")
            print(f"Max tokens: {self.max_tokens}")
            print(f"\nPrompt preview (first 500 chars):")
            print(user_prompt[:500] + "...")
            return None

        if self.client is None:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        print(f"Generating: {page_key} -> {page_config['output_path']}")

        content: str | None = None
        last_issues: list[str] = []
        issues: list[str] = []

        for attempt in range(1, self.max_attempts + 1):
            attempt_prompt = user_prompt
            if last_issues:
                attempt_prompt = (
                    attempt_prompt
                    + "\n\n"
                    + "REVISION REQUIRED:\n"
                    + "The previous output failed validation. Rewrite the ENTIRE page and fix ALL issues:\n"
                    + "\n".join([f"- {issue}" for issue in last_issues])
                    + "\n\nRemember: output ONLY markdown for the full page."
                )

            kwargs: dict = {
                "model": self.model,
                "instructions": SYSTEM_PROMPT,
                "input": attempt_prompt,
                "max_output_tokens": self.max_tokens,
                "text": {"verbosity": self.verbosity},
            }
            if self._is_gpt5_model(self.model):
                kwargs["reasoning"] = {"effort": self.reasoning_effort}

            # Use the Responses API (required)
            response = self.client.responses.create(**kwargs)
            content = response.output_text

            issues = self._validate_generated_markdown(page_key, content or "")
            if not issues:
                last_issues = []
                break
            last_issues = issues

        if not content:
            raise RuntimeError(f"Empty content returned for page: {page_key}")
        if issues:
            raise RuntimeError(
                f"Validation failed for page '{page_key}' after {self.max_attempts} attempts:\n"
                + "\n".join([f"- {issue}" for issue in issues])
            )

        # Write to output file
        output_path = self.project_root / page_config["output_path"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)

        print(f"  ✓ Written to {page_config['output_path']}")
        return content

    def generate(self, pages: list[str], dry_run: bool = False) -> None:
        """Generate multiple documentation pages.

        Args:
            pages: List of page keys to generate, or ["all"] for all pages
            dry_run: If True, print what would be done without calling API
        """
        if "all" in pages:
            pages = list(DOC_PAGES.keys())

        for page_key in pages:
            self.generate_page(page_key, dry_run=dry_run)


# =============================================================================
# NOTE ON BOOTSTRAP VS AUTOPILOT
# =============================================================================
#
# This file is a deterministic "bootstrapper" that generates a fixed set of
# pages. It is intentionally NOT the full Docs‑Autopilot workflow where the
# model decides the doc structure. For the model‑driven workflow, use:
# scripts/docs_ai/docs_autopilot_enhanced.py


def list_pages() -> None:
    """Print all available documentation pages."""
    print("Available documentation pages:\n")
    for key, config in DOC_PAGES.items():
        print(f"  {key}")
        print(f"    Title: {config['title']}")
        print(f"    Output: {config['output_path']}")
        print(f"    Sources: {', '.join(config['source_files'])}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Generate TriBridRAG documentation using AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --list                          # List all available pages
  %(prog)s --dry-run --page index          # Preview without generating
  %(prog)s --page index                    # Generate index page
  %(prog)s --page index --page retrieval/overview       # Generate multiple
  %(prog)s --all                           # Generate all pages
  %(prog)s --all --model gpt-5             # Use specific model
        """
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available documentation pages"
    )
    parser.add_argument(
        "--page",
        action="append",
        dest="pages",
        metavar="PAGE",
        help="Page to generate (can be specified multiple times)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate all documentation pages"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be generated without calling API"
    )
    parser.add_argument(
        "--model",
        default="gpt-5",
        help="OpenAI model to use (default: gpt-5). Use GPT-5 series only."
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=32000,
        help="Maximum tokens for response (default: 32000)"
    )
    parser.add_argument(
        "--verbosity",
        choices=["low", "medium", "high"],
        default="high",
        help="GPT-5 verbosity hint (default: high)"
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=["minimal", "low", "medium", "high"],
        default="high",
        help="GPT-5 reasoning effort (default: high)"
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=2,
        help="Max generation attempts per page if validation fails (default: 2)"
    )

    args = parser.parse_args()

    if args.list:
        list_pages()
        return

    if not args.pages and not args.all:
        parser.print_help()
        print("\nERROR: Specify --page PAGE or --all")
        sys.exit(1)

    pages = args.pages or []
    if args.all:
        pages = ["all"]

    try:
        bootstrapper = DocBootstrapper(
            model=args.model,
            max_tokens=args.max_tokens,
            verbosity=args.verbosity,
            reasoning_effort=args.reasoning_effort,
            max_attempts=args.max_attempts,
        )
        bootstrapper.generate(pages, dry_run=args.dry_run)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
