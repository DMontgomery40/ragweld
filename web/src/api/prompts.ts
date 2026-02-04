import { apiClient, api, withCorpusScope } from './client';
import type { PromptUpdateRequest, PromptUpdateResponse, PromptsResponse } from '@/types/generated';

export const promptsApi = {
  /**
   * System prompts editor API.
   */
  async list(): Promise<PromptsResponse> {
    const { data } = await apiClient.get<PromptsResponse>(withCorpusScope(api('/prompts')));
    return data;
  },

  async update(promptKey: string, value: string): Promise<PromptUpdateResponse> {
    const body: PromptUpdateRequest = { value };
    const { data } = await apiClient.put<PromptUpdateResponse>(
      withCorpusScope(api(`/prompts/${encodeURIComponent(promptKey)}`)),
      body
    );
    return data;
  },

  async reset(promptKey: string): Promise<PromptUpdateResponse> {
    const { data } = await apiClient.post<PromptUpdateResponse>(
      withCorpusScope(api(`/prompts/reset/${encodeURIComponent(promptKey)}`))
    );
    return data;
  },
};
