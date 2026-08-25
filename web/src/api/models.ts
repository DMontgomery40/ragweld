import { apiClient, api, withCorpusScope } from './client';
import type {
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
   * Upsert a catalog row.
   */
  async upsert(payload: ModelCatalogUpsertRequest): Promise<ModelCatalogUpsertResponse> {
    const { data } = await apiClient.post<ModelCatalogUpsertResponse>(api('/models/upsert'), payload);
    return data;
  },
};
