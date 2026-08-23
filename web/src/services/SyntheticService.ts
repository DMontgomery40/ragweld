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

/**
 * Turn a failed Synthetic Lab request into the operator-facing message.
 *
 * axios rejects with "Request failed with status code 409"; the server's `detail`
 * (a string such as `QUALITY_GATE_FAILED: …` / `TRIPLETS_ARTIFACT_CORRUPT: …`, a
 * FastAPI validation list, or a typed `{code, message, operator_hint}` outage body)
 * is what the operator needs to act, so it is decoded here once for every caller.
 */
export function describeSyntheticFailure(error: unknown, action: string): string {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
  const status = response?.status;
  const detail = response?.data?.detail;
  const parts: string[] = [status ? `${action} (HTTP ${status})` : action];
  if (typeof detail === 'string' && detail.trim()) {
    parts.push(detail.trim());
  } else if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item === 'object' && 'msg' in item ? String((item as { msg: unknown }).msg) : ''))
      .filter(Boolean);
    if (messages.length) parts.push(messages.join('; '));
  } else if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>;
    const message = [record.code, record.message].filter((v) => typeof v === 'string' && v).join(': ');
    if (message) parts.push(message);
    if (typeof record.operator_hint === 'string' && record.operator_hint) parts.push(`Hint: ${record.operator_hint}`);
  } else if (error instanceof Error && error.message) {
    parts.push(error.message);
  }
  return parts.join(' — ');
}

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
