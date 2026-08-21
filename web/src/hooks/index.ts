/**
 * TriBridRAG React Hooks
 *
 * These hooks bridge the React components with the legacy module system
 * while maintaining full functionality and ADA compliance.
 */

// App lifecycle
export { useAppInit } from './useAppInit';
export { useApplyButton } from './useApplyButton';
export { useNotification } from './useNotification';
export { useErrorHandler } from './useErrorHandler';

// Core utility hooks (converted from legacy modules)
export { useAPI } from './useAPI';
export { useTheme } from './useTheme';
export { useUIHelpers } from './useUIHelpers';
export { useTooltips } from './useTooltips';
export { useTooltipStore } from '../stores/useTooltipStore';
export { useGlobalSearch } from './useGlobalSearch';

// Navigation hooks (React Router integration)
export { useSubtab } from './useSubtab';

// Config management (Zustand-backed)
export { useConfig, useConfigField } from './useConfig';
export { useConfigStore } from '../stores/useConfigStore';

// Embedding status (critical mismatch detection)
export { useEmbeddingStatus } from '@/hooks/useEmbeddingStatus';

// Embedding model (derives active model/setter/tooltip from embedding_type)
export { useEmbeddingModel } from './useEmbeddingModel';

// Feature hooks
export { useIndexing } from './useIndexing';
export { useModels } from './useModels';
export type { Model } from './useModels';
export { useRuntimeCapabilities } from './useRuntimeCapabilities';
export { useReranker } from './useReranker';
export { useMCPServer } from './useMCPServer';
// useOnboarding removed - banned feature per CLAUDE.md
// Evaluation hooks (using generated types from Pydantic)
export { useEvalDataset } from './useEvalDataset';

// Graph hooks (using generated types from Pydantic)
export { useGraph } from './useGraph';
