/**
 * ModelFlowsService
 * Replacement for legacy `web/src/modules/model_flows.js` (no window globals).
 *
 * Scope:
 * - Upsert pricing/catalog entries into backend models catalog via POST /api/models/upsert.
 */
import { modelsApi } from '@/api/models';
import type { ModelCatalogUpsertRequest, ModelCatalogUpsertResponse } from '@/types/generated';

export type ModelsUpsertRequest = ModelCatalogUpsertRequest;
export type ModelsUpsertResponse = ModelCatalogUpsertResponse;

export class ModelFlowsService {
  async upsertModel(entry: ModelsUpsertRequest): Promise<ModelsUpsertResponse> {
    return await modelsApi.upsert(entry);
  }
}
