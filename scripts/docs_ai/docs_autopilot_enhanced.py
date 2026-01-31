#!/usr/bin/env python3
"""
Enhanced Docs Autopilot for TriBridRAG.

Generates comprehensive documentation using OpenAI GPT-4 with full context awareness.
Unlike bootstrap_docs.py, this script does NOT have a restrictive VALID_PAGES list.
It gathers comprehensive context from the codebase and lets the LLM generate
whatever documentation the codebase needs.

Usage:
    python scripts/docs_ai/docs_autopilot_enhanced.py --regenerate-all
    python scripts/docs_ai/docs_autopilot_enhanced.py --dry-run
    python scripts/docs_ai/docs_autopilot_enhanced.py --full-scan
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import requests
    import yaml
except ImportError:
    print("ERROR: Missing dependencies. Run: pip install requests pyyaml")
    sys.exit(1)


@dataclass
class DocumentationContext:
    """Comprehensive context for documentation generation."""

    claude_md: str = ""
    tribrid_config: str = ""
    models_json: str = ""
    glossary_json: str = ""
    api_endpoints: dict[str, str] = field(default_factory=dict)
    retrieval_modules: dict[str, str] = field(default_factory=dict)
    db_modules: dict[str, str] = field(default_factory=dict)
    indexing_modules: dict[str, str] = field(default_factory=dict)
    docker_compose: str = ""
    readme: str = ""
    existing_docs: dict[str, str] = field(default_factory=dict)
    all_files: list[str] = field(default_factory=list)


class EnhancedDocsAutopilot:
    """Enhanced documentation automation with LLM integration for TriBridRAG."""

    def __init__(self, repo_root: Path | None = None):
        self.repo_root = Path(repo_root or os.getcwd())
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.docs_dir = self.repo_root / "mkdocs" / "docs"

        # Material for MkDocs features to utilize
        self.material_features = [
            "navigation.instant",
            "navigation.tabs",
            "navigation.top",
            "navigation.sections",
            "search.suggest",
            "search.highlight",
            "content.code.copy",
            "content.code.annotate",
        ]

    def _read_file(self, path: Path, max_chars: int = 50000) -> str:
        """Read file safely with size limit."""
        try:
            content = path.read_text(encoding="utf-8")
            if len(content) > max_chars:
                content = content[:max_chars] + "\n... [truncated]"
            return content
        except Exception:
            return ""

    def gather_comprehensive_context(self) -> DocumentationContext:
        """Gather comprehensive context from the entire codebase."""
        print("  Gathering CLAUDE.md...")
        claude_md = self._read_file(self.repo_root / "CLAUDE.md", max_chars=15000)

        print("  Gathering tribrid_config_model.py...")
        tribrid_config = self._read_file(
            self.repo_root / "server" / "models" / "tribrid_config_model.py",
            max_chars=30000,
        )

        print("  Gathering models.json...")
        models_json = self._read_file(
            self.repo_root / "data" / "models.json", max_chars=10000
        )

        print("  Gathering glossary.json...")
        glossary_json = self._read_file(
            self.repo_root / "data" / "glossary.json", max_chars=10000
        )

        print("  Gathering API endpoints...")
        api_endpoints = self._gather_api_modules()

        print("  Gathering retrieval modules...")
        retrieval_modules = self._gather_retrieval_modules()

        print("  Gathering database modules...")
        db_modules = self._gather_db_modules()

        print("  Gathering indexing modules...")
        indexing_modules = self._gather_indexing_modules()

        print("  Gathering docker-compose.yml...")
        docker_compose = self._read_file(
            self.repo_root / "docker-compose.yml", max_chars=5000
        )

        print("  Gathering README.md...")
        readme = self._read_file(self.repo_root / "README.md", max_chars=10000)

        print("  Analyzing existing docs...")
        existing_docs = self._analyze_existing_docs()

        print("  Getting file list...")
        all_files = self._get_all_files()

        return DocumentationContext(
            claude_md=claude_md,
            tribrid_config=tribrid_config,
            models_json=models_json,
            glossary_json=glossary_json,
            api_endpoints=api_endpoints,
            retrieval_modules=retrieval_modules,
            db_modules=db_modules,
            indexing_modules=indexing_modules,
            docker_compose=docker_compose,
            readme=readme,
            existing_docs=existing_docs,
            all_files=all_files,
        )

    def _gather_api_modules(self) -> dict[str, str]:
        """Gather API router modules."""
        modules = {}
        api_path = self.repo_root / "server" / "api"
        if api_path.exists():
            for py_file in api_path.glob("*.py"):
                if py_file.name != "__init__.py":
                    content = self._read_file(py_file, max_chars=5000)
                    modules[py_file.name] = content
        return modules

    def _gather_retrieval_modules(self) -> dict[str, str]:
        """Gather retrieval pipeline modules."""
        modules = {}
        retrieval_path = self.repo_root / "server" / "retrieval"
        if retrieval_path.exists():
            for py_file in retrieval_path.glob("*.py"):
                if py_file.name != "__init__.py":
                    content = self._read_file(py_file, max_chars=5000)
                    modules[py_file.name] = content
        return modules

    def _gather_db_modules(self) -> dict[str, str]:
        """Gather database modules."""
        modules = {}
        db_path = self.repo_root / "server" / "db"
        if db_path.exists():
            for py_file in db_path.glob("*.py"):
                if py_file.name != "__init__.py":
                    content = self._read_file(py_file, max_chars=5000)
                    modules[py_file.name] = content
        return modules

    def _gather_indexing_modules(self) -> dict[str, str]:
        """Gather indexing modules."""
        modules = {}
        indexing_path = self.repo_root / "server" / "indexing"
        if indexing_path.exists():
            for py_file in indexing_path.glob("*.py"):
                if py_file.name != "__init__.py":
                    content = self._read_file(py_file, max_chars=3000)
                    modules[py_file.name] = content
        return modules

    def _analyze_existing_docs(self) -> dict[str, str]:
        """Analyze existing documentation structure."""
        docs = {}
        if self.docs_dir.exists():
            for doc_file in self.docs_dir.rglob("*.md"):
                rel_path = doc_file.relative_to(self.docs_dir)
                # Get first 500 chars to understand the document
                content = self._read_file(doc_file, max_chars=500)
                docs[str(rel_path)] = content
        return docs

    def _get_all_files(self) -> list[str]:
        """Get list of all important files in the repository."""
        try:
            cmd = "git ls-files"
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, cwd=self.repo_root
            )
            if result.returncode == 0:
                all_files = [
                    line.strip() for line in result.stdout.splitlines() if line.strip()
                ]
                # Filter to important files
                important_extensions = {
                    ".py",
                    ".ts",
                    ".tsx",
                    ".js",
                    ".jsx",
                    ".md",
                    ".yml",
                    ".yaml",
                    ".json",
                }
                important_files = []
                for f in all_files:
                    if any(f.endswith(ext) for ext in important_extensions):
                        if (
                            "node_modules" not in f
                            and "__pycache__" not in f
                            and ".tests/" not in f
                        ):
                            important_files.append(f)
                return important_files[:300]
        except Exception as e:
            print(f"  Warning: Could not get file list: {e}")
        return []

    def _create_system_prompt(self) -> str:
        """Create the system prompt for the LLM - TriBridRAG specific."""
        return """You are writing documentation for TriBridRAG, a tri-brid RAG engine combining:
- Vector search (pgvector in PostgreSQL)
- Sparse search (PostgreSQL Full-Text Search/BM25)
- Graph search (Neo4j for entity relationships)

KEY ARCHITECTURE POINTS:
1. THREE search legs fused together (hence "tri-brid")
2. Pydantic is THE LAW - all config flows from tribrid_config_model.py
3. TypeScript types are GENERATED from Pydantic (never hand-written)
4. pgvector replaces Qdrant (simpler, same Postgres instance)
5. Neo4j for graph RAG - entities, relationships, communities
6. Fusion methods: RRF (Reciprocal Rank Fusion) or weighted scoring
7. Reranking: local models, cloud APIs, or trained models

BANNED TERMS (DO NOT USE):
- "Qdrant" - we use pgvector
- "Redis" - removed from project
- "LangChain" - use LangGraph directly if needed
- "cards" - use "chunk_summaries"
- "AGRO" or "agro" - this is TriBridRAG
- "vivified" - wrong project

MKDOCS MATERIAL FORMATTING (MANDATORY):
Reference: https://squidfunk.github.io/mkdocs-material/reference/

You MUST use these components where appropriate:

1. ADMONITIONS (Use liberally!):
!!! note "Implementation Note"
    Technical notes and implementation details.

!!! warning "Important"
    Critical information the user must know.

!!! tip "Pro Tip"
    Helpful tips and best practices.

??? note "Collapsible Section"
    Use ??? for collapsible content.

2. CODE BLOCKS WITH TABS:
=== "Python"
    ```python
    # Python code here
    ```

=== "curl"
    ```bash
    # curl examples
    ```

3. MERMAID DIAGRAMS (use for architecture and flows):
```mermaid
flowchart LR
    A[Query] --> B[Vector Search]
    A --> C[Sparse Search]
    A --> D[Graph Search]
    B --> E[Fusion]
    C --> E
    D --> E
    E --> F[Reranker]
    F --> G[Results]
```

4. DATA TABLES for configuration options and comparisons

5. DEFINITION LISTS for parameters:
`term`
:   Definition of the term

6. Use relative links between pages (e.g., ../features/tribrid-search.md)

OUTPUT FORMAT:
Return a JSON object where keys are file paths (relative to docs/) and values are the complete markdown content.
Example: {"index.md": "# Welcome\\n\\nContent here...", "features/fusion.md": "# Fusion\\n\\n..."}

IMPORTANT:
- Generate whatever documentation the codebase needs based on the context provided
- DO NOT limit yourself to a fixed list of pages
- Create pages for any topic that deserves its own documentation
- Ensure all cross-references use correct relative paths
- Every major feature should have its own page
- Start each page with a level-1 heading (# Title)
- Do not include YAML frontmatter
"""

    def _create_user_prompt(self, context: DocumentationContext) -> str:
        """Create the user prompt with full context."""
        prompt_parts = [
            "Generate comprehensive documentation for TriBridRAG based on the following context:",
            "",
            "## Project Overview (from CLAUDE.md)",
            context.claude_md[:8000],
            "",
            "## Pydantic Config Model (THE LAW - tribrid_config_model.py)",
            context.tribrid_config[:15000],
            "",
            "## Model Definitions (data/models.json)",
            context.models_json[:5000],
            "",
            "## README.md",
            context.readme[:5000],
            "",
            "## Docker Compose",
            context.docker_compose[:3000],
            "",
            "## API Endpoints",
        ]

        for name, content in list(context.api_endpoints.items())[:10]:
            prompt_parts.append(f"### {name}")
            prompt_parts.append(content[:2000])
            prompt_parts.append("")

        prompt_parts.extend(
            [
                "",
                "## Retrieval Modules",
            ]
        )

        for name, content in context.retrieval_modules.items():
            prompt_parts.append(f"### {name}")
            prompt_parts.append(content[:2000])
            prompt_parts.append("")

        prompt_parts.extend(
            [
                "",
                "## Database Modules",
            ]
        )

        for name, content in context.db_modules.items():
            prompt_parts.append(f"### {name}")
            prompt_parts.append(content[:2000])
            prompt_parts.append("")

        prompt_parts.extend(
            [
                "",
                "## Existing Documentation Structure",
                f"Current files: {', '.join(context.existing_docs.keys())}",
                "",
                "## Repository File Structure",
                f"Total important files: {len(context.all_files)}",
                "Key directories: server/api/, server/retrieval/, server/db/, server/indexing/, web/src/",
                "",
                "## YOUR TASK",
                "",
                "Analyze the codebase context above and generate comprehensive documentation.",
                "YOU decide what pages are needed based on what you see in the code.",
                "Create pages for every feature, API, configuration option, and concept that deserves documentation.",
                "",
                "CRITICAL: Every link you create MUST point to a page you are also creating.",
                "If you link to ./foo.md, you must include 'foo.md' in your output.",
                "",
                "Return JSON: {\"path/to/file.md\": \"# Title\\n\\nContent...\", ...}",
            ]
        )

        return "\n".join(prompt_parts)

    def _call_openai_api(self, system_prompt: str, user_prompt: str) -> str:
        """Call OpenAI API with the prompts, with basic 429 backoff and CI-safe soft-fail."""
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }

        # Primary and fallback models
        primary_model = os.getenv("OPENAI_MODEL", "gpt-4o")
        fallback_model = "gpt-4o-mini"

        def build_payload(model: str) -> dict[str, Any]:
            return {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 16000,
                "response_format": {"type": "json_object"},
            }

        def post_with_retries(
            model: str, attempts: int = 4, base_delay: float = 5.0
        ) -> str | None:
            print(f"  Using OpenAI model: {model}")
            payload = build_payload(model)
            for i in range(attempts):
                try:
                    resp = requests.post(url, headers=headers, json=payload, timeout=300)
                    if resp.status_code == 429:
                        wait = base_delay * (2**i)
                        print(
                            f"  Rate limited (429). Retrying in {wait:.1f}s... [{i+1}/{attempts}]"
                        )
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()
                    result = resp.json()
                    return result["choices"][0]["message"]["content"]
                except requests.exceptions.HTTPError as he:
                    if hasattr(he, "response") and he.response.status_code == 429:
                        wait = base_delay * (2**i)
                        print(f"  Rate limited. Retrying in {wait:.1f}s...")
                        time.sleep(wait)
                        continue
                    print(f"  HTTP error from OpenAI: {he}")
                    return None
                except Exception as e:
                    wait = base_delay * (2**i)
                    print(
                        f"  Error calling OpenAI ({type(e).__name__}): {e}. Retrying in {wait:.1f}s..."
                    )
                    time.sleep(wait)
            return None

        # Try primary, then fallback
        resp_text = post_with_retries(primary_model)
        if resp_text is None:
            print(f"  Attempting fallback with {fallback_model}...")
            resp_text = post_with_retries(fallback_model)

        # If still failing in CI, soft-fail with empty updates
        if resp_text is None:
            if os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("CI"):
                print(
                    "  OpenAI API unavailable; skipping documentation generation in CI."
                )
                return "{}"
            raise RuntimeError(
                "Failed to generate documentation via OpenAI API after retries"
            )

        return resp_text

    def _parse_llm_response(self, response: str) -> dict[str, str]:
        """Parse the LLM response to extract documentation updates."""
        try:
            # Try to parse as JSON first
            docs = json.loads(response)
            if isinstance(docs, dict):
                return docs
        except json.JSONDecodeError as e:
            print(f"  Warning: JSON parse error: {e}")
            # Try to extract JSON from markdown code block
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
            if json_match:
                try:
                    docs = json.loads(json_match.group(1))
                    if isinstance(docs, dict):
                        return docs
                except json.JSONDecodeError:
                    pass

        print("  Warning: Could not parse LLM response as JSON")
        return {}

    def generate_documentation_with_llm(
        self, context: DocumentationContext
    ) -> dict[str, str]:
        """Generate documentation using OpenAI GPT-4."""
        system_prompt = self._create_system_prompt()
        user_prompt = self._create_user_prompt(context)

        print("  Calling OpenAI API (this may take a minute)...")
        response = self._call_openai_api(system_prompt, user_prompt)

        print("  Parsing response...")
        docs_updates = self._parse_llm_response(response)

        print(f"  Generated {len(docs_updates)} documentation pages")
        return docs_updates

    def _generate_navigation(self, docs_updates: dict[str, str]) -> list:
        """Generate navigation structure dynamically from whatever was generated."""
        nav: list[Any] = []

        # Group files by directory
        sections: dict[str, list[str]] = {}
        for path in sorted(docs_updates.keys()):
            if "/" in path:
                section = path.split("/")[0]
                if section not in sections:
                    sections[section] = []
                sections[section].append(path)
            else:
                # Root level file
                if path == "index.md":
                    nav.append({"Home": "index.md"})
                else:
                    # Extract title from first heading
                    content = docs_updates[path]
                    title = self._extract_title(content, path)
                    nav.append({title: path})

        # Add each section
        for section, files in sections.items():
            section_nav = []
            for path in files:
                content = docs_updates[path]
                title = self._extract_title(content, path)
                section_nav.append({title: path})
            if section_nav:
                # Title case the section name
                section_title = section.replace("-", " ").replace("_", " ").title()
                nav.append({section_title: section_nav})

        return nav

    def _extract_title(self, content: str, path: str) -> str:
        """Extract title from markdown content or derive from path."""
        # Look for first # heading
        for line in content.split("\n")[:10]:
            if line.startswith("# "):
                return line[2:].strip()
        # Fallback: derive from filename
        filename = path.split("/")[-1].replace(".md", "")
        return filename.replace("-", " ").replace("_", " ").title()

    def update_mkdocs_config(self, docs_updates: dict[str, str]) -> dict[str, Any]:
        """Update mkdocs.yml configuration with generated nav."""
        nav = self._generate_navigation(docs_updates)

        config: dict[str, Any] = {
            "site_name": "TriBridRAG Docs",
            "site_url": "https://dmontgomery40.github.io/tribrid-rag/",
            "repo_url": "https://github.com/DMontgomery40/tribrid-rag",
            "edit_uri": "edit/main/mkdocs/docs/",
            "docs_dir": "mkdocs/docs",
            "theme": {
                "name": "material",
                "language": "en",
                "features": self.material_features,
                "palette": [
                    {
                        "scheme": "slate",
                        "primary": "teal",
                        "accent": "amber",
                        "toggle": {
                            "icon": "material/brightness-4",
                            "name": "Switch to light mode",
                        },
                    },
                    {
                        "scheme": "default",
                        "primary": "teal",
                        "accent": "amber",
                        "toggle": {
                            "icon": "material/brightness-7",
                            "name": "Switch to dark mode",
                        },
                    },
                ],
            },
            "markdown_extensions": [
                "admonition",
                "attr_list",
                "def_list",
                "footnotes",
                "md_in_html",
                "pymdownx.details",
                "pymdownx.emoji",
                {"pymdownx.highlight": {"anchor_linenums": True}},
                "pymdownx.inlinehilite",
                "pymdownx.keys",
                "pymdownx.mark",
                "pymdownx.smartsymbols",
                "pymdownx.snippets",
                {
                    "pymdownx.superfences": {
                        "custom_fences": [
                            {"name": "mermaid", "class": "mermaid"}
                        ]
                    }
                },
                {"pymdownx.tabbed": {"alternate_style": True}},
                "tables",
                {"toc": {"permalink": True}},
            ],
            "plugins": ["search", "glightbox"],
            "extra_javascript": [
                "https://unpkg.com/mermaid@11/dist/mermaid.min.js",
                "assets/js/mermaid-init.js",
            ],
            "nav": nav,
        }

        return config

    def write_documentation_files(self, docs_updates: dict[str, str]) -> None:
        """Write documentation files to disk."""
        self.docs_dir.mkdir(parents=True, exist_ok=True)

        for file_path, content in docs_updates.items():
            full_path = self.docs_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            print(f"  Wrote: {file_path}")

    def write_mkdocs_config(self, config: dict[str, Any]) -> None:
        """Write mkdocs.yml configuration."""
        mkdocs_path = self.repo_root / "mkdocs.yml"

        # Custom YAML representer to avoid anchors/aliases
        class NoAliasDumper(yaml.SafeDumper):
            def ignore_aliases(self, data: Any) -> bool:
                return True

        with open(mkdocs_path, "w") as f:
            yaml.dump(
                config,
                f,
                Dumper=NoAliasDumper,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        print(f"  Updated: mkdocs.yml")

    def run(self, dry_run: bool = False) -> None:
        """Run the full documentation generation pipeline."""
        print("\n" + "=" * 60)
        print("TriBridRAG Enhanced Docs Autopilot")
        print("=" * 60)

        print("\n[1/4] Gathering comprehensive context...")
        context = self.gather_comprehensive_context()

        if dry_run:
            print("\n" + "=" * 60)
            print("DRY RUN - Context gathered (LLM decides what pages to create)")
            print("=" * 60)
            print(f"  CLAUDE.md: {len(context.claude_md)} chars")
            print(f"  tribrid_config_model.py: {len(context.tribrid_config)} chars")
            print(f"  models.json: {len(context.models_json)} chars")
            print(f"  API modules: {list(context.api_endpoints.keys())}")
            print(f"  Retrieval modules: {list(context.retrieval_modules.keys())}")
            print(f"  DB modules: {list(context.db_modules.keys())}")
            print(f"  Existing docs: {list(context.existing_docs.keys())}")
            print(f"  Total repo files: {len(context.all_files)}")
            print("\n  Run without --dry-run to generate docs (requires OPENAI_API_KEY)")
            return

        print("\n[2/4] Generating documentation with AI...")
        docs_updates = self.generate_documentation_with_llm(context)

        if not docs_updates:
            print("\n  No documentation generated. Check API key and try again.")
            return

        print("\n[3/4] Writing documentation files...")
        self.write_documentation_files(docs_updates)

        print("\n[4/4] Updating mkdocs.yml configuration...")
        config = self.update_mkdocs_config(docs_updates)
        self.write_mkdocs_config(config)

        print("\n" + "=" * 60)
        print("Documentation generation complete!")
        print("=" * 60)
        print("\nNext steps:")
        print("  1. Review the generated documentation")
        print("  2. Run 'mkdocs serve' to preview")
        print("  3. Check for any WARNING lines about broken links")
        print("  4. Commit and push changes")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Enhanced Docs Autopilot for TriBridRAG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --regenerate-all    # Full regeneration of all docs
  %(prog)s --dry-run           # Preview what would be generated
  %(prog)s --full-scan         # Alias for --regenerate-all
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write files, just show what would be done",
    )
    parser.add_argument(
        "--regenerate-all",
        action="store_true",
        help="Regenerate all documentation from entire codebase",
    )
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="Scan entire repository (alias for --regenerate-all)",
    )

    args = parser.parse_args()

    autopilot = EnhancedDocsAutopilot()
    autopilot.run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
