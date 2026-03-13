import { apiClient, api, withCorpusScope } from '@/api/client';
import type {
  LineageAliasesResponse,
  LineageBundle,
} from '@/types/generated';

export type LineageAliasName = 'baseline' | 'canary' | 'current' | 'promoted';

export class LineageService {
  async getCurrent(corpusId?: string): Promise<LineageBundle> {
    const { data } = await apiClient.get<LineageBundle>(withCorpusScope(api('/lineage/current'), corpusId), {
      headers: { 'Cache-Control': 'no-store' },
    });
    return data;
  }

  async listAliases(corpusId?: string): Promise<LineageAliasesResponse> {
    const { data } = await apiClient.get<LineageAliasesResponse>(withCorpusScope(api('/lineage/aliases'), corpusId), {
      headers: { 'Cache-Control': 'no-store' },
    });
    return data;
  }

  async setAlias(alias: LineageAliasName, bundleId: string, corpusId?: string): Promise<LineageAliasesResponse> {
    const { data } = await apiClient.post<LineageAliasesResponse>(
      withCorpusScope(api(`/lineage/aliases/${encodeURIComponent(alias)}`), corpusId),
      { bundle_id: bundleId }
    );
    return data;
  }
}

export const lineageService = new LineageService();
