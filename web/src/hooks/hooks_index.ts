/**
 * AGRO React Hooks
 *
 * These hooks bridge the React components with the legacy module system
 * while maintaining full functionality and ADA compliance.
 */

// App lifecycle
export { useAppInit } from './useAppInit';
export { useModuleLoader } from './useModuleLoader';
export { useEventBus } from './useEventBus';
export { useGlobalState } from './useGlobalState';
export { useApplyButton } from './useApplyButton';
export { useNotification } from './useNotification';
export { useErrorHandler } from './useErrorHandler';

// Core utility hooks (converted from legacy modules)
export { useAPI } from './useAPI';
export { useTheme } from './useTheme';
export { useUIHelpers } from './useUIHelpers';
export { useTooltips } from './useTooltips';
export { useGlobalSearch } from './useGlobalSearch';

// Navigation hooks (React Router integration)
export { useNavigation } from './useNavigation';
export { useTabs } from './useTabs';
export { useVSCodeEmbed } from './useVSCodeEmbed';

// Config management (Zustand-backed)
export { useConfig, useConfigField } from './useConfig';
export { useConfigStore } from '../stores/useConfigStore';

// Embedding status (critical mismatch detection)
export { useEmbeddingStatus } from './useEmbeddingStatus';
export type { EmbeddingStatus } from './useEmbeddingStatus';

// Feature hooks
export { useDashboard } from './useDashboard';
export { useIndexing } from './useIndexing';
export type { IndexStatus } from './useIndexing';
export { useReranker } from './useReranker';
export { useKeywords } from './useKeywords';
export { useMCPRag } from './useMCPRag';
// Chunk Summaries (formerly "cards" - renamed per CLAUDE.md)
export { useChunkSummaries, useCards } from './useChunkSummaries';
// useOnboarding removed - banned feature per CLAUDE.md
export { useStorageCalculator } from './useStorageCalculator';
