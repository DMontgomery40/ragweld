import { apiClient, api } from './client';
import type { HealthStatus } from '@web/types';

export const healthApi = {
  /**
   * Check system health status
   */
  async check(): Promise<HealthStatus> {
    const { data } = await apiClient.get<HealthStatus>(api('/health'));
    return data;
  },
};
