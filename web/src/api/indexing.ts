import { apiClient, api } from './client';
import type { IndexEstimate, IndexRequest } from '@/types/generated';

/**
 * An estimate that actually measured something.
 *
 * Only `status: 'ready'` carries numbers; the wire type makes every measured quantity nullable
 * so an unguarded consumer cannot render a zero it was never given. This narrowing is what lets
 * components use those numbers without a null check — they can only obtain one through
 * `indexingApi.estimate`, which never resolves with anything else.
 */
export type ReadyIndexEstimate = IndexEstimate & {
  status: 'ready';
  estimated_total_tokens: number;
  estimated_total_chunks: number;
  estimated_tokens_low: number;
  estimated_tokens_high: number;
  estimated_chunks_low: number;
  estimated_chunks_high: number;
  estimate_relative_error: number;
  sampled_files: number;
  sampled_bytes: number;
};

/** The estimator never became ready within the deadline. */
export class EstimateNotReadyError extends Error {
  readonly status: IndexEstimate['status'];
  readonly detail: string;

  constructor(last: IndexEstimate, waitedMs: number) {
    const detail = last.assumptions?.[0] ?? '';
    super(
      last.status === 'insufficient_sample'
        ? detail || 'the estimator could not measure enough of this corpus'
        : `the estimator was still preparing after ${Math.round(waitedMs / 1000)}s`
    );
    this.name = 'EstimateNotReadyError';
    this.status = last.status;
    this.detail = detail;
  }
}

// The estimator's tokenizer loads on first use in a fresh API process (~27 s), and a corpus can
// need more than one sampling pass. Long enough for both on a loaded box, short enough that a
// genuinely stuck estimator becomes an error the operator sees rather than a spinner.
const WARMUP_DEADLINE_MS = 120_000;
const WARMUP_POLL_MS = 3000;

export type EstimateOptions = {
  /** Called with each non-ready answer, so a caller can show the wait. */
  onWaiting?: (estimate: IndexEstimate) => void;
  deadlineMs?: number;
};

export const indexingApi = {
  /**
   * Estimate a corpus, waiting out a cold or under-sampled estimator.
   *
   * The polling lives HERE rather than in each component on purpose: a warming payload carries
   * no measurements, and the one component that forgot to guard opened a confirmation dialog on
   * it — "tokens 0 / chunks 0 / $0.0000 / Build indexes" on the first-run wizard. Funnelling
   * both callers through one function means no component can receive a non-ready estimate at
   * all, and the return type says so.
   */
  async estimate(req: IndexRequest, opts: EstimateOptions = {}): Promise<ReadyIndexEstimate> {
    const deadlineMs = opts.deadlineMs ?? WARMUP_DEADLINE_MS;
    const startedAt = Date.now();
    for (;;) {
      const { data } = await apiClient.post<IndexEstimate>(api('/index/estimate'), req);
      if (data.status === 'ready') return data as ReadyIndexEstimate;
      const waited = Date.now() - startedAt;
      if (waited >= deadlineMs) throw new EstimateNotReadyError(data, waited);
      opts.onWaiting?.(data);
      const remaining = Math.max(0, Number(data.warmup_seconds_remaining ?? 0));
      await new Promise((resolve) =>
        setTimeout(resolve, Math.min(WARMUP_POLL_MS, Math.max(1000, remaining * 1000)))
      );
    }
  },
};
