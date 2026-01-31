/**
 * Chunk Summaries Types - Re-exported from generated.ts
 *
 * Per CLAUDE.md: All types come from Pydantic via generated.ts.
 * This file provides named exports for convenience.
 */

export type {
  ChunkSummary,
  ChunkSummariesResponse,
  ChunkSummariesBuildRequest,
  ChunkSummariesLastBuild,
  ChunkSummaryConfig,
} from './generated';

// Legacy aliases - DO NOT USE in new code
export type { ChunkSummary as Card } from './generated';
export type { ChunkSummariesResponse as CardsResponse } from './generated';
