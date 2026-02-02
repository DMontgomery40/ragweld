#!/usr/bin/env python3
"""
Enhanced Docs Autopilot for TriBridRAG
Generates comprehensive documentation using OpenAI GPT-5 (Responses API) with full context awareness

TriBridRAG is a tri-brid RAG engine combining:
- Vector search (pgvector in PostgreSQL)
- Sparse search (PostgreSQL FTS/BM25)
- Graph search (Neo4j)
"""

from __future__ import annotations

import os
import re
import json
import subprocess
import shlex
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
import requests
from dataclasses import dataclass, field


_MERMAID_FENCE_RE = re.compile(r"```mermaid\s*\n(?P<code>[\s\S]*?)\n```", re.MULTILINE)


def _normalize_mermaid_v11_code(code: str) -> str:
    """
    Normalize Mermaid flowchart syntax to reduce Mermaid v11 parse errors.

    This is intentionally conservative and only fixes common, mechanical issues:
    - `\\n` line breaks must be inside quoted labels: `A[foo\\nbar]` -> `A[\"foo\\nbar\"]`
    - `A[foo]\\nbar` -> `A[\"foo\\nbar\"]`
    - Endpoint tokens like `/metrics` must NOT be node IDs: `--> /metrics` -> `--> METRICS[\"/metrics\"]`
    - `subgraph` titles with spaces should be quoted: `subgraph Foo Bar` -> `subgraph \"Foo Bar\"`
    """

    fixed = code

    # 1) Quote subgraph titles that contain spaces and are not already quoted / bracketed.
    lines: list[str] = []
    for line in fixed.splitlines():
        m = re.match(r"^(\s*)subgraph\s+([^\[\"\n]+)$", line)
        if m:
            indent, title = m.group(1), m.group(2).strip()
            if " " in title and not title.startswith('"') and "[" not in title:
                line = f'{indent}subgraph "{title}"'
        lines.append(line)
    fixed = "\n".join(lines)

    # 2) Replace bare endpoint tokens used as node IDs.
    endpoint_nodes = {
        "/metrics": "METRICS",
        "/ready": "READY",
        "/health": "HEALTH",
    }
    for endpoint, node_id in endpoint_nodes.items():
        # ... --> /metrics
        fixed = re.sub(
            rf"(-->)\s*{re.escape(endpoint)}\s*$",
            rf'\1 {node_id}["{endpoint}"]',
            fixed,
            flags=re.MULTILINE,
        )
        # /metrics --> ...
        fixed = re.sub(
            rf"^(\s*){re.escape(endpoint)}(\s*-->)",
            rf'\1{node_id}["{endpoint}"]\2',
            fixed,
            flags=re.MULTILINE,
        )

    # 3) Quote labels that contain a literal "\\n" inside brackets.
    #    A[foo\nbar] -> A["foo\nbar"]
    fixed = re.sub(
        r'(\b[A-Za-z][A-Za-z0-9_]*)\[(?!")(\s*[^\]]*\\n[^\]]*)\]',
        r'\1["\2"]',
        fixed,
    )

    # 4) Merge the invalid pattern: A[foo]\\nbar -> A["foo\\nbar"]
    fixed = re.sub(
        r'(\b[A-Za-z][A-Za-z0-9_]*)\[([^\]]+)\]\\n([^\n]+)$',
        r'\1["\2\\n\3"]',
        fixed,
        flags=re.MULTILINE,
    )

    return fixed


def normalize_mermaid_v11_markdown(markdown: str) -> Tuple[str, int]:
    """Normalize Mermaid blocks in markdown. Returns (updated_markdown, blocks_changed)."""

    blocks_changed = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal blocks_changed
        code = match.group("code")
        normalized = _normalize_mermaid_v11_code(code)
        if normalized != code:
            blocks_changed += 1
        return f"```mermaid\n{normalized}\n```"

    updated = _MERMAID_FENCE_RE.sub(_replace, markdown or "")
    return updated, blocks_changed


@dataclass
class DocumentationContext:
    """Comprehensive context for documentation generation

    This dataclass holds all the context gathered from the TriBridRAG codebase
    that will be fed to the LLM for documentation generation.
    """

    # Core project files
    claude_md: str = ""                      # CLAUDE.md - project instructions
    tribrid_config: str = ""                 # tribrid_config_model.py - THE source of truth
    models_json: str = ""                    # data/models.json - LLM/embedding definitions
    glossary_json: str = ""                  # data/glossary.json - tooltip definitions

    # Backend modules
    api_endpoints: Dict[str, str] = field(default_factory=dict)      # server/api/*.py
    retrieval_modules: Dict[str, str] = field(default_factory=dict)  # server/retrieval/*.py
    db_modules: Dict[str, str] = field(default_factory=dict)         # server/db/*.py
    indexing_modules: Dict[str, str] = field(default_factory=dict)   # server/indexing/*.py
    services_modules: Dict[str, str] = field(default_factory=dict)   # server/services/*.py

    # Frontend modules
    web_components: List[str] = field(default_factory=list)  # web/src/components/**/*.tsx
    stores: Dict[str, str] = field(default_factory=dict)     # web/src/stores/*.ts
    hooks: Dict[str, str] = field(default_factory=dict)      # web/src/hooks/*.ts

    # Configuration and environment
    docker_compose: str = ""                 # docker-compose.yml
    env_example: str = ""                    # .env.example

    # Documentation
    readme: str = ""                         # README.md
    existing_docs: Dict[str, str] = field(default_factory=dict)  # mkdocs/docs/**/*.md

    # Git info
    recent_changes: List[str] = field(default_factory=list)
    all_files: List[str] = field(default_factory=list)


class EnhancedDocsAutopilot:
    """Enhanced documentation automation with LLM integration for TriBridRAG"""

    def __init__(self, repo_root: Path = None):
        self.repo_root = Path(repo_root or os.getcwd())
        self.docs_dir = self.repo_root / "mkdocs" / "docs"

        # Load local environment variables from `.env` (if present).
        # This helps local runs without requiring `export OPENAI_API_KEY=...`.
        try:
            from dotenv import load_dotenv

            load_dotenv(dotenv_path=self.repo_root / ".env", override=False)
        except Exception:
            pass

        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.github_token = os.getenv("GITHUB_TOKEN")

        # Content filtering patterns - exclude internal plans and runbooks
        self.exclude_patterns = [
            r"phase\s*\d+",
            r"v\d+\s*(plan|runbook)",
            r"internal[-_]?plan",
            r"TODO[-_]?plan",
            r"migration[-_]?plan",
            r"dev[-_]?mode[-_]?only",
            r"WAVI[-_]?",              # Personal health data
            r"brain[-_]?scan",         # Personal health data
        ]

        # Banned terms for TriBridRAG - these should NOT appear in docs
        self.banned_terms = [
            "qdrant",
            "redis",
            "langchain",
            "cards",           # Use chunk_summaries
            "golden questions", # Use eval_dataset
            "ranker",          # Use reranker
            "profiles",        # Removed
            "onboarding",      # Removed
        ]

        # Material for MkDocs features to utilize
        self.material_features = [
            "navigation.instant",
            "navigation.tracking",
            "navigation.tabs",
            "navigation.sections",
            "navigation.expand",
            "navigation.indexes",
            "navigation.top",
            "toc.follow",
            "toc.integrate",
            "content.code.copy",
            "content.code.annotate",
            "content.tabs.link",
            "content.tooltips",
            "search.suggest",
            "search.highlight",
            "search.share",
        ]

    def gather_comprehensive_context(self, base_ref: str = None) -> DocumentationContext:
        """Gather comprehensive context from the entire TriBridRAG codebase"""

        print("  📖 Reading CLAUDE.md...")
        claude_md = self._read_file(self.repo_root / "CLAUDE.md")
        claude_md = self._filter_sensitive_content(claude_md)

        print("  📐 Reading tribrid_config_model.py (source of truth)...")
        tribrid_config = self._read_file(
            self.repo_root / "server" / "models" / "tribrid_config_model.py",
        )

        print("  🤖 Reading models.json...")
        models_json = self._read_file(self.repo_root / "data" / "models.json")

        print("  📚 Reading glossary.json...")
        glossary_json = self._read_file(self.repo_root / "data" / "glossary.json")

        print("  🔌 Analyzing API endpoints...")
        api_endpoints = self._analyze_directory(self.repo_root / "server" / "api", "*.py")

        print("  🔍 Analyzing retrieval modules...")
        retrieval_modules = self._analyze_directory(self.repo_root / "server" / "retrieval", "*.py")

        print("  💾 Analyzing database modules...")
        db_modules = self._analyze_directory(self.repo_root / "server" / "db", "*.py")

        print("  📦 Analyzing indexing modules...")
        indexing_modules = self._analyze_directory(self.repo_root / "server" / "indexing", "*.py")

        print("  ⚙️ Analyzing services modules...")
        services_modules = self._analyze_directory(self.repo_root / "server" / "services", "*.py")

        print("  🎨 Analyzing web components...")
        web_components = self._list_components(self.repo_root / "web" / "src" / "components")

        print("  🏪 Analyzing stores...")
        stores = self._analyze_directory(self.repo_root / "web" / "src" / "stores", "*.ts")

        print("  🪝 Analyzing hooks...")
        hooks = self._analyze_directory(self.repo_root / "web" / "src" / "hooks", "*.ts")

        print("  🐳 Reading docker-compose.yml...")
        docker_compose = self._read_file(self.repo_root / "docker-compose.yml")

        print("  🔐 Reading .env.example...")
        env_example = self._read_file(self.repo_root / ".env.example")
        env_example = self._sanitize_env_example(env_example)

        print("  📄 Reading README.md...")
        readme = self._read_file(self.repo_root / "README.md")

        print("  📚 Analyzing existing documentation...")
        existing_docs = self._analyze_existing_docs()

        print("  📝 Getting file list...")
        recent_changes, all_files = self._get_git_info(base_ref)

        return DocumentationContext(
            claude_md=claude_md,
            tribrid_config=tribrid_config,
            models_json=models_json,
            glossary_json=glossary_json,
            api_endpoints=api_endpoints,
            retrieval_modules=retrieval_modules,
            db_modules=db_modules,
            indexing_modules=indexing_modules,
            services_modules=services_modules,
            web_components=web_components,
            stores=stores,
            hooks=hooks,
            docker_compose=docker_compose,
            env_example=env_example,
            readme=readme,
            existing_docs=existing_docs,
            recent_changes=recent_changes,
            all_files=all_files,
        )

    def _read_file(self, path: Path, max_chars: Optional[int] = None) -> str:
        """Read file safely (optionally truncated)."""
        try:
            content = path.read_text(encoding="utf-8")
            if max_chars is not None and max_chars > 0 and len(content) > max_chars:
                content = content[:max_chars] + "\n... [truncated]"
            return content
        except Exception:
            return ""

    def _filter_sensitive_content(self, content: str) -> str:
        """Filter out sensitive internal content"""
        lines = content.split('\n')
        filtered_lines = []
        skip_section = False

        for line in lines:
            # Check if we should skip this line
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in self.exclude_patterns):
                skip_section = True
                continue

            # Reset skip on new major section
            if line.startswith('#') and not line.startswith('####'):
                skip_section = False

            if not skip_section:
                # Additional filtering for specific terms
                if not any(term in line.lower() for term in ['dev_mode=true', 'phase 1', 'phase 2']):
                    filtered_lines.append(line)

        return '\n'.join(filtered_lines)

    def _sanitize_env_example(self, content: str) -> str:
        """Sanitize environment example to remove actual secrets"""
        lines = content.split('\n')
        sanitized = []
        for line in lines:
            if '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                # Keep the key but sanitize the value
                if any(secret in key.lower() for secret in ['key', 'secret', 'token', 'password']):
                    sanitized.append(f"{key}=<your-{key.lower().replace('_', '-')}-here>")
                else:
                    sanitized.append(line)
            else:
                sanitized.append(line)
        return '\n'.join(sanitized)

    def _analyze_directory(self, dir_path: Path, pattern: str) -> Dict[str, str]:
        """Analyze all files in a directory matching pattern"""
        results = {}

        if not dir_path.exists():
            return results

        for file_path in dir_path.glob(pattern):
            if file_path.name.startswith('_') and file_path.name != '__init__.py':
                continue

            content = self._read_file(file_path)

            # Extract docstrings and key info
            summary = self._extract_module_summary(content)
            results[file_path.name] = summary

        return results

    def _extract_module_summary(self, content: str) -> str:
        """Extract module docstring and function/class signatures"""
        lines = []

        # Get module docstring
        docstring_match = re.search(r'^"""(.*?)"""', content, re.DOTALL | re.MULTILINE)
        if docstring_match:
            lines.append(docstring_match.group(1).strip())
            lines.append("")

        # Get class definitions with their docstrings
        class_matches = re.findall(r'class\s+(\w+).*?:\s*\n\s*"""(.*?)"""', content, re.DOTALL)
        for class_name, docstring in class_matches[:5]:
            lines.append(f"class {class_name}: {docstring.strip()}")

        # Get function definitions
        func_matches = re.findall(r'def\s+(\w+)\([^)]*\).*?:', content)
        public_funcs = [f for f in func_matches if not f.startswith('_')][:10]
        if public_funcs:
            lines.append(f"Functions: {', '.join(public_funcs)}")

        # Get FastAPI router routes
        route_matches = re.findall(r'@router\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', content)
        if route_matches:
            routes = [f"{method.upper()} {path}" for method, path in route_matches]
            lines.append(f"Routes: {', '.join(routes)}")

        return '\n'.join(lines) if lines else content

    def _list_components(self, components_dir: Path) -> List[str]:
        """List all React components"""
        components = []

        if not components_dir.exists():
            return components

        for ext in ['tsx', 'jsx']:
            for component_file in components_dir.rglob(f"*.{ext}"):
                rel_path = component_file.relative_to(components_dir)
                components.append(str(rel_path))

        return components[:50]  # Limit to avoid overwhelming context

    def _get_git_info(self, base_ref: str = None) -> Tuple[List[str], List[str]]:
        """Get list of changed files and all files"""
        recent_changes = []
        all_files = []

        try:
            # Get all tracked files
            cmd = "git ls-files"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=self.repo_root)
            if result.returncode == 0:
                all_files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
                # Filter to important files
                important_extensions = {'.py', '.ts', '.tsx', '.js', '.jsx', '.md', '.yml', '.yaml', '.json'}
                all_files = [
                    f for f in all_files
                    if any(f.endswith(ext) for ext in important_extensions)
                    and 'node_modules' not in f
                    and '__pycache__' not in f
                ][:500]
                print(f"  📂 Found {len(all_files)} important files in repository")

            # Get changed files if base_ref provided
            if base_ref:
                cmd = f"git diff --name-only {shlex.quote(base_ref)}..HEAD"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=self.repo_root)
                if result.returncode == 0:
                    recent_changes = [line.strip() for line in result.stdout.splitlines() if line.strip()]

        except Exception as e:
            print(f"  ⚠️ Error getting git info: {e}")

        return recent_changes, all_files

    def _analyze_existing_docs(self) -> Dict[str, str]:
        """Analyze existing documentation structure"""
        docs = {}

        if not self.docs_dir.exists():
            return docs

        for doc_file in self.docs_dir.rglob("*.md"):
            rel_path = doc_file.relative_to(self.docs_dir)
            content = self._read_file(doc_file)
            docs[str(rel_path)] = content

        return docs

    def generate_documentation_with_llm(self, context: DocumentationContext) -> Dict[str, str]:
        """Generate documentation using OpenAI GPT-4"""

        api_key = (self.openai_api_key or "").strip().strip('"').strip("'")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        self.openai_api_key = api_key

        # Prepare the comprehensive prompt
        system_prompt = self._create_system_prompt()
        user_prompt = self._create_user_prompt(context)

        # Call OpenAI API
        response = self._call_openai_api(system_prompt, user_prompt)

        # Parse the response to extract documentation updates
        docs_updates = self._parse_llm_response(response)

        return docs_updates

    def _create_system_prompt(self) -> str:
        """Create the system prompt for the LLM"""
        return """You are an expert technical documentation writer for TriBridRAG, a tri-brid
Retrieval-Augmented Generation engine.

Write **extremely detailed, high-signal, deeply technical** documentation. Do not be "stiff", these should feel human written This is not marketing
copy.

**Write for all audiences:**

1. **The reader who is an engineer** who will run, debug, extend, and operate this system.
2. **The reader who is not very technical**, and wants to learn about RAG.
3. **The reader who is not interested in the technical details**, and just wants to know how to search for information in their own data. 

You MUST create documentation that extensively uses Material for MkDocs features.

## TRIBRIDRAG ARCHITECTURE

TriBridRAG runs three retrieval methods in parallel, fuses their results, and optionally reranks:

1. **Vector Search** (pgvector in PostgreSQL) - Semantic similarity
2. **Sparse Search** (PostgreSQL FTS/BM25) - Exact matches, identifiers
3. **Graph Search** (Neo4j) - Entity traversal, relationships



All configuration and types are defined in `server/models/tribrid_config_model.py`.
TypeScript types are GENERATED from Pydantic—never hand-written.

### BANNED TERMS (DO NOT USE)
- Qdrant (we use pgvector)
- Redis (removed)
- LangChain (banned - use langgraph directly if needed)
- "cards" (use chunk_summaries)
- "golden questions" (use eval_dataset)
- "ranker" (use reranker)

## CRITICAL: MATERIAL FOR MKDOCS FEATURES

YOU MUST USE THESE FEATURES IN EVERY DOCUMENT:

### 1. ADMONITIONS (Use liberally throughout all docs!)
ALWAYS use admonitions for important information. Examples:

!!! note "Implementation Note"
    Use this for technical notes and implementation details.

!!! warning "Security Warning"
    Critical security information goes here.

!!! tip "Pro Tip"
    Helpful tips and best practices. Feel free to add multiple tips, bullet pointed out of a list. Do not be afraid to be verbose; not every line of documentation should be a technical bullet point, readers should assume these docs were written by a human, who has some narrative prose, especially when addressing features or concepts that are complex, interesting, unique to this repo, etc. 

!!! info "Information"
    General information blocks. Feel free to add multiple information blocks, bullet pointed out of a list. Do not be afraid to be verbose; not every line of documentation should be a technical bullet point, readers should assume these docs were written by a human, who has some narrative prose, especially when addressing features or concepts that are complex, interesting, unique to this repo, etc. 

!!! success "Success"
    Success messages and confirmations. Feel free to add multiple success messages, bullet pointed out of a list. Do not be afraid to be verbose; not every line of documentation should be a technical bullet point, readers should assume these docs were written by a human, who has some narrative prose, especially when addressing features or concepts that are complex, interesting, unique to this repo, etc. 

!!! danger "Critical"
    Critical warnings about data loss or security.

!!! example "Example"
    Code examples and use cases. If it it not inhently obvious, explain it in a way that is easy to understand and follow.

??? note "Collapsible Section"
    Use ??? for collapsible content that users can expand. Primarily use this for pieces of documentation that are important to include, but may not be relevant to most users, and therefore are collapsible as to not take up real estate or distract from more relevant documentation.

### 2. CODE BLOCKS WITH TABS (Use for ALL code examples!)
=== "Python"
    ```python
    # Python code here
    ```

=== "curl"
    ```bash
    # curl examples
    ```

=== "TypeScript"
    ```typescript
    // TypeScript code here
    ```

### 3. ANNOTATIONS IN CODE (Use to explain complex code!)
```python
def search(query: str, repo_id: str): # (1)
    results = fusion.fuse(query) # (2)
    return rerank(results) # (3)
```

1. The query and corpus identifier
2. Fusion combines vector, sparse, and graph results
3. Optional reranking with cross-encoder

### 4. DATA TABLES (Use for comparisons, features, APIs!)
| Feature | Description | Status |
|---------|-------------|--------|
| Vector Search | pgvector in PostgreSQL | ✅ Active |
| Sparse Search | PostgreSQL FTS/BM25 | ✅ Active |
| Graph Search | Neo4j traversal | ✅ Active |

### 5. GRIDS (Use for feature showcases!)
<div class="grid chunk_summaries" markdown>

-   :material-vector-combine:{ .lg .middle } **Tri-Brid Retrieval**

    ---

    Three search methods fused for better recall

-   :material-database:{ .lg .middle } **PostgreSQL Backbone**

    ---

    pgvector + FTS in one database

-   :material-graph:{ .lg .middle } **Knowledge Graph**

    ---

    Neo4j for entity relationships

</div>

### 6. MERMAID DIAGRAMS (Use for architecture and flows!)
```mermaid
flowchart LR
    Query[User Query] --> Vector[Vector Search]
    Query --> Sparse[Sparse Search]
    Query --> Graph[Graph Search]
    Vector --> Fusion[Fusion Layer]
    Sparse --> Fusion
    Graph --> Fusion
    Fusion --> Rerank[Reranker]
    Rerank --> Results[Final Results]
```

### MERMAID v11 (CRITICAL: AVOID SYNTAX ERRORS)
- ONLY generate `flowchart` diagrams (`flowchart LR` / `flowchart TB`). Avoid other diagram types.
- NO HTML anywhere in Mermaid (no `<br>`, no tags, no raw HTML labels).
- Node IDs MUST be simple: start with a letter, then letters/numbers/underscore only (`^[A-Za-z][A-Za-z0-9_]*$`).
- NEVER use URL-ish or path-ish tokens as node IDs (e.g., do NOT write `--> /metrics`). Use an ID + quoted label:
  - `METRICS["/metrics"]`, `READY["/ready"]`, `HEALTH["/health"]`
- If you want multi-line labels, you MUST quote the label and put `\\n` *inside* the quotes:
  - GOOD: `UI["Frontend\\n(generated.ts)"]`
  - BAD: `UI[Frontend]\\n(generated.ts)`
- If you use `subgraph` and the title contains spaces, quote it:
  - GOOD: `subgraph "Tuning Inputs"`
  - GOOD: `subgraph tuning_inputs["Tuning Inputs"]`
  - BAD: `subgraph Tuning Inputs`
- Prefer quoting any label containing punctuation like `/`, `(`, `)`, `:`, `+`, `-`.
- Keep diagrams small and shallow. Prefer 6–14 nodes per diagram; use multiple diagrams instead of one huge diagram.

### 7. CONTENT ORGANIZATION
- Use hierarchical headers (##, ###, ####)
- Add table of contents markers
- Use definition lists for glossaries
- Include footnotes for references[^1]

[^1]: This is a footnote example

### 8. ICONS AND VISUAL ELEMENTS
- :material-check-circle: for success
- :material-alert-circle: for warnings
- :material-information: for info
- :material-database: for database
- :material-magnify: for search
- :material-cog: for configuration

### 9. INTERACTIVE ELEMENTS
- Use ++ctrl+c++ for keyboard shortcuts
- Use task lists for checklists:
  - [x] Completed task
  - [ ] Pending task

### 10. QUICK LINKS (Material buttons)
Include a short “Quick links” block near the top of every page:

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

Adjust relative paths correctly for the page location (e.g., a nested page should use `../index.md`).

## DOCUMENTATION REQUIREMENTS:
1. EVERY page must have at least 3 admonitions
2. EVERY code example must use tabs for multiple languages
3. EVERY complex topic must have a Mermaid diagram
4. EVERY configuration must use a data table
5. EVERY feature list must use a grid (`<div class="grid chunk_summaries" markdown>`)
6. Include internal implementation details where operationally relevant (request/response shapes, config flow, pipeline stages, caching, metrics, failure modes)
7. Write for dyslexic-friendly reading (visual breaks, clear sections)
8. Exclude internal plans, phase numbers, development details
9. NEVER mention Qdrant, Redis, LangChain, or other banned terms

Output Format:
Return a JSON object where keys are file paths (relative to mkdocs/docs/) and values are
the complete markdown content. Every file MUST extensively use the Material for MkDocs
features shown above.

Remember: Plain markdown without Material features is UNACCEPTABLE. Every section needs
visual enhancement!"""

    def _create_user_prompt(self, context: DocumentationContext) -> str:
        """Create the user prompt with full context"""

        # Check if this is a full scan or just recent changes
        is_full_scan = len(context.all_files) > 100 and len(context.recent_changes) == 0

        # Build a comprehensive prompt
        prompt_parts = [
            "Generate comprehensive documentation for TriBridRAG based on the following context:",
            "",
            "## Project Instructions (from CLAUDE.md)",
            context.claude_md,
            "",
        ]

        if is_full_scan:
            prompt_parts.extend([
                "## Full Repository Documentation Request",
                "This is a COMPLETE DOCUMENTATION GENERATION from the entire codebase.",
                f"The repository contains {len(context.all_files)} important files.",
                "Create comprehensive documentation covering ALL aspects of the platform.",
                "",
            ])
        elif context.recent_changes:
            prompt_parts.extend([
                "## Recent Changes",
                "The following files have been modified recently:",
                *[f"- {change}" for change in context.recent_changes[:30]],
                "",
            ])

        # Add Pydantic config (THE source of truth)
        prompt_parts.extend([
            "",
            "## Configuration Model (tribrid_config_model.py - SOURCE OF TRUTH)",
            "This file defines ALL configurable parameters (~500+ fields):",
            context.tribrid_config,
            "",
        ])

        # Add API endpoints
        prompt_parts.extend([
            "## API Endpoints (server/api/)",
            *[f"### {name}\n{desc}" for name, desc in list(context.api_endpoints.items())[:10]],
            "",
        ])

        # Add retrieval modules
        prompt_parts.extend([
            "## Retrieval Pipeline (server/retrieval/)",
            *[f"### {name}\n{desc}" for name, desc in list(context.retrieval_modules.items())[:10]],
            "",
        ])

        # Add database modules
        prompt_parts.extend([
            "## Database Modules (server/db/)",
            *[f"### {name}\n{desc}" for name, desc in list(context.db_modules.items())[:5]],
            "",
        ])

        # Add indexing modules
        prompt_parts.extend([
            "## Indexing Pipeline (server/indexing/)",
            *[f"### {name}\n{desc}" for name, desc in list(context.indexing_modules.items())[:5]],
            "",
        ])

        # Add models.json
        prompt_parts.extend([
            "## LLM/Embedding Models (data/models.json)",
            context.models_json,
            "",
        ])

        # Add glossary
        prompt_parts.extend([
            "## Glossary Terms (data/glossary.json)",
            context.glossary_json,
            "",
        ])

        # Add docker compose
        prompt_parts.extend([
            "## Docker Compose Configuration",
            context.docker_compose,
            "",
        ])

        # Add environment example
        prompt_parts.extend([
            "## Environment Configuration",
            context.env_example,
            "",
        ])

        # Add web components
        prompt_parts.extend([
            "## Frontend Components",
            f"Available UI components: {', '.join(context.web_components[:20])}",
            "",
        ])

        # Add existing docs
        prompt_parts.extend([
            "## Existing Documentation Structure",
            *[f"- {path}: {content}" for path, content in list(context.existing_docs.items())[:20]],
            "",
        ])

        # Final instructions (NO PRESCRIPTIVE LIST - let LLM decide)
        prompt_parts.extend([
            "## Documentation Generation Instructions",
            "",
            "Based on the codebase context above, generate comprehensive documentation.",
            "Create whatever pages are needed to fully document the system.",
            "The LLM should determine what pages to create based on the code.",
            "",
            "MANDATORY Material for MkDocs Features to Include:",
            "",
            "For EVERY documentation file you create:",
            "1. Start with a grid of feature cards using <div class='grid cards'>",
            "2. Add at least 3 admonitions (!!! note, !!! tip, !!! warning, !!! danger)",
            "3. Use collapsible sections (???) for detailed information",
            "4. Include data tables for ALL configuration options and comparisons",
            "5. Add Mermaid diagrams for EVERY workflow or architecture",
            "6. Use code tabs (===) for EVERY code example - show Python, curl, TypeScript",
            "7. Add annotations (1), (2), (3) to explain complex code",
            "8. Use Material icons (:material-*:) liberally throughout",
            "9. Include task lists for step-by-step guides",
            "10. Add keyboard shortcuts with ++key++ notation",
            "",
            "Example structure for EVERY page:",
            "- Start with an eye-catching grid of features",
            "- Add a !!! tip admonition early for best practices",
            "- Use data tables for configuration/comparison",
            "- Include tabbed code examples for all languages",
            "- Add Mermaid diagrams for visual learners",
            "- End with ??? note sections for advanced topics",
            "",
            "Remember: Plain text documentation is FAILURE. Every section needs:",
            "- Visual elements (icons, badges, cards)",
            "- Interactive elements (tabs, collapsibles)",
            "- Structured data (tables, lists, diagrams)",
            "- Color-coded admonitions for different information types",
            "",
            "BANNED: Do not mention Qdrant, Redis, LangChain, 'cards', 'golden questions'.",
            "",
            "Return as JSON with file paths as keys and richly-formatted markdown as values."
        ])

        return '\n'.join(prompt_parts)

    def _call_openai_api(self, system_prompt: str, user_prompt: str) -> str:
        """Call OpenAI Responses API with the prompts, with basic 429 backoff and CI-safe soft-fail."""

        import time
        from requests import HTTPError

        url = "https://api.openai.com/v1/responses"
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }

        # Primary and fallback models (GPT-5 only)
        primary_model = os.getenv("OPENAI_MODEL", "gpt-5")
        fallback_model = os.getenv("OPENAI_FALLBACK_MODEL", "gpt-5-2025-08-07")
        if not primary_model.startswith("gpt-5"):
            raise ValueError(f"OPENAI_MODEL must be GPT-5 (got: {primary_model})")
        if fallback_model and not fallback_model.startswith("gpt-5"):
            raise ValueError(f"OPENAI_FALLBACK_MODEL must be GPT-5 (got: {fallback_model})")

        def build_payload(model: str) -> Dict[str, Any]:
            if not model.startswith("gpt-5"):
                raise ValueError(f"Model must be GPT-5 (got: {model})")
            base = {
                "model": model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            # GPT-5 models use new controls
            base["text"] = {"verbosity": os.getenv("OPENAI_VERBOSITY", "high")}
            base["reasoning"] = {"effort": os.getenv("OPENAI_REASONING_EFFORT", "high")}
            base["max_output_tokens"] = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "32000"))
            return base

        def post_with_retries(model: str, attempts: int = 4, base_delay: float = 5.0) -> Optional[str]:
            print(f"Using OpenAI model: {model}")
            payload = build_payload(model)
            for i in range(attempts):
                try:
                    timeout_s = int(os.getenv("OPENAI_HTTP_TIMEOUT_SECONDS", "900"))
                    resp = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
                    if resp.status_code == 429:
                        raise HTTPError("429 Too Many Requests", response=resp)
                    resp.raise_for_status()
                    result = resp.json()
                    # Responses API format - extract text from response
                    if isinstance(result, dict) and "output" in result:
                        output = result["output"]
                        if isinstance(output, list):
                            for item in output:
                                if isinstance(item, dict) and "content" in item:
                                    content = item["content"]
                                    # content is a list of content blocks
                                    if isinstance(content, list):
                                        for block in content:
                                            if isinstance(block, dict) and block.get("type") == "output_text":
                                                text = block.get("text", "")
                                                if text:
                                                    print(f"  ✓ Got {len(text)} chars from API")
                                                    return text
                                    elif isinstance(content, str):
                                        print(f"  ✓ Got {len(content)} chars from API")
                                        return content
                        # Fallback: check for choices (legacy format)
                        if "choices" in result:
                            text = result["choices"][0]["message"]["content"]
                            print(f"  ✓ Got {len(text)} chars from API (legacy)")
                            return text
                    # Don't retry on parse errors - return None to try fallback
                    print(f"  ✗ Unknown response format: {list(result.keys()) if isinstance(result, dict) else type(result)}")
                    return None
                except HTTPError as he:
                    status = he.response.status_code if he.response is not None else None
                    if status == 429:
                        wait = base_delay * (2**i)
                        print(f"Rate limited (429). Retrying in {wait:.1f}s... [{i+1}/{attempts}]")
                        time.sleep(wait)
                        continue
                    # Non-429 HTTP error; do not retry.
                    #
                    # For auth failures, fail fast with a useful message (this will never succeed on retry).
                    detail = ""
                    if he.response is not None:
                        try:
                            body = he.response.json()
                            if isinstance(body, dict) and isinstance(body.get("error"), dict):
                                detail = str(body["error"].get("message") or "")
                            else:
                                detail = (he.response.text or "")[:500]
                        except Exception:
                            detail = (he.response.text or "")[:500]

                    if status in (401, 403):
                        raise RuntimeError(
                            f"OpenAI API auth failed ({status}). "
                            f"{detail or 'Check OPENAI_API_KEY (and that it is a real, unrevoked key).'}"
                        )

                    if detail:
                        print(f"HTTP error from OpenAI ({status}): {detail}")
                    else:
                        print(f"HTTP error from OpenAI: {he}")
                    return None
                except Exception as e:
                    # Network or parse error; retry with backoff
                    wait = base_delay * (2**i)
                    print(f"Error calling OpenAI ({type(e).__name__}): {e}. Retrying in {wait:.1f}s...")
                    time.sleep(wait)
            return None

        # Try primary, then fallback (GPT-5 only)
        resp_text = post_with_retries(primary_model)
        if resp_text is None and fallback_model:
            print(f"Attempting fallback with {fallback_model}...")
            resp_text = post_with_retries(fallback_model)

        # If still failing in CI, soft-fail with empty updates
        if resp_text is None:
            if os.getenv("GITHUB_ACTIONS") == "true":
                print("OpenAI API unavailable or rate-limited; skipping documentation generation in CI.")
                return "{}"  # Return empty JSON to indicate no updates
            # Outside CI, raise to signal interactive failure
            raise RuntimeError("Failed to generate documentation via OpenAI API after retries")

        return resp_text

    def _parse_llm_response(self, response: str) -> Dict[str, str]:
        """Parse the LLM response to extract documentation updates"""
        if not response:
            print("  ✗ Empty response")
            return {}

        print(f"  Parsing {len(response)} chars...")

        # If response starts with {, try to parse directly
        response_stripped = response.strip()
        if response_stripped.startswith('{'):
            try:
                docs = json.loads(response_stripped)
                if isinstance(docs, dict):
                    print(f"  ✓ Parsed {len(docs)} documentation files")
                    for path, content in docs.items():
                        docs[path] = self._filter_banned_terms(content)
                    return docs
            except json.JSONDecodeError as e:
                print(f"  ✗ Direct JSON parse error: {e}")

        # Try to extract JSON from ```json code block specifically
        json_match = re.search(r'```json\s*\n(.*?)\n```', response, re.DOTALL)
        if json_match:
            try:
                docs = json.loads(json_match.group(1))
                if isinstance(docs, dict):
                    print(f"  ✓ Parsed {len(docs)} files from json block")
                    for path, content in docs.items():
                        docs[path] = self._filter_banned_terms(content)
                    return docs
            except json.JSONDecodeError as e:
                print(f"  ✗ JSON block parse error: {e}")

        # Fallback: extract markdown sections
        docs = {}
        current_file = None
        current_content = []

        for line in response.split('\n'):
            if line.startswith('FILE:') or line.startswith('### FILE:'):
                if current_file and current_content:
                    docs[current_file] = '\n'.join(current_content)
                current_file = line.replace('FILE:', '').replace('### FILE:', '').strip()
                current_content = []
            else:
                current_content.append(line)

        if current_file and current_content:
            docs[current_file] = '\n'.join(current_content)

        return docs

    def _filter_banned_terms(self, content: str) -> str:
        """Remove or replace banned terms in content"""
        replacements = {
            r'\bqdrant\b': 'pgvector',
            r'\bredis\b': 'PostgreSQL',
            r'\blangchain\b': 'langgraph',
            r'\bcards?\b': 'chunk_summaries',
            r'\bgolden questions?\b': 'eval_dataset',
            r'\branker\b': 'reranker',
        }

        result = content
        for pattern, replacement in replacements.items():
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        return result

    def update_mkdocs_config(self, docs_updates: Dict[str, str]) -> dict:
        """Update mkdocs.yml configuration with enhanced features"""

        # Enhanced configuration for TriBridRAG
        config = {
            "site_name": "TriBridRAG Docs",
            "site_description": "Tri-Brid Retrieval-Augmented Generation combining Vector, Sparse, and Graph search",
            "site_url": "https://dmontgomery40.github.io/tribrid-rag/",
            "repo_url": "https://github.com/DMontgomery40/tribrid-rag",
            "repo_name": "DMontgomery40/tribrid-rag",
            "copyright": "Copyright &copy; 2025 TriBridRAG",
            "docs_dir": "mkdocs/docs",

            "theme": {
                "name": "material",
                "language": "en",
                "palette": [
                    {
                        "scheme": "default",
                        "primary": "deep purple",
                        "accent": "purple",
                        "toggle": {
                            "icon": "material/brightness-7",
                            "name": "Switch to dark mode",
                        }
                    },
                    {
                        "scheme": "slate",
                        "primary": "deep purple",
                        "accent": "purple",
                        "toggle": {
                            "icon": "material/brightness-4",
                            "name": "Switch to light mode",
                        }
                    }
                ],
                "font": {
                    "text": "Roboto",
                    "code": "Roboto Mono",
                },
                "features": self.material_features,
                "icon": {
                    "logo": "material/vector-combine",
                    "repo": "fontawesome/brands/github",
                    "admonition": {
                        "note": "material/note-text",
                        "info": "material/information",
                        "tip": "material/lightbulb",
                        "success": "material/check-circle",
                        "warning": "material/alert",
                        "danger": "material/alert-circle",
                    }
                }
            },

            "plugins": [
                "search",
                {"git-revision-date-localized": {
                    "enable_creation_date": True,
                    "type": "iso_datetime",
                }},
                {"minify": {
                    "minify_html": True,
                    "minify_js": True,
                    "minify_css": True,
                }},
            ],

            "markdown_extensions": [
                "admonition",
                "pymdownx.details",
                "pymdownx.superfences",
                "pymdownx.tabbed",
                "pymdownx.keys",
                "pymdownx.snippets",
                "attr_list",
                "md_in_html",
                "def_list",
                "footnotes",
                "tables",
                "pymdownx.arithmatex",
                "pymdownx.betterem",
                "pymdownx.caret",
                "pymdownx.mark",
                "pymdownx.tilde",
                "pymdownx.smartsymbols",
                "pymdownx.emoji",
                {"pymdownx.superfences": {
                    "custom_fences": [
                        {
                            "name": "mermaid",
                            "class": "mermaid",
                            "format": "!!python/name:pymdownx.superfences.fence_code_format",
                        }
                    ]
                }},
                {"pymdownx.tabbed": {
                    "alternate_style": True,
                }},
                {"pymdownx.tasklist": {
                    "custom_checkbox": True,
                }},
                {"pymdownx.highlight": {
                    "anchor_linenums": True,
                    "line_spans": "__span",
                    "pygments_lang_class": True,
                }},
                "pymdownx.inlinehilite",
                {"pymdownx.emoji": {
                    "emoji_index": "!!python/name:material.extensions.emoji.twemoji",
                    "emoji_generator": "!!python/name:material.extensions.emoji.to_svg",
                }},
            ],

            "extra": {
                "social": [
                    {
                        "icon": "fontawesome/brands/github",
                        "link": "https://github.com/DMontgomery40/tribrid-rag",
                    },
                ],
            },

            "extra_javascript": [
                "https://unpkg.com/mermaid@10/dist/mermaid.min.js",
                "javascripts/mermaid-init.js",
            ],

            "nav": self._generate_navigation(docs_updates),
        }

        return config

    def _generate_navigation(self, docs_updates: Dict[str, str]) -> list:
        """Generate navigation structure based on documentation

        This creates a TriBridRAG-specific navigation structure.
        """

        # If no docs provided, return empty
        if not docs_updates:
            return []

        nav = [
            {"Home": "index.md"},
        ]

        # Getting Started section
        getting_started_pages = []
        if "getting-started/quickstart.md" in docs_updates or self._doc_exists("getting-started/quickstart.md"):
            getting_started_pages.append({"Quick Start": "getting-started/quickstart.md"})
        if "getting-started/installation.md" in docs_updates or self._doc_exists("getting-started/installation.md"):
            getting_started_pages.append({"Installation": "getting-started/installation.md"})
        if "getting-started/configuration.md" in docs_updates or self._doc_exists("getting-started/configuration.md"):
            getting_started_pages.append({"Configuration": "getting-started/configuration.md"})
        if getting_started_pages:
            nav.append({"Getting Started": getting_started_pages})

        # Features section (tri-brid search)
        features_pages = []
        if "features/tribrid-search.md" in docs_updates or self._doc_exists("features/tribrid-search.md"):
            features_pages.append({"Tri-Brid Search": "features/tribrid-search.md"})
        if "features/pgvector.md" in docs_updates or self._doc_exists("features/pgvector.md"):
            features_pages.append({"Vector Search (pgvector)": "features/pgvector.md"})
        if "features/sparse-search.md" in docs_updates or self._doc_exists("features/sparse-search.md"):
            features_pages.append({"Sparse Search (BM25)": "features/sparse-search.md"})
        if "features/neo4j-graph.md" in docs_updates or self._doc_exists("features/neo4j-graph.md"):
            features_pages.append({"Graph Search (Neo4j)": "features/neo4j-graph.md"})
        if "features/fusion.md" in docs_updates or self._doc_exists("features/fusion.md"):
            features_pages.append({"Fusion & Reranking": "features/fusion.md"})
        if "features/indexing.md" in docs_updates or self._doc_exists("features/indexing.md"):
            features_pages.append({"Indexing Pipeline": "features/indexing.md"})
        if features_pages:
            nav.append({"Features": features_pages})

        # Configuration section
        config_pages = []
        if "configuration/overview.md" in docs_updates or self._doc_exists("configuration/overview.md"):
            config_pages.append({"Overview": "configuration/overview.md"})
        if "configuration/settings.md" in docs_updates or self._doc_exists("configuration/settings.md"):
            config_pages.append({"Settings Reference": "configuration/settings.md"})
        if "configuration/models.md" in docs_updates or self._doc_exists("configuration/models.md"):
            config_pages.append({"Model Configuration": "configuration/models.md"})
        if config_pages:
            nav.append({"Configuration": config_pages})

        # API Reference section
        api_pages = []
        if "api/endpoints.md" in docs_updates or self._doc_exists("api/endpoints.md"):
            api_pages.append({"Endpoints": "api/endpoints.md"})
        if "api/search.md" in docs_updates or self._doc_exists("api/search.md"):
            api_pages.append({"Search API": "api/search.md"})
        if "api/index.md" in docs_updates or self._doc_exists("api/index.md"):
            api_pages.append({"Index API": "api/index.md"})
        if "api/config.md" in docs_updates or self._doc_exists("api/config.md"):
            api_pages.append({"Config API": "api/config.md"})
        if "api/graph.md" in docs_updates or self._doc_exists("api/graph.md"):
            api_pages.append({"Graph API": "api/graph.md"})
        if api_pages:
            nav.append({"API Reference": api_pages})

        # Operations section
        ops_pages = []
        if "operations/deployment.md" in docs_updates or self._doc_exists("operations/deployment.md"):
            ops_pages.append({"Deployment": "operations/deployment.md"})
        if "operations/monitoring.md" in docs_updates or self._doc_exists("operations/monitoring.md"):
            ops_pages.append({"Monitoring": "operations/monitoring.md"})
        if "operations/troubleshooting.md" in docs_updates or self._doc_exists("operations/troubleshooting.md"):
            ops_pages.append({"Troubleshooting": "operations/troubleshooting.md"})
        if ops_pages:
            nav.append({"Operations": ops_pages})

        # Development section
        dev_pages = []
        if "development/architecture.md" in docs_updates or self._doc_exists("development/architecture.md"):
            dev_pages.append({"Architecture": "development/architecture.md"})
        if "development/contributing.md" in docs_updates or self._doc_exists("development/contributing.md"):
            dev_pages.append({"Contributing": "development/contributing.md"})
        if "development/testing.md" in docs_updates or self._doc_exists("development/testing.md"):
            dev_pages.append({"Testing": "development/testing.md"})
        if dev_pages:
            nav.append({"Development": dev_pages})

        return nav

    def _doc_exists(self, path: str) -> bool:
        """Check if a documentation file exists"""
        return (self.docs_dir / path).exists()

    def write_documentation_files(self, docs_updates: Dict[str, str]) -> None:
        """Write documentation files to disk"""

        self.docs_dir.mkdir(parents=True, exist_ok=True)

        for file_path, content in docs_updates.items():
            # Strip mkdocs/docs/ prefix if LLM included it
            file_path = file_path.removeprefix("mkdocs/docs/").removeprefix("docs/")
            full_path = self.docs_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Filter content one more time before writing
            filtered_content = self._filter_sensitive_content(content)
            filtered_content = self._filter_banned_terms(filtered_content)
            filtered_content, blocks_changed = normalize_mermaid_v11_markdown(filtered_content)

            full_path.write_text(filtered_content, encoding="utf-8")
            if blocks_changed:
                print(f"    ↳ Mermaid normalized: {blocks_changed} block(s)")
            print(f"  ✅ Wrote: {file_path}")

    def normalize_existing_mermaid(self) -> Tuple[int, int]:
        """Normalize Mermaid blocks across existing mkdocs/docs markdown files."""

        if not self.docs_dir.exists():
            return 0, 0

        files_changed = 0
        blocks_changed_total = 0

        for md_file in sorted(self.docs_dir.rglob("*.md")):
            try:
                original = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            updated, blocks_changed = normalize_mermaid_v11_markdown(original)
            if blocks_changed and updated != original:
                md_file.write_text(updated, encoding="utf-8")
                files_changed += 1
                blocks_changed_total += blocks_changed
                rel = md_file.relative_to(self.docs_dir)
                print(f"  ✅ Mermaid normalized: {rel} ({blocks_changed} block(s))")

        return files_changed, blocks_changed_total

    def write_mkdocs_config(self, config: dict) -> None:
        """Write mkdocs.yml configuration"""

        import yaml

        mkdocs_path = self.repo_root / "mkdocs.yml"

        with open(mkdocs_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        print(f"  ✅ Updated: mkdocs.yml")

    def create_github_workflow(self) -> None:
        """Create enhanced GitHub workflow for documentation automation"""

        workflow = """name: Documentation Automation
on:
  push:
    branches: ["main", "develop"]
  pull_request:
    branches: ["main"]
  workflow_dispatch:
    inputs:
      regenerate_all:
        description: 'Regenerate all documentation'
        required: false
        type: boolean
        default: false

permissions:
  contents: write
  pages: write
  id-token: write
  pull-requests: write

jobs:
  generate-docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install mkdocs mkdocs-material pymdown-extensions
          pip install requests pyyaml
          pip install mkdocs-git-revision-date-localized-plugin mkdocs-minify-plugin

      - name: Generate documentation with AI
        if: ${{ github.event.inputs.regenerate_all == 'true' }}
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          python scripts/docs_ai/docs_autopilot_enhanced.py --regenerate-all

      - name: Build documentation
        run: mkdocs build

      - name: Create PR with documentation updates
        if: github.event_name == 'workflow_dispatch' && github.event.inputs.regenerate_all == 'true'
        uses: peter-evans/create-pull-request@v6
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          title: "docs: AI-generated documentation updates"
          body: |
            This PR contains AI-generated documentation updates based on the codebase.

            **Please review carefully before merging.**

            - [ ] Documentation is accurate
            - [ ] No internal/sensitive information exposed
            - [ ] Material for MkDocs features utilized
            - [ ] Navigation structure is logical
            - [ ] No banned terms (Qdrant, Redis, LangChain, cards)
          commit-message: "docs: update documentation with AI assistance"
          branch: docs/ai-updates-${{ github.run_id }}
          base: main

  deploy-docs:
    needs: generate-docs
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install mkdocs mkdocs-material pymdown-extensions
          pip install mkdocs-git-revision-date-localized-plugin mkdocs-minify-plugin

      - name: Build documentation
        run: mkdocs build

      - name: Setup Pages
        uses: actions/configure-pages@v4

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: 'site'

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
"""

        workflow_path = self.repo_root / ".github" / "workflows" / "docs-automation.yml"
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text(workflow, encoding="utf-8")
        print(f"  ✅ Created: {workflow_path}")

    def dry_run(self, context: DocumentationContext) -> None:
        """Show what would be generated without actually calling the LLM"""

        print("\n" + "=" * 60)
        print("DRY RUN - Context Analysis")
        print("=" * 60)

        print(f"\n📖 CLAUDE.md: {len(context.claude_md)} chars")
        print(f"📐 tribrid_config_model.py: {len(context.tribrid_config)} chars")
        print(f"🤖 models.json: {len(context.models_json)} chars")
        print(f"📚 glossary.json: {len(context.glossary_json)} chars")

        print(f"\n🔌 API Endpoints: {len(context.api_endpoints)} files")
        for name in context.api_endpoints:
            print(f"   - {name}")

        print(f"\n🔍 Retrieval Modules: {len(context.retrieval_modules)} files")
        for name in context.retrieval_modules:
            print(f"   - {name}")

        print(f"\n💾 Database Modules: {len(context.db_modules)} files")
        for name in context.db_modules:
            print(f"   - {name}")

        print(f"\n📦 Indexing Modules: {len(context.indexing_modules)} files")
        for name in context.indexing_modules:
            print(f"   - {name}")

        print(f"\n🎨 Web Components: {len(context.web_components)} components")
        for comp in context.web_components[:10]:
            print(f"   - {comp}")
        if len(context.web_components) > 10:
            print(f"   ... and {len(context.web_components) - 10} more")

        print(f"\n📚 Existing Docs: {len(context.existing_docs)} files")
        for path in context.existing_docs:
            print(f"   - {path}")

        print(f"\n📂 Total Files in Repo: {len(context.all_files)}")

        if context.recent_changes:
            print(f"\n📝 Recent Changes: {len(context.recent_changes)} files")
            for change in context.recent_changes[:10]:
                print(f"   - {change}")

        print("\n" + "=" * 60)
        print("The LLM would receive this context and generate documentation.")
        print("Run without --dry-run to actually generate docs.")
        print("=" * 60)


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Enhanced Docs Autopilot for TriBridRAG")
    parser.add_argument("--base", default=None, help="Base branch for comparison (default: full scan)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write files, just show what would be done")
    parser.add_argument("--regenerate-all", action="store_true", help="Regenerate all documentation from entire codebase")
    parser.add_argument("--full-scan", action="store_true", help="Scan entire repository, not just changes")
    parser.add_argument(
        "--normalize-mermaid",
        action="store_true",
        help="Normalize Mermaid v11 blocks in existing docs (no LLM call)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("TriBridRAG Documentation Autopilot")
    print("=" * 60)

    autopilot = EnhancedDocsAutopilot()

    if args.normalize_mermaid:
        print("\n🧹 Normalizing Mermaid blocks across mkdocs/docs ...")
        files_changed, blocks_changed = autopilot.normalize_existing_mermaid()
        print(f"✅ Mermaid normalization complete: {files_changed} file(s), {blocks_changed} block(s) updated")
        return

    # Force full repository scan if regenerate-all or full-scan
    if args.regenerate_all or args.full_scan:
        print("\n🔄 Full repository scan mode - generating docs from entire codebase...")
        args.base = None

    print("\n📚 Gathering comprehensive context...")
    context = autopilot.gather_comprehensive_context(args.base)

    if args.dry_run:
        autopilot.dry_run(context)
        return

    print("\n🤖 Generating documentation with AI...")
    docs_updates = autopilot.generate_documentation_with_llm(context)

    if not docs_updates:
        print("\n⚠️ No documentation updates generated. Check API key and try again.")
        return

    print(f"\n📝 Writing {len(docs_updates)} documentation files...")
    autopilot.write_documentation_files(docs_updates)

    # Note: mkdocs.yml is managed manually to avoid config issues
    # print("\n⚙️ Updating mkdocs.yml configuration...")
    # config = autopilot.update_mkdocs_config(docs_updates)
    # autopilot.write_mkdocs_config(config)
    print("\n⚙️ mkdocs.yml update skipped (managed manually)")

    # Workflows are managed in-repo; do not rewrite from this script.
    print("\n🔧 GitHub workflow update skipped (managed manually)")

    print("\n" + "=" * 60)
    print("✅ Documentation automation setup complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Review the generated documentation in mkdocs/docs/")
    print("2. Run 'mkdocs serve' to preview locally")
    print("3. Commit and push changes")
    print("4. GitHub Actions will deploy to GitHub Pages")


if __name__ == "__main__":
    main()
