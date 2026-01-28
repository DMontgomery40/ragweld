# TriBridRAG Build Progress

Track file creation progress. Check off each file as completed.

---

## Phase 1: Backend Models (server/models/)

- [ ] server/models/__init__.py
- [ ] server/models/config.py
- [ ] server/models/retrieval.py
- [ ] server/models/index.py
- [ ] server/models/graph.py
- [ ] server/models/eval.py
- [ ] server/models/chat.py
- [ ] server/models/repo.py
- [ ] server/models/cost.py
- [ ] server/models/dataset.py

---

## Phase 2: Database Clients (server/db/)

- [ ] server/db/__init__.py
- [ ] server/db/postgres.py
- [ ] server/db/neo4j.py

---

## Phase 3: Retrieval Pipeline (server/retrieval/)

- [ ] server/retrieval/__init__.py
- [ ] server/retrieval/vector.py
- [ ] server/retrieval/sparse.py
- [ ] server/retrieval/graph.py
- [ ] server/retrieval/fusion.py
- [ ] server/retrieval/rerank.py
- [ ] server/retrieval/learning.py
- [ ] server/retrieval/cache.py

---

## Phase 4: Indexing Pipeline (server/indexing/)

- [ ] server/indexing/__init__.py
- [ ] server/indexing/chunker.py
- [ ] server/indexing/embedder.py
- [ ] server/indexing/graph_builder.py
- [ ] server/indexing/summarizer.py
- [ ] server/indexing/loader.py

---

## Phase 5: API Routers (server/api/)

- [ ] server/api/__init__.py
- [ ] server/api/chat.py
- [ ] server/api/config.py
- [ ] server/api/cost.py
- [ ] server/api/docker.py
- [ ] server/api/eval.py
- [ ] server/api/dataset.py
- [ ] server/api/graph.py
- [ ] server/api/health.py
- [ ] server/api/index.py
- [ ] server/api/reranker.py
- [ ] server/api/repos.py
- [ ] server/api/search.py
- [ ] server/main.py
- [ ] server/__init__.py
- [ ] server/config.py

---

## Phase 5.5: Services (server/services/)

- [ ] server/services/__init__.py
- [ ] server/services/config_store.py
- [ ] server/services/dataset.py
- [ ] server/services/indexing.py
- [ ] server/services/rag.py
- [ ] server/services/traces.py

---

## Phase 5.6: Observability (server/observability/)

- [ ] server/observability/__init__.py
- [ ] server/observability/metrics.py
- [ ] server/observability/tracing.py
- [ ] server/observability/alerts.py

---

## Phase 6: TypeScript Types (auto-generated)

- [ ] web/src/types/index.ts
- [ ] web/src/types/generated.ts (run pydantic2ts)
- [ ] web/src/types/graph.ts
- [ ] web/src/types/ui.ts

---

## Phase 7: Zustand Stores (web/src/stores/)

- [ ] web/src/stores/index.ts
- [ ] web/src/stores/useConfigStore.ts
- [ ] web/src/stores/useGraphStore.ts
- [ ] web/src/stores/useHealthStore.ts
- [ ] web/src/stores/useRepoStore.ts
- [ ] web/src/stores/useTooltipStore.ts
- [ ] web/src/stores/useUIStore.ts

---

## Phase 7.5: React Hooks (web/src/hooks/)

- [ ] web/src/hooks/index.ts
- [ ] web/src/hooks/useAPI.ts
- [ ] web/src/hooks/useAppInit.ts
- [ ] web/src/hooks/useConfig.ts
- [ ] web/src/hooks/useDashboard.ts
- [ ] web/src/hooks/useEmbeddingStatus.ts
- [ ] web/src/hooks/useEvalHistory.ts
- [ ] web/src/hooks/useFusion.ts
- [ ] web/src/hooks/useGlobalSearch.ts
- [ ] web/src/hooks/useGraph.ts
- [ ] web/src/hooks/useIndexing.ts
- [ ] web/src/hooks/useReranker.ts
- [ ] web/src/hooks/useTheme.ts
- [ ] web/src/hooks/useTooltips.ts

---

## Phase 7.6: API Client (web/src/api/)

- [ ] web/src/api/index.ts
- [ ] web/src/api/client.ts
- [ ] web/src/api/chat.ts
- [ ] web/src/api/config.ts
- [ ] web/src/api/docker.ts
- [ ] web/src/api/eval.ts
- [ ] web/src/api/graph.ts
- [ ] web/src/api/health.ts
- [ ] web/src/api/search.ts

---

## Phase 8: UI Components

### UI Primitives (web/src/components/ui/)

- [ ] web/src/components/ui/index.ts
- [ ] web/src/components/ui/ApiKeyStatus.tsx
- [ ] web/src/components/ui/Button.tsx
- [ ] web/src/components/ui/CollapsibleSection.tsx
- [ ] web/src/components/ui/EmbeddingMismatchWarning.tsx
- [ ] web/src/components/ui/ErrorBoundary.tsx
- [ ] web/src/components/ui/LoadingSpinner.tsx
- [ ] web/src/components/ui/ProgressBar.tsx
- [ ] web/src/components/ui/ProgressBarWithShimmer.tsx
- [ ] web/src/components/ui/RepoSelector.tsx
- [ ] web/src/components/ui/RepoSwitcherModal.tsx
- [ ] web/src/components/ui/SkeletonLoader.tsx
- [ ] web/src/components/ui/StatusIndicator.tsx
- [ ] web/src/components/ui/SubtabErrorFallback.tsx
- [ ] web/src/components/ui/TooltipIcon.tsx

### Navigation (web/src/components/Navigation/)

- [ ] web/src/components/Navigation/index.ts
- [ ] web/src/components/Navigation/TabBar.tsx
- [ ] web/src/components/Navigation/TabRouter.tsx

### Admin (web/src/components/Admin/)

- [ ] web/src/components/Admin/index.ts
- [ ] web/src/components/Admin/AdminSubtabs.tsx
- [ ] web/src/components/Admin/GeneralSubtab.tsx

### Analytics (web/src/components/Analytics/)

- [ ] web/src/components/Analytics/index.ts
- [ ] web/src/components/Analytics/Cost.tsx
- [ ] web/src/components/Analytics/Performance.tsx
- [ ] web/src/components/Analytics/Tracing.tsx
- [ ] web/src/components/Analytics/Usage.tsx

### Chat (web/src/components/Chat/)

- [ ] web/src/components/Chat/index.ts
- [ ] web/src/components/Chat/ChatInterface.tsx
- [ ] web/src/components/Chat/ChatSettings.tsx
- [ ] web/src/components/Chat/ChatSubtabs.tsx
- [ ] web/src/components/Chat/MessageBubble.tsx

### Dashboard (web/src/components/Dashboard/)

- [ ] web/src/components/Dashboard/index.ts
- [ ] web/src/components/Dashboard/DashboardSubtabs.tsx
- [ ] web/src/components/Dashboard/EmbeddingConfigPanel.tsx
- [ ] web/src/components/Dashboard/GlossarySubtab.tsx
- [ ] web/src/components/Dashboard/HelpGlossary.tsx
- [ ] web/src/components/Dashboard/HelpGlossary.css
- [ ] web/src/components/Dashboard/HelpSubtab.tsx
- [ ] web/src/components/Dashboard/IndexDisplayPanels.tsx
- [ ] web/src/components/Dashboard/IndexingCostsPanel.tsx
- [ ] web/src/components/Dashboard/MonitoringSubtab.tsx
- [ ] web/src/components/Dashboard/QuickActions.tsx
- [ ] web/src/components/Dashboard/StorageSubtab.tsx
- [ ] web/src/components/Dashboard/SystemStatus.tsx
- [ ] web/src/components/Dashboard/SystemStatusSubtab.tsx

### Evaluation (web/src/components/Evaluation/)

- [ ] web/src/components/Evaluation/index.ts
- [ ] web/src/components/Evaluation/DatasetManager.tsx
- [ ] web/src/components/Evaluation/EvalDrillDown.tsx
- [ ] web/src/components/Evaluation/EvaluationRunner.tsx
- [ ] web/src/components/Evaluation/FeedbackPanel.tsx
- [ ] web/src/components/Evaluation/HistoryViewer.tsx
- [ ] web/src/components/Evaluation/TraceViewer.tsx

### Grafana (web/src/components/Grafana/)

- [ ] web/src/components/Grafana/index.ts
- [ ] web/src/components/Grafana/GrafanaConfig.tsx
- [ ] web/src/components/Grafana/GrafanaDashboard.tsx
- [ ] web/src/components/Grafana/GrafanaSubtabs.tsx

### Graph (web/src/components/Graph/)

- [ ] web/src/components/Graph/index.ts
- [ ] web/src/components/Graph/GraphExplorer.tsx
- [ ] web/src/components/Graph/EntityDetail.tsx
- [ ] web/src/components/Graph/CommunityView.tsx
- [ ] web/src/components/Graph/GraphConfigPanel.tsx

### Infrastructure (web/src/components/Infrastructure/)

- [ ] web/src/components/Infrastructure/index.ts
- [ ] web/src/components/Infrastructure/DockerSubtab.tsx
- [ ] web/src/components/Infrastructure/InfrastructureSubtabs.tsx
- [ ] web/src/components/Infrastructure/PathsSubtab.tsx
- [ ] web/src/components/Infrastructure/ServicesSubtab.tsx

### LiveTerminal (web/src/components/LiveTerminal/)

- [ ] web/src/components/LiveTerminal/index.ts
- [ ] web/src/components/LiveTerminal/LiveTerminal.tsx
- [ ] web/src/components/LiveTerminal/LiveTerminal.css

### RAG (web/src/components/RAG/)

- [ ] web/src/components/RAG/index.ts
- [ ] web/src/components/RAG/ChunkSummaryPanel.tsx
- [ ] web/src/components/RAG/ChunkSummaryViewer.tsx
- [ ] web/src/components/RAG/DataQualitySubtab.tsx
- [ ] web/src/components/RAG/EvaluateSubtab.tsx
- [ ] web/src/components/RAG/FusionWeightsPanel.tsx
- [ ] web/src/components/RAG/IndexingSubtab.tsx
- [ ] web/src/components/RAG/IndexStatsPanel.tsx
- [ ] web/src/components/RAG/LearningRerankerSubtab.tsx
- [ ] web/src/components/RAG/ModelPicker.tsx
- [ ] web/src/components/RAG/RAGSubtabs.tsx
- [ ] web/src/components/RAG/RerankerConfigSubtab.tsx
- [ ] web/src/components/RAG/RetrievalSubtab.tsx

### Search (web/src/components/Search/)

- [ ] web/src/components/Search/index.ts
- [ ] web/src/components/Search/GlobalSearch.tsx

### Tabs (web/src/components/tabs/)

- [ ] web/src/components/tabs/AdminTab.tsx
- [ ] web/src/components/tabs/ChatTab.tsx
- [ ] web/src/components/tabs/EvalAnalysisTab.tsx
- [ ] web/src/components/tabs/EvaluationTab.tsx
- [ ] web/src/components/tabs/GrafanaTab.tsx
- [ ] web/src/components/tabs/GraphTab.tsx
- [ ] web/src/components/tabs/InfrastructureTab.tsx
- [ ] web/src/components/tabs/RAGTab.tsx
- [ ] web/src/components/tabs/StartTab.tsx

---

## Phase 9: Final Assembly

### App Entry

- [ ] web/src/main.tsx
- [ ] web/src/App.tsx

### Config

- [ ] web/src/config/index.ts
- [ ] web/src/config/routes.ts

### Contexts

- [ ] web/src/contexts/index.ts
- [ ] web/src/contexts/CoreContext.tsx

### Services

- [ ] web/src/services/index.ts
- [ ] web/src/services/IndexingService.ts
- [ ] web/src/services/RAGService.ts
- [ ] web/src/services/RerankService.ts
- [ ] web/src/services/TerminalService.ts

### Utils

- [ ] web/src/utils/index.ts
- [ ] web/src/utils/errorHelpers.ts
- [ ] web/src/utils/formatters.ts
- [ ] web/src/utils/uiHelpers.ts

### Styles (copy from agro-rag-engine)

- [ ] web/src/styles/global.css
- [ ] web/src/styles/inline-gui-styles.css
- [ ] web/src/styles/main.css
- [ ] web/src/styles/micro-interactions.css
- [ ] web/src/styles/slider-polish.css
- [ ] web/src/styles/storage-calculator.css
- [ ] web/src/styles/style.css
- [ ] web/src/styles/tokens.css

### Web Config Files

- [ ] web/index.html
- [ ] web/package.json
- [ ] web/postcss.config.js
- [ ] web/tailwind.config.ts
- [ ] web/tsconfig.json
- [ ] web/vite.config.ts

---

## Infrastructure & Root Files

### Root Config

- [ ] .env.example
- [ ] .gitignore
- [ ] docker-compose.yml
- [ ] Dockerfile
- [ ] pyproject.toml
- [ ] README.md
- [ ] tribrid_config.json

### .claude/

- [x] .claude/hooks.json (EXISTS)
- [x] .claude/settings.json (EXISTS)

### .github/

- [ ] .github/workflows/ci.yml

### infra/

- [ ] infra/alertmanager.yml
- [ ] infra/docker-compose.dev.yml
- [ ] infra/prometheus.yml
- [ ] infra/repos.docker.json
- [ ] infra/grafana/provisioning/dashboards/rag-metrics.json

### models/

- [ ] models/cross-encoder-tribrid/config.json
- [ ] models/cross-encoder-tribrid/special_tokens_map.json
- [ ] models/cross-encoder-tribrid/tokenizer_config.json
- [ ] models/cross-encoder-tribrid/tokenizer.json

---

## Scripts (scripts/)

- [ ] scripts/generate_types.py
- [ ] scripts/mine_triplets.py
- [ ] scripts/train_reranker.py
- [ ] scripts/promote_reranker.py
- [ ] scripts/seed_training_logs.py
- [ ] scripts/quick_setup.py
- [ ] scripts/test_backend.py
- [ ] scripts/eval_reranker.py
- [ ] scripts/debug_ast.py
- [ ] scripts/analyze_index.py
- [ ] scripts/grafana_dash.py
- [ ] scripts/create_eval_dataset.py

---

## Tests (tests/)

### Root

- [ ] tests/__init__.py
- [ ] tests/conftest.py

### Unit Tests

- [ ] tests/unit/__init__.py
- [ ] tests/unit/test_chunker.py
- [ ] tests/unit/test_config.py
- [ ] tests/unit/test_embedder.py
- [ ] tests/unit/test_fusion.py
- [ ] tests/unit/test_graph_builder.py
- [ ] tests/unit/test_reranker.py
- [ ] tests/unit/test_sparse.py

### Integration Tests

- [ ] tests/integration/__init__.py
- [ ] tests/integration/test_eval_persistence.py
- [ ] tests/integration/test_graph_pipeline.py
- [ ] tests/integration/test_index_pipeline.py
- [ ] tests/integration/test_search_pipeline.py

### API Tests

- [ ] tests/api/__init__.py
- [ ] tests/api/test_config_endpoints.py
- [ ] tests/api/test_graph_endpoints.py
- [ ] tests/api/test_search_endpoints.py

---

## Spec Files (spec/)

- [ ] spec/README.md

### Backend Specs

- [ ] spec/backend/api_chat.yaml
- [ ] spec/backend/api_config.yaml
- [ ] spec/backend/api_eval.yaml
- [ ] spec/backend/api_graph.yaml
- [ ] spec/backend/api_health.yaml
- [ ] spec/backend/api_index.yaml
- [ ] spec/backend/api_search.yaml
- [ ] spec/backend/db_neo4j.yaml
- [ ] spec/backend/db_postgres.yaml
- [ ] spec/backend/indexing_chunker.yaml
- [ ] spec/backend/indexing_embedder.yaml
- [ ] spec/backend/indexing_graph_builder.yaml
- [ ] spec/backend/retrieval_fusion.yaml
- [ ] spec/backend/retrieval_rerank.yaml

### Frontend Specs

- [ ] spec/frontend/components_chat.yaml
- [ ] spec/frontend/components_dashboard.yaml
- [ ] spec/frontend/components_eval.yaml
- [ ] spec/frontend/components_grafana.yaml
- [ ] spec/frontend/components_graph.yaml
- [ ] spec/frontend/components_infra.yaml
- [ ] spec/frontend/components_rag.yaml
- [ ] spec/frontend/components_ui.yaml
- [ ] spec/frontend/hooks.yaml
- [ ] spec/frontend/stores.yaml
- [ ] spec/frontend/api_client.yaml
- [ ] spec/frontend/types.yaml
- [ ] spec/frontend/tabs.yaml

---

## Progress Summary

| Phase | Files | Done |
|-------|-------|------|
| 1. Models | 10 | 0 |
| 2. DB | 3 | 0 |
| 3. Retrieval | 8 | 0 |
| 4. Indexing | 6 | 0 |
| 5. API | 16 | 0 |
| 5.5 Services | 6 | 0 |
| 5.6 Observability | 4 | 0 |
| 6. Types | 4 | 0 |
| 7. Stores | 7 | 0 |
| 7.5 Hooks | 14 | 0 |
| 7.6 API Client | 9 | 0 |
| 8. Components | ~89 | 0 |
| 9. Final | ~30 | 0 |
| Infra | ~15 | 2 |
| Scripts | 12 | 0 |
| Tests | 18 | 0 |
| Specs | 28 | 0 |
| **TOTAL** | **~280** | **2** |

---

## Notes

- Check off files as `[x]` when complete
- If blocked, document here:
  - Blocker: 
  - Attempted: 
  - Resolution:
