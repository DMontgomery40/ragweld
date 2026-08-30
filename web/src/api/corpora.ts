import { apiClient, api } from './client';
import type { Corpus } from '@/types/generated';

export const corporaApi = {
  /** One corpus registry row, including its stored keywords. */
  async get(corpusId: string): Promise<Corpus> {
    const { data } = await apiClient.get<Corpus>(api(`/corpora/${encodeURIComponent(corpusId)}`));
    return data;
  },
};
