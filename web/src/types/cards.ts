/**
 * DEPRECATED: "cards" is a banned term per CLAUDE.md
 *
 * Use chunk_summaries.ts or import directly from generated.ts
 */

// Re-export legacy aliases for backward compatibility only
export type {
  Card,
  CardsResponse,
  ChunkSummary,
  ChunkSummariesResponse,
  ChunkSummariesBuildRequest,
  ChunkSummariesLastBuild,
} from './chunk_summaries';
