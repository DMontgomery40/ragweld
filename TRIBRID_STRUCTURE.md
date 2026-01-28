# tribrid-rag Complete Structure

## Overview

This is the COMPLETE file structure for tribrid-rag - every file, every module, every component. 
Total: ~280 files (not counting __init__.py and index.ts barrel files)

**What's CUT from agro-rag-engine:**
- Onboarding wizard (7 files)
- Profiles system (4 files)
- VSCode embed (3 files)  
- MCP multi-transport (simplified to 1)
- Legacy JS modules (6 files)
- Duplicate Docker components (4 of 5 versions)
- Qdrant (replaced with pgvector)
- Redis/LangGraph (replaced with Neo4j for graph)
- Autotune/Autoprofile (2 files)
- 19 redundant hooks → consolidated to 14

**What's ADDED:**
- Neo4j graph layer (5 backend + 4 frontend files)
- Tri-brid fusion (3 backend + 2 frontend files)
- pgvector + FTS (2 backend files)
- Entity/relationship extraction (2 backend files)

---

## Root Directory

```
tribrid-rag/
├── .claude/                          # Claude Code config
│   └── hooks/
│       └── stop.js                   # Ralph loop stop hook
├── .github/
│   └── workflows/
│       └── ci.yml                    # GitHub Actions CI
├── infra/                            # Docker & observability configs
├── models/                           # Trained model weights
├── server/                           # Python backend
├── web/                              # React frontend
├── scripts/                          # Dev/ops scripts
├── tests/                            # Python tests
├── spec/                             # YAML specifications
├── .env.example
├── .gitignore
├── CLAUDE.md                         # Claude Code instructions
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml                    # uv project config
├── README.md
├── tribrid_config.json               # Main config file
└── uv.lock
```

---

## infra/ - Infrastructure Configs (5 files)

```
infra/
├── alertmanager.yml                  # Grafana alertmanager config
├── docker-compose.dev.yml            # Dev overrides
├── grafana/
│   └── provisioning/
│       └── dashboards/
│           └── rag-metrics.json      # Pre-built RAG dashboard
├── prometheus.yml                    # Prometheus scrape config
└── repos.docker.json                 # Container path mappings
```

---

## models/ - Trained Model Artifacts (5 files)

```
models/
└── cross-encoder-tribrid/
    ├── config.json                   # HuggingFace model config
    ├── model.safetensors             # Model weights (gitignored)
    ├── special_tokens_map.json
    ├── tokenizer_config.json
    └── tokenizer.json
```

---

## server/ - Python Backend (52 files)

```
server/
├── __init__.py
├── main.py                           # FastAPI ASGI entrypoint
├── config.py                         # Pydantic settings loader
│
├── api/                              # API routers (13 files)
│   ├── __init__.py
│   ├── chat.py                       # POST /chat, /chat/stream
│   ├── config.py                     # GET/PUT /config
│   ├── cost.py                       # GET /cost/estimate, /cost/history
│   ├── docker.py                     # GET /docker/status, POST /docker/restart
│   ├── eval.py                       # POST /eval/run, GET /eval/history
│   ├── dataset.py                    # GET/POST /dataset (was "golden")
│   ├── graph.py                      # NEW: GET /graph/entities, /graph/relationships
│   ├── health.py                     # GET /health, /ready, /metrics
│   ├── index.py                      # POST /index, GET /index/status
│   ├── reranker.py                   # GET/POST /reranker/*, /reranker/triplets
│   ├── repos.py                      # GET/POST /repos
│   └── search.py                     # POST /search, /answer
│
├── db/                               # Database clients (3 files)
│   ├── __init__.py
│   ├── postgres.py                   # pgvector + FTS client
│   └── neo4j.py                      # Neo4j graph client
│
├── indexing/                         # Indexing pipeline (6 files)
│   ├── __init__.py
│   ├── chunker.py                    # AST-aware code chunking
│   ├── embedder.py                   # Batch embedding with caching
│   ├── graph_builder.py              # NEW: Entity/relationship extraction
│   ├── summarizer.py                 # Chunk summary generation (was "cards")
│   └── loader.py                     # File loading + filtering
│
├── models/                           # Pydantic schemas (10 files)
│   ├── __init__.py
│   ├── chat.py                       # ChatRequest, ChatResponse, Message
│   ├── config.py                     # TriBridConfig (main config schema)
│   ├── cost.py                       # CostEstimate, CostHistory
│   ├── dataset.py                    # DatasetEntry, DatasetStats (was "golden")
│   ├── eval.py                       # EvalRun, EvalResult, EvalMetrics
│   ├── graph.py                      # NEW: Entity, Relationship, Community
│   ├── index.py                      # IndexStatus, IndexStats, Chunk
│   ├── repo.py                       # Repository, RepoStats
│   └── retrieval.py                  # SearchResult, RetrievalConfig
│
├── retrieval/                        # Search & reranking (8 files)
│   ├── __init__.py
│   ├── vector.py                     # pgvector similarity search
│   ├── sparse.py                     # Postgres FTS (BM25-style)
│   ├── graph.py                      # NEW: Neo4j Cypher queries
│   ├── fusion.py                     # NEW: Tri-brid RRF fusion
│   ├── rerank.py                     # 4-mode reranker (none/local/trained/api)
│   ├── learning.py                   # Self-learning reranker training
│   └── cache.py                      # Embedding cache
│
├── services/                         # Business logic (6 files)
│   ├── __init__.py
│   ├── config_store.py               # Config persistence
│   ├── dataset.py                    # Dataset management (was "golden")
│   ├── indexing.py                   # Index orchestration
│   ├── rag.py                        # RAG pipeline orchestration
│   └── traces.py                     # Tracing service
│
└── observability/                    # Metrics & tracing (4 files)
    ├── __init__.py
    ├── metrics.py                    # Prometheus metrics
    ├── tracing.py                    # OpenTelemetry spans
    └── alerts.py                     # Alert threshold management
```

---

## web/ - React Frontend (148 files)

```
web/
├── index.html
├── package.json
├── postcss.config.js
├── tailwind.config.ts
├── tsconfig.json
├── vite.config.ts
│
└── src/
    ├── main.tsx                      # React entry
    ├── App.tsx                       # Root component + router
    │
    ├── api/                          # API client layer (8 files)
    │   ├── index.ts
    │   ├── client.ts                 # Axios/fetch wrapper
    │   ├── chat.ts                   # Chat endpoints
    │   ├── config.ts                 # Config endpoints
    │   ├── docker.ts                 # Docker endpoints
    │   ├── eval.ts                   # Eval endpoints
    │   ├── graph.ts                  # NEW: Graph endpoints
    │   ├── health.ts                 # Health endpoints
    │   └── search.ts                 # Search endpoints
    │
    ├── components/                   # UI components (89 files)
    │   │
    │   ├── Admin/                    # Admin tab (3 files)
    │   │   ├── index.ts
    │   │   ├── AdminSubtabs.tsx
    │   │   └── GeneralSubtab.tsx
    │   │
    │   ├── Analytics/                # Analytics subtab (5 files)
    │   │   ├── index.ts
    │   │   ├── Cost.tsx
    │   │   ├── Performance.tsx
    │   │   ├── Tracing.tsx
    │   │   └── Usage.tsx
    │   │
    │   ├── Chat/                     # Chat interface (5 files)
    │   │   ├── index.ts
    │   │   ├── ChatInterface.tsx
    │   │   ├── ChatSettings.tsx
    │   │   ├── ChatSubtabs.tsx
    │   │   └── MessageBubble.tsx
    │   │
    │   ├── Dashboard/                # Dashboard tab (14 files)
    │   │   ├── index.ts
    │   │   ├── DashboardSubtabs.tsx
    │   │   ├── EmbeddingConfigPanel.tsx
    │   │   ├── GlossarySubtab.tsx
    │   │   ├── HelpGlossary.tsx
    │   │   ├── HelpGlossary.css
    │   │   ├── HelpSubtab.tsx
    │   │   ├── IndexDisplayPanels.tsx
    │   │   ├── IndexingCostsPanel.tsx
    │   │   ├── MonitoringSubtab.tsx
    │   │   ├── QuickActions.tsx
    │   │   ├── StorageSubtab.tsx
    │   │   ├── SystemStatus.tsx
    │   │   └── SystemStatusSubtab.tsx
    │   │
    │   ├── Evaluation/               # Evaluation components (7 files)
    │   │   ├── index.ts
    │   │   ├── DatasetManager.tsx    # (was QuestionManager)
    │   │   ├── EvalDrillDown.tsx
    │   │   ├── EvaluationRunner.tsx
    │   │   ├── FeedbackPanel.tsx
    │   │   ├── HistoryViewer.tsx
    │   │   └── TraceViewer.tsx
    │   │
    │   ├── Grafana/                  # Grafana integration (4 files)
    │   │   ├── index.ts
    │   │   ├── GrafanaConfig.tsx
    │   │   ├── GrafanaDashboard.tsx
    │   │   └── GrafanaSubtabs.tsx
    │   │
    │   ├── Graph/                    # NEW: Knowledge graph UI (5 files)
    │   │   ├── index.ts
    │   │   ├── GraphExplorer.tsx     # Interactive graph visualization
    │   │   ├── EntityDetail.tsx      # Entity with relationships
    │   │   ├── CommunityView.tsx     # Community summaries
    │   │   └── GraphConfigPanel.tsx  # Neo4j connection settings
    │   │
    │   ├── Infrastructure/           # Infrastructure tab (5 files)
    │   │   ├── index.ts
    │   │   ├── DockerSubtab.tsx      # SINGLE docker component
    │   │   ├── InfrastructureSubtabs.tsx
    │   │   ├── PathsSubtab.tsx
    │   │   └── ServicesSubtab.tsx
    │   │
    │   ├── LiveTerminal/             # Terminal output (3 files)
    │   │   ├── index.ts
    │   │   ├── LiveTerminal.tsx
    │   │   └── LiveTerminal.css
    │   │
    │   ├── Navigation/               # Tab navigation (3 files)
    │   │   ├── index.ts
    │   │   ├── TabBar.tsx
    │   │   └── TabRouter.tsx
    │   │
    │   ├── RAG/                      # RAG config tab (13 files)
    │   │   ├── index.ts
    │   │   ├── ChunkSummaryPanel.tsx # (was CardsBuilderPanel)
    │   │   ├── ChunkSummaryViewer.tsx# (was CardsViewer)
    │   │   ├── DataQualitySubtab.tsx
    │   │   ├── EvaluateSubtab.tsx
    │   │   ├── FusionWeightsPanel.tsx# NEW: 3-way slider
    │   │   ├── IndexingSubtab.tsx
    │   │   ├── IndexStatsPanel.tsx
    │   │   ├── LearningRerankerSubtab.tsx
    │   │   ├── ModelPicker.tsx
    │   │   ├── RAGSubtabs.tsx
    │   │   ├── RerankerConfigSubtab.tsx
    │   │   └── RetrievalSubtab.tsx
    │   │
    │   ├── Search/                   # Global search (2 files)
    │   │   ├── index.ts
    │   │   └── GlobalSearch.tsx
    │   │
    │   ├── tabs/                     # Top-level tabs (8 files)
    │   │   ├── AdminTab.tsx
    │   │   ├── ChatTab.tsx
    │   │   ├── EvalAnalysisTab.tsx
    │   │   ├── EvaluationTab.tsx
    │   │   ├── GrafanaTab.tsx
    │   │   ├── GraphTab.tsx          # NEW
    │   │   ├── InfrastructureTab.tsx
    │   │   ├── RAGTab.tsx
    │   │   └── StartTab.tsx
    │   │
    │   └── ui/                       # Primitive components (15 files)
    │       ├── index.ts
    │       ├── ApiKeyStatus.tsx
    │       ├── Button.tsx
    │       ├── CollapsibleSection.tsx
    │       ├── EmbeddingMismatchWarning.tsx
    │       ├── ErrorBoundary.tsx
    │       ├── LoadingSpinner.tsx
    │       ├── ProgressBar.tsx
    │       ├── ProgressBarWithShimmer.tsx
    │       ├── RepoSelector.tsx
    │       ├── RepoSwitcherModal.tsx
    │       ├── SkeletonLoader.tsx
    │       ├── StatusIndicator.tsx
    │       ├── SubtabErrorFallback.tsx
    │       └── TooltipIcon.tsx
    │
    ├── config/                       # App config (2 files)
    │   ├── index.ts
    │   └── routes.ts
    │
    ├── contexts/                     # React contexts (2 files)
    │   ├── index.ts
    │   └── CoreContext.tsx
    │
    ├── hooks/                        # React hooks (14 files - down from 31)
    │   ├── index.ts
    │   ├── useAPI.ts                 # API client wrapper
    │   ├── useAppInit.ts             # App initialization
    │   ├── useConfig.ts              # Config read/write
    │   ├── useDashboard.ts           # Dashboard data
    │   ├── useEmbeddingStatus.ts     # Embedding mismatch detection
    │   ├── useEvalHistory.ts         # Evaluation history
    │   ├── useFusion.ts              # NEW: Tri-brid weights
    │   ├── useGlobalSearch.ts        # Global search
    │   ├── useGraph.ts               # NEW: Graph exploration
    │   ├── useIndexing.ts            # Index operations
    │   ├── useReranker.ts            # Reranker config
    │   ├── useTheme.ts               # Dark/light mode
    │   └── useTooltips.ts            # Tooltip display
    │
    ├── services/                     # Client-side services (5 files)
    │   ├── index.ts
    │   ├── IndexingService.ts
    │   ├── RAGService.ts
    │   ├── RerankService.ts
    │   └── TerminalService.ts
    │
    ├── stores/                       # Zustand stores (6 files)
    │   ├── index.ts
    │   ├── useConfigStore.ts         # All RAG config
    │   ├── useGraphStore.ts          # NEW: Graph exploration state
    │   ├── useHealthStore.ts         # System health + Docker status
    │   ├── useRepoStore.ts           # Repository selection
    │   ├── useTooltipStore.ts        # Glossary aggregation
    │   └── useUIStore.ts             # Tab state, eval preservation
    │
    ├── styles/                       # CSS files (8 files)
    │   ├── global.css
    │   ├── inline-gui-styles.css
    │   ├── main.css
    │   ├── micro-interactions.css
    │   ├── slider-polish.css
    │   ├── storage-calculator.css
    │   ├── style.css
    │   └── tokens.css
    │
    ├── types/                        # TypeScript types (4 files)
    │   ├── index.ts
    │   ├── generated.ts              # AUTO-GENERATED from Pydantic
    │   ├── graph.ts                  # Graph-specific types
    │   └── ui.ts                     # UI-only types
    │
    └── utils/                        # Utility functions (4 files)
        ├── index.ts
        ├── errorHelpers.ts
        ├── formatters.ts
        └── uiHelpers.ts
```

---

## scripts/ - Development Scripts (12 files)

```
scripts/
├── generate_types.py                 # pydantic2ts wrapper
├── mine_triplets.py                  # Reranker triplet mining
├── train_reranker.py                 # Cross-encoder training
├── promote_reranker.py               # Promote trained model
├── seed_training_logs.py             # Seed training data
├── quick_setup.py                    # Dev environment setup
├── test_backend.py                   # Backend smoke tests
├── eval_reranker.py                  # Reranker evaluation
├── debug_ast.py                      # AST chunker debugging
├── analyze_index.py                  # Index analysis (was keywords)
├── grafana_dash.py                   # Grafana dashboard provisioning
└── create_eval_dataset.py            # (was create_langtrace_dataset)
```

---

## tests/ - Python Tests (18 files)

```
tests/
├── conftest.py                       # Pytest fixtures
├── __init__.py
│
├── unit/                             # Unit tests (8 files)
│   ├── __init__.py
│   ├── test_chunker.py
│   ├── test_config.py
│   ├── test_embedder.py
│   ├── test_fusion.py                # NEW
│   ├── test_graph_builder.py         # NEW
│   ├── test_reranker.py
│   └── test_sparse.py
│
├── integration/                      # Integration tests (5 files)
│   ├── __init__.py
│   ├── test_eval_persistence.py
│   ├── test_graph_pipeline.py        # NEW
│   ├── test_index_pipeline.py
│   └── test_search_pipeline.py
│
└── api/                              # API tests (4 files)
    ├── __init__.py
    ├── test_config_endpoints.py
    ├── test_graph_endpoints.py       # NEW
    └── test_search_endpoints.py
```

---

## spec/ - YAML Specifications (28 files)

```
spec/
├── README.md                         # Spec format documentation
│
├── backend/                          # Backend specs (14 files)
│   ├── api_chat.yaml
│   ├── api_config.yaml
│   ├── api_eval.yaml
│   ├── api_graph.yaml                # NEW
│   ├── api_health.yaml
│   ├── api_index.yaml
│   ├── api_search.yaml
│   ├── db_neo4j.yaml                 # NEW
│   ├── db_postgres.yaml              # NEW
│   ├── indexing_chunker.yaml
│   ├── indexing_embedder.yaml
│   ├── indexing_graph_builder.yaml   # NEW
│   ├── retrieval_fusion.yaml         # NEW
│   └── retrieval_rerank.yaml
│
└── frontend/                         # Frontend specs (13 files)
    ├── components_chat.yaml
    ├── components_dashboard.yaml
    ├── components_eval.yaml
    ├── components_grafana.yaml
    ├── components_graph.yaml         # NEW
    ├── components_infra.yaml
    ├── components_rag.yaml
    ├── components_ui.yaml
    ├── hooks.yaml
    ├── stores.yaml
    ├── api_client.yaml
    ├── types.yaml
    └── tabs.yaml
```

---

## File Count Summary

| Category | Files |
|----------|-------|
| Root config | 12 |
| infra/ | 5 |
| models/ | 5 |
| server/ | 52 |
| web/ | 148 |
| scripts/ | 12 |
| tests/ | 18 |
| spec/ | 28 |
| **TOTAL** | **280** |

---

## Key Naming Changes

| Old (agro) | New (tribrid-rag) | Reason |
|------------|------------------|--------|
| `cards` | `chunk_summaries` | Industry standard term |
| `golden` / `golden_questions` | `dataset` / `eval_dataset` | It's literally a dataset |
| `CardsBuilderPanel` | `ChunkSummaryPanel` | Consistent naming |
| `QuestionManager` | `DatasetManager` | Clear purpose |
| `build_cards.py` | `summarizer.py` | Descriptive |
| `golden.py` (router) | `dataset.py` | Match the model |

---

## Docker Services (4 containers)

```yaml
services:
  postgres:      # pgvector + FTS + app tables
    image: pgvector/pgvector:pg16
    ports: ["5432:5432"]
    
  neo4j:         # Knowledge graph
    image: neo4j:5-community
    ports: ["7474:7474", "7687:7687"]
    
  grafana:       # Observability (includes Prometheus)
    image: grafana/grafana-oss:10.0.0
    ports: ["3000:3000"]
    
  api:           # FastAPI backend
    build: .
    ports: ["8000:8000"]
```

**CUT containers:** qdrant, redis, loki, promtail, alertmanager (separate), editor (vscode), mcp-http, mcp-node

---

## Hooks Consolidation (31 → 14)

**KEEP (14):**
- useAPI, useAppInit, useConfig, useDashboard, useEmbeddingStatus
- useEvalHistory, useGlobalSearch, useIndexing, useReranker
- useTheme, useTooltips
- NEW: useFusion, useGraph

**DELETE (17):**
- useApplyButton → merge into useConfig
- useCards → rename, merge into useConfig
- useErrorHandler → inline
- useEventBus → Zustand handles
- useGlobalState → Zustand handles
- useKeywords → merge into useConfig
- useMCPRag → simplified, not needed
- useModels → merge into useConfig
- useModuleLoader → legacy bridge, gone
- useNavigation → React Router handles
- useNotification → inline
- useOnboarding → feature removed
- useStorageCalculator → merge into useDashboard
- useTabs → React Router handles
- useUIHelpers → inline into utils
- useVSCodeEmbed → feature removed

---

## Stores Consolidation (8 → 6)

**KEEP (5):**
- useConfigStore, useHealthStore, useRepoStore, useTooltipStore, useUIStore

**ADD (1):**
- useGraphStore (NEW)

**DELETE (2):**
- useAlertThresholdsStore → merge into useConfigStore
- useCardsStore → merge into useConfigStore
- useDockerStore → merge into useHealthStore
