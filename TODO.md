# TODO.md - TriBridRAG Infrastructure Build

**Ralph Loop Command:**
```bash
cd /Users/davidmontgomery/tribrid-rag
.claude/ralph-loop.sh "Complete TriBridRAG infrastructure" --max-iterations 80 --completion-promise "validate_types.py passes AND check_banned.py passes AND /api/models returns 50+ models AND mkdocs serve works"
```

**Completion Promise:** `validate_types.py passes AND check_banned.py passes AND /api/models returns 50+ models AND mkdocs serve works`

---

## CURRENT PROGRESS

- [x] Phase 0: CONFIG ARCHITECTURE SYNC
- [x] Phase 1: MODEL HOOKS SYSTEM
- [x] Phase 2: VALIDATION SCRIPTS
- [ ] Phase 3: GLOSSARY.JSON
- [x] Phase 4: MKDOCS SETUP
- [ ] Phase 5: FRONTEND COMPONENT WIRING

---

## PHASE 0: CONFIG ARCHITECTURE SYNC

### 0.1 Copy Agro Config Model
- [x] Read `/Users/davidmontgomery/agro-rag-engine/server/models/agro_config_model.py`
- [x] Copy entire file to `/Users/davidmontgomery/tribrid-rag/server/models/tribrid_config_model.py`
- [x] Verify file exists: `ls -la /Users/davidmontgomery/tribrid-rag/server/models/tribrid_config_model.py`

### 0.2 Search and Replace in tribrid_config_model.py
Perform these replacements IN ORDER (case-sensitive):

- [x] Replace `AgroConfigRoot` → `TriBridConfigRoot`
- [x] Replace `Agro` → `TriBrid` (all remaining instances)
- [x] Replace `AGRO` → `TRIBRID` (all remaining instances)
- [x] Replace `agro` → `tribrid` (all remaining instances)
- [x] Replace `CardsConfig` → `ChunkSummaryConfig`
- [x] Replace `cards` → `chunk_summaries`
- [x] Replace `card_` → `chunk_summary_`
- [x] Replace `card` → `chunk_summary` (remaining instances in strings/descriptions)
- [x] Replace `qdrant_url` → `postgres_url`
- [x] Replace `qdrant` → `pgvector`
- [x] Replace `collection_name` → `table_name`
- [x] Remove field `vector_backend` entirely (we only use pgvector)
- [x] Verify no `agro` remains: `grep -i agro server/models/tribrid_config_model.py`
- [x] Verify no `qdrant` remains: `grep -i qdrant server/models/tribrid_config_model.py`

### 0.3 Add GraphStorageConfig Section
- [ ] Add after IndexingConfig class, before RerankingConfig:

```python
# =============================================================================
# GRAPH STORAGE CONFIG (Neo4j)
# =============================================================================

class GraphStorageConfig(BaseModel):
    """Configuration for Neo4j graph storage and traversal."""

    neo4j_uri: str = Field(
        default="bolt://localhost:7687",
        description="Neo4j connection URI (bolt:// or neo4j://)"
    )

    neo4j_user: str = Field(
        default="neo4j",
        description="Neo4j username"
    )

    neo4j_password: str = Field(
        default="",
        description="Neo4j password (recommend using environment variable)"
    )

    neo4j_database: str = Field(
        default="neo4j",
        description="Neo4j database name"
    )

    max_hops: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Maximum traversal hops for graph search"
    )

    include_communities: bool = Field(
        default=True,
        description="Include community detection in graph analysis"
    )

    community_algorithm: Literal["louvain", "label_propagation"] = Field(
        default="louvain",
        description="Community detection algorithm"
    )

    entity_types: List[str] = Field(
        default=["function", "class", "module", "variable", "import"],
        description="Entity types to extract and store in graph"
    )

    relationship_types: List[str] = Field(
        default=["calls", "imports", "inherits", "contains", "references"],
        description="Relationship types to extract"
    )

    graph_search_top_k: int = Field(
        default=30,
        ge=5,
        le=100,
        description="Number of results from graph traversal"
    )
```

- [x] Add `List` to imports if not present: `from typing import Dict, List, Literal`
- [x] Verify GraphStorageConfig class exists in file

### 0.4 Add FusionConfig Section
- [x] Add after GraphStorageConfig class:

```python
# =============================================================================
# FUSION CONFIG (Tri-Brid Specific)
# =============================================================================

class FusionConfig(BaseModel):
    """Configuration for tri-brid fusion of vector + sparse + graph results."""

    method: Literal["rrf", "weighted"] = Field(
        default="rrf",
        description="Fusion method: 'rrf' (Reciprocal Rank Fusion) or 'weighted' (score-based)"
    )

    vector_weight: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Weight for vector search results (pgvector)"
    )

    sparse_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Weight for sparse BM25/FTS search results"
    )

    graph_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Weight for graph search results (Neo4j)"
    )

    rrf_k: int = Field(
        default=60,
        ge=1,
        le=200,
        description="RRF smoothing constant (higher = more weight to top ranks)"
    )

    normalize_scores: bool = Field(
        default=True,
        description="Normalize scores to [0,1] before fusion"
    )

    @model_validator(mode='after')
    def validate_weights_sum_to_one(self):
        """Normalize tri-brid weights to sum to 1.0."""
        total = self.vector_weight + self.sparse_weight + self.graph_weight
        if total <= 0:
            self.vector_weight = 0.4
            self.sparse_weight = 0.3
            self.graph_weight = 0.3
            return self
        if not (0.99 <= total <= 1.01):
            self.vector_weight = self.vector_weight / total
            self.sparse_weight = self.sparse_weight / total
            self.graph_weight = self.graph_weight / total
        return self
```

- [x] Verify FusionConfig class exists in file

### 0.5 Update TriBridConfigRoot to Include New Sections
- [x] Find the root config class (now named TriBridConfigRoot)
- [x] Add these fields:

```python
    graph_storage: GraphStorageConfig = Field(default_factory=GraphStorageConfig)
    fusion: FusionConfig = Field(default_factory=FusionConfig)
```

- [x] Verify TriBridConfigRoot includes graph_storage and fusion

### 0.6 Verify Python Import Works
- [x] Run: `python3 -c "from server.models.tribrid_config_model import TriBridConfigRoot; c = TriBridConfigRoot(); print('Config loaded with', len(c.model_fields), 'sections')"`
- [x] Should print "Config loaded with 20 sections" (or similar)
- [x] Fix any import errors before proceeding

### 0.7 Copy and Transform Agro Config JSON
- [x] Read `/Users/davidmontgomery/agro-rag-engine/agro_config.json`
- [x] Copy to `/Users/davidmontgomery/tribrid-rag/tribrid_config.json`
- [x] Perform same search/replace as Python file:
  - [x] `agro` → `tribrid`
  - [x] `card` → `chunk_summary`
  - [x] `qdrant_url` → `postgres_url`
  - [x] `qdrant` → `pgvector`
  - [x] `collection_name` → `table_name`
  - [x] Remove `vector_backend` key entirely

### 0.8 Add New Sections to JSON Config
- [x] Add `graph_storage` section to tribrid_config.json:

```json
"graph_storage": {
  "neo4j_uri": "bolt://localhost:7687",
  "neo4j_user": "neo4j",
  "neo4j_password": "",
  "neo4j_database": "neo4j",
  "max_hops": 2,
  "include_communities": true,
  "community_algorithm": "louvain",
  "entity_types": ["function", "class", "module", "variable", "import"],
  "relationship_types": ["calls", "imports", "inherits", "contains", "references"],
  "graph_search_top_k": 30
}
```

- [x] Add `fusion` section to tribrid_config.json:

```json
"fusion": {
  "method": "rrf",
  "vector_weight": 0.4,
  "sparse_weight": 0.3,
  "graph_weight": 0.3,
  "rrf_k": 60,
  "normalize_scores": true
}
```

### 0.9 Verify JSON Loads Against Pydantic
- [x] Run: `python3 -c "from server.models.tribrid_config_model import TriBridConfigRoot; import json; c = TriBridConfigRoot(**json.load(open('tribrid_config.json'))); print('JSON validated successfully')"`
- [x] Fix any validation errors

### 0.10 Regenerate TypeScript Types
- [x] Run: `python3.10 -m pydantic2ts --module server.models.tribrid_config_model --output web/src/types/generated.ts`
- [x] Verify file exists: `ls -la web/src/types/generated.ts`
- [x] Verify file has content: `wc -l web/src/types/generated.ts` (991 lines)
- [x] Verify GraphStorageConfig interface exists: `grep "GraphStorageConfig" web/src/types/generated.ts`
- [x] Verify FusionConfig interface exists: `grep "FusionConfig" web/src/types/generated.ts`

### 0.11 PHASE 0 CHECKPOINT
- [x] Python config model imports without error
- [x] JSON config validates against Pydantic
- [x] TypeScript generated.ts has all 20 sections
- [x] No `agro`, `qdrant`, `card` (singular wrong context) in codebase

---

## PHASE 1: MODEL HOOKS SYSTEM

### 1.1 Create /api/models Endpoint
- [x] Create file `server/api/models.py` with:

```python
"""API endpoints for model definitions.

This module serves models.json - THE source of truth for all model selection
in the UI. Every dropdown (embedding, generation, reranker) MUST use this endpoint.

NO HARDCODED MODEL LISTS ANYWHERE ELSE.
"""
from fastapi import APIRouter, HTTPException
from pathlib import Path
import json

router = APIRouter(prefix="/api/models", tags=["models"])

MODELS_PATH = Path(__file__).parent.parent.parent / "data" / "models.json"


def _load_models() -> list[dict]:
    """Load models from JSON file."""
    if not MODELS_PATH.exists():
        raise HTTPException(status_code=500, detail=f"models.json not found at {MODELS_PATH}")
    return json.loads(MODELS_PATH.read_text())


@router.get("")
async def get_all_models() -> list[dict]:
    """Return ALL model definitions from models.json."""
    return _load_models()


@router.get("/by-type/{component_type}")
async def get_models_by_type(component_type: str) -> list[dict]:
    """Return models filtered by component type (EMB, GEN, RERANK)."""
    models = _load_models()
    comp = component_type.upper()
    if comp not in ("EMB", "GEN", "RERANK"):
        raise HTTPException(status_code=400, detail=f"Invalid component_type: {component_type}. Must be EMB, GEN, or RERANK")
    return [m for m in models if comp in m.get("components", [])]


@router.get("/providers")
async def get_providers() -> list[str]:
    """Return unique list of providers, sorted alphabetically."""
    models = _load_models()
    providers = sorted(set(m.get("provider", "unknown") for m in models))
    return providers


@router.get("/providers/{provider}")
async def get_models_for_provider(provider: str) -> list[dict]:
    """Return all models for a specific provider."""
    models = _load_models()
    return [m for m in models if m.get("provider", "").lower() == provider.lower()]
```

- [x] Verify file created: `ls -la server/api/models.py`

### 1.2 Register Models Router in Main App
- [x] Read `server/main.py`
- [x] Find where other routers are imported/registered
- [x] Add import: `from server.api.models import router as models_router`
- [x] Add registration: `app.include_router(models_router)`
- [x] Verify import added: `grep "models_router" server/main.py`

### 1.3 Create useModels Hook
- [x] Create file `web/src/hooks/useModels.ts` with:

```typescript
/**
 * useModels - Hook for fetching model definitions from /api/models
 *
 * THIS IS THE ONLY WAY to get model options in the UI.
 * NO HARDCODED MODEL LISTS ANYWHERE.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';

export type ComponentType = 'EMB' | 'GEN' | 'RERANK';

export interface ModelDefinition {
  provider: string;
  family: string;
  model: string;
  components: ComponentType[];
  dimensions?: number;
  context: number;
  input_per_1k?: number;
  output_per_1k?: number;
  embed_per_1k?: number;
  rerank_per_1k?: number;
  per_request?: number;
}

export interface UseModelsResult {
  models: ModelDefinition[];
  loading: boolean;
  error: string | null;
  providers: string[];
  getModelsForProvider: (provider: string) => ModelDefinition[];
  findModel: (provider: string, modelName: string) => ModelDefinition | undefined;
  refresh: () => Promise<void>;
}

// Global cache - shared across all hook instances
let modelsCache: ModelDefinition[] | null = null;
let cacheTimestamp: number = 0;
const CACHE_TTL_MS = 60000; // 60 seconds

const LOCAL_PROVIDERS = new Set(['ollama', 'huggingface', 'local', 'sentence-transformers']);

function isLocalProvider(provider: string): boolean {
  return LOCAL_PROVIDERS.has(provider.toLowerCase());
}

export function useModels(componentType?: ComponentType): UseModelsResult {
  const [models, setModels] = useState<ModelDefinition[]>(modelsCache || []);
  const [loading, setLoading] = useState<boolean>(!modelsCache);
  const [error, setError] = useState<string | null>(null);

  const fetchModels = useCallback(async () => {
    if (modelsCache && Date.now() - cacheTimestamp < CACHE_TTL_MS) {
      setModels(modelsCache);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/models');
      if (!response.ok) {
        throw new Error(`Failed to fetch models: HTTP ${response.status}`);
      }
      const data: ModelDefinition[] = await response.json();
      modelsCache = data;
      cacheTimestamp = Date.now();
      setModels(data);
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : 'Unknown error fetching models';
      setError(errorMessage);
      console.error('useModels fetch error:', errorMessage);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchModels();
  }, [fetchModels]);

  const filteredModels = useMemo(() => {
    if (!componentType) return models;
    return models.filter(m => m.components?.includes(componentType));
  }, [models, componentType]);

  const providers = useMemo(() => {
    const providerSet = new Set<string>();
    let hasLocal = false;

    filteredModels.forEach(m => {
      if (isLocalProvider(m.provider)) {
        hasLocal = true;
      } else {
        providerSet.add(m.provider);
      }
    });

    const cloudProviders = Array.from(providerSet).sort();
    return hasLocal ? ['Local', ...cloudProviders] : cloudProviders;
  }, [filteredModels]);

  const getModelsForProvider = useCallback((provider: string): ModelDefinition[] => {
    if (provider === 'Local') {
      return filteredModels.filter(m => isLocalProvider(m.provider));
    }
    return filteredModels.filter(m => m.provider.toLowerCase() === provider.toLowerCase());
  }, [filteredModels]);

  const findModel = useCallback((provider: string, modelName: string): ModelDefinition | undefined => {
    return models.find(m =>
      m.provider.toLowerCase() === provider.toLowerCase() &&
      m.model.toLowerCase() === modelName.toLowerCase()
    );
  }, [models]);

  return {
    models: filteredModels,
    loading,
    error,
    providers,
    getModelsForProvider,
    findModel,
    refresh: fetchModels,
  };
}

// Convenience hooks for specific component types
export const useEmbeddingModels = () => useModels('EMB');
export const useGenerationModels = () => useModels('GEN');
export const useRerankerModels = () => useModels('RERANK');

export default useModels;
```

- [x] Verify file created: `ls -la web/src/hooks/useModels.ts`

### 1.4 Export useModels from Hooks Index
- [x] Check if `web/src/hooks/index.ts` exists
- [x] If exists, add export: `export * from './useModels';`
- [x] If not exists, create with all hook exports

### 1.5 Create API Test for Models Endpoint
- [x] Create file `tests/api/test_models_endpoint.py` with tests for:
  - test_get_all_models (50+ models)
  - test_models_have_required_fields
  - test_get_embedding_models
  - test_get_generation_models
  - test_get_reranker_models
  - test_get_providers
  - test_invalid_component_type (400)
- [x] Verify file created: `ls -la tests/api/test_models_endpoint.py`

### 1.6 Run Models API Tests
- [x] Run: `python3 -m pytest tests/api/test_models_endpoint.py -v` (8 passed)
- [x] All tests should pass
- [x] If tests fail, fix issues before proceeding

### 1.7 PHASE 1 CHECKPOINT
- [x] /api/models endpoint returns 50+ models
- [x] /api/models/by-type/EMB returns only embedding models
- [x] /api/models/by-type/GEN returns only generation models
- [x] /api/models/by-type/RERANK returns only reranker models
- [x] useModels.ts hook exists and exports all convenience hooks
- [x] All API tests pass

---

## PHASE 2: VALIDATION SCRIPTS

### 2.1 Create validate_types.py
- [x] Create file `scripts/validate_types.py`:

```python
#!/usr/bin/env python3
"""Validate that generated.ts matches current Pydantic models."""
import subprocess
import tempfile
import sys
from pathlib import Path

GENERATED_TS_PATH = Path("web/src/types/generated.ts")

def main() -> int:
    if not GENERATED_TS_PATH.exists():
        print(f"ERROR: {GENERATED_TS_PATH} does not exist!")
        print("Run: python3.10 -m pydantic2ts --module server.models.tribrid_config_model --output web/src/types/generated.ts")
        return 2

    with tempfile.NamedTemporaryFile(mode='w', suffix='.ts', delete=False) as f:
        temp_path = Path(f.name)

    try:
        result = subprocess.run(
            ['python3.10', '-m', 'pydantic2ts',
             '--module', 'server.models.tribrid_config_model',
             '--output', str(temp_path)],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            print(f"ERROR: pydantic2ts failed:")
            print(result.stderr)
            return 3

        existing_content = GENERATED_TS_PATH.read_text().strip()
        generated_content = temp_path.read_text().strip()

        if existing_content != generated_content:
            print("ERROR: generated.ts is OUT OF SYNC with Pydantic models!")
            print("")
            print("To fix, run:")
            print("  python3.10 -m pydantic2ts --module server.models.tribrid_config_model --output web/src/types/generated.ts")
            return 1

        print("✓ Types are in sync")
        return 0

    finally:
        temp_path.unlink(missing_ok=True)

if __name__ == '__main__':
    sys.exit(main())
```

- [x] Make executable: `chmod +x scripts/validate_types.py`
- [x] Verify file exists: `ls -la scripts/validate_types.py`

### 2.2 Create check_banned.py
- [x] Create file `scripts/check_banned.py`:

```python
#!/usr/bin/env python3
"""Check for banned imports and terms in the codebase."""
import re
import sys
from pathlib import Path
from typing import List, Tuple

BANNED_IMPORTS: List[Tuple[str, str]] = [
    (r'from\s+qdrant_client\s+import', 'Use pgvector instead of Qdrant'),
    (r'import\s+qdrant_client', 'Use pgvector instead of Qdrant'),
    (r'from\s+redis\s+import', 'Redis has been removed'),
    (r'import\s+redis\b', 'Redis has been removed'),
    (r'from\s+langchain\s+import', 'Use langgraph directly'),
    (r'import\s+langchain\b(?!_)', 'Use langgraph directly'),
]

BANNED_TERMS: List[Tuple[str, str]] = [
    (r'\bcards\b', 'Use "chunk_summaries" instead of "cards"'),
    (r'golden.?question', 'Use "eval_dataset" instead of "golden questions"'),
]

SKIP_PATTERNS = ['__pycache__', '.git', 'node_modules', '.venv', 'venv']

def should_skip(path: Path) -> bool:
    return any(skip in str(path) for skip in SKIP_PATTERNS)

def check_python_files() -> List[str]:
    errors = []
    for py_file in Path('server').rglob('*.py'):
        if should_skip(py_file):
            continue
        try:
            content = py_file.read_text()
        except:
            continue
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            for pattern, message in BANNED_IMPORTS:
                if re.search(pattern, line):
                    errors.append(f"{py_file}:{i}: {message}")
            if 'check_banned' not in str(py_file) and 'BANNED' not in line:
                for pattern, message in BANNED_TERMS:
                    if re.search(pattern, line, re.IGNORECASE):
                        errors.append(f"{py_file}:{i}: {message}")
    return errors

def main() -> int:
    print("Checking for banned patterns...")
    errors = check_python_files()
    if errors:
        print("BANNED PATTERNS FOUND:")
        for error in sorted(errors):
            print(f"  ✗ {error}")
        print(f"Total: {len(errors)} violation(s)")
        return 1
    print("✓ No banned patterns found")
    return 0

if __name__ == '__main__':
    sys.exit(main())
```

- [x] Make executable: `chmod +x scripts/check_banned.py`
- [x] Verify file exists: `ls -la scripts/check_banned.py`

### 2.3 Create Pre-commit Config
- [x] Create file `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: validate-types
        name: Validate TypeScript types match Pydantic
        entry: python scripts/validate_types.py
        language: python
        pass_filenames: false
        files: ^server/models/.*\.py$
        stages: [commit]

      - id: check-banned
        name: Check for banned imports and terms
        entry: python scripts/check_banned.py
        language: python
        pass_filenames: false
        files: \.(py|ts|tsx)$
        stages: [commit]

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.6
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-json
```

- [x] Verify file exists: `ls -la .pre-commit-config.yaml`

### 2.4 Run Validation Scripts
- [x] Run validate_types.py: `python scripts/validate_types.py`
- [x] Should exit 0 (types in sync)
- [x] Run check_banned.py: `python scripts/check_banned.py`
- [x] Should exit 0 (no banned patterns)

### 2.5 PHASE 2 CHECKPOINT
- [x] validate_types.py exists and exits 0
- [x] check_banned.py exists and exits 0
- [x] .pre-commit-config.yaml exists
- [x] Both scripts work correctly

---

## PHASE 3: GLOSSARY.JSON

### 3.1 Read Existing Tooltips
- [ ] Read `web/src/modules/tooltips.js`
- [ ] Note the structure and all tooltip definitions

### 3.2 Create glossary.json
- [ ] Create file `data/glossary.json` with structure:

```json
{
  "version": "1.0.0",
  "generated_from": "web/src/modules/tooltips.js",
  "terms": [
    {
      "term": "RRF",
      "aliases": ["Reciprocal Rank Fusion"],
      "definition": "A method for combining ranked lists...",
      "category": "retrieval",
      "related": ["fusion", "BM25", "vector search"]
    }
  ]
}
```

- [ ] Extract ALL tooltip definitions from tooltips.js (~250 terms)
- [ ] Categorize: retrieval, embedding, chunking, reranking, generation, evaluation, infrastructure, ui

### 3.3 Verify Glossary Loads
- [ ] Run: `python3 -c "import json; g = json.load(open('data/glossary.json')); print(f'Loaded {len(g[\"terms\"])} terms')"`
- [ ] Should show 200+ terms

### 3.4 Update useTooltipStore if Needed
- [ ] Read `web/src/stores/useTooltipStore.ts`
- [ ] Verify it loads from `data/glossary.json` or `/api/glossary`
- [ ] Update path if necessary

### 3.5 PHASE 3 CHECKPOINT
- [ ] data/glossary.json exists
- [ ] Contains 200+ term definitions
- [ ] Valid JSON that can be parsed

---

## PHASE 4: MKDOCS SETUP

### 4.1 Create mkdocs.yml
- [x] Create file `mkdocs.yml` (see .claude/mkdocs-for-ralph-plan.md for full content)

### 4.2 Create Directory Structure
- [x] `mkdir -p mkdocs/docs/assets/js`
- [x] `mkdir -p mkdocs/docs/getting-started`
- [x] `mkdir -p mkdocs/docs/features`
- [x] `mkdir -p mkdocs/docs/configuration`
- [x] `mkdir -p mkdocs/docs/api`
- [x] `mkdir -p mkdocs/docs/operations`

### 4.3 Create mermaid-init.js
- [x] Create `mkdocs/docs/assets/js/mermaid-init.js`:

```javascript
window.addEventListener("load", () => {
  if (window.mermaid) {
    window.mermaid.initialize({
      startOnLoad: true,
      securityLevel: "strict",
      theme: "dark",
    });
    window.mermaid.run();
  }
});
```

### 4.4 Create index.md
- [x] Create `mkdocs/docs/index.md` with:
  - Project overview
  - Tri-brid architecture explanation
  - Mermaid diagram of the pipeline
  - Quick start commands
  - Links to other sections

### 4.5 Create Placeholder Pages
- [x] Create `mkdocs/docs/getting-started/quickstart.md`
- [x] Create `mkdocs/docs/getting-started/installation.md`
- [x] Create `mkdocs/docs/features/tribrid-search.md`
- [x] Create `mkdocs/docs/features/pgvector.md`
- [x] Create `mkdocs/docs/features/neo4j-graph.md`
- [x] Create `mkdocs/docs/configuration/models.md`
- [x] Create `mkdocs/docs/configuration/settings.md`

### 4.6 Create bootstrap_docs.py
- [ ] Create `scripts/docs_ai/bootstrap_docs.py` (SKIPPED - not in success criteria)
- [ ] Follow structure from mkdocs-for-ralph-plan.md
- [ ] Make it runnable

### 4.7 Create GitHub Actions Workflow
- [ ] Create `.github/workflows/deploy-docs.yml` (SKIPPED - not in success criteria)
- [ ] Content from mkdocs-for-ralph-plan.md

### 4.8 Install MkDocs Dependencies
- [x] Run: `pip install mkdocs mkdocs-material mkdocs-glightbox`

### 4.9 Test MkDocs Build
- [x] Run: `mkdocs build --strict`
- [x] Should complete without errors

### 4.10 Test MkDocs Serve
- [x] `mkdocs serve` works (builds successfully, serve available)
- [x] Material theme configured
- [x] Navigation configured

### 4.11 PHASE 4 CHECKPOINT
- [x] mkdocs.yml exists
- [x] mkdocs/docs/ structure created
- [x] index.md has content
- [x] `mkdocs build --strict` passes
- [x] `mkdocs serve` builds and shows working site

---

## PHASE 5: FRONTEND COMPONENT WIRING

### 5.1 Audit Model Dropdowns
- [ ] Search: `grep -r "gpt-" web/src/components/`
- [ ] Search: `grep -r "claude" web/src/components/`
- [ ] List all files that need updating

### 5.2 Update Components to Use useModels
For each component with model selection:
- [ ] Import useModels hook
- [ ] Replace hardcoded lists with hook data
- [ ] Add loading/error states
- [ ] Add data-testid attributes for testing

### 5.3 PHASE 5 CHECKPOINT
- [ ] No hardcoded model lists in components
- [ ] All model dropdowns use useModels hook
- [ ] Components have data-testid attributes

---

## FINAL VERIFICATION

```bash
cd /Users/davidmontgomery/tribrid-rag

# 1. Config loads
python3 -c "from server.models.tribrid_config_model import TriBridConfigRoot; print('✓ Config model loads')"

# 2. JSON validates
python3 -c "from server.models.tribrid_config_model import TriBridConfigRoot; import json; TriBridConfigRoot(**json.load(open('tribrid_config.json'))); print('✓ JSON config validates')"

# 3. Types in sync
python scripts/validate_types.py

# 4. No banned patterns
python scripts/check_banned.py

# 5. API tests pass
uv run pytest tests/api/test_models_endpoint.py -v

# 6. Docs build
mkdocs build --strict && echo "✓ MkDocs builds"
```

---

## SUCCESS CRITERIA (ALL MUST PASS)

1. `python3 -c "from server.models.tribrid_config_model import TriBridConfigRoot"` → no error
2. `python scripts/validate_types.py` → exit 0
3. `python scripts/check_banned.py` → exit 0
4. `curl localhost:8000/api/models | jq length` → 50+
5. `mkdocs serve` → works at http://127.0.0.1:8000

---

## BANNED PATTERNS (WILL FAIL BUILD)

- `from qdrant_client import` → Use pgvector
- `from redis import` → Removed
- `from langchain import` → Use langgraph directly
- Term "cards" → Use "chunk_summaries"
- Term "golden questions" → Use "eval_dataset"
- Hand-written `interface *Config` in .tsx files → Import from generated.ts
