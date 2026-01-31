#!/usr/bin/env python3
"""
Docs Autopilot bootstrap for TriBridRAG.

Reads source files for each documentation page, calls OpenAI API
to generate MkDocs pages automatically.

Usage:
    python scripts/docs_ai/bootstrap_docs.py --list
    python scripts/docs_ai/bootstrap_docs.py --dry-run --page index
    python scripts/docs_ai/bootstrap_docs.py --page index --page features/tribrid-search
    python scripts/docs_ai/bootstrap_docs.py --all --model gpt-5.2
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

WRITING STYLE: Technical, precise, thorough. Humorous where appropriate. 

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
Reference: https://squidfunk.github.io/mkdocs-material/reference/

You MUST use these components where appropriate:
- **Admonitions**: !!! note, !!! tip, !!! warning, !!! danger, ??? collapsible "Title"
- **Code blocks** with line numbers, highlighting, and annotations:
  ```python linenums="1" hl_lines="3 4"
  code here  # (1)!
  ```
  1. Annotations go in a numbered list after the code block
  
- **Content tabs** for multiple languages or approaches:
  === "Python"
      ```python
      code
      ```
  === "TypeScript"
      ```typescript
      code
      ```
      
- **Mermaid v11 diagrams with 3D handDrawn style** (CRITICAL - USE THESE NEW FEATURES):
  
  The site uses `look: "handDrawn"` for a cool 3D sketchy style - your diagrams will look awesome!
  
  **Flowchart with styling** (v11):
  ```mermaid
  flowchart LR
      A[Start]:::highlight --> B{Decision}
      B -->|Yes| C[Action 1]:::success
      B -->|No| D[Action 2]:::warning
      C --> E[End]
      D --> E
      
      classDef highlight fill:#2dd4bf,stroke:#14b8a6,stroke-width:3px
      classDef success fill:#22c55e,stroke:#16a34a,stroke-width:2px
      classDef warning fill:#eab308,stroke:#ca8a04,stroke-width:2px
  ```
  
  **Multi-line labels with colors**:
  ```mermaid
  flowchart LR
      Query[User Query]:::input --> Vector["Vector Search\n(pgvector in PostgreSQL)"]:::search
      Query --> Sparse["Sparse Search\n(PostgreSQL FTS/BM25)"]:::search
      Query --> Graph["Graph Search\n(Neo4j traversal)"]:::search
      
      Vector --> Fusion["Fusion Layer\n(RRF or Weighted)"]:::process
      Sparse --> Fusion
      Graph --> Fusion
      
      Fusion --> Rerank["Reranker\n(local/cloud/trained)"]:::process
      Rerank --> Results[Final Results]:::output
      
      classDef input fill:#3b82f6,stroke:#2563eb,stroke-width:3px
      classDef search fill:#8b5cf6,stroke:#7c3aed,stroke-width:2px
      classDef process fill:#ec4899,stroke:#db2777,stroke-width:2px
      classDef output fill:#10b981,stroke:#059669,stroke-width:3px
  ```
  
  **Sequence diagram with styling**:
  ```mermaid
  sequenceDiagram
      participant User
      participant API
      participant Vector as Vector DB
      participant Graph as Graph DB
      
      User->>+API: Search Query
      API->>+Vector: Embed & Search
      API->>+Graph: Entity Lookup
      Vector-->>-API: Top-K Results
      Graph-->>-API: Related Entities
      API->>API: Fuse & Rerank
      API-->>-User: Final Results
  ```
  
  **State diagram** (great for workflows):
  ```mermaid
  stateDiagram-v2
      [*] --> Indexing
      Indexing --> Ready
      Ready --> Searching
      Searching --> Reranking
      Reranking --> Ready
      Ready --> [*]
  ```
  
  **MERMAID v11 RULES** (handDrawn style enabled sitewide):
  - Use \n for multi-line labels (NOT <br/> or HTML)
  - Add color classes with `:::className` for visual appeal
  - Make them big and bold and colorful! And 3D!
  - Define classDef for custom colors (use hex colors)
  - Node shapes: [] rectangle, () rounded, {} diamond, (()) circle, [[ ]] subroutine
  - Edge types: --> solid, -.-> dotted, ==> thick
  - Edge labels: -->|label| or -->|"multi\nline"|
  - Proper indentation (4 spaces)
  - NO HTML tags anywhere
  - Use quotes for labels with special chars/newlines
  - Include at least 2-3 diagrams per major page (mix flowcharts, sequences, states)
  - Make diagrams colorful and visually interesting with classDef styling!
  
- **Data tables** with proper Markdown formatting
- **Definition lists** for parameters:
  `term`
  :   Definition of the term
  
- **Links** between related pages using relative paths

OUTPUT FORMAT:
- Output ONLY the markdown content for the page
- Start with a level-1 heading (# Title)
- Do not include YAML frontmatter
- Do not wrap output in code blocks
"""

# =============================================================================
# VALID_PAGES - Documentation structure for accurate cross-linking
# =============================================================================

VALID_PAGES = """
DOCUMENTATION STRUCTURE - Only link to these pages:

HOME:
- index.md (the landing page)

GETTING STARTED:
- getting-started/quickstart.md
- getting-started/installation.md

FEATURES:
- features/tribrid-search.md (covers tri-brid architecture, fusion, retrieval)
- features/pgvector.md (vector search)
- features/neo4j-graph.md (graph search)

CONFIGURATION:
- configuration/models.md (model configuration, models.json)
- configuration/settings.md (all config settings, reranking, scoring)

API:
- api/endpoints.md (all API endpoints)

OPERATIONS:
- operations/monitoring.md (observability, metrics, health)
- operations/troubleshooting.md

LINKING RULES:
1. From index.md, link to: ./getting-started/quickstart.md, ./features/tribrid-search.md, etc.
2. From getting-started/*.md, link to: ./quickstart.md (same dir) or ../features/tribrid-search.md (other dir)
3. DO NOT invent pages like ./configuration.md, ./retrieval.md, ./api.md - they don't exist
4. Link to the specific file that covers the topic (e.g., for "reranking" link to ./configuration/settings.md)
"""

# =============================================================================
# DOC_PAGES - Maps each doc page to source files that inform it
# =============================================================================

DOC_PAGES = {
    "index": {
        "title": "TriBridRAG - Tri-Brid RAG Engine",
        "output_path": "mkdocs/docs/index.md",
        "source_files": [
            "README.md",
            "CLAUDE.md",
            "server/models/tribrid_config_model.py",
        ],
        "instruction": """Write the landing page for TriBridRAG documentation.

Include:
1. Project overview - what is TriBridRAG and why tri-brid search?
2. A Mermaid flowchart showing the tri-brid pipeline:
   Query -> [Vector Search, Sparse Search, Graph Search] -> Fusion -> Reranker -> Results
3. Key features list with brief descriptions
4. Quick start commands (docker-compose up, API endpoints)
5. Links to detailed documentation sections
6. Architecture highlights from the Pydantic config model

Make it welcoming but technically substantive.""",
    },
    "getting-started/quickstart": {
        "title": "Quick Start",
        "output_path": "mkdocs/docs/getting-started/quickstart.md",
        "source_files": [
            "README.md",
            "docker-compose.yml",
            "server/main.py",
        ],
        "instruction": """Write a quickstart guide for getting TriBridRAG running.

Include:
1. Prerequisites (Docker, Python 3.10+, Node.js)
2. Clone and setup commands
3. Docker compose up command
4. Verify services are running (health checks)
5. First API call example (search endpoint)
6. Next steps links

Keep it practical and copy-paste friendly.""",
    },
    "getting-started/installation": {
        "title": "Installation",
        "output_path": "mkdocs/docs/getting-started/installation.md",
        "source_files": [
            "README.md",
            "pyproject.toml",
            "docker-compose.yml",
        ],
        "instruction": """Write detailed installation instructions.

Cover:
1. Docker-based installation (recommended)
2. Local development setup with uv
3. Environment variables required
4. Database setup (PostgreSQL with pgvector, Neo4j)
5. Verifying the installation
6. Common installation issues and solutions""",
    },
    "features/tribrid-search": {
        "title": "Tri-Brid Search Architecture",
        "output_path": "mkdocs/docs/features/tribrid-search.md",
        "source_files": [
            "server/retrieval/fusion.py",
            "server/retrieval/vector.py",
            "server/retrieval/sparse.py",
            "server/retrieval/graph.py",
            "server/models/tribrid_config_model.py",
        ],
        "instruction": """Explain the tri-brid search architecture in depth.

Include:
1. Overview of the three search legs
2. Mermaid diagram showing data flow
3. How each search type works:
   - Vector search with pgvector (HNSW, similarity metrics)
   - Sparse search with BM25/FTS (term frequency, IDF)
   - Graph search with Neo4j (entity traversal, communities)
4. Fusion methods: RRF vs weighted scoring
5. When to use which configuration
6. Performance considerations""",
    },
    "features/pgvector": {
        "title": "Vector Search (pgvector)",
        "output_path": "mkdocs/docs/features/pgvector.md",
        "source_files": [
            "server/db/postgres.py",
            "server/retrieval/vector.py",
            "server/models/tribrid_config_model.py",
        ],
        "instruction": """Document the pgvector integration for vector search.

Cover:
1. Why pgvector over dedicated vector DBs
2. Index types: HNSW vs IVFFlat
3. Configuration options from IndexingConfig
4. Embedding dimensions and models supported
5. Query examples
6. Performance tuning tips""",
    },
    "features/neo4j-graph": {
        "title": "Graph Search (Neo4j)",
        "output_path": "mkdocs/docs/features/neo4j-graph.md",
        "source_files": [
            "server/db/neo4j.py",
            "server/retrieval/graph.py",
            "server/indexing/graph_builder.py",
            "server/models/tribrid_config_model.py",
        ],
        "instruction": """Document the Neo4j graph search integration.

Cover:
1. Graph RAG approach - why graphs for code search
2. Entity types extracted (functions, classes, modules, etc.)
3. Relationship types (calls, imports, inherits, contains)
4. Community detection algorithms (Louvain, label propagation)
5. GraphStorageConfig options
6. Cypher query patterns used
7. Traversal depth configuration""",
    },
    "configuration/models": {
        "title": "Model Configuration",
        "output_path": "mkdocs/docs/configuration/models.md",
        "source_files": [
            "server/models/tribrid_config_model.py",
            "data/models.json",
            "server/api/models.py",
        ],
        "instruction": """Document the model configuration system.

Cover:
1. models.json structure and purpose
2. Model types: EMB (embedding), GEN (generation), RERANK
3. Adding new models to models.json
4. Provider support (OpenAI, Anthropic, Voyage, local)
5. Cost tracking fields
6. API endpoint /api/models
7. How the frontend uses useModels hook""",
    },
    "configuration/settings": {
        "title": "Configuration Settings",
        "output_path": "mkdocs/docs/configuration/settings.md",
        "source_files": [
            "server/models/tribrid_config_model.py",
            "tribrid_config.json",
        ],
        "instruction": """Document all configuration settings.

Structure by config section:
1. RetrievalConfig - search parameters
2. ScoringConfig - result scoring/boosting
3. EmbeddingConfig - embedding generation
4. ChunkingConfig - code chunking
5. IndexingConfig - vector storage
6. GraphStorageConfig - Neo4j settings
7. FusionConfig - tri-brid fusion weights
8. RerankingConfig - reranker settings

For each, show the field, type, default, range, and description.""",
    },
    "api/endpoints": {
        "title": "API Endpoints",
        "output_path": "mkdocs/docs/api/endpoints.md",
        "source_files": [
            "server/api/search.py",
            "server/api/index.py",
            "server/api/config.py",
            "server/api/models.py",
            "server/api/health.py",
            "server/main.py",
        ],
        "instruction": """Document all API endpoints.

For each endpoint include:
1. HTTP method and path
2. Description
3. Request body schema (if applicable)
4. Response schema
5. Example curl command
6. Example response

Group by category: Search, Indexing, Configuration, Health""",
    },
    "operations/monitoring": {
        "title": "Monitoring & Observability",
        "output_path": "mkdocs/docs/operations/monitoring.md",
        "source_files": [
            "server/observability/metrics.py",
            "server/observability/tracing.py",
            "server/api/health.py",
        ],
        "instruction": """Document monitoring and observability.

Cover:
1. Health check endpoints
2. Metrics exposed (if Prometheus)
3. Tracing integration
4. Logging configuration
5. Alerting setup""",
    },
    "operations/troubleshooting": {
        "title": "Troubleshooting",
        "output_path": "mkdocs/docs/operations/troubleshooting.md",
        "source_files": [
            "README.md",
            "server/main.py",
        ],
        "instruction": """Write a troubleshooting guide.

Common issues:
1. Connection errors (Postgres, Neo4j)
2. Embedding failures
3. Search returning no results
4. Performance issues
5. Memory problems
6. Docker issues

For each, show symptoms, diagnosis steps, and solutions.""",
    },
}


# =============================================================================
# DocBootstrapper class
# =============================================================================

class DocBootstrapper:
    """Generates documentation pages using OpenAI API."""

    def __init__(self, model: str = "gpt-4o", max_tokens: int = 4096):
        """Initialize with OpenAI client.

        Args:
            model: OpenAI model to use (default: gpt-4o, can use gpt-5.2)
            max_tokens: Maximum tokens for response (default: 4096)
        """
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.project_root = Path(__file__).parent.parent.parent

    def _read_source_files(self, source_files: list[str]) -> str:
        """Read and concatenate source files."""
        contents = []
        for file_path in source_files:
            full_path = self.project_root / file_path
            if full_path.exists():
                try:
                    content = full_path.read_text()
                    # Truncate very large files
                    if len(content) > 50000:
                        content = content[:50000] + "\n\n... [truncated] ..."
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

        print(f"Generating: {page_key} -> {page_config['output_path']}")

        # Use the Responses API (newer than Chat Completions)
        response = self.client.responses.create(
            model=self.model,
            instructions=SYSTEM_PROMPT,
            input=user_prompt,
            max_output_tokens=self.max_tokens,
        )

        content = response.output_text

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
  %(prog)s --page index --page features/tribrid-search  # Generate multiple
  %(prog)s --all                           # Generate all pages
  %(prog)s --all --model gpt-5.2           # Use specific model
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
        default="gpt-4o",
        help="OpenAI model to use (default: gpt-4o, recommended: gpt-5.2)"
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="Maximum tokens for response (default: 4096)"
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
            max_tokens=args.max_tokens
        )
        bootstrapper.generate(pages, dry_run=args.dry_run)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
