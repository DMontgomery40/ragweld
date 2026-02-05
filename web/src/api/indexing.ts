import { apiClient, api } from './client';
import type { IndexEstimate, IndexRequest } from '@/types/generated';

export const indexingApi = {
  async estimate(req: IndexRequest): Promise<IndexEstimate> {
    const { data } = await apiClient.post<IndexEstimate>(api('/index/estimate'), req);
    return data;
  },
};

