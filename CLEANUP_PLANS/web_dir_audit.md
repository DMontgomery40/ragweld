Web Directory Audit Report
Critical issues
1. Duplicate navigation systems
Location: web/src/modules/navigation.js vs web/src/hooks/useNavigation.ts + web/src/config/routes.ts
Problem:
navigation.js (767 lines) implements DOM-based navigation with window.Navigation
useNavigation.ts uses React Router
routes.ts duplicates tab definitions from navigation.js's NEW_TABS and TAB_REGISTRY
Both systems run simultaneously, causing conflicts
Impact: Confusion, potential bugs, maintenance overhead
Recommendation:
Remove modules/navigation.js after migrating all legacy modules
Use React Router (useNavigation.ts + routes.ts) as the single source of truth
Remove window.Navigation global
2. Duplicate hook barrel exports
Location: web/src/hooks/index.ts vs web/src/hooks/hooks_index.ts
Problem:
Two nearly identical barrel export files
hooks_index.ts is missing some exports (useModels, useGraph, useEvaluation, useEvalDataset, useEvalHistory)
Both are imported inconsistently
Impact: Import confusion, potential missing exports
Recommendation:
Delete hooks/hooks_index.ts
Standardize on hooks/index.ts
Update imports to use @/hooks
3. Duplicate store definitions (Cards vs ChunkSummaries)
Location: web/src/stores/useCardsStore.ts vs web/src/stores/useChunkSummariesStore.ts
Problem:
useCardsStore.ts (80 lines) defines a standalone CardsStore with custom types
useChunkSummariesStore.ts uses generated types and exports useCardsStore as an alias
stores/index.ts exports both, creating ambiguity
useCardsStore.ts is not used anywhere (no imports found)
Impact: Dead code, type confusion, violates "cards → chunk_summaries" migration
Recommendation:
Delete stores/useCardsStore.ts
Keep only useChunkSummariesStore.ts with the alias
Update stores/index.ts to only export from useChunkSummariesStore
4. Duplicate hook files (Cards vs ChunkSummaries)
Location: web/src/hooks/useCards.ts vs web/src/hooks/useChunkSummaries.ts
Problem:
useCards.ts (4 lines) is a thin wrapper re-exporting useChunkSummaries
useChunkSummaries.ts already exports useCards as an alias
Both are exported from hooks/index.ts
No components use useCards (grep found 0 matches)
Impact: Unnecessary file, redundant exports
Recommendation:
Delete hooks/useCards.ts
Keep the alias in useChunkSummaries.ts for backward compatibility
5. Dead code: archived folders
Location: web/_archived/ and web/src/modules/_archived/
Problem:
web/_archived/ contains 7 files (4 JSX, 3 JS) including old tab components
web/src/modules/_archived/error-helpers.js exists but error helpers are in utils/errorHelpers.ts
These files are not imported anywhere
Impact: Dead code, confusion
Recommendation:
Delete web/_archived/ entirely
Delete web/src/modules/_archived/error-helpers.js
If needed for reference, move to a docs folder outside the codebase
6. Invalid file type in React components
Location: web/src/components/RAG/__init__.py
Problem:
Python __init__.py file in a TypeScript React component directory
Empty file (0 bytes)
No Python code in web/src/ (grep found 0 .py files)
Impact: Confusion, potential build issues
Recommendation:
Delete web/src/components/RAG/__init__.py
Architectural issues
7. Legacy module system still active
Location: web/src/modules/*.js (30+ legacy JS modules)
Problem:
Heavy reliance on window.* globals (window.CoreUtils, window.Navigation, window.ErrorHelpers, window.UiHelpers, window.Tabs)
Mixed JS/TS codebase with unclear migration path
Legacy modules loaded in App.tsx alongside React components
Duplicate functionality between modules and hooks/stores
Examples:
modules/tooltips.js vs hooks/useTooltips.ts + stores/useTooltipStore.ts
modules/config.js vs hooks/useConfig.ts + stores/useConfigStore.ts
modules/tabs.js vs hooks/useTabs.ts + React Router
Impact: Technical debt, maintenance burden, inconsistent patterns
Recommendation:
Create migration plan to remove legacy modules
Prioritize: tooltips, config, navigation, tabs
Document which modules are still needed and why
8. Inconsistent API client patterns
Location: web/src/api/ vs web/src/hooks/useAPI.ts vs web/src/services/
Problem:
Multiple API client patterns:
api/client.ts - axios instance + apiUrl() helper
api/*.ts - feature-specific API clients (dashboard, docker, health, config)
hooks/useAPI.ts - React hook wrapper
services/*.ts - service classes with API calls
Some components use useAPI() hook, others use direct apiUrl() or apiClient
Inconsistent error handling
Impact: Inconsistent patterns, harder to maintain
Recommendation:
Standardize on api/*.ts feature clients
Use useAPI() hook only for simple cases
Services should use api/*.ts clients, not direct fetch/axios
9. Duplicate tooltip system
Location: web/src/modules/tooltips.js vs web/src/hooks/useTooltips.ts + web/src/stores/useTooltipStore.ts
Problem:
tooltips.js loads tooltip data and exposes window.Tooltips
useTooltipStore.ts loads the same data via Zustand
useTooltips.ts wraps the store
Both systems load from the same source but maintain separate state
Impact: Duplicate state, potential sync issues
Recommendation:
Migrate all components to useTooltips() hook
Remove modules/tooltips.js after migration
Ensure single source of truth in the store
Organizational issues
10. Mixed concerns in component directories
Location: web/src/components/
Problem:
Some directories are feature-based (Chat/, RAG/, Dashboard/)
Others are type-based (ui/, icons/)
Some components are at root level (Sidepanel.tsx, Notification.tsx, KeywordManager.tsx)
Inconsistent nesting depth (some 1 level, some 2-3 levels)
Impact: Hard to find components, inconsistent structure
Recommendation:
Standardize on feature-based organization
Move root-level components into appropriate feature directories
Create clear directory structure guidelines
11. Inconsistent import paths
Location: Throughout web/src/
Problem:
Mix of relative (../hooks) and absolute (@/hooks) imports
Some files use @/hooks, others use ../hooks
Inconsistent alias usage
Impact: Harder refactoring, inconsistent code style
Recommendation:
Standardize on @/ aliases for all internal imports
Add ESLint rule to enforce this
Refactor existing relative imports
12. Unused exports and dead code
Location: Various files
Problem:
hooks/index.ts exports useTooltipStore directly (should be internal)
Multiple legacy aliases exported but never used (useCards, useCardsStore)
Some components may be unused (need usage analysis)
Impact: Confusion, bundle bloat
Recommendation:
Audit all exports for actual usage
Remove unused exports
Use tools like ts-prune or depcheck to find unused code
Summary statistics
Duplicate systems: 5 (navigation, tooltips, hooks exports, cards stores, cards hooks)
Dead code files: 8+ (archived folders, unused stores, invalid files)
Legacy modules: 30+ JS files still active
Inconsistent patterns: 3 major areas (API clients, imports, component organization)
Priority recommendations
High priority (fix immediately)
Delete hooks/hooks_index.ts (duplicate barrel export)
Delete stores/useCardsStore.ts (unused duplicate)
Delete hooks/useCards.ts (unused wrapper)
Delete components/RAG/__init__.py (invalid file type)
Delete _archived/ folders (dead code)
Medium priority (plan migration)
Migrate away from modules/navigation.js to React Router only
Consolidate tooltip system (remove modules/tooltips.js)
Standardize API client patterns
Standardize import paths to use @/ aliases
Low priority (refactor over time)
Organize component directory structure
Audit and remove unused exports
Create migration plan for remaining legacy modules
Next steps
Create a cleanup branch
Delete the high-priority duplicates/dead code
Run tests to ensure nothing breaks
Create migration tickets for medium-priority items
Document the standardized patterns in AGENTS.md
Should I start implementing these fixes?