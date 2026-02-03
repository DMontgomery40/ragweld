/**
 * ModelFlowsService
 * Replacement for legacy `web/src/modules/model_flows.js` (no window globals).
 *
 * Scope:
 * - Upsert pricing/catalog entries into backend models catalog via POST /api/models/upsert.
 *
 * Notes:
 * - API payload/response is not currently represented in `generated.ts`, so we keep this typed narrowly.
 */
import { apiClient, api } from '@/api/client';

export type ModelsUpsertRequest = {
  provider: string;
  model: string;
  family?: string;
  base_url?: string;
  unit?: '1k_tokens' | 'request';

  // Pricing (optional; depends on unit/family)
  input_per_1k?: number | null;
  output_per_1k?: number | null;
  embed_per_1k?: number | null;
  rerank_per_1k?: number | null;
  per_request?: number | null;
};

export type ModelsUpsertResponse = {
  success?: boolean;
  ok?: boolean;
  error?: string;
  [k: string]: unknown;
};

export class ModelFlowsService {
  async upsertModel(entry: ModelsUpsertRequest): Promise<ModelsUpsertResponse> {
    const res = await apiClient.post(api('/models/upsert'), entry);
    return res.data as ModelsUpsertResponse;
  }
}

