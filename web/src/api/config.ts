import { apiClient, api, withCorpusScope } from './client';
import type { TriBridConfig } from '@/types/generated';

export const configApi = {
  /**
   * Load full TriBrid configuration (tribrid_config.json)
   */
  async load(): Promise<TriBridConfig> {
    const { data } = await apiClient.get<TriBridConfig>(withCorpusScope(api('/config')));
    return data;
  },

  /**
   * Persist full TriBrid configuration (overwrites tribrid_config.json)
   */
  async save(config: TriBridConfig): Promise<TriBridConfig> {
    const { data } = await apiClient.put<TriBridConfig>(withCorpusScope(api('/config')), config);
    return data;
  },

  /**
   * Patch a single top-level config section (e.g. retrieval, fusion, graph_search)
   */
  async patchSection(section: string, updates: Record<string, unknown>): Promise<TriBridConfig> {
    const { data } = await apiClient.patch<TriBridConfig>(
      withCorpusScope(api(`/config/${section}`)),
      updates
    );
    return data;
  },

  /**
   * Reset configuration to LAW defaults
   */
  async reset(): Promise<TriBridConfig> {
    const { data } = await apiClient.post<TriBridConfig>(withCorpusScope(api('/config/reset')));
    return data;
  },

  // NOTE: Keyword, secret, integration helpers are migrated later as their
  // backend endpoints are implemented. Keep config API narrowly focused on
  // TriBridConfig persistence.
};
