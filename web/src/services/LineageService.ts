import { apiClient, api, withCorpusScope } from '@/api/client';
import type { LineageAliasesResponse } from '@/types/generated';

export type LineageAliasName = 'baseline' | 'canary' | 'current' | 'promoted';

export class LineageService {
  async setAlias(alias: LineageAliasName, bundleId: string, corpusId?: string): Promise<LineageAliasesResponse> {
    const { data } = await apiClient.post<LineageAliasesResponse>(
      withCorpusScope(api(`/lineage/aliases/${encodeURIComponent(alias)}`), corpusId),
      { bundle_id: bundleId }
    );
    return data;
  }
}

export const lineageService = new LineageService();
