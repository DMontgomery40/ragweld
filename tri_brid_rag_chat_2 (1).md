# TriBridRAG — Chat 2.0 Implementation Prompt

You are implementing the Chat 2.0 feature for TriBridRAG. This is the single
source of truth. There are no other versions. Follow this exactly.

---

## SUBAGENT DEPLOYMENT GUIDE

Claude Code should use subagents for **isolated, well-scoped units of work**
where the output is a file or small set of files with clear acceptance criteria.
Do NOT use subagents for design decisions, cross-cutting refactors, or anything
that requires understanding the full codebase state.

### WHEN TO USE A SUBAGENT

| Task | Subagent? | Why |
|------|-----------|-----|
| Write a single Pydantic model file | ✅ YES | Isolated file, clear schema, no cross-file deps |
| Write a single React component | ✅ YES | Isolated file with clear props interface |
| Write a SQL migration file | ✅ YES | Self-contained DDL |
| Write unit tests for one module | ✅ YES | Reads one file, outputs one test file |
| Generate TypeScript types from Pydantic | ✅ YES | Script execution, deterministic output |
| Write a single API endpoint handler | ✅ YES | Clear input/output contract |
| Write CSS / Tailwind for one component | ✅ YES | Scoped styling |
| Research a library's API surface | ✅ YES | Read docs, summarize, no code changes |

### WHEN NOT TO USE A SUBAGENT

| Task | Subagent? | Why |
|------|-----------|-----|
| Decide how two modules should interact | ❌ NO | Requires architectural context |
| Refactor retrieval pipeline to accept list | ❌ NO | Touches multiple files, needs full picture |
| Wire up source_router → fusion → handler | ❌ NO | Cross-cutting integration |
| Debug a failing integration test | ❌ NO | Requires runtime state + multi-file understanding |
| Modify TriBridConfig (touches everything) | ❌ NO | Central model, ripple effects everywhere |
| Choose between two implementation approaches | ❌ NO | Design decision, not implementation |
| Update multiple components for new data flow | ❌ NO | Coordinated changes across files |

### SUBAGENT RULES

1. **Give the subagent ONLY what it needs.** Pass the Pydantic model it must implement,
   the file path, and the acceptance criteria. Do NOT dump the entire spec.
2. **One file per subagent** (or a tightly coupled pair like component + test).
3. **Subagent output must be verifiable.** If you can't write a one-line check
   ("does this file exist and does `uv run pytest tests/unit/test_X.py` pass?"),
   don't subagent it.
4. **The orchestrator owns integration.** After subagents produce their files,
   the main agent wires everything together. This is NOT delegated.
5. **Never subagent the first file in a dependency chain.** If file B imports from
   file A, write file A yourself, then subagent file B with file A's interface.

### SUBAGENT DEPLOYMENT MAP FOR THIS SPEC

Phase 1 — THE LAW (do these first; not subagent):
```
ORCHESTRATOR: Modify server/models/tribrid_config_model.py  (add ChatConfig + submodels; add ImageAttachment; update ChatRequest to use ActiveSources)
SUBAGENT (optional): Write server/models/chat_config.py  (thin re-export only; do NOT define new models outside THE LAW)
```

NOTE: Recall uses the existing Postgres `corpora` + `chunks` schema (repo_id == corpus_id). However, the current `chunks` table does NOT have a place to store chat-only metadata (role, timestamp, conversation_id). This spec REQUIRES a small, generic schema upgrade: add `chunks.metadata` as JSONB (default '{}'). This is implemented idempotently in `server/db/postgres.py:_ensure_schema` via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` so existing installs upgrade automatically.

Phase 2 — Backend modules (mix of subagent and orchestrator):
```
ORCHESTRATOR: Modify server/db/postgres.py  (add chunks.metadata JSONB; idempotent ALTER; wire through PostgresClient)
ORCHESTRATOR: Modify server/retrieval/fusion.py  (cross-cutting change: corpus_ids list + update fusion identity keys)
ORCHESTRATOR: Modify server/models/tribrid_config_model.py  (add ChatConfig + submodels in THE LAW; add Chunk.metadata; update ChatRequest)
ORCHESTRATOR: Modify server/api/chat.py  (ENTRYPOINT: parse new ChatRequest; wire to new chat modules)
ORCHESTRATOR: Modify all TriBridFusion.search callers for new signature:
  - server/api/search.py
  - server/api/eval.py
  - server/api/config.py
  - server/mcp/tools.py
  - server/services/rag.py
SUBAGENT: Write server/chat/source_router.py  (5 lines, give it ActiveSources model)
SUBAGENT: Write server/chat/provider_router.py  (give it provider config models)
SUBAGENT: Write server/chat/recall_indexer.py  (give it RecallConfig + PostgresClient corpora/chunks schema)
SUBAGENT: Write server/chat/model_discovery.py  (give it LocalModelConfig)
ORCHESTRATOR: Modify server/chat/handler.py  (wires everything together)
ORCHESTRATOR: Modify server/chat/generation.py  (provider routing + multimodal)
```

Phase 3 — Frontend (subagent-friendly after types are generated):
```
ORCHESTRATOR: Run scripts/generate_types.py  (must happen before any frontend)
SUBAGENT: Write web/src/components/Chat/SourceDropdown.tsx
SUBAGENT: Write web/src/components/Chat/ModelPicker.tsx
SUBAGENT: Write web/src/components/Chat/StatusBar.tsx
SUBAGENT: Write web/src/components/Chat/ProviderSetup.tsx
SUBAGENT: Write web/src/components/Chat/ChatSettings2.tsx
ORCHESTRATOR: Modify web/src/components/Chat/ChatInterface.tsx  (integration)
```

Phase 4 — Benchmark tab (subagent-friendly, independent feature):
```
SUBAGENT: Write web/src/components/Benchmark/BenchmarkTab.tsx
SUBAGENT: Write web/src/components/Benchmark/SplitScreen.tsx
SUBAGENT: Write web/src/components/Benchmark/ResultsTable.tsx
SUBAGENT: Write web/src/components/Benchmark/PipelineProfile.tsx
SUBAGENT: Write server/chat/benchmark_runner.py
```

Phase 5 — Tests (always subagent):
```
SUBAGENT: Write tests for each module (one subagent per test file)
```

---

## THE ARCHITECTURE: COMPOSABLE DATA SOURCES

### The Rule

There are NO modes. There are NO radio buttons. There is ONE chat interface
with a dropdown of checkboxes controlling which data sources contribute context.

```
┌─ Data Sources ──────────────────────────────┐
│                                               │
│  ☑ 🧠 Recall          (chat memory corpus)  │
│  ☑ 📦 tribrid-rag     (codebase corpus)     │
│  ☐ 📦 docs-v2         (documentation)       │
│  ☐ 📦 old-project     (archived)            │
│                                               │
│  Retrieval legs: [☑ Vector] [☑ Sparse] [☐ Graph]       │
│  [Manage corpora →]                           │
└───────────────────────────────────────────────┘
```

### How It Works

The user checks/unchecks boxes. The backend receives a list of corpus IDs.
The existing `TriBridFusion` pipeline queries all of them. One path. One pipeline.

| Checked sources | What happens |
|----------------|--------------|
| Nothing checked | No retrieval. Query goes straight to LLM. |
| ☑ Recall only | Retrieves from chat history corpus |
| ☑ A corpus only | RAG over that corpus |
| ☑ Recall + corpus | Retrieves from BOTH, merges via RRF |
| ☑ Multiple corpora | Multi-corpus retrieval, all merged via RRF |

**Recall is just another corpus ID** (`recall_default`). The pipeline does not
know or care which chunks came from chat history and which came from code.
They are all chunks with embeddings in the same schema.

### The Routing (entire thing)

```python
# server/chat/source_router.py

def resolve_sources(sources: ActiveSources) -> list[str]:
    """Return checked corpus IDs (Recall is `recall_default`)."""
    # De-dupe while preserving order
    return list(dict.fromkeys([cid for cid in sources.corpus_ids if cid]))
```

That's it. The list goes to `TriBridFusion.search()`.

### The Retrieval Flow

```
User checks boxes → ActiveSources
         ↓
  source_router.resolve_sources()
         ↓
  corpus_ids: list[str]
         ↓
  len == 0?  → skip retrieval, send query straight to LLM
  len >= 1?  → TriBridFusion.search(corpus_ids=corpus_ids, query=query)
                  ↓
              For each corpus_id:
                - vector search  (pgvector)
                - sparse search  (PostgreSQL FTS)
                - graph search   (Neo4j, if enabled; Recall graph is optional and gated by ChatConfig.recall.graph_enabled)
                  ↓
              RRF merge all results across all corpora
                  ↓
              Rerank (if enabled)
                  ↓
              Ranked chunks → injected into LLM context
```

**There is no `federated_retrieval.py`. There is no `RetrievalStrategy` enum.
There is no `RecallTarget` vs `CorpusTarget`. One pipeline. One plane.**

### The Change to fusion.py

The existing `TriBridFusion` currently accepts `repo_id: str`. Change it to
`corpus_ids: list[str]`. For each corpus ID, run the per-corpus retrieval legs
(vector, sparse, optional graph). Collect all results. RRF merge once. Rerank
once. Return. This is a MODIFICATION to an existing file, not a new module.

```python
# BEFORE (wrong — single corpus)
async def search(self, repo_id: str, query: str, config: FusionConfig) -> list[ChunkMatch]:

# AFTER (correct — multiple corpora)
async def search(self, corpus_ids: list[str], query: str, config: FusionConfig) -> list[ChunkMatch]:
    all_results: list[list[ChunkMatch]] = []
    for cid in corpus_ids:
        per_corpus = await self._search_single_corpus(cid, query, config)
        all_results.extend(per_corpus)
    return self.rrf_fusion(all_results, k=config.rrf_k)
```

#### Reranker config injection (IMPORTANT)

TriBridFusion takes `FusionConfig`, which does NOT include chat-specific reranker settings. When Chat-specific reranking ships (P1), chat must NOT use the global `retrieval.reranking` config. Use `TriBridConfig.chat.reranker` instead.

Implementation options (pick ONE; keep it consistent):
- Option A (preferred): Add `reranker_override: ChatRerankerConfig | None = None` to `TriBridFusion.search(...)` and use it when reranking.
- Option B: Keep TriBridFusion as retrieval-only; perform rerank in `server/api/chat.py` (or `server/chat/handler.py`) after fusion returns matches. Apply `recency_weight` using `chunks.metadata.timestamp`.

Until reranking is implemented, TriBridFusion should remain retrieval+fusion only.

---

## NAMING: RECALL

"Recall" is the name for persistent chat memory. It is:
- Technically precise (it recalls from an indexed conversation store)
- Unique (no competitor uses this term)
- Non-creepy ("Memory" implies sentience; "Recall" implies search)
- Verb-friendly ("Recall found 3 relevant messages")

Where it appears:
- Pydantic: `RecallConfig`
- UI: `☑ 🧠 Recall` in the data sources dropdown
- API: Recall is `recall_default` inside `ChatRequest.sources.corpus_ids`
- StatusBar: "Recall: 3 matches" / "Recall: indexing..."
- Settings: `[Recall]` tab

---

## DECISIONS — ALL LOCKED

| # | Decision | Answer |
|---|----------|--------|
| 1 | Chat memory name | **Recall** |
| 2 | Architecture | **Composable checkboxes, not radio modes** |
| 3 | Recall default | **ON by default** — self-hosted, local, zero risk |
| 4 | Vector backend | **pgvector** (Neo4j as config option) |
| 5 | Providers (P0) | **OpenRouter (MANDATORY) + Ollama + llama.cpp** |
| 6 | Providers (P1) | LM Studio + vLLM |
| 7 | Image gen (local) | Terminal command / subprocess (NOT ComfyUI for local) |
| 8 | Image gen (cloud) | ComfyUI API + Replicate + DALL-E (all paid) |
| 9 | Ship order | **All together** — Recall + Direct + RAG share plumbing |
| 10 | Settings | **Burn and rebuild** |
| 11 | Benchmark | **Full tab** — split-screen model comparison + pipeline profiling |
| 12 | Recall graph | Optional (default OFF) — checkbox + warning; P1 uses Neo4j chunk-mode |

---

## PYDANTIC MODELS

All new Chat 2.0 models are defined in THE LAW: `server/models/tribrid_config_model.py`.

`server/models/chat_config.py` (if created) is a thin re-export module for convenience only.

TypeScript types are generated from THE LAW via `scripts/generate_types.py`. Frontend never hand-writes types.
TypeScript types are generated from these. Frontend never hand-writes types.

```python
from pydantic import BaseModel, Field, model_validator
from enum import Enum
from typing import Self


# ─── Active Sources (the checkbox state) ─────────────────────────

class ActiveSources(BaseModel):
    """What the user has checked in the data sources dropdown.
    This is what the frontend sends. The backend passes corpus_ids straight into fusion."""
    corpus_ids: list[str] = Field(
        default=["recall_default"],  # Recall ON by default
        description="Checked corpus IDs (include recall_default when Recall is checked)"
    )


# ─── Chat Reranker ───────────────────────────────────────────────

class ChatRerankerConfig(BaseModel):
    """Chat-specific reranker. Separate from RAG reranker because:
    - Shorter passages (conversation turns, not code blocks)
    - Recency bias (recent messages matter more)
    - Lower latency tolerance (chat feels slow >500ms)
    No 'learning' mode — chat passages are too short for triplet training.
    """
    mode: str = Field(
        default="local",
        pattern="^(cloud|local|none)$",
        description="Chat reranker mode."
    )
    local_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Local cross-encoder. L-6 not L-12 — faster for chat."
    )
    cloud_provider: str = Field(default="cohere")
    cloud_model: str = Field(default="rerank-v3.5")
    top_n: int = Field(default=20, ge=5, le=100)
    recency_weight: float = Field(
        default=0.3, ge=0.0, le=1.0,
        description="Blend weight for recency. 0=pure relevance, 1=pure recency."
    )
    max_age_hours: int = Field(
        default=0, ge=0,
        description="Only retrieve messages from last N hours. 0=no limit."
    )


# ─── Recall ──────────────────────────────────────────────────────

class RecallConfig(BaseModel):
    """Persistent chat memory. ON by default.
    Indexes every conversation into a lightweight pgvector corpus.
    Self-hosted, local, zero privacy risk, negligible storage.
    """
    enabled: bool = Field(
        default=True,  # ON BY DEFAULT
        description="Enable Recall. ON by default."
    )
    vector_backend: str = Field(
        default="pgvector",
        pattern="^(pgvector|neo4j)$",
        description="pgvector recommended (already running)."
    )
    auto_index: bool = Field(default=True)
    index_delay_seconds: int = Field(default=5, ge=1, le=60)
    chunking_strategy: str = Field(
        default="sentence",
        pattern="^(sentence|paragraph|turn|fixed)$",
        description="'turn'=one chunk per message, 'sentence'=split by sentence."
    )
    chunk_max_tokens: int = Field(
        default=256, ge=64, le=1024,
        description="Chat chunks should be smaller than code chunks."
    )
    embedding_model: str = Field(
        default="",
        description="Override embedding model. Empty=use global config."
    )
    max_history_tokens: int = Field(default=4096, ge=512, le=32768)
    default_corpus_id: str = Field(
        default="recall_default",
        description="Auto-created at first launch. Users never touch this."
    )


# ─── Multimodal ──────────────────────────────────────────────────

class ChatMultimodalConfig(BaseModel):
    """Image upload + vision model configuration."""
    vision_enabled: bool = Field(default=True)
    max_image_size_mb: int = Field(default=20, ge=1, le=50)
    max_images_per_message: int = Field(default=5, ge=1, le=10)
    supported_formats: list[str] = Field(
        default=["png", "jpg", "jpeg", "gif", "webp"]
    )
    image_detail: str = Field(
        default="auto",
        pattern="^(auto|low|high)$",
        description="OpenAI vision detail level."
    )
    vision_model_override: str = Field(
        default="",
        description="Force model for vision. Empty=use chat model if it supports vision."
    )


# ─── Image Attachment (vision inputs) ─────────────────────────

class ImageAttachment(BaseModel):
    """Single image attached to a chat message.

    Exactly ONE of `url` or `base64` must be provided.
    """
    url: str | None = Field(default=None, description="Remote URL")
    base64: str | None = Field(default=None, description="Base64 data URI (no data: prefix required)")
    mime_type: str = Field(default="image/png", description="MIME type (e.g., image/png)")

    @model_validator(mode="after")
    def _check_source(self) -> Self:
        if not self.url and not self.base64:
            raise ValueError("Must provide either url or base64")
        if self.url and self.base64:
            raise ValueError("Provide only one of url or base64")
        return self


# ─── Image Generation ────────────────────────────────────────────

class ImageGenConfig(BaseModel):
    """Two tiers:
    - LOCAL: Direct CLI/subprocess (free, self-hosted)
    - CLOUD: Paid APIs (ComfyUI API, Replicate, DALL-E)
    ComfyUI is typically self-hosted. We do NOT use ComfyUI as the local P0 path; local P0 is direct CLI/subprocess. `comfyui_api` is a remote endpoint (self-hosted or paid).
    """
    enabled: bool = Field(default=False)
    provider: str = Field(
        default="local",
        pattern="^(local|openai|comfyui_api|replicate)$"
    )
    # Local (free)
    local_command: str = Field(
        default="python -m qwen_image.generate",
        description="CLI command. Receives --prompt, --output, --steps, --width, --height."
    )
    local_model_path: str = Field(default="")
    use_lightning_lora: bool = Field(default=True)
    # Cloud (paid)
    comfyui_api_endpoint: str = Field(default="")
    replicate_model: str = Field(default="")
    # Shared
    default_steps: int = Field(default=8, ge=1, le=50)
    default_resolution: str = Field(default="1024x1024")


# ─── OpenRouter ──────────────────────────────────────────────────

class OpenRouterConfig(BaseModel):
    """Unified gateway to 400+ cloud models. OpenAI-compatible.
    MANDATORY P0 provider.
    """
    enabled: bool = Field(default=False)
    api_key: str = Field(default="")
    base_url: str = Field(default="https://openrouter.ai/api/v1")
    default_model: str = Field(default="anthropic/claude-sonnet-4-20250514")
    site_name: str = Field(default="TriBridRAG")
    fallback_models: list[str] = Field(
        default=["openai/gpt-4o", "google/gemini-2.0-flash"]
    )


# ─── Local Models ────────────────────────────────────────────────

class LocalProviderEntry(BaseModel):
    """A single local inference provider endpoint."""
    name: str = Field(description="Display name")
    provider_type: str = Field(
        pattern="^(ollama|llamacpp|lmstudio|vllm|custom)$"
    )
    base_url: str = Field(description="Provider API endpoint")
    enabled: bool = Field(default=True)
    priority: int = Field(
        default=0, ge=0,
        description="Lower = higher priority when multiple have same model."
    )


class LocalModelConfig(BaseModel):
    """Supports MULTIPLE simultaneous local providers.
    P0: Ollama + llama.cpp. All use OpenAI-compatible API.
    """
    providers: list[LocalProviderEntry] = Field(
        default=[
            LocalProviderEntry(
                name="Ollama",
                provider_type="ollama",
                base_url="http://127.0.0.1:11434",
                priority=0,
            ),
            LocalProviderEntry(
                name="llama.cpp",
                provider_type="llamacpp",
                base_url="http://127.0.0.1:8080",
                priority=1,
            ),
        ]
    )
    auto_detect: bool = Field(default=True)
    health_check_interval: int = Field(default=30, ge=10, le=300)
    fallback_to_cloud: bool = Field(default=True)
    gpu_memory_limit_gb: float = Field(default=0, ge=0)
    default_chat_model: str = Field(default="qwen3:8b")
    default_vision_model: str = Field(default="qwen3-vl:8b")
    default_embedding_model: str = Field(default="nomic-embed-text")


# ─── Benchmark ───────────────────────────────────────────────────

class BenchmarkConfig(BaseModel):
    """FULL FEATURE TAB. Not a nice-to-have.
    Split-screen model comparison + pipeline profiling.
    """
    enabled: bool = Field(default=True)
    max_concurrent_models: int = Field(default=4, ge=2, le=8)
    save_results: bool = Field(default=True)
    results_path: str = Field(default="data/benchmarks/")
    include_cost_tracking: bool = Field(default=True)
    include_timing_breakdown: bool = Field(default=True)


# ─── Top-Level ChatConfig ────────────────────────────────────────

class ChatConfig(BaseModel):
    """Top-level chat configuration. Lives at TriBridConfig.chat

    KEY CONCEPT: There are no modes. The user checks/unchecks data sources.
    Recall is always available and ON by default. Corpora are available when
    indexed. Everything composes freely.
    """
    # Default checkbox state for new conversations
    default_corpus_ids: list[str] = Field(
        default=["recall_default"],
        description="Default checked corpus IDs for new conversations (Recall ON by default)."
    )

    # System prompts (composed dynamically based on active sources)
    system_prompt_base: str = Field(
        default="You are a helpful assistant."
    )
    system_prompt_recall_suffix: str = Field(
        default=" You have access to conversation history. Reference past discussions when relevant."
    )
    system_prompt_rag_suffix: str = Field(
        default=" Answer questions using the provided code context. Cite file paths and line ranges."
    )

    # Sub-configs
    reranker: ChatRerankerConfig = Field(default_factory=ChatRerankerConfig)
    recall: RecallConfig = Field(default_factory=RecallConfig)
    multimodal: ChatMultimodalConfig = Field(default_factory=ChatMultimodalConfig)
    image_gen: ImageGenConfig = Field(default_factory=ImageGenConfig)
    local_models: LocalModelConfig = Field(default_factory=LocalModelConfig)
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)

    # Generation defaults
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    temperature_no_retrieval: float = Field(
        default=0.7, ge=0.0, le=2.0,
        description="Temperature when nothing is checked (direct chat = more creative)"
    )
    max_tokens: int = Field(default=4096, ge=100, le=16384)

    # Features
    show_source_dropdown: bool = Field(default=True)
    send_shortcut: str = Field(default="ctrl+enter")
```

### Add to TriBridConfig

```python
class TriBridConfig(BaseModel):
    # ... existing sections ...
    chat: ChatConfig = Field(default_factory=ChatConfig)  # NEW
```

---

## UPDATED ChatRequest

```python
class ChatRequest(BaseModel):
    """Chat request — composable data sources, not modes."""
    message: str

    # Active data sources (what's checked in the dropdown)
    sources: ActiveSources = Field(
        default_factory=ActiveSources,
        description="Checked sources. Empty corpus_ids = no retrieval. If recall_default is not present, Recall is OFF for both retrieval and indexing.",
    )

    # Existing fields
    conversation_id: str | None = Field(default=None)
    stream: bool = Field(default=False)
    images: list[ImageAttachment] = Field(default_factory=list, description="Optional images for vision (max 5)")
    model_override: str = Field(default="")
    include_vector: bool = Field(default=True)
    include_sparse: bool = Field(default=True)
    include_graph: bool = Field(
        default=False,
        description="Advanced. Graph leg runs per-corpus; Recall only if ChatConfig.recall.graph_enabled.",
    )
    top_k: int | None = Field(default=None, ge=1, le=100)
```

**`mode: str` is gone. `repo_id: str` is gone. Replaced by `sources.corpus_ids` (which includes `recall_default` when Recall is checked).**

---

## RECALL INDEXING PIPELINE

### Recall vs RAG Indexing

| | RAG (code) | Recall (chat) |
|---|-----------|---------------|
| Chunking | AST / fixed-size | Per-turn or sentence-split |
| Chunk size | 512-1024 tokens | 64-256 tokens |
| BM25 tokenizer | Whitespace (code identifiers) | NLP tokenizer |
| Knowledge Graph | YES | Optional (default OFF; checkbox + latency warning; P1) |
| Enrichment | Code summaries | NO — messages are natural language |
| Metadata | file_path, language, repo_id | timestamp, role, conversation_id (stored in chunks.metadata JSONB) |

### Recall Graph (optional; default OFF)

Recall can optionally participate in Neo4j graph retrieval for long-horizon recall (e.g., conversations from months/years ago), but it is **EXPERIMENTAL**.

UI requirements (Defaults, not mandates):
- Expose a checkbox: **Graph (Experimental)** with a clear warning: "Adds indexing time and can add ~200–500ms/query."
- Default **OFF**.

Implementation notes (P1):
- When enabled, the Recall indexer also writes Recall chunks into Neo4j using `Neo4jClient.upsert_document_and_chunks(...)` with:
  - `repo_id = recall_default`
  - `file_path = recall/conversations/<conversation_id>.md`
  - `store_embeddings = True`
- Ensure the Neo4j Chunk vector index exists (use existing `graph_indexing.chunk_vector_index_name` and embedding dims).
- For Recall, graph retrieval uses `graph_search.mode = "chunk"` only (NOT entity KG) in P1.

Retrieval gating (LOCKED):
- Graph leg runs for Recall only when:
  - `request.include_graph` is true AND
  - scoped config enables graph search AND
  - `ChatConfig.recall.graph_enabled` is true.

P2 (optional): semantic entity extraction for Recall (people/projects/places) can be added later, but is not required for P1.

### Auto-creation

On first launch (or when recall is enabled and no corpus exists):

```python
async def ensure_recall_corpus(pg: PostgresClient, config: RecallConfig) -> None:
    corpus_id = config.default_corpus_id  # "recall_default"
    if await pg.get_corpus(corpus_id) is None:
        await pg.upsert_corpus(
            repo_id=corpus_id,
            name="Recall",
            root_path="data/recall",
            description="Persistent chat recall corpus (auto-managed)",
            meta={"system_kind": "recall", "pinned": True},
        )
```

### Postgres storage (existing schema)

Recall does NOT use a separate table. Recall messages are indexed into the existing
Postgres `corpora` + `chunks` tables under `repo_id = recall_default` (same schema as all corpora).

#### Schema upgrade (REQUIRED): `chunks.metadata` (JSONB)

The current codebase creates `chunks` without any generic metadata column. Chat needs metadata for:
- `role` (user/assistant)
- `timestamp` (recency weighting, max_age_hours)
- `conversation_id` / `message_id` (stable identity)

Implement this upgrade in `server/db/postgres.py:_ensure_schema`:

1) Update the `CREATE TABLE IF NOT EXISTS chunks` DDL to include:

```sql
metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
```

2) Upgrade existing installs with an idempotent alter (must run every boot):

```sql
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
```

3) Wire the new column through PostgresClient:
- `upsert_embeddings` and `upsert_fts`: insert/update `metadata`
- `vector_search` and `sparse_search`: SELECT `metadata` and populate `ChunkMatch.metadata`

Update THE LAW `Chunk` model in `server/models/tribrid_config_model.py`:

```python
metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary chunk metadata")
```

Chunk mapping (recommended):
- `repo_id`: `recall_default`
- `chunk_id`: `f"recall:{conversation_id}:{message_id}"`
- `file_path`: `f"recall/conversations/{conversation_id}.md"`
- `start_line` / `end_line`: monotonic turn index (or `0/0` if unused)
- `language`: `None`
- `content`: message text (or sentence-split chunks)
- `tsv`: computed via Postgres FTS config `english`
- `metadata`: JSONB with stable keys for Recall
  - `{"kind":"recall_message","conversation_id":"...","message_id":"...","role":"user|assistant","timestamp":"2026-02-02T12:34:56Z","turn_index":123}`

Optional but recommended for Recall latency (idempotent):

```sql
CREATE INDEX IF NOT EXISTS idx_chunks_recall_embedding_hnsw
  ON chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64)
  WHERE repo_id = 'recall_default' AND embedding IS NOT NULL;
```

Bidirectional rule (LOCKED):
- Only write new messages into Recall when `recall_default` is present in `ChatRequest.sources.corpus_ids`.
- If `recall_default` is unchecked, Recall is OFF for both retrieval and indexing.

---

## MODEL DISCOVERY

All local providers use OpenAI-compatible `/v1/models` endpoint.
One adapter. No per-provider code.

```python
async def discover_models(providers: list[LocalProviderEntry]) -> list[ModelInfo]:
    all_models = []
    for provider in providers:
        if not provider.enabled:
            continue
        try:
            resp = await httpx.get(f"{provider.base_url}/v1/models")
            models = resp.json()["data"]
            all_models.extend([
                ModelInfo(id=m["id"], provider=provider.name, ...)
                for m in models
            ])
        except Exception:
            try:  # Ollama native fallback
                resp = await httpx.get(f"{provider.base_url}/api/tags")
                models = resp.json()["models"]
                all_models.extend([
                    ModelInfo(id=m["name"], provider=provider.name, ...)
                    for m in models
                ])
            except Exception:
                pass  # Provider offline
    return all_models
```

Model dropdown groups: ☁️ Cloud Direct | 🌐 OpenRouter | 🏠 Local

---

## API ENDPOINTS

### Updated

```
POST /api/chat            — accepts sources (ActiveSources), images
POST /api/chat/stream     — same (sources + images)
```

### New

```
GET  /api/chat/models     — list available models (local + cloud + OpenRouter)
GET  /api/chat/health     — provider health status
POST /api/recall/index    — manually trigger recall indexing
GET  /api/recall/status   — recall index status
POST /api/image/generate  — image gen (routes to local CLI or cloud API)
GET  /api/image/models    — available image gen models/providers
GET  /api/providers       — list all configured providers and status
POST /api/benchmark/run   — run model comparison
GET  /api/benchmark/results — fetch benchmark results
```

---

## UI LAYOUT

### Chat Header

```
┌──────────────────────────────────────────────────────────┐
│  [Data Sources ▼]     [Model: qwen3:8b ▼]    [⚙️]      │
│  ─────────────────────────────────────────────────────── │
│                                                          │
│  ... chat messages ...                                   │
│                                                          │
│  ─────────────────────────────────────────────────────── │
│  [📎] [🎨] [  Type a message...              ] [Send]    │
│  ─────────────────────────────────────────────────────── │
│  Recall: 3 matches | tribrid-rag: 7 matches | 1.2s      │
└──────────────────────────────────────────────────────────┘
```

### Settings — Burned and Rebuilt

```
[Model]  [Sources]  [Recall]  [Multimodal]  [Local]  [OpenRouter]  [Benchmark]  [UI]
```

**[Model]** — Provider (☁️/🌐/🏠), model picker, generation params, system prompt
**[Sources]** — Corpus management, default checkboxes, retrieval legs per source
**[Recall]** — Defaults, not mandates (all with tooltips + warnings): vector backend, chunking_strategy, chunk_max_tokens, embedding override, auto_index/index_delay_seconds, max_history_tokens, Recall graph (experimental toggle + latency warning), and Recall corpus bootstrap status
**[Multimodal]** — Vision toggle, image limits, image gen config
**[Local]** — Ollama/llama.cpp/LM Studio/vLLM setup, model management, GPU config
**[OpenRouter]** — API key, model selection, cost tracking
**[Benchmark]** — Split-screen comparison config, pipeline profiling, history
**[UI]** — Streaming, citations, confidence, debug footer, theme

### Benchmark Tab (FULL FEATURE, TOP-LEVEL TAB)

Lives alongside Chat, RAG, Dashboard in the main nav. Not nested under Chat.

1. Split-screen model comparison (2-4 models simultaneously)
2. Same prompt to multiple models with real-time streaming
3. Timing breakdown per model: retrieval → rerank → generate with ms
4. Cost comparison: tokens + estimated cost per model
5. Response quality scoring (manual thumbs up/down)
6. Export comparison results (JSON, Markdown)
7. Historical benchmark tracking
8. Pipeline profiling — identify bottlenecks

---

## FILE CHANGES

### New Files

```
server/models/chat_config.py               — All Pydantic models above
server/chat/source_router.py               — resolve_sources() (5 lines)
server/chat/provider_router.py             — Route to correct model provider
server/chat/recall_indexer.py              — Background indexer for Recall
server/chat/model_discovery.py             — Probe ALL providers for models
server/chat/image_handler.py               — Process image uploads
server/chat/image_gen.py                   — Image gen (local subprocess + cloud APIs)
server/chat/benchmark_runner.py            — Model comparison engine
web/src/components/Chat/SourceDropdown.tsx  — Checkbox dropdown
web/src/components/Chat/StatusBar.tsx       — Bottom status bar
web/src/components/Chat/ImageUpload.tsx     — Image upload + preview
web/src/components/Chat/ImageGen.tsx        — Image gen UI
web/src/components/Chat/ModelPicker.tsx     — Model selection (☁️🌐🏠)
web/src/components/Chat/ChatSettings2.tsx   — Rebuilt settings
web/src/components/Chat/ProviderSetup.tsx   — OpenRouter + local config
web/src/components/Benchmark/BenchmarkTab.tsx    — Main benchmark UI
web/src/components/Benchmark/SplitScreen.tsx     — Side-by-side comparison
web/src/components/Benchmark/ResultsTable.tsx    — Results display
web/src/components/Benchmark/PipelineProfile.tsx — Timing waterfall
```

### Modified Files

```
server/db/postgres.py                        — Add chunks.metadata JSONB + idempotent ALTER + query wiring
server/models/tribrid_config_model.py        — Add ChatConfig + submodels in THE LAW; add Chunk.metadata; update ChatRequest
server/retrieval/fusion.py                   — repo_id: str → corpus_ids: list[str]
server/api/chat.py                           — ENTRYPOINT updates for new ChatRequest + Recall I/O
server/api/search.py                         — Update fusion.search caller
server/api/eval.py                           — Update fusion.search caller
server/api/config.py                         — Update fusion.search caller
server/mcp/tools.py                          — Update fusion.search caller
server/services/rag.py                       — Update fusion.search callers
server/chat/handler.py                       — Call source_router, pass corpus_ids to fusion
server/chat/generation.py                    — Multimodal messages, provider routing
web/src/types/generated.ts                   — Regenerated from Pydantic
web/src/components/Chat/ChatInterface.tsx    — New layout, source dropdown, status bar
```

### Deleted Files

```
web/src/components/Chat/ChatSettings.tsx   — Replaced by ChatSettings2.tsx
```

### Files That Do NOT Exist (do not create these)

```
server/chat/federated_retrieval.py         — NO. One pipeline. One plane.
server/chat/mode_router.py                 — NO. There are no modes.
web/src/components/Chat/ModeToggle.tsx      — NO. There is no toggle.
```

---

## IMPLEMENTATION PRIORITY

**Ship RAG + Direct + Recall TOGETHER. They all share the same plumbing.**

| Phase | What | Effort |
|-------|------|--------|
| **P0** | ActiveSources model + ChatConfig + source dropdown | M |
| **P0** | Provider router (OpenAI + Anthropic + OpenRouter + Ollama + llama.cpp) | M |
| **P0** | OpenRouter integration (API key, model discovery, routing) | S |
| **P0** | Local model auto-discovery (Ollama + llama.cpp) | S |
| **P0** | Recall indexing pipeline (pgvector, sentence chunking, auto-create) | M |
| **P0** | `fusion.py` accepts `corpus_ids: list[str]` (replaces single `repo_id`) | S |
| **P0** | UI: source dropdown + rebuilt settings + model picker | L |
| **P0** | Benchmark tab: split-screen comparison + pipeline profiling | L |
| **P1** | Image upload (vision passthrough) | M |
| **P1** | Chat-specific reranker | M |
| **P1** | LM Studio + vLLM provider support | S |
| **P2** | Local image gen (CLI/subprocess) | M |
| **P2** | Cloud image gen (ComfyUI API, Replicate, DALL-E) | M |
| **P2** | Slash commands (/imagine, /compare, /model, /cost, /export) | M |
| **P2** | Smart model routing | M |
| **P3** | Voice input | S |
| **P3** | Conversation forking | L |

---

## BANNED TERMS AND PATTERNS

These are enforced by hooks. Do not use them.

| Banned | Use Instead |
|--------|-------------|
| `card` / `cards` | `chunk_brief` / `chunk_briefs` |
| `golden questions` | `eval_dataset` |
| `ranker` (without `re` prefix) | `reranker` |
| `from qdrant` / `import qdrant` | Use pgvector / Neo4j |
| `from redis` / `import redis` | Use Neo4j |
| `from langchain` / `import langchain` | Banned entirely |
| `from langgraph` / `import langgraph` | Banned entirely |
| `pip install` / `pip3 install` | `uv add` |
| `python -m venv` / `virtualenv` | `uv` |

---

## CONTRACT CHAIN (enforced)

```
Pydantic Model → TypeScript Interface → Zustand Store → Hook → Component
```

1. TypeScript types are GENERATED from Pydantic (`scripts/generate_types.py`)
2. Never hand-write TypeScript interfaces for API types
3. If frontend needs a different shape, change the Pydantic model
4. No adapters, no transformers, no mappers
5. Max 3 Zustand stores, max 10 hooks

---

## VERIFICATION BEFORE RESPONDING

Every change must be tested before claiming completion:

- **GUI changes**: Playwright test with real interactions
- **API changes**: pytest with actual result validation
- **New Pydantic models**: `uv run python -c "from server.models.chat_config import ChatConfig; print(ChatConfig().model_dump_json(indent=2))"`
- **Type generation**: `uv run python scripts/generate_types.py` must succeed
- **Type sync**: `uv run python scripts/validate_types.py` must pass

Do NOT say "done" without running verification. Do NOT say "I've created the file"
without the file actually existing on disk.

