import { apiClient, api } from './client';
import type { RuntimeCapabilitiesResponse } from '@/types/generated';

export const runtimeCapabilitiesApi = {
  async get(): Promise<RuntimeCapabilitiesResponse> {
    const { data } = await apiClient.get<RuntimeCapabilitiesResponse>(api('/runtime-capabilities'));
    return data;
  },
};
