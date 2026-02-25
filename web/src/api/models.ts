import { apiClient, api, withCorpusScope } from './client';
import type {
  ModelCatalogEntry,
  ModelCatalogResponse,
  ModelCatalogUpsertRequest,
  ModelCatalogUpsertResponse,
} from '@/types/generated';

export const modelsApi = {
  /**
   * Full model catalog.
   */
  async listAll(): Promise<ModelCatalogResponse> {
    const { data } = await apiClient.get<ModelCatalogResponse>(withCorpusScope(api('/models')));
    return data;
  },

  /**
   * Filtered model catalog endpoint by component type.
   */
  async listByType(type: string): Promise<ModelCatalogEntry[]> {
    const { data } = await apiClient.get<ModelCatalogEntry[]>(
      withCorpusScope(api(`/models/by-type/${encodeURIComponent(type)}`))
    );
    return Array.isArray(data) ? data : [];
  },

  /**
   * Upsert a catalog row.
   */
  async upsert(payload: ModelCatalogUpsertRequest): Promise<ModelCatalogUpsertResponse> {
    const { data } = await apiClient.post<ModelCatalogUpsertResponse>(api('/models/upsert'), payload);
    return data;
  },
};
