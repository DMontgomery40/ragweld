# Tooltip wiring source audit — 2026-10-01

Base: `2448941b`. Wiring owner: `/root/astra_coordinator/wiring`. Integration owner: `/root/astra_coordinator`.

## Scope and counting method

Inspected all 125 TSX files under `web/src/components`, including RetrievalSubtab after the final tooltip-only ownership grant. Counts are source templates, not rendered instances: dynamic mappings can render multiple controls; dormant components remain included. Removed block comments before counting. Control tags: input, select, textarea, NumberField, ModelPicker, ChatModelPicker, SyntheticModelPicker. Label help count means TooltipIcon appears inside the label template; group help intentionally appears outside repeated option labels.

The coordinator also inspected the four TSX files outside components (`App.tsx`, `main.tsx`, `pages/Dashboard.tsx`, `pages/GrafanaEmbed.tsx`). Only `App.tsx` adds a form control: the Auto/Light/Dark theme selector, already named by `title="Theme Mode"`; no technical parameter explanation is missing there. Thus the source sweep covers all 129 TSX files and 477 control templates overall. The table below retains the reproducible 125-component-file denominator.

| Metric | Before | After |
|---|---:|---:|
| Control templates | 476 | 476 |
| Label templates | 423 | 423 |
| Label templates without an internal TooltipIcon | 134 | 6 |
| TooltipIcon templates | 313 | 484 |

## Remaining bare label templates (exact)

| File | Line | Reason |
|---|---:|---|
| `web/src/components/Admin/configControlPlane.tsx` | 385 | Shared Admin field renderer is owned by the integration coordinator and has a separate 460-field mapping/content audit. |
| `web/src/components/Benchmark/BenchmarkTab.tsx` | 370 | Repeated model option; Models group heading has BENCHMARK_MODEL_SELECTION help. |
| `web/src/components/Chat/SourceDropdown.tsx` | 323 | Repeated corpus option; Corpora group heading has CHAT_CORPUS_SOURCE help. |
| `web/src/components/RAG/GraphSubtab.tsx` | 1401 | Repeated entity/relation option; group heading has GRAPH_VIEWER_ENTITY_TYPES/GRAPH_VIEWER_RELATION_TYPES help. |
| `web/src/components/RAG/GraphSubtab.tsx` | 1427 | Repeated entity/relation option; group heading has GRAPH_VIEWER_ENTITY_TYPES/GRAPH_VIEWER_RELATION_TYPES help. |
| `web/src/components/ui/confirmDialog.tsx` | 130 | Typed confirmation uses the action-specific required text and details; mechanical safeguard, not a configurable setting. |

## Non-label controls and existing contextual help

The following controls do not need an extra glossary icon: obvious text searches (Advanced Explorer, Glossary, Dock picker, Global Search, chunk summaries, Studio event/log search); chat/onboarding/MCP question composers with task-specific instructions; hidden chat image file input; System Prompts textarea with its existing per-prompt description. Generic NumberField/ModelPicker helpers inherit help from their callers. RepoSelector defaults to REPO help; RepoSelectorCompact is labeled by DataQualitySubtab. Expected location start/end inputs share the EVAL_EXPECTED_LOCATION group explanation. RepositoryConfig exclude-path entry shares EXCLUDE_PATHS help. Admin field renderer inputs are in the coordinator-owned registry audit. Action buttons retain existing meaningful title/status instructions.

The extra semantic audit replaced all eight inert data-tooltip attributes with visible glossary help: IndexDisplayPanels metadata, EmbeddingMismatchWarning InlineWarning/FullWarning, EvalAnalysisTab three tabs and Run Eval (sibling icons outside buttons), and EvalDrillDown embedding badge. Storage planner native ? titles were replaced by glossary help; the unsupported fixed 5% product-quantization accuracy claim was removed.

The 32 static owned files add 170 TooltipIcon templates, including the final seven RetrievalSubtab label insertions on HEAD `49da64e3`. The whole-tree after count also includes one concurrently added coordinator-owned Admin field-renderer template.

## Changed component files and new wired keys

Each listed component symbol was impact-checked on LXC100 before its edit. Nested SyntheticModelPicker, renderRunSettings, LocationEditor, InlineWarning and FullWarning were checked separately. No local build/runtime/tests, source upload, restart, deployment, or commit was performed by the wiring owner.

- `web/src/components/Admin/ConfigExplorerSubtab.tsx`: `ADMIN_CONFIG_IMPACT_FILTER`, `ADMIN_CONFIG_INTEGRATION_FILTER`, `ADMIN_CONFIG_SCOPE_FILTER`, `ADMIN_CONFIG_SURFACE_FILTER`.
- `web/src/components/Admin/ConfigRawSubtab.tsx`: `ADMIN_CONFIG_RAW_SECTION`.
- `web/src/components/AgentTraining/RunDiff.tsx`: `TRAINING_BASELINE_RUN`, `TRAINING_CURRENT_RUN`.
- `web/src/components/AgentTraining/TrainingStudio.tsx`: `RAGWELD_AGENT_FLYTE_ADMIN_BASE_URL`, `RAGWELD_AGENT_FLYTE_CALLBACK_BASE_URL`, `RAGWELD_AGENT_FLYTE_CONSOLE_BASE_URL`, `RAGWELD_AGENT_FLYTE_DOMAIN`, `RAGWELD_AGENT_FLYTE_LAUNCHPLAN`, `RAGWELD_AGENT_FLYTE_PROJECT`, `RAGWELD_AGENT_MLFLOW_CONSOLE_BASE_URL`, `RAGWELD_AGENT_MLFLOW_EXPERIMENT_NAME`, `RAGWELD_AGENT_MLFLOW_TRACKING_URL`, `RAGWELD_AGENT_TRACKING_BACKEND`, `RAGWELD_AGENT_UNSLOTH_IMAGE`, `RAGWELD_AGENT_WORKFLOW_BACKEND`, `TRAINING_EXECUTION`, `TRAINING_RECIPE`.
- `web/src/components/Benchmark/BenchmarkTab.tsx`: `BENCHMARK_MODEL_SELECTION`, `BENCHMARK_PROMPT`.
- `web/src/components/Chat/ChatInterface.tsx`: `CHAT_MAX_TOKENS`, `CHAT_MODEL_OVERRIDE`, `CHAT_TEMPERATURE`, `CHAT_TOP_K_OVERRIDE`.
- `web/src/components/Chat/ProviderSetup.tsx`: `LITELLM_BASE_URL`, `LITELLM_DEFAULT_MODEL`, `LITELLM_ENABLED`, `VLLM_BASE_URL`, `VLLM_DEFAULT_MODEL`, `VLLM_ENABLED`.
- `web/src/components/Chat/SourceDropdown.tsx`: `CHAT_CORPUS_SOURCE`, `CHAT_RECALL_SOURCE`, `CHAT_RETRIEVAL_LEGS`, `CHAT_WEB_ENABLED`.
- `web/src/components/Dashboard/IndexDisplayPanels.tsx`: `DASHBOARD_INDEX_PANEL`.
- `web/src/components/Dashboard/StorageCalculatorSuite.tsx`: `STORAGE_PLANNER_CHUNK_BYTES`, `STORAGE_PLANNER_COMPRESSION_SCENARIOS`, `STORAGE_PLANNER_CORPUS_SIZE`, `STORAGE_PLANNER_DIMENSIONS`, `STORAGE_PLANNER_GRAPH_NODES`, `STORAGE_PLANNER_GRAPH_RELATIONSHIPS`, `STORAGE_PLANNER_HNSW_MULTIPLIER`, `STORAGE_PLANNER_HYDRATION`, `STORAGE_PLANNER_NODE_BYTES`, `STORAGE_PLANNER_PRECISION`, `STORAGE_PLANNER_RELATIONSHIP_BYTES`, `STORAGE_PLANNER_REPLICATION`, `STORAGE_PLANNER_SPARSE_PERCENT`, `STORAGE_PLANNER_SUMMARIES_PERCENT`, `STORAGE_PLANNER_TARGET_SIZE`.
- `web/src/components/Evaluation/EvalDrillDown.tsx`: `EMBEDDING_MISMATCH`.
- `web/src/components/Evaluation/PromptfooRegressionPanel.tsx`: `PROMPTFOO_SAMPLE_SIZE`.
- `web/src/components/Evaluation/QuestionManager.tsx`: `EVAL_EXPECTED_ANSWER`, `EVAL_EXPECTED_LOCATION`, `EVAL_EXPECTED_PATHS`, `EVAL_QUESTION`.
- `web/src/components/Evaluation/TraceViewer.tsx`: `REPO`.
- `web/src/components/Grafana/GrafanaConfig.tsx`: `ALERTMANAGER_BASE_URL`, `FARO_BASE_URL`, `GRAFANA_BASE_URL`, `GRAFANA_DASHBOARD_PRESET`, `GRAFANA_DASHBOARD_SLUG`, `GRAFANA_DASHBOARD_UID`, `GRAFANA_EMBED_ENABLED`, `GRAFANA_KIOSK`, `GRAFANA_ORG_ID`, `GRAFANA_REFRESH`, `MIMIR_BASE_URL`, `OPENCOST_BASE_URL`, `PROMETHEUS_BASE_URL`, `PYROSCOPE_BASE_URL`.
- `web/src/components/Grafana/GrafanaDashboard.tsx`: `GRAFANA_DASHBOARD_PRESET`, `GRAFANA_TIME_RANGE`.
- `web/src/components/Infrastructure/PathsSubtab.tsx`: `CORPUS_DESCRIPTION`, `CORPUS_NAME`, `REPO_PATH`, `neo4j_password`.
- `web/src/components/RAG/DataQualitySubtab.tsx`: `REPO`.
- `web/src/components/RAG/GraphSubtab.tsx`: `GRAPH_VIEWER_ENTITY_TYPES`, `GRAPH_VIEWER_MAX_HOPS`, `GRAPH_VIEWER_MAX_NODES`, `GRAPH_VIEWER_RELATION_TYPES`, `REPO`.
- `web/src/components/RAG/IndexingSubtab.tsx`: `BUILD_CODE_GRAPH`, `FORCE_REINDEX`, `GRAPH_INDEXING_ENABLED`, `INDEX_GRAPH_ENTITY_SPARSE_OVERRIDE_REASON`, `LEXICAL_GRAPH_ENABLED`, `PARQUET_EXTRACT_MAX_CELL_CHARS`, `PARQUET_EXTRACT_MAX_CHARS`, `SEMANTIC_KG_LLM_MODEL`, `SEMANTIC_KG_LLM_TIMEOUT_S`, `SEMANTIC_KG_MAX_CHUNKS`, `SEMANTIC_KG_REASONING_EFFORT`, `AST_CONTAINS_WEIGHT`, `AST_INHERITS_WEIGHT`, `AST_IMPORTS_WEIGHT`, `AST_CALLS_WEIGHT`.
- `web/src/components/RAG/RepositoryConfig.tsx`: `EXCLUDE_PATHS`, `PATH_BOOSTS`, `REPO_KEYWORDS`, `REPO_LAYER_BONUSES`, `REPO_PATH`.
- `web/src/components/RAG/SyntheticLabSubtab.tsx`: `GROUNDED_QA`, `SYNTHETIC_CONFIG_PATCH`, `SYNTHETIC_GENERATOR_MODEL`, `SYNTHETIC_GROUNDING`, `SYNTHETIC_MAX_PAIRS`, `SYNTHETIC_MAX_SOURCE_CHUNKS`, `SYNTHETIC_PAIRS_PER_SOURCE`, `SYNTHETIC_PUBLISH`, `SYNTHETIC_QUALITY_GATE`, `SYNTHETIC_RECIPE`.
- `web/src/components/RerankerTraining/GradientDescentViz.tsx`: `LEARNING_RERANKER_GRADIENT_LIVE`.
- `web/src/components/RerankerTraining/NeuralVisualizerCore.tsx`: `LEARNING_RERANKER_VISUALIZER_ZOOM`.
- `web/src/components/RerankerTraining/RunDiff.tsx`: `TRAINING_BASELINE_RUN`, `TRAINING_CURRENT_RUN`.
- `web/src/components/RerankerTraining/TrainingStudio.tsx`: `RERANKER_PROBE_DOCUMENT`, `RERANKER_PROBE_QUERY`, `RERANKER_PROBE_RAW_LOGITS`, `TRAINING_EXECUTION`, `TRAINING_RECIPE`.
- `web/src/components/tabs/ChatTab.tsx`: `CHAT_INSPECTOR_FILTER`.
- `web/src/components/tabs/EvalAnalysisTab.tsx`: `EVAL_ANALYSIS_SUBTAB`, `EVAL_COMPARE_RUN`, `EVAL_FINAL_K`, `EVAL_MULTI`, `EVAL_MULTI_M`, `EVAL_PRIMARY_RUN`, `EVAL_SAMPLE_SIZE`, `FUSION_GRAPH_WEIGHT`, `FUSION_METHOD`, `FUSION_RRF_K`, `FUSION_SPARSE_WEIGHT`, `FUSION_VECTOR_WEIGHT`, `GRAPH_SEARCH_ENABLED`, `GRAPH_SEARCH_TOP_K`, `REPO`, `RUN_EVAL_ANALYSIS`, `SPARSE_SEARCH_ENABLED`, `SPARSE_SEARCH_TOP_K`, `SYSTEM_PROMPTS_SUBTAB`, `TRACE_VIEWER_SUBTAB`, `VECTOR_SEARCH_ENABLED`, `VECTOR_SEARCH_TOP_K`.
- `web/src/components/tabs/StartTab.tsx`: `CORPUS_NAME`, `REPO`, `REPO_PATH`.
- `web/src/components/ui/CorpusRegistry.tsx`: `CORPUS_DESCRIPTION`, `CORPUS_NAME`, `REPO_PATH`.
- `web/src/components/ui/EmbeddingMismatchWarning.tsx`: `EMBEDDING_MISMATCH`.

- `web/src/components/RAG/RetrievalSubtab.tsx`: `GEN_MODEL`, `GEN_MODEL_HTTP`, `GEN_MODEL_MCP`, `GEN_MODEL_CLI`, `ENRICH_MODEL`, `LITELLM_API_KEY`, `OTEL_EXPORT_ENABLED`. Final batch modifies only labels; all model selection, runtime routing, config setters, and generation logic remain byte-for-byte unchanged.

## Impact and verification evidence

GrafanaDashboard returned CRITICAL (125 impacted symbols, one direct caller, 183 affected processes, 20 modules). A user-facing CRITICAL warning was sent before the two label mutations. The impact output is preserved at `/tmp/ragweld-wiring-impact-GrafanaDashboard.txt`; the CLI itself truncates very large output, so its header/summary are authoritative evidence but the saved body is not valid complete JSON. Original checks for other TSX symbols returned UNKNOWN/target not found in the then-advertised current index; these are not reported as LOW. A subsequent isolated fresh index resolved ConfigExplorerSubtab and ConfigRawSubtab as LOW (one direct AdminTab caller, one affected process/module) before the final five accessible select names were added. Fresh evidence is preserved at `/tmp/ragweld-wiring-impact-ConfigExplorerSubtab-fresh.txt` and `/tmp/ragweld-wiring-impact-ConfigRawSubtab-fresh.txt`. Direct UI parents were confirmed by source imports (GrafanaTab, RAGTab, LearningAgentSubtab and their other component callers).

Final RetrievalSubtab impact on the isolated validation checkout at HEAD `49da64e3` returned LOW: one direct RAGTab caller, one affected process and module. Evidence is preserved at `/tmp/ragweld-wiring-impact-RetrievalSubtab-final.txt`. No remote source upload was performed by this worker.

`git diff --check` passed after each stable batch, including the final retrieval batch. Remote parser/typecheck/build/glossary validation and authenticated UI acceptance remain with the integration owner; source inspection does not establish runtime success.

## Complete per-file template inventory

| File | Controls | Labels | Bare labels before → after | Icons before → after |
|---|---:|---:|---:|---:|
| `web/src/components/Admin/AdminSubtabs.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Admin/ConfigBasicsSubtab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Admin/ConfigExplorerSubtab.tsx` | 5 | 0 | 0 → 0 | 0 → 4 |
| `web/src/components/Admin/ConfigRawSubtab.tsx` | 1 | 0 | 0 → 0 | 0 → 1 |
| `web/src/components/Admin/DependenciesSubtab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Admin/configControlPlane.tsx` | 4 | 1 | 1 → 1 | 0 → 1 |
| `web/src/components/AgentTraining/ControlPlaneStatus.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/AgentTraining/RunDiff.tsx` | 2 | 2 | 2 → 0 | 0 → 2 |
| `web/src/components/AgentTraining/RunOverview.tsx` | 0 | 0 | 0 → 0 | 1 → 1 |
| `web/src/components/AgentTraining/TrainingStudio.tsx` | 48 | 47 | 14 → 0 | 33 → 47 |
| `web/src/components/Benchmark/BenchmarkTab.tsx` | 3 | 1 | 1 → 1 | 0 → 2 |
| `web/src/components/Benchmark/CostAttribution.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Benchmark/PipelineProfile.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Benchmark/ResultsTable.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Benchmark/SplitScreen.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Chat/ChatHistorySidebar.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Chat/ChatInterface.tsx` | 6 | 3 | 3 → 0 | 0 → 4 |
| `web/src/components/Chat/ChatSettings.tsx` | 27 | 27 | 0 → 0 | 27 → 27 |
| `web/src/components/Chat/ChatSubtabs.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Chat/ModelPicker.tsx` | 1 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Chat/ProviderSetup.tsx` | 6 | 6 | 6 → 0 | 0 → 6 |
| `web/src/components/Chat/SourceDropdown.tsx` | 7 | 6 | 6 → 1 | 1 → 7 |
| `web/src/components/Chat/SourceList.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Chat/StatusBar.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Dashboard/DashboardSubtabs.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Dashboard/GlossarySubtab.tsx` | 1 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Dashboard/HelpSubtab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Dashboard/IndexDisplayPanels.tsx` | 0 | 0 | 0 → 0 | 0 → 1 |
| `web/src/components/Dashboard/LiveTerminalPanel.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Dashboard/MonitoringSubtab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Dashboard/QuickActionButton.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Dashboard/QuickActions.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Dashboard/StorageCalculatorSuite.tsx` | 22 | 17 | 17 → 0 | 0 → 18 |
| `web/src/components/Dashboard/StorageSubtab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Dashboard/SystemStatusSubtab.tsx` | 0 | 0 | 0 → 0 | 4 → 4 |
| `web/src/components/Dock/DockPanel.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Dock/DockPickerModal.tsx` | 1 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Dock/DockView.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Dock/EmbeddedDockNavigation.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Documents/DocumentViewer.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Documents/FigureBadge.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Documents/MarkdownView.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Documents/PdfPageView.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Documents/RegionOverlay.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Documents/TextView.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Evaluation/EvalDatasetSubtab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Evaluation/EvalDrillDown.tsx` | 0 | 0 | 0 → 0 | 0 → 1 |
| `web/src/components/Evaluation/PromptfooRegressionPanel.tsx` | 1 | 1 | 1 → 0 | 0 → 1 |
| `web/src/components/Evaluation/QuestionManager.tsx` | 9 | 0 | 0 → 0 | 0 → 7 |
| `web/src/components/Evaluation/SystemPromptsSubtab.tsx` | 1 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Evaluation/TraceViewer.tsx` | 1 | 0 | 0 → 0 | 0 → 1 |
| `web/src/components/Grafana/GrafanaConfig.tsx` | 14 | 14 | 14 → 0 | 0 → 14 |
| `web/src/components/Grafana/GrafanaDashboard.tsx` | 2 | 2 | 2 → 0 | 0 → 2 |
| `web/src/components/Grafana/GrafanaSubtabs.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Infrastructure/DockerSubtab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Infrastructure/InfrastructureSubtabs.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Infrastructure/MCPSubtab.tsx` | 1 | 0 | 0 → 0 | 1 → 1 |
| `web/src/components/Infrastructure/MonitoringSubtab.tsx` | 0 | 0 | 0 → 0 | 1 → 1 |
| `web/src/components/Infrastructure/PathsSubtab.tsx` | 10 | 11 | 4 → 0 | 7 → 11 |
| `web/src/components/Infrastructure/ServicesSubtab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/KeywordManager.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/LiveTerminal/LiveTerminal.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Navigation/Breadcrumbs.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Navigation/HealthPill.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Navigation/NotFound.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Navigation/RouteGuards.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Navigation/TabBar.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Navigation/TabRouter.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Observability/IncidentsBoard.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Observability/OperatorDeck.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Observability/TraceExternalLinks.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/RAG/DataQualitySubtab.tsx` | 11 | 11 | 1 → 0 | 10 → 11 |
| `web/src/components/RAG/GraphEntitySources.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/RAG/GraphSchemaReview.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/RAG/GraphSubtab.tsx` | 6 | 3 | 3 → 2 | 0 → 5 |
| `web/src/components/RAG/IndexRunCosts.tsx` | 0 | 0 | 0 → 0 | 1 → 1 |
| `web/src/components/RAG/IndexingSubtab.tsx` | 76 | 74 | 12 → 0 | 69 → 83 |
| `web/src/components/RAG/IntentMatrixEditor.tsx` | 0 | 1 | 0 → 0 | 1 → 1 |
| `web/src/components/RAG/LearningAgentSubtab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/RAG/LearningRankerSubtab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/RAG/ModelAssignments.tsx` | 0 | 0 | 0 → 0 | 1 → 1 |
| `web/src/components/RAG/ModelPicker.tsx` | 2 | 3 | 0 → 0 | 3 → 3 |
| `web/src/components/RAG/RAGSubtabs.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/RAG/RepoSelector.tsx` | 2 | 1 | 0 → 0 | 1 → 1 |
| `web/src/components/RAG/RepositoryConfig.tsx` | 5 | 5 | 5 → 0 | 0 → 5 |
| `web/src/components/RAG/RerankerConfigSubtab.tsx` | 12 | 12 | 0 → 0 | 13 → 13 |
| `web/src/components/RAG/RetrievalSubtab.tsx` | 97 | 99 | 7 → 0 | 92 → 99 |
| `web/src/components/RAG/SyntheticCallout.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/RAG/SyntheticLabSubtab.tsx` | 9 | 9 | 6 → 0 | 3 → 13 |
| `web/src/components/RAG/indexEstimateConsent.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/RerankerTraining/GradientDescentViz.tsx` | 2 | 1 | 1 → 0 | 0 → 1 |
| `web/src/components/RerankerTraining/NeuralVisualizer.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/RerankerTraining/NeuralVisualizerCanvas2D.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/RerankerTraining/NeuralVisualizerCore.tsx` | 3 | 2 | 1 → 0 | 5 → 6 |
| `web/src/components/RerankerTraining/NeuralVisualizerWebGL2.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/RerankerTraining/NeuralVisualizerWebGPU.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/RerankerTraining/RunDiff.tsx` | 2 | 2 | 2 → 0 | 0 → 2 |
| `web/src/components/RerankerTraining/RunOverview.tsx` | 0 | 0 | 0 → 0 | 1 → 1 |
| `web/src/components/RerankerTraining/StudioLogTerminal.tsx` | 1 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/RerankerTraining/TrainingStudio.tsx` | 45 | 42 | 5 → 0 | 38 → 43 |
| `web/src/components/Search/GlobalSearch.tsx` | 2 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/Sidepanel.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/tabs/AdminTab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/tabs/ChatTab.tsx` | 1 | 1 | 1 → 0 | 0 → 1 |
| `web/src/components/tabs/EvalAnalysisTab.tsx` | 18 | 15 | 15 → 0 | 0 → 22 |
| `web/src/components/tabs/GrafanaTab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/tabs/InfrastructureTab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/tabs/RAGTab.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/tabs/StartTab.tsx` | 4 | 3 | 3 → 0 | 0 → 3 |
| `web/src/components/ui/ApiKeyStatus.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/ui/AssistantMarkdown.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/ui/Button.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/ui/CollapsibleSection.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/ui/CorpusRegistry.tsx` | 3 | 0 | 0 → 0 | 0 → 3 |
| `web/src/components/ui/EmbeddingMismatchWarning.tsx` | 0 | 0 | 0 → 0 | 0 → 2 |
| `web/src/components/ui/ErrorBoundary.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/ui/LineageMeta.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/ui/LoadingSpinner.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/ui/NumberField.tsx` | 1 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/ui/PromptLink.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/ui/StatusIndicator.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/ui/SubtabErrorFallback.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/ui/TooltipIcon.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/ui/TruncatedId.tsx` | 0 | 0 | 0 → 0 | 0 → 0 |
| `web/src/components/ui/confirmDialog.tsx` | 1 | 1 | 1 → 1 | 0 → 0 |
