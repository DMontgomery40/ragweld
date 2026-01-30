/**
 * UI Components - Reusable feedback and loading components
 *
 * These components provide visual feedback for async operations and loading states.
 * All components are fully accessible with ARIA labels and support theming.
 */

// Button
export { Button } from './Button';

// Progress indicators
export { ProgressBar } from './ProgressBar';
export type { ProgressBarProps } from './ProgressBar';
export { ProgressBarWithShimmer } from './ProgressBarWithShimmer';
export type { ProgressBarWithShimmerProps } from './ProgressBarWithShimmer';

// Status indicators
export { StatusIndicator } from './StatusIndicator';
export type { StatusIndicatorProps } from './StatusIndicator';

// Loading states
export { LoadingSpinner, LoadingOverlay, LoadingButton } from './LoadingSpinner';
export type { LoadingSpinnerProps } from './LoadingSpinner';

// Skeleton loaders
export { SkeletonLoader, SkeletonCard, SkeletonList } from './SkeletonLoader';
export type { SkeletonLoaderProps } from './SkeletonLoader';

// Repository components
export { RepoSelector } from './RepoSelector';
export { RepoSwitcherModal } from './RepoSwitcherModal';

// Embedding mismatch warning (critical for search accuracy)
export { EmbeddingMismatchWarning, EmbeddingMatchIndicator } from './EmbeddingMismatchWarning';
