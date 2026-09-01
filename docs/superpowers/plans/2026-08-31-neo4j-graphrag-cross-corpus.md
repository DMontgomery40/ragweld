# Neo4j GraphRAG Cross-Corpus Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Repository rules override the generic worktree/subagent recommendation: use the one existing `main` worktree on the Mac and the one existing `/opt/ragweld` checkout on LXC100; do not create a branch, worktree, or subagent.

**Goal:** Replace Ragweld's chunk-only fake graph lane with a corpus-scoped, schema-reviewed Neo4j GraphRAG pipeline whose Qdrant-seeded traversal, resolved entities, fail-closed promotion, GDS Leiden communities, UI, and live browser behavior work honestly across NASA, Epstein, and code corpora.

**Architecture:** Postgres remains generation and chunk truth, Qdrant remains vector truth, and Neo4j stores the official lexical graph, resolved semantic/code entities, relationships, and Leiden properties. A single corpus graph policy selects `semantic`, `code`, `off`, or `excluded`; external document corpora derive and approve one persisted schema before bulk extraction, code corpora use AST entities, and internal Recall remains excluded. Retrieval constructs an official `QdrantNeo4jRetriever` from the promoted manifest per request and credits only traversal-derived chunks.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, `neo4j-graphrag==1.19.0`, Neo4j 5.26.20 Community, GDS 2.13.x, APOC, Qdrant 1.17, Postgres, Haystack, React/Vite, generated TypeScript, Playwright, GitNexus, LiteLLM/OpenRouter DeepSeek V4 Flash.

**Spec:** `docs/superpowers/specs/2026-08-31-neo4j-graphrag-cross-corpus-design.md`

## Global Constraints

- The Mac checkout is source-editing only. Run dependency resolution, generators, tests, builds, services, indexing, models, databases, observability, and browser acceptance on LXC100 (`192.168.68.225`, `/opt/ragweld`) only.
- Before editing any existing function, class, or method, run `node .gitnexus/run.cjs impact --repo ragweld --direction upstream --target <symbol>` and report HIGH or CRITICAL risk before mutation.
- Before every commit, run `node .gitnexus/run.cjs detect-changes --scope compare --base-ref main --repo ragweld` and verify the affected symbols/processes match that task.
- Use replacement-only behavior: no legacy fallback, compatibility shim, dual read/write, deprecated hidden setting, or old `IN_CHUNK`/Neo4j-vector/Community-node path.
- Pin `neo4j-graphrag[openai]==1.19.0`; import components from `neo4j_graphrag.components`. `Pipeline` remains in `neo4j_graphrag.experimental.pipeline` because 1.19 has not moved that orchestrator.
- Use the shipped lexical defaults `FROM_DOCUMENT`, `NEXT_CHUNK`, and `FROM_CHUNK`; never introduce `PART_OF_*` names.
- Install GDS 2.13.x with Neo4j 5.26.20 and record that this is the terminal GDS line for Neo4j 5.x.
- No semantic graph opt-in exists for internal corpora during this phase. `recall_default` and all `meta.system_kind` corpora resolve to policy `excluded` regardless of UI/config input.
- Every new/edited test uses real stores and real domain inputs. No Python mocks/monkeypatch, Playwright route fulfillment, skip stubs, placeholder queries, or fake graph data at a public acceptance boundary.
- Each task is a DeepSeek work chunk. Submit the exact task diff, relevant 1.19/GDS docs, test commands, and outputs to production alias `deepseek.deepseek-v4-flash` at temperature 0; resolve every substantiated P1/P2 and obtain PASS before committing.
- Do not hand-edit `mkdocs/**` or `mkdocs.yml`. Update normal docs, generated contracts, and both glossary mirrors through their owners.
- Browser acceptance uses the authenticated in-app browser and real visible clicks, selects, typing, scrolling, node selection, neighborhood expansion, zoom/pan/fit, filters, reloads, and screenshots. DOM/API calls are diagnostic only and cannot satisfy acceptance.

## Execution Workspace and Review Contract

Use an explicit LXC overlay for uncommitted TDD files without creating another Git worktree:

```bash
rsync -aR -e 'ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519' \
  <relative-paths> root@192.168.68.225:/tmp/ragweld-graphrag/
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 \
  root@192.168.68.225 \
  'cd /tmp/ragweld-graphrag && set -a && . /etc/ragweld/runtime.env && set +a && PYTHONPATH=/tmp/ragweld-graphrag /opt/ragweld/.venv/bin/python -m pytest <tests>'
```

The overlay starts as a copy of `/opt/ragweld` at the plan commit and is refreshed only with the explicit paths owned by the current task. Never point tests at the Mac checkout.

For each DeepSeek review, send:

```text
Review this complete Ragweld GraphRAG task diff adversarially. Verify correctness,
generation/corpus isolation, official neo4j-graphrag 1.19 or GDS 2.13 contracts,
replacement-only cleanup, real test strength, blocking I/O, failure behavior, and
operator/UI truth. Return VERDICT PASS or FAIL and P1/P2/P3 findings with exact files.
A P1/P2 is FAIL. Do not suggest compatibility fallbacks.
```

Include `git diff <task-base>...HEAD` (or the exact staged diff before commit), focused test output, and the source/doc snippets that define the external API used. A gateway timeout or empty response is not a review; retry the same payload. Record response id, resolved model, usage, cost, verdict, fixes, and re-review verdict in `docs/exec-plans/active/graphrag-cross-corpus-2026-08-31.md`, never credentials or headers.

---

### Task 1: Pin and Characterize Neo4j GraphRAG 1.19

**Files:**
- Modify: `pyproject.toml:56`
- Modify mechanically on LXC100, then copy back: `uv.lock`
- Modify: `server/indexing/official_graphrag.py:7-25`
- Modify: `server/indexing/code_graph.py:15-30`
- Modify: `server/db/neo4j.py:14-17`
- Modify: `tests/unit/test_official_graphrag.py:1-107`
- Modify: `tests/integration/test_graph_communities_live.py:1-30`
- Create: `tests/unit/test_neo4j_graphrag_119_contract.py`
- Create: `docs/exec-plans/active/graphrag-cross-corpus-2026-08-31.md`
- Modify: `AGENTS.md:8` and `CLAUDE.md:255` only for the already-generated GitNexus count refresh

**Interfaces:**
- Consumes: current pin `neo4j-graphrag[openai]==1.14.1` and experimental component imports.
- Produces: installed 1.19.0 contract, non-experimental component imports, and executable characterization evidence for every external API later tasks rely on.

- [x] **Step 1: Run impact analysis for edited import-owning symbols**

Run:

```bash
node .gitnexus/run.cjs impact --repo ragweld --direction upstream --target GraphRAGExtractionResult
node .gitnexus/run.cjs impact --repo ragweld --direction upstream --target Neo4jClient
node .gitnexus/run.cjs impact --repo ragweld --direction upstream --target extract_code_graph
```

Record direct callers, affected processes, and risk in the execution ledger. Stop and report before edits if any result is HIGH or CRITICAL.

- [x] **Step 2: Write the 1.19 contract test before changing the dependency**

Create `tests/unit/test_neo4j_graphrag_119_contract.py` with real imports and signature/default assertions:

```python
from importlib.metadata import version
from inspect import iscoroutinefunction, signature

from neo4j_graphrag.components.kg_writer import Neo4jWriter
from neo4j_graphrag.components.resolver import SinglePropertyExactMatchResolver
from neo4j_graphrag.components.schema import GraphSchema, SchemaFromTextExtractor
from neo4j_graphrag.components.types import LexicalGraphConfig
from neo4j_graphrag.retrievers import QdrantNeo4jRetriever


def test_pinned_graphrag_contract_matches_the_replacement_design() -> None:
    assert version("neo4j-graphrag") == "1.19.0"
    lexical = LexicalGraphConfig()
    assert lexical.chunk_to_document_relationship_type == "FROM_DOCUMENT"
    assert lexical.next_chunk_relationship_type == "NEXT_CHUNK"
    assert lexical.node_to_chunk_relationship_type == "FROM_CHUNK"
    assert "filter_query" in signature(SinglePropertyExactMatchResolver).parameters
    qdrant = signature(QdrantNeo4jRetriever).parameters
    assert {"collection_name", "id_property_external", "id_property_neo4j", "retrieval_query", "id_property_getter"} <= set(qdrant)
    assert hasattr(GraphSchema, "save") and hasattr(GraphSchema, "from_file")
    assert "use_structured_output" in signature(SchemaFromTextExtractor).parameters
    assert list(signature(Neo4jWriter.run).parameters)[:3] == ["self", "graph", "lexical_graph_config"]
    assert iscoroutinefunction(Neo4jWriter.run), "1.19 Neo4jWriter.run is async despite using a sync driver"
```

- [x] **Step 3: Run the contract test on LXC100 and observe RED**

Run in the LXC overlay:

```bash
/opt/ragweld/.venv/bin/python -m pytest -q --no-cov -p no:cacheprovider \
  tests/unit/test_neo4j_graphrag_119_contract.py
```

Expected: collection fails because 1.14.1 lacks the non-experimental component imports or the version assertion reports `1.14.1`.

- [x] **Step 4: Change the exact pin and regenerate the lock on LXC100**

Change the dependency to:

```toml
"neo4j-graphrag[openai]==1.19.0",
```

Sync `pyproject.toml` to the overlay, then run on LXC100:

```bash
cd /tmp/ragweld-graphrag
uv lock
uv sync --extra dev
```

Copy only the generated `uv.lock` back to the Mac. Do not run `uv lock` or `uv sync` on the Mac.

- [x] **Step 5: Replace experimental component imports**

Use these 1.19 modules everywhere except `Pipeline`:

```python
from neo4j_graphrag.components.entity_relation_extractor import LLMEntityRelationExtractor, OnError
from neo4j_graphrag.components.graph_pruning import GraphPruning
from neo4j_graphrag.components.kg_writer import Neo4jWriter
from neo4j_graphrag.components.lexical_graph import LexicalGraphBuilder
from neo4j_graphrag.components.resolver import SinglePropertyExactMatchResolver
from neo4j_graphrag.components.schema import GraphSchema, SchemaFromTextExtractor
from neo4j_graphrag.components.types import DocumentInfo, LexicalGraphConfig, Neo4jGraph, TextChunk, TextChunks
from neo4j_graphrag.experimental.pipeline import Pipeline
from neo4j_graphrag.llm import OpenAILLM
```

Do not change behavior in this task; only make the installed contract importable.

- [x] **Step 6: Run focused and dependency-boundary verification on LXC100**

Run:

```bash
uv run pytest -q --no-cov -p no:cacheprovider \
  tests/unit/test_neo4j_graphrag_119_contract.py \
  tests/unit/test_official_graphrag.py \
  tests/unit/test_code_graph.py
uv run python -c 'import neo4j_graphrag; from importlib.metadata import version; assert version("neo4j-graphrag") == "1.19.0"'
uv run scripts/check_banned.py
```

Expected: all tests and checks PASS with 1.19.0.

- [x] **Step 7: Obtain DeepSeek V4 Flash PASS for Task 1**

Submit the complete dependency/import diff, the characterization test, `uv lock` result, and focused output. Fix every substantiated P1/P2 and rerun Step 6 before re-review. Record a completed PASS in the ledger.

- [x] **Step 8: Detect scope and commit Task 1**

Run:

```bash
node .gitnexus/run.cjs detect-changes --scope compare --base-ref main --repo ragweld
git add AGENTS.md CLAUDE.md pyproject.toml uv.lock \
  server/indexing/official_graphrag.py server/indexing/code_graph.py server/db/neo4j.py \
  tests/unit/test_official_graphrag.py tests/unit/test_neo4j_graphrag_119_contract.py \
  tests/integration/test_graph_communities_live.py
git commit -m "build: upgrade Neo4j GraphRAG to 1.19"
```

Expected: only dependency/import/characterization surfaces are affected.

---

### Task 2: Replace Contradictory Graph Defaults with One Corpus Policy

**Files:**
- Create: `server/indexing/graph_policy.py`
- Modify: `server/models/tribrid_config_model.py:4733-5223`
- Modify: `server/api/index.py:2323-2425, 3910-4055`
- Modify: `tribrid_config.json`
- Modify: `data/glossary.json`
- Modify mechanically on LXC100: `web/public/glossary.json`, `web/src/types/generated.ts`
- Modify: `web/src/components/RAG/IndexingSubtab.tsx:368-375, 3090-3260`
- Modify: `web/src/components/RAG/RetrievalSubtab.tsx:224-241, 718-820`
- Modify: `web/src/components/RAG/ModelAssignments.tsx:30-55`
- Modify: `tests/unit/test_config.py:104-224`
- Modify: `tests/api/test_config_endpoints.py:1-100`
- Create: `tests/unit/test_graph_policy.py`
- Create: `web/tests/e2e/exhaustive/graph_policy.spec.ts`

**Interfaces:**
- Consumes: corpus `meta.system_kind`, `GraphIndexingConfig.enabled`, and `build_code_graph`.
- Produces: `resolve_graph_policy(*, internal: bool, enabled: bool, build_code_graph: bool) -> GraphPolicy`, where `GraphPolicy = Literal["semantic", "code", "off", "excluded"]`; one truthful graph configuration/UI surface.

- [x] **Step 1: Run impact analysis on policy/config/UI symbols**

Run:

```bash
node .gitnexus/run.cjs impact --repo ragweld --direction upstream --target GraphStorageConfig
node .gitnexus/run.cjs impact --repo ragweld --direction upstream --target GraphSearchConfig
node .gitnexus/run.cjs impact --repo ragweld --direction upstream --target GraphIndexingConfig
node .gitnexus/run.cjs impact --repo ragweld --direction upstream --target _run_index_body
node .gitnexus/run.cjs impact --repo ragweld --direction upstream --target IndexingSubtab
node .gitnexus/run.cjs impact --repo ragweld --direction upstream --target RetrievalSubtab
```

Record blast radius and warn before editing on HIGH/CRITICAL.

- [x] **Step 2: Write policy and config RED tests**

Create `tests/unit/test_graph_policy.py`:

```python
from server.indexing.graph_policy import resolve_graph_policy


def test_graph_policy_matrix_has_no_internal_or_chunk_only_semantic_trap() -> None:
    assert resolve_graph_policy(internal=True, enabled=True, build_code_graph=False) == "excluded"
    assert resolve_graph_policy(internal=True, enabled=True, build_code_graph=True) == "excluded"
    assert resolve_graph_policy(internal=False, enabled=False, build_code_graph=False) == "off"
    assert resolve_graph_policy(internal=False, enabled=True, build_code_graph=False) == "semantic"
    assert resolve_graph_policy(internal=False, enabled=True, build_code_graph=True) == "code"
```

Extend config tests to assert these removed fields are absent from serialization:

```python
def test_graph_config_has_one_policy_surface_without_a_second_semantic_toggle() -> None:
    payload = TriBridConfig().model_dump(mode="json")
    assert payload["graph_indexing"]["enabled"] is True
    for key in {
        "semantic_kg_enabled", "semantic_kg_mode", "semantic_kg_typed_entities_enabled",
        "semantic_kg_require_llm_success", "semantic_kg_relation_weight_llm",
        "semantic_kg_relation_weight_heuristic", "semantic_kg_max_concepts_per_chunk",
        "semantic_kg_min_concept_len", "semantic_kg_max_relations_per_chunk",
    }:
        assert key not in payload["graph_indexing"]
```

The schema type lists remain until Task 3 replaces them with the approved per-corpus schema. Neo4j vector/search fields remain until Task 6 replaces their consumers. Community fields remain until Task 7 replaces the Community-node implementation. This task removes only the contradictory semantic toggle and truly unused heuristic controls.

- [x] **Step 3: Run policy/config tests and observe RED**

Run on LXC100:

```bash
uv run pytest -q --no-cov -p no:cacheprovider \
  tests/unit/test_graph_policy.py tests/unit/test_config.py tests/api/test_config_endpoints.py
```

Expected: missing policy module and obsolete fields still serialized.

- [x] **Step 4: Implement the pure policy resolver**

Create `server/indexing/graph_policy.py`:

```python
from typing import Literal

GraphPolicy = Literal["semantic", "code", "off", "excluded"]


def resolve_graph_policy(*, internal: bool, enabled: bool, build_code_graph: bool) -> GraphPolicy:
    if internal:
        return "excluded"
    if not enabled:
        return "off"
    return "code" if build_code_graph else "semantic"
```

Resolve `internal` from the corpus row's own `meta.system_kind` at estimate/start time. Do not hardcode `recall_default` and do not accept a request/config override for internal corpora.

- [x] **Step 5: Remove dead configuration and make semantic extraction the external default**

Remove the second semantic enablement and unused heuristic controls while retaining the fields still consumed by later replacement tasks. The effective policy ignores any stale persisted `semantic_kg_enabled` key because Pydantic no longer defines it:

```python
class GraphIndexingConfig(BaseModel):
    enabled: bool = True
    build_code_graph: bool = False
    ast_contains_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    ast_inherits_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    ast_imports_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    ast_calls_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    semantic_kg_reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh"] = "medium"
    semantic_kg_max_chunks: int = Field(default=40000, ge=1, le=100000)
    semantic_kg_llm_model: str = ""
    semantic_kg_llm_timeout_s: int = Field(default=90, ge=5, le=600)
    semantic_kg_allowed_entity_types: list[str] = Field(default=["person", "org", "location", "event", "concept"])
    semantic_kg_allowed_relation_types: list[str] = Field(default=["associated_with", "met_with", "communicated_with", "works_for", "member_of", "founded", "owns", "funded", "participated_in", "located_in", "references", "related_to"])
    store_chunk_embeddings: bool = True
    chunk_vector_index_name: str = "tribrid_chunk_embeddings"
    chunk_embedding_property: str = "embedding"
    vector_similarity_function: Literal["cosine", "euclidean"] = "cosine"
    wait_vector_index_online: bool = True
    vector_index_online_timeout_s: float = Field(default=60.0, ge=1.0, le=600.0)
```

`semantic_kg_max_chunks` becomes a preflight ceiling: if estimated or actual eligible chunks exceed it, the run is refused as non-promotable. It never slices the input.

- [x] **Step 6: Replace the Indexing and Retrieval graph controls**

The Indexing card renders one enablement plus a read-only derived policy badge:

```tsx
<input
  data-testid="graph-indexing-enabled"
  type="checkbox"
  checked={graphIndexingEnabled}
  disabled={Boolean(activeCorpus?.internal)}
  onChange={(event) => setGraphIndexingEnabled(event.target.checked)}
/>
<strong>Build a real graph during indexing</strong>
<span data-testid="graph-policy-badge">
  {activeCorpus?.internal ? 'Excluded internal corpus' : buildCodeGraph ? 'Code AST graph' : 'Semantic entity graph'}
</span>
```

Remove the separate semantic checkbox and disabled heuristic engine selector. Keep the current storage/retrieval controls until their owning replacement tasks, plus model, reasoning effort, timeout, ceiling, code-graph selection, and AST weights. The main graph card and policy badge must state that an enabled external document corpus will run semantic extraction; there is no second switch that can contradict it.

- [x] **Step 7: Regenerate and verify public contracts on LXC100**

Run:

```bash
uv run scripts/generate_types.py
uv run scripts/validate_types.py
uv run pytest -q --no-cov -p no:cacheprovider \
  tests/unit/test_graph_policy.py tests/unit/test_config.py tests/api/test_config_endpoints.py
cd web && npm run lint && npm run build
```

Copy generated `web/src/types/generated.ts` and mirrored `web/public/glossary.json` back to the Mac. Expected: removed fields have no generated representation and all checks PASS.

- [x] **Step 8: Add real Playwright policy coverage**

`web/tests/e2e/exhaustive/graph_policy.spec.ts` must select an external corpus and the internal Recall corpus through visible dropdowns, open Graph & Enrichment, and assert:

```typescript
await expect(page.getByTestId('graph-policy-badge')).toHaveText('Semantic entity graph');
await corpusSelect.selectOption('recall_default');
await expect(page.getByTestId('graph-policy-badge')).toHaveText('Excluded internal corpus');
await expect(page.getByTestId('graph-indexing-enabled')).toBeDisabled();
```

No request interception. Run headed on LXC100 against the real API.

- [x] **Step 9: Obtain DeepSeek V4 Flash PASS for Task 2**

Submit policy/config/UI diff, generated-contract evidence, pytest output, frontend lint/build, and headed Playwright output. Resolve P1/P2, rerun Steps 7-8, and obtain PASS.

- [x] **Step 10: Detect scope and commit Task 2**

Run `detect-changes`, then commit explicit files:

```bash
git commit -m "refactor: make graph indexing policy truthful"
```

Expected affected processes: config load/save, indexing preflight, Indexing/Retrieval controls; no retrieval implementation change yet.

---

### Task 3: Derive, Persist, Review, and Approve One Corpus Schema

**Files:**
- Create: `server/indexing/graphrag_schema.py`
- Modify: `server/models/index.py:120-215, 265-427`
- Modify: `server/indexing/generations.py:67-113, 381-420`
- Modify: `server/db/postgres.py:1866-2215, 2580-2710`
- Modify: `server/api/index.py:120-190, 3800-4120, start_index endpoint`
- Modify: `web/src/components/RAG/IndexingSubtab.tsx` estimate/confirmation state and Graph & Enrichment panel
- Modify mechanically: `web/src/types/generated.ts`
- Create: `tests/unit/test_graphrag_schema.py`
- Create: `tests/integration/test_graph_schema_proposal_live.py`
- Create: `tests/api/test_graph_schema_endpoints.py`
- Modify: `web/tests/e2e/exhaustive/graph_policy.spec.ts`

**Interfaces:**
- Consumes: external semantic graph policy, corpus file inventory, canonical chunks, and resolved semantic model route.
- Produces: `GraphSchemaProposal`, persisted `corpora.meta.graph_schema_proposal`, `GenerationManifest.graph_metadata.schema_hash`, proposal endpoint, and `IndexRequest.approved_graph_schema_hash`.

- [x] **Step 1: Run impact analysis**

Run impact for `IndexRequest`, `IndexEstimate`, `GenerationManifest`, `PostgresClient.promote_staging_index`, `start_index`, and `IndexingSubtab`. Report HIGH/CRITICAL before mutation.

- [x] **Step 2: Write schema determinism and boundary RED tests**

Define public models in `server/models/index.py`:

```python
class GraphSchemaSample(BaseModel):
    recipe: Literal["documents-and-positions-v1"] = "documents-and-positions-v1"
    seed: int = 0
    chunk_ids: list[str]
    chunk_hashes: list[str]


class GraphSchemaProposal(BaseModel):
    corpus_id: str
    policy: Literal["semantic"]
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema: dict[str, Any]
    sample: GraphSchemaSample
    model_alias: str
    graphrag_version: Literal["1.19.0"] = "1.19.0"
    created_at: datetime


class GraphExtractionTelemetry(BaseModel):
    selected_chunks: int = Field(ge=0)
    attempted_chunks: int = Field(ge=0)
    succeeded_chunks: int = Field(ge=0)
    failed_chunks: int = Field(ge=0)
    truncated_chunks: int = Field(ge=0)
    extracted_entities: int = Field(ge=0)
    semantic_relationships: int = Field(ge=0)
    from_chunk_relationships: int = Field(ge=0)


class GraphResolutionTelemetry(BaseModel):
    candidate_nodes: int = Field(ge=0)
    resolved_nodes: int = Field(ge=0)
    merged_nodes: int = Field(ge=0)
    unresolved_duplicate_groups: int = Field(ge=0)


class GraphCommunityTelemetry(BaseModel):
    algorithm: Literal["gds-leiden-2.13"] = "gds-leiden-2.13"
    community_count: int = Field(ge=0)
    levels: int = Field(ge=0)
    modularity: float
    did_converge: bool
    nodes_written: int = Field(ge=0)


class GraphPromotionOverride(BaseModel):
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=20)
    created_at: datetime
    failure_codes: list[Literal["zero_entities", "zero_semantic_relationships"]]


class GraphGenerationMetadata(BaseModel):
    policy: Literal["semantic", "code"]
    schema_hash: str | None = None
    schema: dict[str, Any] | None = None
    extraction: GraphExtractionTelemetry
    resolution: GraphResolutionTelemetry
    communities: GraphCommunityTelemetry | None = None
    override: GraphPromotionOverride | None = None
    partial: bool = False
```

Test that canonical JSON key ordering yields the same SHA-256, sample selection spans multiple documents and early/middle/late positions, openness fields are false, generic `Object`/`RELATED_TO`/`ASSOCIATED_WITH` labels are rejected, and proposal validation rejects a mismatched hash.

- [x] **Step 3: Run schema tests and observe RED**

Run on LXC100:

```bash
uv run pytest -q --no-cov -p no:cacheprovider \
  tests/unit/test_graphrag_schema.py tests/api/test_graph_schema_endpoints.py
```

Expected: models/module/endpoints do not exist.

- [x] **Step 4: Implement deterministic stratified sampling and schema normalization**

In `server/indexing/graphrag_schema.py`, implement:

```python
def select_schema_chunks(
    chunks: Sequence[Chunk], *, corpus_id: str, max_documents: int = 12
) -> list[Chunk]:
    grouped: dict[str, list[Chunk]] = defaultdict(list)
    for chunk in chunks:
        if str(chunk.content or "").strip():
            grouped[str(chunk.file_path)].append(chunk)
    paths = sorted(
        grouped,
        key=lambda path: hashlib.sha256(f"{corpus_id}:{path}".encode()).hexdigest(),
    )
    if len(paths) > max_documents:
        paths = [
            paths[round(index * (len(paths) - 1) / (max_documents - 1))]
            for index in range(max_documents)
        ]
    selected: list[Chunk] = []
    for path in paths:
        ordered = sorted(grouped[path], key=lambda chunk: (chunk.start_line, chunk.chunk_id))
        for index in sorted({0, len(ordered) // 2, len(ordered) - 1}):
            selected.append(ordered[index])
    return selected


def canonical_schema_dict(schema: GraphSchema) -> dict[str, Any]:
    return GraphSchema(
        node_types=schema.node_types,
        relationship_types=schema.relationship_types,
        patterns=schema.patterns,
        constraints=schema.constraints,
        additional_node_types=False,
        additional_relationship_types=False,
        additional_patterns=False,
    ).model_dump(mode="json")


def graph_schema_hash(schema_dict: Mapping[str, Any]) -> str:
    encoded = json.dumps(schema_dict, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


async def derive_graph_schema_proposal(
    *,
    corpus_id: str,
    chunks: Sequence[Chunk],
    model_alias: str,
    route_model: str,
    route_base_url: str,
    route_api_key: str,
    input_fingerprint: str,
) -> GraphSchemaProposal:
    sample = select_schema_chunks(chunks, corpus_id=corpus_id)
    text = "\n\n".join(
        f"## {chunk.file_path} lines {chunk.start_line}-{chunk.end_line}\n{chunk.content[:6000]}"
        for chunk in sample
    )
    llm = OpenAILLM(
        model_name=route_model,
        model_params={"temperature": 0},
        api_key=route_api_key,
        base_url=route_base_url,
    )
    extracted = await SchemaFromTextExtractor(llm=llm, use_structured_output=True).run(text)
    schema = canonical_schema_dict(extracted)
    validate_domain_schema(schema)
    return GraphSchemaProposal(
        corpus_id=corpus_id,
        policy="semantic",
        input_fingerprint=input_fingerprint,
        schema_hash=graph_schema_hash(schema),
        schema=schema,
        sample=GraphSchemaSample(
            chunk_ids=[chunk.chunk_id for chunk in sample],
            chunk_hashes=[hashlib.sha256(chunk.content.encode()).hexdigest() for chunk in sample],
        ),
        model_alias=model_alias,
        created_at=datetime.now(UTC),
    )
```

Selection sorts documents by a stable SHA-256 of `corpus_id:file_path`, chooses up to 12 spread across that order, then chooses first/middle/last nonempty chunk from each document and records IDs plus content hashes. Concatenate bounded excerpts with document/chunk headings, call `SchemaFromTextExtractor` with the configured `OpenAILLM` instance shown above and `use_structured_output=True`, then rebuild `GraphSchema` with `additional_node_types=False`, `additional_relationship_types=False`, and `additional_patterns=False`. Validate precise Neo4j naming and reject prohibited catch-alls before hashing. Task 3 also removes `semantic_kg_allowed_entity_types` and `semantic_kg_allowed_relation_types` from configuration, checked-in JSON, glossary, and generated types because the approved proposal now owns those contracts.

- [x] **Step 5: Persist proposal and manifest metadata in Postgres authority**

Add:

```python
async def PostgresClient.get_graph_schema_proposal(
    self, repo_id: str
) -> GraphSchemaProposal | None:
    row = await self.get_corpus(repo_id)
    raw = ((row or {}).get("meta") or {}).get("graph_schema_proposal")
    return GraphSchemaProposal.model_validate(raw) if raw is not None else None


async def PostgresClient.set_graph_schema_proposal(
    self, repo_id: str, proposal: GraphSchemaProposal
) -> None:
    await self.patch_corpus_meta_locked(
        repo_id,
        {"graph_schema_proposal": proposal.model_dump(mode="json")},
    )
```

`patch_corpus_meta_locked` is a new private Postgres helper implemented with `SELECT meta FROM corpora WHERE repo_id=$1 FOR UPDATE`, a dict-only JSON merge, and `UPDATE corpora SET meta=$2::jsonb WHERE repo_id=$1` in the same transaction. Store under `corpora.meta.graph_schema_proposal`. Extend `GenerationManifest` with `graph_metadata: GraphGenerationMetadata | None`; extend `build_generation` and `promote_staging_index` to accept the exact graph metadata created by the run. Do not fall back to a prior proposal when the approved hash is absent/mismatched.

- [x] **Step 6: Add explicit proposal and approval API**

Add:

```python
class GraphSchemaProposalRequest(BaseModel):
    force_refresh: bool = False


@router.post("/index/{corpus_id}/graph-schema/proposal", response_model=GraphSchemaProposal)
async def propose_graph_schema(
    corpus_id: str, request: GraphSchemaProposalRequest
) -> GraphSchemaProposal:
    corpus, cfg = await load_corpus_and_scoped_config(corpus_id)
    policy = resolve_graph_policy(
        internal=bool((corpus.get("meta") or {}).get("system_kind")),
        enabled=cfg.graph_indexing.enabled,
        build_code_graph=cfg.graph_indexing.build_code_graph,
    )
    if policy != "semantic":
        raise HTTPException(status_code=409, detail=graph_schema_policy_detail(policy))
    existing = await postgres.get_graph_schema_proposal(corpus_id)
    fingerprint = await graph_schema_input_fingerprint(corpus, cfg)
    if existing and not request.force_refresh and proposal_matches(existing, fingerprint, cfg):
        return existing
    proposal = await build_proposal_from_corpus(corpus, cfg, fingerprint=fingerprint)
    await postgres.set_graph_schema_proposal(corpus_id, proposal)
    return proposal
```

Define the endpoint helpers in `server/api/index.py` with these exact contracts:

- `load_corpus_and_scoped_config(corpus_id) -> tuple[dict[str, Any], TriBridConfig]` reads the one Postgres corpus row and `load_scoped_config`, raising the existing typed corpus-not-found response.
- `graph_schema_policy_detail(policy) -> GraphSchemaPolicyConflictDetail` returns code `graph_schema_policy_not_semantic`, the resolved policy, and an operator hint; define/register that focused Pydantic detail in `server/models/index.py`.
- `graph_schema_input_fingerprint(corpus, cfg) -> str` hashes sorted `(relative_path, size, mtime_ns)`, semantic alias, sampling recipe, and the literal `neo4j-graphrag:1.19.0` with canonical JSON/SHA-256.
- `proposal_matches(existing, fingerprint, cfg) -> bool` requires equal input fingerprint, model alias, sampling recipe, and GraphRAG version.
- `build_proposal_from_corpus(corpus, cfg, fingerprint) -> GraphSchemaProposal` loads/chunks only the deterministic sample candidates, resolves the authenticated gateway route, calls `derive_graph_schema_proposal`, attaches the fingerprint, and never processes the bulk corpus.

Refuse internal/off/code policies with typed 409. Reuse a persisted proposal only when corpus content fingerprint, sampling recipe, model alias, and 1.19 version match; otherwise derive and persist a new proposal. Extend `IndexRequest` with `approved_graph_schema_hash: str | None` and make `start_index` reject a semantic run unless the hash matches the current proposal.

- [x] **Step 7: Add visible schema review UI**

The confirmation flow has an explicit **Generate proposed schema** button before **Approve schema & index**. Render node types, properties, relationship verbs, directed patterns, constraints, sample documents/positions, model, hash, and estimated bulk cost. The final POST sends exactly the displayed `schema_hash`; a changed corpus/config invalidates the view and disables approval.

- [x] **Step 8: Run live proposal and browser tests on LXC100**

Use a real Apollo subset and the configured production semantic alias. Assert one real proposal, persisted readback, stable hash on unchanged input, changed hash on changed sample, typed refusal for Recall, and 409 for missing/stale approval. The headed browser test must click generation, expand schema sections, approve, and observe the outgoing run enter indexing without request interception.

- [x] **Step 9: Regenerate contracts and run verification**

Run `generate_types`, `validate_types`, focused pytest, frontend lint/build, and the headed schema flow. Expected: PASS.

- [x] **Step 10: Obtain DeepSeek V4 Flash PASS for Task 3**

Submit exact diff plus source evidence for `SchemaFromTextExtractor`, `GraphSchema` openness fields, persistence/locking tests, real gateway response, and browser proof. Resolve P1/P2 and re-review.

- [x] **Step 11: Detect scope and commit Task 3**

Commit with:

```bash
git commit -m "feat: add reviewed per-corpus graph schemas"
```

---

### Task 4: Replace Custom Graph Writes with the Official Pipeline and Lexical Contract

**Files:**
- Rewrite/split: `server/indexing/official_graphrag.py`
- Create: `server/indexing/graphrag_pipeline.py`
- Modify: `server/indexing/code_graph.py:388-end`
- Modify: `server/api/index.py:211-250, 2323-3006`
- Modify: `server/db/neo4j.py:183-575` to remove custom GraphRAG/vector writer code
- Modify: `tests/unit/test_official_graphrag.py`
- Modify: `tests/unit/test_code_graph.py`
- Create: `tests/integration/test_graphrag_pipeline_live.py`
- Modify: `tests/integration/test_neo4j_live.py`

**Interfaces:**
- Consumes: approved `GraphSchemaProposal`, canonical chunks, semantic/code policy, sync Neo4j driver, manifest staging `graph_repo_id`.
- Produces: `ScopedNeo4jWriter`, `build_semantic_pipeline(...) -> Pipeline`, `write_semantic_file_graph(...) -> GraphFileTelemetry`, `write_code_file_graph(...) -> GraphFileTelemetry`, official lexical relationships, and no Neo4j chunk embeddings.

- [x] **Step 1: Run impact analysis**

Run impact for `_run_index_body`, `_write_code_graph`, `extract_semantic_kg_with_graphrag`, `write_lexical_graph_with_graphrag`, `Neo4jClient.upsert_graphrag_graph`, `_upsert_graphrag_nodes`, `_upsert_graphrag_relationships`, and `extract_code_graph`. Report HIGH/CRITICAL before editing.

- [x] **Step 2: Write official-writer and relationship RED tests**

Tests must assert:

```python
assert lexical.chunk_to_document_relationship_type == "FROM_DOCUMENT"
assert lexical.next_chunk_relationship_type == "NEXT_CHUNK"
assert lexical.node_to_chunk_relationship_type == "FROM_CHUNK"
assert all("embedding" not in node.properties for node in graph.nodes if node.label == "Chunk")
assert all(rel.type != "IN_CHUNK" for rel in graph.relationships)
```

The live writer test writes one semantic file and one code file to unique staging ids, then queries Neo4j and proves all Document/Chunk/entity nodes plus all relationships carry `repo_id` and `run_id`; chunks carry `graphJoinId`; every entity has `entity_id`, `entity_type`, and `FROM_CHUNK` provenance; no Community nodes, `IN_COMMUNITY`, `IN_CHUNK`, or chunk embedding property exists. Insert an extracted node with reserved `repo_id` and prove the writer refuses before the node count changes.

- [x] **Step 3: Run writer/pipeline tests and observe RED**

Run focused tests on LXC100. Expected: current custom writer emits `IN_CHUNK` and chunk embeddings, and no scoped official writer exists.

- [x] **Step 4: Implement the thin official writer seam**

Create:

```python
import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from neo4j_graphrag.components.kg_writer import KGWriterModel, Neo4jWriter
from neo4j_graphrag.components.types import LexicalGraphConfig, Neo4jGraph


RESERVED_SCOPE_KEYS = frozenset({"repo_id", "run_id", "graphJoinId"})


@dataclass(frozen=True, slots=True)
class GraphFileTelemetry:
    selected_chunks: int
    attempted_chunks: int
    succeeded_chunks: int
    failed_chunks: int
    extracted_entities: int
    semantic_relationships: int
    from_chunk_relationships: int
    pruned_nodes: int
    pruned_relationships: int


class ScopedNeo4jWriter(Neo4jWriter):
    def __init__(self, *args: Any, repo_id: str, run_id: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.repo_id = require_staging_graph_id(repo_id)
        self.run_id = require_run_id(run_id)

    async def run(self, graph: Neo4jGraph, lexical_graph_config: LexicalGraphConfig = LexicalGraphConfig()) -> KGWriterModel:
        validate_no_reserved_scope_keys(graph, RESERVED_SCOPE_KEYS)
        stamp_graph_scope(graph, repo_id=self.repo_id, run_id=self.run_id, lexical=lexical_graph_config)
        base_run = super().run
        return await asyncio.to_thread(
            run_writer_coroutine_in_worker,
            base_run,
            graph,
            lexical_graph_config,
        )


def run_writer_coroutine_in_worker(
    run: Callable[[Neo4jGraph, LexicalGraphConfig], Coroutine[Any, Any, KGWriterModel]],
    graph: Neo4jGraph,
    lexical_graph_config: LexicalGraphConfig,
) -> KGWriterModel:
    # neo4j-graphrag 1.19 declares Neo4jWriter.run as async but performs
    # synchronous driver calls inside it. This helper runs its coroutine to
    # completion on the worker thread's own event loop, never the API loop.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("GraphRAG writer helper must run on a worker thread")
    return asyncio.run(run(graph, lexical_graph_config))


async def run_async_component_off_event_loop(
    run: Callable[[], Coroutine[Any, Any, ResultT]],
) -> ResultT:
    return await asyncio.to_thread(run_component_coroutine_in_worker, run)


def run_component_coroutine_in_worker(
    run: Callable[[], Coroutine[Any, Any, ResultT]],
) -> ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("GraphRAG component helper must run on a worker thread")
    return asyncio.run(run())
```

For Chunk nodes, stamp `chunk_id` and `graphJoinId=f"{repo_id}:{chunk_id}"`; for entities, stamp `entity_id=str(node.id)` and `entity_type=node.label`; for Document nodes, retain file path. Stamp every relationship. The subclass does not override batching, labels, Cypher, cleanup, or error handling.

Implement the helpers in the same module:

- `require_staging_graph_id(value) -> str` accepts only the server format `__staging__<corpus>__<32-hex-run>` and raises before driver creation otherwise.
- `require_run_id(value) -> str` accepts exactly 32 lowercase hexadecimal characters.
- `validate_no_reserved_scope_keys(graph, keys) -> None` inspects every node and relationship property dict and raises one typed `GraphScopeCollisionError` naming the offending graph item/key before any mutation.
- `stamp_graph_scope(graph, repo_id, run_id, lexical) -> None` applies the canonical fields described above in memory; it does no I/O and returns only after every node/relationship is stamped.
- `run_writer_coroutine_in_worker` exists because the pinned 1.19 source declares `Neo4jWriter.run` with `async def` while its body calls the synchronous Neo4j driver. Calling `await asyncio.to_thread(base_run, ...)` would return an unawaited coroutine; the worker-local `asyncio.run` is required and is not nested in the FastAPI loop.
- `base_run = super().run` is a bound async method; `base_run(graph, lexical_graph_config)` creates the `Coroutine[Any, Any, KGWriterModel]` consumed by the helper. `asyncio.to_thread(...)` itself returns a coroutine, so `ScopedNeo4jWriter.run` must await it exactly as shown. `Neo4jWriter.__init__` currently accepts `driver`, `neo4j_database`, `batch_size`, and `clean_db`; the subclass deliberately forwards all positional/keyword arguments unchanged before adding only scoped ids.
- Define `ResultT = TypeVar("ResultT")`. `run_async_component_off_event_loop` and its guarded worker helper are the no-argument equivalent used by Task 5's official resolver and any later 1.19 component whose async method wraps synchronous driver work.

- [x] **Step 5: Build the exact official semantic pipeline**

Use one `Pipeline` per staging run with connections copied from the 1.19 template contract:

```python
pipeline = Pipeline()
pipeline.add_component(extractor, "extractor")
pipeline.add_component(GraphPruning(), "pruner")
pipeline.add_component(writer, "writer")
pipeline.connect("extractor", "pruner", {"graph": "extractor", "schema": "schema"})
pipeline.connect("pruner", "writer", {"graph": "pruner.graph"})
```

Run data supplies `extractor.chunks`, `extractor.document_info`, `extractor.lexical_graph_config`, `extractor.schema`, `pruner.schema`, `pruner.lexical_graph_config`, and `writer.lexical_graph_config`. Use `OnError.RAISE`, structured output, and the approved persisted schema. Execute the sync Neo4j writer/driver work in a worker thread so it never blocks the FastAPI event loop.

- [x] **Step 6: Write one complete graph per file, not one graph per vector batch**

Make `_upsert_chunk_batch` write only Postgres/Qdrant. Accumulate the embedded chunks for the current file, then call the semantic or code graph writer once after the complete file is available. The streaming path enforces the preflight chunk ceiling and retains the file's eligible chunks only after the run has passed that ceiling; it may not create duplicate Document nodes or broken `NEXT_CHUNK` boundaries.

For code policy, build the official lexical graph with `LexicalGraphBuilder(LexicalGraphConfig())`, merge its graph with `extract_code_graph(...)`, and submit one combined graph to `ScopedNeo4jWriter`. Remove current custom `Neo4jClient.upsert_graphrag_graph` and custom node/relationship serialization.

- [x] **Step 7: Run real pipeline and bug-family tests**

Run the unit suites plus the live Neo4j/gateway pipeline test. Add a matrix covering one file, multiple files, a file larger than one vector batch, code, semantic prose, missing route, malformed LLM output, all-pruned output, reserved-key collision, and graph-disabled policy. All expected failures must leave the staging graph unpromoted and deletable.

Add a real event-loop isolation test with a live Neo4j write of at least 10,000 nodes. Run a concurrent `asyncio.sleep(0)` ticker while awaiting `ScopedNeo4jWriter.run`; assert the ticker advances before the writer completes and the resulting node count is exact. Do not patch the parent writer or use a fake driver.

- [x] **Step 8: Obtain DeepSeek V4 Flash PASS for Task 4**

Submit exact pipeline/writer/index-loop diff, 1.19 writer/Pipeline source, live test queries, and event-loop handling. Resolve P1/P2 and rerun.

- [x] **Step 9: Detect scope and commit Task 4**

Commit:

```bash
git commit -m "feat: build graphs through the official pipeline"
```

---

### Task 5: Resolve Entities and Fail Promotion on Dishonest Graphs

**Files:**
- Create: `server/indexing/graph_invariants.py`
- Modify: `server/indexing/graphrag_pipeline.py`
- Modify: `server/api/index.py:2323-3006, 3390-3455`
- Modify: `server/models/index.py` telemetry/override fields
- Modify: `server/indexing/generations.py` graph metadata
- Modify: `server/db/neo4j.py` scoped stats/invariant queries
- Modify: `web/src/components/RAG/IndexingSubtab.tsx` run telemetry and override dialog
- Create: `tests/integration/test_graph_resolution_isolation_live.py`
- Create: `tests/integration/test_graph_promotion_invariants_live.py`
- Modify: `tests/api/test_index_run_replay_endpoints.py`

**Interfaces:**
- Consumes: completely written staged graph and approved schema hash.
- Produces: `resolve_staged_entities(...) -> GraphResolutionTelemetry`, `verify_graph_promotion(...) -> GraphInvariantReport`, explicit sparse-corpus override, persisted graph telemetry, and promotion refusal on every invalid state.

- [x] **Step 1: Run impact analysis**

Run impact for `SinglePropertyExactMatchResolver` call boundary, `_run_index_body`, `get_graph_stats`, `start_index`, `IndexRunSummary`, and `GenerationManifest`. Warn before HIGH/CRITICAL edits.

- [x] **Step 2: Write resolver isolation and RED invariant tests**

Define the invariant result in `server/indexing/graph_invariants.py`:

```python
@dataclass(frozen=True, slots=True)
class GraphInvariantReport:
    policy: GraphPolicy
    failure_codes: tuple[str, ...]
    total_chunks: int
    total_entities: int
    semantic_relationships: int
    from_chunk_relationships: int
    linked_chunks: int
    duplicate_groups: int
    cross_scope_nodes: int
    cross_scope_relationships: int

    @property
    def promotable(self) -> bool:
        return not self.failure_codes
```

Create two generations containing same-label/same-name entities and raw chunk ids. Run the resolver with one staged id and assert only those nodes merge. Require `ResolutionStats.number_of_nodes_to_resolve` to equal the staged generation's pre-merge node count (proving the count query was scoped), require the staged post-merge node count to shrink, and require the other generation's node ids/count/properties to remain byte-for-byte unchanged (proving the merge query was scoped). This characterizes the installed 1.19 `filter_query` on both query paths without mocks or query-log guessing.

Create one live mutation case per invariant:

```python
cases = [
    "extraction_failure",
    "silent_truncation",
    "zero_entities",
    "zero_semantic_relationships",
    "missing_from_chunk_provenance",
    "cross_generation_node",
    "cross_generation_relationship",
    "unresolved_duplicate_entity",
]
```

Each case starts a real staging generation, mutates only that staging graph, calls the real promotion verifier, asserts a typed failure code, and proves the active manifest still names the previous generation.

- [x] **Step 3: Run tests and observe RED**

Expected: no resolution phase/report exists and current promotion checks only chunk count.

- [x] **Step 4: Run official exact-match resolution once after all file writes**

Create a sync driver and:

```python
filter_query = f"WHERE entity.repo_id = {cypher_literal(validated_graph_repo_id)} "
resolver = SinglePropertyExactMatchResolver(
    driver=driver,
    filter_query=filter_query,
    resolve_property="name",
    neo4j_database=database,
)
stats = await run_async_component_off_event_loop(resolver.run)
```

`validated_graph_repo_id` must match the server-generated staging-id allowlist before literal encoding; no user value enters the clause. Record candidates (`number_of_nodes_to_resolve`), created nodes, inferred merges, conflicts, and unresolved duplicate groups. Fuzzy resolution is absent.

- [x] **Step 5: Implement one typed promotion report**

`verify_graph_promotion` queries:

- chunks written versus indexed chunks;
- attempted/succeeded/failed/truncated extraction counts;
- entity and semantic relationship counts;
- `FROM_CHUNK` count and distinct linked chunks;
- duplicate `(labels, name)` groups after resolution;
- nodes/relationships whose scope differs from staged id;
- schema hash and policy;
- community state (filled in Task 7).

Semantic policy refuses promotion on any failed/truncated extraction, zero entities, zero semantic relationships, zero provenance, cross-scope record, or unresolved duplicate group. Code policy requires nonzero AST entities/relationships/provenance but not a semantic schema.

- [x] **Step 6: Implement audited entity-sparse override**

Extend `IndexRequest` with `graph_empty_override_reason: str | None` (minimum 20 visible characters). Permit it only for the `zero_entities`/`zero_semantic_relationships` class after extraction attempted the entire approved scope successfully. Capture `Remote-User` from the authenticated proxy; if missing, override is unavailable. Persist actor, reason, timestamp, telemetry, and `partial=True` in `GraphGenerationMetadata`. It never enables graph retrieval or changes chunk-only retrieval into graph success.

- [x] **Step 7: Surface telemetry and refusal in the real run UI**

Run history shows policy, schema hash, chunks selected/attempted/succeeded/failed/truncated, extracted/resolved entities, semantic relations, provenance links, duplicate groups, community status, promotion verdict, and override audit. A failed invariant is a visible error with operator hint; no completed badge appears.

- [x] **Step 8: Run live RED/GREEN suite and UI refusal proof**

Run all mutation cases, resolver collision test, run replay tests, generated types, lint/build, and a headed browser case that sees a real safe test corpus refused and confirms the previous generation remains selected after reload.

- [x] **Step 9: Obtain DeepSeek V4 Flash PASS for Task 5**

Submit the full invariant matrix and actual active-manifest assertions. Resolve P1/P2 and re-review.

- [x] **Step 10: Detect scope and commit Task 5**

Commit:

```bash
git commit -m "feat: fail graph promotion on invalid generations"
```

---

### Task 6: Seed Neo4j Traversal from Qdrant Without Double-Counting Dense Hits

**Files:**
- Create: `server/retrieval/graphrag_retriever.py`
- Modify: `server/retrieval/qdrant_store.py:134-244, 368-395`
- Modify: `server/retrieval/fusion.py:447-1097`
- Modify: `server/services/rag.py:180-207`
- Modify: `server/chat/handler.py:360-410, 700-755`
- Modify: `server/models/tribrid_config_model.py:1316-1395`
- Modify: `server/observability/metrics.py` graph retrieval counters
- Rewrite: `tests/integration/test_graph_hydration_live.py`
- Create: `tests/unit/test_graphrag_retriever_contract.py`
- Modify: `tests/integration/test_required_retrieval_leg_contract.py`

**Interfaces:**
- Consumes: promoted `GenerationManifest.qdrant_collection`, `graph_repo_id`, Qdrant payload `graph_join_id`, Neo4j `Chunk.graphJoinId`, canonical query vector, GraphSearchConfig Top-K/hops/window.
- Produces: `retrieve_graph_chunks(...) -> GraphTraversalResult`, traversal-only graph matches, truthful debug fields, and no Neo4j vector index/search path.

- [x] **Step 1: Run impact analysis**

Run impact for `QdrantChunkStore.write_chunks`, `TriBridFusion._search_single_corpus`, `Neo4jClient.chunk_vector_search`, `expand_chunks_via_entities`, `entity_chunk_search`, `ChatDebugInfo`, and chat debug aggregation. Report HIGH/CRITICAL.

- [x] **Step 2: Write join/isolation and no-double-credit RED tests**

Define the internal result in `server/retrieval/graphrag_retriever.py`:

```python
@dataclass(frozen=True, slots=True)
class GraphTraversalResult:
    chunk_scores: tuple[tuple[str, float], ...]
    qdrant_seed_chunks: int
    resolved_entities: int
    relationship_expansion_hits: int
    community_expansion_hits: int
```

The unit contract test asserts the official constructor fields and the retrieval query contains `FROM_CHUNK`, excludes every `$match_params` seed id, and scopes every traversed node/relationship by `node.repo_id`.

The live test creates two retained generations with identical raw chunk ids, different physical Qdrant collections, and different `graphJoinId` values. It proves a request constructs a fresh retriever for the manifest's physical collection and cannot return the retired graph. It also proves every graph result lies outside the original Qdrant seed set and Postgres hydration returns exact canonical content.

- [x] **Step 3: Run retrieval tests and observe RED**

Expected: current graph leg calls `Neo4jClient.chunk_vector_search`, debug says entity hits for chunk seeds, and the same Qdrant/dense evidence can be fused twice.

- [x] **Step 4: Stamp top-level Qdrant join payloads atomically per batch**

After Haystack writes documents, use Qdrant `batch_update_points` with one `SetPayloadOperation` per deterministic point id:

```python
SetPayloadOperation(
    set_payload=SetPayload(
        payload={"graph_join_id": f"{graph_repo_id}:{chunk.chunk_id}"},
        points=[point_id_for_chunk(chunk.chunk_id)],
    )
)
```

Pass the staging `graph_repo_id` into `write_chunks`. The method returns only after vector and payload writes succeed. Add an exact pre-promotion payload-count check; missing join keys fail the run.

- [x] **Step 5: Implement the official request-scoped retriever**

Construct in a worker thread:

```python
retriever = QdrantNeo4jRetriever(
    driver=sync_driver,
    client=qdrant_client,
    collection_name=manifest.qdrant_collection,
    using="text-dense",
    id_property_external="graph_join_id",
    id_property_neo4j="graphJoinId",
    node_label_neo4j="Chunk",
    retrieval_query=traversal_query(max_hops=config.max_hops, neighbor_window=config.chunk_neighbor_window),
    result_formatter=format_graph_record,
    neo4j_database=database,
)
result = retriever.search(query_vector=query_vector, top_k=seed_k)
```

The generated Cypher starts from the matched Chunk, follows incoming `FROM_CHUNK`, traverses only entity-entity relationships whose `repo_id` equals `node.repo_id`, returns related chunks through `FROM_CHUNK`, optionally adds `NEXT_CHUNK` neighbors, and excludes all generation-qualified seed ids from `$match_params`. Inline only validated bounded hop/window integers.

- [x] **Step 6: Replace fusion and debug contracts**

Delete mode branches, Neo4j vector search, overfetch, entity text match, and expansion blend. Hydrate traversal chunk ids from Postgres. Replace debug with:

```python
fusion_graph_qdrant_seed_chunks
fusion_graph_resolved_entities
fusion_graph_relationship_expansion_hits
fusion_graph_community_expansion_hits
fusion_graph_hydrated_chunks
```

Replace public `graph_entity_hits` with the corresponding truthful fields. RRF/weighted fusion receives only traversal-derived graph matches; the Qdrant seeds remain exclusively in the dense leg. Remove old aggregation from Recall debug because internal Recall graph policy is excluded.

API and Chat contract tests must assert `fusion_graph_entity_hits` is absent and that `fusion_graph_qdrant_seed_chunks`, `fusion_graph_relationship_expansion_hits`, and `fusion_graph_hydrated_chunks` are present with exact integer values.

- [x] **Step 7: Delete obsolete Neo4j vector and graph-search code**

Remove `ensure_vector_index`, `_assert_vector_index_contract`, `chunk_vector_search`, `graph_search`, `entity_chunk_search`, `expand_chunks_via_entities`, their configuration, metrics, and tests. Search the repo for `IN_CHUNK`, `fusion_graph_entity_hits`, `chunk_vector_index_name`, and `chunk_seed_overfetch_multiplier`; expected result is no production hit.

- [x] **Step 8: Run real retrieval matrix on LXC100**

Use real Apollo calibration and Epstein flight-record questions. Test dense-only, graph-only, tri-brid, graph-disabled, missing manifest graph, Qdrant outage, Neo4j outage, retained-generation collision, and zero-traversal results. Required graph failure stays typed/fail-closed. Assert graph results include at least one chunk outside Qdrant seeds for each semantic corpus.

- [x] **Step 9: Regenerate contracts and verify**

Run generated types, banned checks, focused/live retrieval tests, chat tests, lint/build. Expected: PASS and no obsolete symbol search hits.

- [x] **Step 10: Obtain DeepSeek V4 Flash PASS for Task 6**

Submit official 1.19 retriever source/signature, exact generated Cypher, collision/no-double-credit tests, and failure matrix. Resolve P1/P2 and re-review.

- [x] **Step 11: Detect scope and commit Task 6**

Commit:

```bash
git commit -m "feat: seed graph traversal from Qdrant"
```

---

### Task 7: Install GDS 2.13 and Replace Community Nodes with Leiden Properties

**Files:**
- Modify: `docker-compose.yml:36-68`
- Modify: `deploy/proxmox/render-config.sh` or deployment config owner for Neo4j plugin env
- Modify: `tests/unit/test_runtime_launch_contract.py`
- Modify: `tests/unit/test_proxmox_deployment_contract.py`
- Create: `server/graph/communities.py`
- Modify: `server/db/neo4j.py:183-207, 760-930, 1092-1198, 1505-1555, 1672-1743`
- Modify: `server/api/graph.py:128-220`
- Modify: `server/models/tribrid_config_model.py:2753-2825`
- Modify: `web/src/hooks/useGraph.ts:112-300`
- Modify: `web/src/stores/useGraphStore.ts`
- Modify: `web/src/components/RAG/GraphSubtab.tsx:672-733, 850-1260`
- Rewrite: `tests/integration/test_graph_communities_live.py`
- Modify: `tests/api/test_graph_endpoints.py`
- Modify: `web/tests/e2e/exhaustive/graph_explorer.spec.ts`

**Interfaces:**
- Consumes: resolved, scoped entity graph with relationship weights.
- Produces: `detect_leiden_communities(repo_id) -> GraphCommunityTelemetry`, `communityPath` list plus scalar `communityId` on entities, derived community APIs/UI, and no `Community`/`IN_COMMUNITY` ontology.

- [x] **Step 1: Run impact analysis**

Run impact for `Neo4jClient.detect_communities`, `_store_communities`, `_modularity_groups`, `get_communities`, community member/subgraph methods, `get_graph_stats`, `list_communities`, `useGraph`, and `GraphSubtab`. Report HIGH/CRITICAL.

- [x] **Step 2: Write deployment and community RED tests**

Deployment tests assert Neo4j 5.26.20 includes APOC and GDS 2.13.x plugin configuration, unrestricted/allowlisted `apoc.*,gds.*`, and a readiness probe that calls `gds.version()`.

Live tests create two weighted cliques joined by a weak bridge, run detection twice, and assert identical `communityPath`/`communityId`, two connected final communities, `concurrency=1`, fixed random seed, no Community nodes/IN_COMMUNITY edges, and projection removal. Repeat with AST relationship types to prove code corpora receive communities.

- [x] **Step 3: Run tests and observe RED**

Expected: GDS absent, code graphs get zero communities, and current implementation creates Community nodes through NetworkX Louvain.

- [x] **Step 4: Install the documented compatible plugin**

Use Neo4j's plugin contract:

```yaml
NEO4J_PLUGINS: '["apoc", "graph-data-science"]'
NEO4J_dbms_security_procedures_unrestricted: apoc.*,gds.*
NEO4J_dbms_security_procedures_allowlist: apoc.*,gds.*
```

Pin/verify the installed GDS result is `2.13.x`; do not upgrade Neo4j in this slice. Update deployment contract and readiness to fail closed when GDS is required but unavailable.

- [x] **Step 5: Implement scoped weighted Leiden**

`server/graph/communities.py` must:

1. create a unique safe projection name;
2. call `gds.graph.project.cypher` with node query restricted to `(:__Entity__ {repo_id:$repo_id})` and relationship query restricted to entity-entity edges of the same repo, returning both directions and `coalesce(r.weight, 1.0)`;
3. call:

```cypher
CALL gds.leiden.write($graph_name, {
  writeProperty: 'communityPath',
  relationshipWeightProperty: 'weight',
  includeIntermediateCommunities: true,
  randomSeed: 19,
  concurrency: 1
})
YIELD communityCount, ranLevels, modularity, modularities,
      nodeCount, didConverge, nodePropertiesWritten
```

4. set `e.communityId = last(e.communityPath)` only for the staged repo;
5. verify every eligible entity received both properties and no out-of-scope entity changed;
6. drop the named projection in `finally`, including failure paths.

- [x] **Step 6: Derive API communities from entity properties**

Delete Community constraints, nodes, membership edges, `_store_communities`, and `_modularity_groups`. `get_communities` groups scoped entities by `communityId`, selects a deterministic highest-degree/name hub, returns the existing `Community` view model with member ids and level derived from `communityPath`. Member/subgraph routes match entity properties. Stats counts distinct non-null `communityId`.

Keep the public route shapes needed by Graph Explorer, but they now represent derived views, not persisted Community objects. Remove any UI wording claiming communities are separate nodes.

- [x] **Step 7: Run live GDS/API/UI tests**

Run deployment contract, live Leiden semantic/code tests, graph endpoint tests, generated types, lint/build, and headed Graph Explorer. The browser test selects a real corpus, clicks a community filter, selects members, expands a neighborhood, uses zoom/pan/fit, and reloads; no route interception.

- [x] **Step 8: Obtain DeepSeek V4 Flash PASS for Task 7**

Submit GDS 2.13 compatibility/Leiden docs, deployment diff, projection/drop queries, deterministic tests, and browser evidence. Resolve P1/P2 and re-review.

- [x] **Step 9: Detect scope and commit Task 7**

Commit:

```bash
git commit -m "feat: derive graph communities with GDS Leiden"
```

---

### Task 8: Full Verification, Deploy, Reindex, and Real Browser Acceptance

**Files:**
- Create/update: `docs/exec-plans/active/graphrag-cross-corpus-2026-08-31.md`
- Modify normal product/architecture/runbook docs whose truth changed
- Modify: `docs/superpowers/specs/2026-08-31-neo4j-graphrag-cross-corpus-design.md` status only after acceptance
- Modify: `docs/superpowers/plans/2026-08-31-neo4j-graphrag-cross-corpus.md` checkboxes/evidence references
- Never modify: `mkdocs/**`, `mkdocs.yml`

**Interfaces:**
- Consumes: DeepSeek-PASS Tasks 1-7, clean Mac/LXC checkouts, production credentials, and acceptance corpora.
- Produces: pushed/deployed exact hash, rebuilt NASA/Epstein/code graphs, negative invariant proof, visible click ledger/screenshots, complete docs, and completion-audit evidence.

- [x] **Step 1: Freeze the requirement/evidence matrix**

In the ledger, create one row for every spec section and goal requirement: 1.19 upgrade, schema proposal/review, default policy, Recall exclusion, official lexical names, official writer/Pipeline, resolution, promotion RED tests, Qdrant traversal/no double credit, GDS deployment/Leiden/code communities, dead-surface removal, DeepSeek reviews, LXC gates, deploy parity, three-corpus visible drive, and future Recall Intelligence note. Each row names the exact test/output/screenshot that will prove it.

- [x] **Step 2: Run the full LXC100 quality gate before deployment**

On `/opt/ragweld` after syncing/committing the exact candidate:

```bash
uv sync --extra dev
uv run scripts/generate_types.py
uv run scripts/validate_types.py
uv run scripts/check_banned.py
uv run python scripts/check_docs_ownership.py
uv run ruff check server tests scripts
uv run mypy server
uv run pytest -q --no-cov -p no:cacheprovider
cd web && npm run lint && npm run build && npx playwright test tests/e2e/exhaustive/graph_policy.spec.ts tests/e2e/exhaustive/graph_explorer.spec.ts --headed
```

Record exact counts and failures. Fix root causes, rerun the failed family, then rerun this complete gate. No skip caused by unavailable gateway/store counts as green.

- [ ] **Step 3: Obtain final DeepSeek V4 Flash integration PASS**

Submit the complete spec-to-main diff, all task review verdicts, full gate output, remaining dead-symbol searches, deployment diff, and acceptance matrix. Resolve every substantiated P1/P2, rerun impacted tests/full gate, and get PASS.

- [x] **Step 4: Commit, push, and deploy the exact candidate**

Run final `detect-changes` against `main`, commit docs/evidence by explicit path, and push `main` non-force. On LXC100: require a clean checkout, fast-forward to `origin/main`, run the deployment render, rebuild frontend/runtime images as required, restart through the systemd-owned launcher, and wait for `/api/health`, `/api/ready`, Neo4j/APOC/GDS, Qdrant, Postgres, LiteLLM, and deployment marker readiness. Record Mac/origin/LXC/deployment hashes; all must match.

- [x] **Step 5: Rebuild NASA through visible controls**

In the authenticated in-app browser:

1. select `nasa-apollo-11` from the visible corpus dropdown;
2. open RAG → Indexing → Graph & Enrichment;
3. verify the semantic policy badge and cost/ceiling/model;
4. click **Generate proposed schema**;
5. expand and inspect node types, relationships, patterns, properties, constraints, sample documents/positions, and hash;
6. click **Approve schema & index** and confirm the visible cost dialog;
7. watch run events until complete and record extraction/resolution/community/promotion telemetry;
8. reload and confirm the promoted generation/schema hash persists.

No direct API start call satisfies this step.

- [ ] **Step 6: Rebuild Epstein and code through visible controls**

Repeat the complete visible flow for `epstein-files-public`. For `ragweld_code`, visibly select code policy, confirm AST types/weights, index, and observe resolution/community telemetry. Ensure no run is active before restart/deploy actions.

- [ ] **Step 7: Perform the full Graph Explorer drive on all three corpora**

For each corpus, visibly:

- select it from the dropdown;
- inspect nonzero entity/relationship/community counts and schema/policy status;
- open Graph Explorer and capture the initial graph;
- click at least three different node types and inspect properties/source provenance;
- expand two neighborhoods and verify nodes/edges visibly change;
- zoom in/out, pan, fit, change hop limit, entity type, relation type, and community filters;
- click a community and inspect derived members/subgraph;
- run a real graph-including search and inspect truthful debug fields;
- hard reload and verify corpus/generation/filter state and counts remain correct.

For every graph-including search, the visible debug disclosure must not contain `fusion_graph_entity_hits`; it must show `fusion_graph_qdrant_seed_chunks`, `fusion_graph_relationship_expansion_hits`, and `fusion_graph_hydrated_chunks` with values matching the recorded API response.

Use real corpus questions, including Apollo sensor/calibration content and Epstein flight/communication records. Record screenshot path, timestamp, corpus, visible action, expected result, and actual result for every step.

- [ ] **Step 8: Perform visible negative promotion proof**

Use a safe temporary external corpus whose approved extraction is forced into one invariant failure through the test-only fixture path. Start it through visible controls, observe the typed failure and operator hint, verify no completed badge/promoted generation appears after reload, then delete the temporary corpus through visible UI. Do not mutate NASA/Epstein/code active generations for the negative proof.

- [x] **Step 9: Audit replacement cleanup and runtime state**

Require zero production hits for obsolete names/settings (`IN_CHUNK`, Neo4j chunk vector index, `graph_entity_hits`, heuristic semantic KG, Community nodes/IN_COMMUNITY, NetworkX community code). Query live Neo4j for zero obsolete relationships/nodes on new generations, zero cross-generation edges/memberships, and no chunk embeddings. Verify one Mac branch/worktree, one LXC branch/worktree, clean status, no active index, no abandoned staging generation/projection, and healthy backups.

- [ ] **Step 10: Close docs and the deferred Recall Intelligence roadmap note**

Confirm the approved spec's section 15 remains explicit in the enterprise RBAC/Kubernetes/GCP plan: repeated needs, misses, exploration transitions, prompt/cache opportunities, role/team aggregates, tenant boundaries, consent, de-identification, retention/deletion, audit, cache invalidation, and anti-surveillance constraints. Mark implementation plan/spec complete only when the evidence matrix has no missing/weak row.

- [ ] **Step 11: Completion audit and goal close**

Re-read the active goal, spec, plan, every DeepSeek verdict, full gate, deployment parity, store queries, and browser ledger. For each requirement classify evidence as proves/contradicts/incomplete/missing. Continue work on every incomplete or missing row. Only when all rows prove completion, mark the goal complete and report the final deployed commit, review verdicts, test counts, reindex run ids, graph counts, and browser evidence locations.

## Self-Review Traceability

| Approved spec requirement | Implemented by |
|---|---|
| Versioned 1.19 source contract and corrected lexical names | Tasks 1 and 4 |
| External semantic/code/internal Recall corpus policy | Task 2 |
| Stratified, structured, persisted, reviewed schema and hash | Task 3 |
| Composable official Pipeline and thin scoped writer | Task 4 |
| Exact-match scoped resolution before communities | Task 5 |
| Fail-closed promotion, telemetry, audited sparse override, RED proofs | Task 5 |
| Qdrant canonical vectors, official retriever, traversal-only graph credit | Task 6 |
| GDS 2.13 weighted deterministic hierarchical Leiden | Task 7 |
| Removal of dead config, Neo4j vectors, old debug, Community ontology | Tasks 2, 6, and 7 |
| DeepSeek per work chunk and final integration review | Tasks 1-8 |
| NASA, Epstein, and code reindex plus real visible browser matrix | Task 8 |
| Deferred Recall Intelligence Graph in RBAC/Kubernetes/GCP roadmap | Approved spec section 15 and Task 8 docs audit |

The subsystems are intentionally one plan rather than independent plans because each later slice consumes the exact generation metadata and store identity produced by the earlier slice; retrieval and community acceptance cannot be independently correct before schema/promotion isolation exists.

## Plan Approval and Execution Handoff

This plan is complete only after self-review, DeepSeek V4 Flash review, and explicit user approval. Once approved, execute inline in this goal thread with `superpowers:executing-plans`; the repository's one-worktree rule and the current no-delegation instruction make inline execution the safe default.
