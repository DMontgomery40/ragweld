import { apiClient, api } from './client';
import type { AppConfig, EnvConfig, ConfigUpdate, KeywordCatalog } from '@web/types';

export const configApi = {
  /**
   * Load full application configuration
   */
  async load(): Promise<AppConfig> {
    const { data } = await apiClient.get<AppConfig>(api('/config'));
    return data;
  },

  /**
   * Reload configuration from agro_config.json (triggers backend re-read)
   */
  async reloadConfig(): Promise<void> {
    await apiClient.post(api('/env/reload'));
  },

  /**
   * Save configuration to agro_config.json
   */
  async saveConfigPartial(config: Partial<EnvConfig>): Promise<void> {
    await apiClient.post(api('/env/save'), { env: config });
  },

  /**
   * Save full configuration (env + repos)
   */
  async saveConfig(update: ConfigUpdate): Promise<void> {
    await apiClient.post(api('/config'), update);
  },

  /**
   * Load keywords catalog
   */
  async loadKeywords(): Promise<KeywordCatalog> {
    const { data } = await apiClient.get<KeywordCatalog>(api('/keywords'));
    return data;
  },

  /**
   * Add a new keyword
   */
  async addKeyword(keyword: string, category?: string): Promise<void> {
    await apiClient.post(api('/keywords/add'), { keyword, category });
  },

  /**
   * Delete a keyword
   */
  async deleteKeyword(keyword: string): Promise<void> {
    await apiClient.post(api('/keywords/delete'), { keyword });
  },

  /**
   * Upload secrets from .env file
   */
  async uploadSecrets(file: File): Promise<{ ok: boolean; applied: string[]; persisted: boolean; count?: number; error?: string }> {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await apiClient.post<{ ok: boolean; applied: string[]; persisted: boolean; count?: number; error?: string }>(
      api('/secrets/ingest'),
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );
    return data;
  },

  /**
   * Save integration settings
   */
  async saveIntegrations(integrations: Record<string, any>): Promise<{ status: string; error?: string }> {
    const { data } = await apiClient.post<{ status: string; error?: string }>(
      api('/integrations/save'),
      { env: integrations }
    );
    return data;
  },

  /**
   * Save MCP API key to .env file
   * @param key - MCP API key value
   */
  async saveMCPKey(key: string): Promise<{ status: string; message?: string }> {
    const { data } = await apiClient.post<{ status: string; message?: string }>(
      api('/config/mcp_key'),
      { key }
    );
    return data;
  },

  /**
   * Get current runtime mode setting
   */
  async getRuntimeMode(): Promise<{ runtime_mode: string }> {
    const { data } = await apiClient.get<{ runtime_mode: string }>(api('/config/runtime_mode'));
    return data;
  },

  /**
   * Update runtime mode setting
   * @param mode - Runtime mode (development or production)
   */
  async updateRuntimeMode(mode: 'development' | 'production'): Promise<{ status: string; runtime_mode: string }> {
    const { data } = await apiClient.patch<{ status: string; runtime_mode: string }>(
      api('/config/runtime_mode'),
      { mode }
    );
    return data;
  },
};
