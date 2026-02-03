## Legacy modules ledger (single source of truth for removals)

This ledger exists to prevent duplicate implementations during the migration away from `web/src/modules/*.js`.

### Zero-duplication rules

- **One canonical path per capability**: React/TS is canonical once a feature is migrated; legacy code must stop being loaded the same PR (or be replaced by a shim delegating to the new canonical code).
- **No TS/TSX should *require* `window.*` feature globals**. Any remaining `window.*` references must be tracked here with an explicit removal target.
- **`web/src/App.tsx` is Orchestrator-owned** for all changes to the legacy module loader.

### Ownership roles

- **Agent_AppOrchestrator**: `web/src/App.tsx`, boot/init sequencing, removal of module loader, removal of `modules/app.js`
- **Agent_UI_CallSites**: React components and their direct dependencies on legacy globals
- **Agent_DataLayer**: hooks/stores/services that replace data/business logic in modules
- **Agent_Infrastructure**: infra-related UI + stores/services (Docker, Grafana, MCP, health, tracing)
- **Agent_Testing**: Playwright + regression suite under `.tests/`

---

## Module-by-module mapping

> Legend:
> - **Status A**: obsolete (no longer loaded / no TS/TSX consumers)
> - **Status B**: still required (loaded or referenced, typically by `modules/app.js`)
> - **Status C**: unique behavior (either keep intentionally or migrate as a discrete feature)

### app.js
- **module**: `web/src/modules/app.js`
- **exposes**: (none) coordinator only
- **loaded in `web/src/App.tsx`**: yes (loaded last)
- **status**: **B** (central coordinator)
- **current consumers**: legacy modules via `window.*` globals
- **canonical replacement candidates**:
  - `web/src/hooks/useAppInit.ts`
  - `web/src/App.tsx`
  - feature components already migrated (Chat, Dashboard, RAG tabs)
- **owner**: **Agent_AppOrchestrator**
- **effort**: **L**
- **notes**: removing this is the “collapse the dependency graph” moment; many other modules become deletable.

### tooltips.js
- **module**: `web/src/modules/tooltips.js`
- **exposes**: `window.Tooltips`
- **loaded in `web/src/App.tsx`**: yes
- **status**: **C** (source-of-truth content currently lives here)
- **current consumers**:
  - `web/src/stores/useTooltipStore.ts` (loads via `window.Tooltips.buildTooltipMap`)
  - `web/src/components/Dashboard/HelpGlossary.tsx` (direct checks/access)
- **canonical replacement candidates**:
  - `web/src/stores/useTooltipStore.ts` + `web/src/hooks/useTooltips.ts`
  - `web/src/components/ui/TooltipIcon.tsx`
- **owner**: **Agent_UI_CallSites** (call sites) + **Agent_DataLayer** (store changes)
- **effort**: **M**
- **notes**: eliminate duplication by making store import a TS registry (no polling) and removing direct `window.Tooltips` reads in components.

### onboarding.js
- **module**: `web/src/modules/onboarding.js`
- **exposes**: `window.Onboarding`
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**:
  - `web/src/components/tabs/StartTab.tsx` (calls `ensureOnboardingInit`, `initOnboarding`)
- **canonical replacement candidates**:
  - (to be created) `web/src/stores/useOnboardingStore.ts`
  - (to be created) `web/src/hooks/useOnboarding.ts`
  - `web/src/components/tabs/StartTab.tsx`
- **owner**: **Agent_UI_CallSites**
- **effort**: **M**

### navigation.js
- **module**: `web/src/modules/navigation.js`
- **exposes**: `window.Navigation`, `window.NavigationViews`
- **loaded in `web/src/App.tsx`**: no (React Router replaces it)
- **status**: **B** (still referenced by many legacy modules via `registerView` / `navigateTo`)
- **current consumers** (legacy modules): `config.js`, `reranker.js`, `grafana.js`, `onboarding.js`, `mcp_server.js`, `tabs.js`, `test-instrumentation.js`, etc.
- **canonical replacement candidates**:
  - `web/src/hooks/useNavigation.ts`
  - `web/src/components/Navigation/TabBar.tsx`
  - `web/src/components/Navigation/TabRouter.tsx`
  - `web/src/config/routes.ts`
- **owner**: **Agent_AppOrchestrator**
- **effort**: **L**
- **notes**: becomes deletable after `modules/app.js` and remaining legacy modules are removed.

### tabs.js
- **module**: `web/src/modules/tabs.js`
- **exposes**: `window.Tabs`
- **loaded in `web/src/App.tsx`**: no (React Router replaces it)
- **status**: **B** (legacy fallback referenced by onboarding/navigation)
- **canonical replacement candidates**:
  - `web/src/components/Navigation/TabBar.tsx`
  - `web/src/components/Navigation/TabRouter.tsx`
- **owner**: **Agent_AppOrchestrator**
- **effort**: **M**

### config.js
- **module**: `web/src/modules/config.js`
- **exposes**: `window.Config`
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**:
  - `web/src/modules/app.js` (load/save/form gather/populate)
  - `web/src/modules/docker.js` (calls save)
  - `web/src/modules/model_flows.js` (calls load)
  - `web/src/hooks/useModuleLoader.ts` (readiness checks)
- **canonical replacement candidates**:
  - `web/src/stores/useConfigStore.ts`
  - `web/src/hooks/useConfig.ts`
- **owner**: **Agent_DataLayer**
- **effort**: **M**

### search.js
- **module**: `web/src/modules/search.js`
- **exposes**: `window.Search`
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**:
  - `web/src/modules/app.js` (bindings + highlight)
  - `web/src/hooks/useModuleLoader.ts` (readiness checks)
- **canonical replacement candidates**:
  - `web/src/hooks/useGlobalSearch.ts`
  - `web/src/components/Search/GlobalSearch.tsx`
- **owner**: **Agent_UI_CallSites**
- **effort**: **M**

### keywords.js
- **module**: `web/src/modules/keywords.js`
- **exposes**: `window.Keywords`
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**:
  - `web/src/modules/app.js` (calls `loadKeywords`)
- **canonical replacement candidates**:
  - `web/src/hooks/useKeywords.ts`
  - `web/src/components/KeywordManager.tsx`
- **owner**: **Agent_DataLayer**
- **effort**: **S**

### index_status.js
- **module**: `web/src/modules/index_status.js`
- **exposes**: `window.IndexStatus`
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**:
  - `web/src/modules/app.js` (start/poll)
- **canonical replacement candidates**:
  - `web/src/hooks/useIndexing.ts` / `web/src/components/RAG/IndexingSubtab.tsx`
- **owner**: **Agent_DataLayer**
- **effort**: **M**

### model_flows.js
- **module**: `web/src/modules/model_flows.js`
- **exposes**: `window.ModelFlows`
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**:
  - `web/src/modules/app.js` (addGen/addEmbed/addRerank/addCost flows)
- **canonical replacement candidates**:
  - `web/src/hooks/useModels.ts`
  - `web/src/components/RAG/ModelPicker.tsx` and related UI
- **owner**: **Agent_DataLayer**
- **effort**: **M**

### cost_logic.js
- **module**: `web/src/modules/cost_logic.js`
- **exposes**: `window.CostLogic`
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**:
  - `web/src/modules/app.js` (estimate/build payload)
- **canonical replacement candidates**:
  - `web/src/stores/useCostCalculatorStore.ts`
  - `web/src/components/Analytics/Cost.tsx`
  - `web/src/components/Dashboard/IndexingCostsPanel.tsx`
- **owner**: **Agent_DataLayer**
- **effort**: **M**

### storage-calculator.js / storage-calculator-template.js
- **modules**:
  - `web/src/modules/storage-calculator.js`
  - `web/src/modules/storage-calculator-template.js`
- **exposes**: none (utility/template)
- **loaded in `web/src/App.tsx`**: yes
- **status**: **A/B** (appear unused by TS/TSX, likely legacy-only)
- **canonical replacement candidates**:
  - `web/src/hooks/useStorageCalculator.ts`
  - `web/src/components/Storage/*`
  - `web/src/components/Dashboard/StorageCalculatorSuite.tsx`
- **owner**: **Agent_DataLayer** (logic) + **Agent_UI_CallSites** (UI verification)
- **effort**: **S**

### docker.js
- **module**: `web/src/modules/docker.js`
- **exposes**: `window.Docker`
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**:
  - self (onclick HTML handlers)
  - `web/src/modules/mcp_server.js` (calls `initDocker`)
- **canonical replacement candidates**:
  - `web/src/stores/useDockerStore.ts`
  - `web/src/components/Infrastructure/DockerSubtab.tsx`
  - `web/src/components/Docker/*`
- **owner**: **Agent_Infrastructure**
- **effort**: **M**

### grafana.js
- **module**: `web/src/modules/grafana.js`
- **exposes**: `window.Grafana`
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**:
  - `web/src/modules/test-instrumentation.js` (visibility checks)
- **canonical replacement candidates**:
  - `web/src/components/Grafana/*`
- **owner**: **Agent_Infrastructure**
- **effort**: **S**

### mcp_rag.js / mcp_server.js
- **modules**:
  - `web/src/modules/mcp_rag.js` (exposes `window.McpRag`)
  - `web/src/modules/mcp_server.js` (exposes `window.MCPServer`)
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**:
  - `web/src/modules/app.js` (binds MCP search)
  - various legacy view registrations
- **canonical replacement candidates**:
  - `web/src/hooks/useMCPRag.ts`
  - `web/src/services/MCPRagService.ts`
  - `web/src/components/Infrastructure/MCPSubtab.tsx`
- **owner**: **Agent_Infrastructure**
- **effort**: **S**

### health.js
- **module**: `web/src/modules/health.js`
- **exposes**: `window.Health`
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**:
  - `web/src/modules/app.js`
  - `web/src/hooks/useModuleLoader.ts` (readiness checks)
- **canonical replacement candidates**:
  - `web/src/stores/useHealthStore.ts`
  - `web/src/components/Dashboard/SystemStatus*`
- **owner**: **Agent_Infrastructure**
- **effort**: **S**

### trace.js / langsmith.js
- **modules**:
  - `web/src/modules/trace.js` (exposes `window.Trace`)
  - `web/src/modules/langsmith.js` (exposes `window.LangSmith`)
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**:
  - `web/src/modules/app.js` (trace loading, viewer binding)
- **canonical replacement candidates**:
  - `web/src/components/Analytics/Tracing.tsx`
  - `web/src/components/Evaluation/TraceViewer.tsx`
- **owner**: **Agent_Infrastructure**
- **effort**: **S**

### live-terminal.js
- **module**: `web/src/modules/live-terminal.js`
- **exposes**: `window.LiveTerminal`
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**:
  - `web/src/modules/reranker.js` (creates terminal)
- **canonical replacement candidates**:
  - `web/src/components/LiveTerminal/LiveTerminal.tsx`
  - `web/src/components/Dashboard/LiveTerminalPanel.tsx`
- **owner**: **Agent_UI_CallSites**
- **effort**: **M**

### reranker.js
- **module**: `web/src/modules/reranker.js`
- **exposes**: `window.RerankerUI`
- **loaded in `web/src/App.tsx`**: yes
- **status**: **B**
- **current consumers**: mostly self; depends on legacy terminal
- **canonical replacement candidates**:
  - `web/src/hooks/useReranker.ts`
  - `web/src/components/RAG/RerankerConfigSubtab.tsx`
  - `web/src/components/RerankerTraining/*`
- **owner**: **Agent_DataLayer**
- **effort**: **M**

### eval_runner.js / golden_questions.js / chat.js
- **modules**:
  - `web/src/modules/eval_runner.js`
  - `web/src/modules/golden_questions.js`
  - `web/src/modules/chat.js`
- **loaded in `web/src/App.tsx`**: no (disabled) / no TS consumers
- **status**: **A**
- **canonical replacement candidates**:
  - `web/src/components/Evaluation/*`
  - `web/src/components/Chat/*`
- **owner**: **Agent_UI_CallSites**
- **effort**: **S**

