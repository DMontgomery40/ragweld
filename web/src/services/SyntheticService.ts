import { syntheticApi } from '@/api/synthetic';
import type {
  SyntheticArtifactPreviewResponse,
  SyntheticConfigPatchResponse,
  SyntheticPublishResponse,
  SyntheticRun,
  SyntheticRunEvent,
  SyntheticRunStartRequest,
  SyntheticRunsResponse,
} from '@/types/generated';

export class SyntheticService {
  async startRun(payload: SyntheticRunStartRequest): Promise<SyntheticRun> {
    return syntheticApi.startRun(payload);
  }

  async listRuns(corpusId: string, limit = 50): Promise<SyntheticRunsResponse> {
    return syntheticApi.listRuns(corpusId, limit);
  }

  async getRun(runId: string): Promise<SyntheticRun> {
    return syntheticApi.getRun(runId);
  }

  async cancelRun(runId: string): Promise<{ ok: boolean }> {
    return syntheticApi.cancelRun(runId);
  }

  async publishEvalDataset(runId: string): Promise<SyntheticPublishResponse> {
    return syntheticApi.publishEvalDataset(runId);
  }

  async publishSemanticCards(runId: string): Promise<SyntheticPublishResponse> {
    return syntheticApi.publishSemanticCards(runId);
  }

  async publishKeywords(runId: string): Promise<SyntheticPublishResponse> {
    return syntheticApi.publishKeywords(runId);
  }

  async publishTriplets(runId: string): Promise<SyntheticPublishResponse> {
    return syntheticApi.publishTriplets(runId);
  }

  async publishConfigPatch(runId: string): Promise<SyntheticConfigPatchResponse> {
    return syntheticApi.publishConfigPatch(runId);
  }

  async previewArtifact(runId: string, kind: string, limit = 5): Promise<SyntheticArtifactPreviewResponse> {
    return syntheticApi.previewArtifact(runId, kind, limit);
  }

  streamRun(
    runId: string,
    onEvent: (ev: SyntheticRunEvent) => void,
    opts?: { onError?: (message: string) => void; onComplete?: () => void }
  ): () => void {
    return syntheticApi.streamRun(runId, onEvent, opts);
  }
}

export const syntheticService = new SyntheticService();
