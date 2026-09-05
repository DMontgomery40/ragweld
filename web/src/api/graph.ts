import { apiClient } from '@/api/client';
import type { GraphEntitySourcesResponse } from '@/types/generated';

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
