import axios from 'axios';
import { apiClient } from '@/api/client';
import { toDocumentViewError, type DocumentViewError } from '@/api/documents';
import type { GraphEntitySourcesResponse, GraphSourceReindexRequiredResponse } from '@/types/generated';

/** Local source-panel recovery state derived from the typed API failure. */
export type GraphSourceError = DocumentViewError & { reindexRequired: boolean };

export function toGraphSourceError(reason: unknown): GraphSourceError {
  const reindexRequired = axios.isAxiosError<GraphSourceReindexRequiredResponse>(reason)
    && reason.response?.status === 409
    && reason.response.data?.detail?.code === 'graph_source_reindex_required';
  return { ...toDocumentViewError(reason), reindexRequired };
}

export async function getEntitySources(
  corpusId: string,
  entityId: string,
  options: { offset?: number; runId?: string; signal?: AbortSignal } = {},
): Promise<GraphEntitySourcesResponse> {
  const response = await apiClient.get<GraphEntitySourcesResponse>(
    `/graph/${encodeURIComponent(corpusId)}/entity/sources`,
    { params: { entity_id: entityId, offset: options.offset, run_id: options.runId }, signal: options.signal },
  );
  return response.data;
}
