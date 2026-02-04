/**
 * RerankService - Learning reranker legacy workflow API client
 *
 * ALL API TYPES COME FROM generated.ts (Pydantic-first).
 */

export type {
  CountResponse,
  FeedbackRequest,
  OkResponse,
  RerankerCostsResponse,
  RerankerEvaluateResponse,
  RerankerInfoResponse,
  RerankerLegacyStatus,
  RerankerLogsResponse,
  RerankerMineResponse,
  RerankerNoHitsResponse,
  RerankerTrainLegacyRequest,
  RerankerTrainLegacyResponse,
} from '@/types/generated';

import type {
  CountResponse,
  FeedbackRequest,
  OkResponse,
  RerankerCostsResponse,
  RerankerEvaluateResponse,
  RerankerInfoResponse,
  RerankerLegacyStatus,
  RerankerLogsResponse,
  RerankerMineResponse,
  RerankerNoHitsResponse,
  RerankerTrainLegacyRequest,
  RerankerTrainLegacyResponse,
} from '@/types/generated';

import { withCorpusScope } from '@/api/client';

export class RerankService {
  private apiBase: string;

  constructor(apiBase: string) {
    this.apiBase = apiBase;
  }

  /**
   * Track file link click (for feedback system)
   */
  async trackFileClick(eventId: string, docId: string): Promise<void> {
    if (!eventId || !docId) return;

    try {
      await fetch(withCorpusScope(`${this.apiBase}/reranker/click`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_id: eventId, doc_id: docId })
      });
    } catch (error) {
      console.error('[RerankService] Failed to track click:', error);
      // Silent failure - click tracking is non-critical for UX
    }
  }

  /**
   * Submit user feedback (thumbs, stars, or note)
   */
  async submitFeedback(feedback: { eventId: string; signal: string; note?: string }): Promise<void> {
    const payload: FeedbackRequest = {
      event_id: feedback.eventId,
      signal: feedback.signal,
      note: feedback.note ?? null,
      doc_id: null,
      rating: null,
      comment: null,
      timestamp: null,
      context: null,
    };
    const response = await fetch(withCorpusScope(`${this.apiBase}/feedback`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      throw new Error('Failed to save feedback');
    }
  }

  /**
   * Mine triplets from user feedback
   */
  async mineTriplets(): Promise<RerankerMineResponse> {
    const response = await fetch(withCorpusScope(`${this.apiBase}/reranker/mine`), {
      method: 'POST'
    });

    if (!response.ok) {
      throw new Error('Failed to start triplet mining');
    }

    return await response.json();
  }

  /**
   * Train reranker model
   */
  async trainModel(options: RerankerTrainLegacyRequest = {}): Promise<RerankerTrainLegacyResponse> {
    const response = await fetch(withCorpusScope(`${this.apiBase}/reranker/train`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options)
    });

    if (!response.ok) {
      throw new Error('Failed to start model training');
    }

    return await response.json();
  }

  /**
   * Evaluate trained model
   */
  async evaluateModel(): Promise<RerankerEvaluateResponse> {
    const response = await fetch(withCorpusScope(`${this.apiBase}/reranker/evaluate`), {
      method: 'POST'
    });

    if (!response.ok) {
      throw new Error('Failed to start evaluation');
    }

    return await response.json();
  }

  /**
   * Get current reranker status (for polling)
   */
  async getStatus(): Promise<RerankerLegacyStatus> {
    try {
      const response = await fetch(withCorpusScope(`${this.apiBase}/reranker/status`));
      const data = await response.json();
      return data;
    } catch (error) {
      return {
        running: false,
        progress: 0,
        task: '',
        message: '',
        result: null,
        live_output: [],
        run_id: null,
      };
    }
  }

  /**
   * Get reranker configuration info
   */
  async getInfo(): Promise<RerankerInfoResponse> {
    const response = await fetch(withCorpusScope(`${this.apiBase}/reranker/info`));
    if (!response.ok) {
      throw new Error('Failed to get reranker info');
    }
    return await response.json();
  }

  /**
   * Get query logs count
   */
  async getLogsCount(): Promise<CountResponse> {
    const response = await fetch(withCorpusScope(`${this.apiBase}/reranker/logs/count`));
    return await response.json();
  }

  /**
   * Get triplets count
   */
  async getTripletsCount(): Promise<CountResponse> {
    const response = await fetch(withCorpusScope(`${this.apiBase}/reranker/triplets/count`));
    return await response.json();
  }

  /**
   * Get cost statistics
   */
  async getCosts(): Promise<RerankerCostsResponse> {
    const response = await fetch(withCorpusScope(`${this.apiBase}/reranker/costs`));
    return await response.json();
  }

  /**
   * Get no-hit queries (queries that returned no results)
   */
  async getNoHits(): Promise<RerankerNoHitsResponse> {
    const response = await fetch(withCorpusScope(`${this.apiBase}/reranker/nohits`));
    return await response.json();
  }

  /**
   * Get query logs
   */
  async getLogs(): Promise<RerankerLogsResponse> {
    const response = await fetch(withCorpusScope(`${this.apiBase}/reranker/logs`));
    return await response.json();
  }

  /**
   * Download query logs
   */
  async downloadLogs(): Promise<Blob> {
    const response = await fetch(withCorpusScope(`${this.apiBase}/reranker/logs/download`));
    if (!response.ok) {
      throw new Error('Failed to download logs');
    }
    return await response.blob();
  }

  /**
   * Clear all query logs
   */
  async clearLogs(): Promise<OkResponse> {
    const response = await fetch(withCorpusScope(`${this.apiBase}/reranker/logs/clear`), {
      method: 'POST'
    });
    if (!response.ok) {
      throw new Error('Failed to clear logs');
    }
    return await response.json();
  }
}
