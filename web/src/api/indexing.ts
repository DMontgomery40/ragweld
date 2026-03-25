import { apiClient, api } from './client';
import type {
  IndexEstimate,
  IndexRequest,
  RetrievalPilotExportRequest,
  RetrievalPilotExportResponse,
  RetrievalPilotIngestRequest,
  RetrievalPilotIngestResponse,
  RetrievalPilotSearchRequest,
  RetrievalPilotSearchResponse,
  RetrievalPilotSearchPreviewRequest,
  RetrievalPilotSearchPreviewResponse,
  RetrievalPilotStatusResponse,
} from '@/types/generated';

export const indexingApi = {
  async estimate(req: IndexRequest): Promise<IndexEstimate> {
    const { data } = await apiClient.post<IndexEstimate>(api('/index/estimate'), req);
    return data;
  },

  async getPilotStatus(corpusId: string, repoPath?: string): Promise<RetrievalPilotStatusResponse> {
    const qs = repoPath ? `?repo_path=${encodeURIComponent(repoPath)}` : '';
    const { data } = await apiClient.get<RetrievalPilotStatusResponse>(api(`/index/${encodeURIComponent(corpusId)}/pilot/status${qs}`));
    return data;
  },

  async exportPilot(corpusId: string, req: RetrievalPilotExportRequest): Promise<RetrievalPilotExportResponse> {
    const { data } = await apiClient.post<RetrievalPilotExportResponse>(
      api(`/index/${encodeURIComponent(corpusId)}/pilot/export`),
      req
    );
    return data;
  },

  async searchPilotPreview(
    corpusId: string,
    req: RetrievalPilotSearchPreviewRequest,
    repoPath?: string
  ): Promise<RetrievalPilotSearchPreviewResponse> {
    const qs = repoPath ? `?repo_path=${encodeURIComponent(repoPath)}` : '';
    const { data } = await apiClient.post<RetrievalPilotSearchPreviewResponse>(
      api(`/index/${encodeURIComponent(corpusId)}/pilot/search-preview${qs}`),
      req
    );
    return data;
  },

  async ingestPilot(corpusId: string, req: RetrievalPilotIngestRequest, repoPath?: string): Promise<RetrievalPilotIngestResponse> {
    const qs = repoPath ? `?repo_path=${encodeURIComponent(repoPath)}` : '';
    const { data } = await apiClient.post<RetrievalPilotIngestResponse>(
      api(`/index/${encodeURIComponent(corpusId)}/pilot/ingest${qs}`),
      req
    );
    return data;
  },

  async searchPilot(corpusId: string, req: RetrievalPilotSearchRequest, repoPath?: string): Promise<RetrievalPilotSearchResponse> {
    const qs = repoPath ? `?repo_path=${encodeURIComponent(repoPath)}` : '';
    const { data } = await apiClient.post<RetrievalPilotSearchResponse>(
      api(`/index/${encodeURIComponent(corpusId)}/pilot/search${qs}`),
      req
    );
    return data;
  },
};
