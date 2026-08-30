import { apiClient, api, withCorpusScope } from './client';
import type {
  ConfigReadinessResponse,
  ConfigRegistryResponse,
  ModelValidationResult,
  TriBridConfig,
} from '@/types/generated';

// The field registry is derived from the registered Pydantic models and carries no
// corpus scope, yet two independent consumers (the Ctrl+K index and the Admin config
// control plane) each fetched it on mount, and every remount refetched (M-129).
// Shared while in flight, never cached: the entry is cleared as soon as the request
// settles, so a remount after the answer arrived still asks the server.
let inFlightRegistry: Promise<ConfigRegistryResponse> | null = null;

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
  async patchSection(section: string, updates: Record<string, unknown>, corpusId?: string): Promise<TriBridConfig> {
    const { data } = await apiClient.patch<TriBridConfig>(
      withCorpusScope(api(`/config/${section}`), corpusId),
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

  /**
   * Reload configuration from disk (best-effort).
   * Used by dashboard quick actions.
   */
  async reload(corpusId?: string): Promise<TriBridConfig> {
    // There is no dedicated /config/reload endpoint in the backend.
    // Reading /config always resolves from persisted scoped config.
    const { data } = await apiClient.get<TriBridConfig>(withCorpusScope(api('/config'), corpusId));
    return data;
  },

  /**
   * Validate current config model assignments against the catalog.
   * Returns soft warnings without blocking saves.
   */
  async validate(): Promise<ModelValidationResult> {
    const { data } = await apiClient.get<ModelValidationResult>(withCorpusScope(api('/config/validate')));
    return data;
  },

  /**
   * Load the registry-driven config field/integration metadata.
   */
  async registry(): Promise<ConfigRegistryResponse> {
    if (inFlightRegistry) return inFlightRegistry;
    const run = apiClient
      .get<ConfigRegistryResponse>(api('/config/registry'))
      .then(({ data }) => data)
      .finally(() => {
        if (inFlightRegistry === run) inFlightRegistry = null;
      });
    inFlightRegistry = run;
    return run;
  },

  /**
   * Load current integration and secret readiness for the selected scope.
   */
  async readiness(): Promise<ConfigReadinessResponse> {
    const { data } = await apiClient.get<ConfigReadinessResponse>(withCorpusScope(api('/config/readiness')));
    return data;
  },

  // NOTE: Keyword, secret, integration helpers are migrated later as their
  // backend endpoints are implemented. Keep config API narrowly focused on
  // TriBridConfig persistence.
};
