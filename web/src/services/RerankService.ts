/**
 * RerankService - Learning Reranker Backend Service
 * Converted from /web/src/modules/reranker.js
 *
 * Handles:
 * - Feedback collection (thumbs up/down, star ratings, notes)
 * - Triplet mining from user feedback
 * - Model training workflow
 * - Evaluation and baseline comparison
 * - Query log management
 * - Automation (cron jobs)
 * - Smoke testing
 */

export interface FeedbackSignal {
  eventId: string;
  signal: 'thumbsup' | 'thumbsdown' | string;
  note?: string;
}

export interface RerankerStatus {
  running: boolean;
  progress: number;
  task: 'mining' | 'training' | 'evaluating' | '';
  message: string;
  result?: {
    ok: boolean;
    output?: string;
    error?: string;
  };
  live_output?: string[];
}

export interface TrainingOptions {
  epochs?: number;
  batch_size?: number;
  max_length?: number;
}

export interface RerankerInfo {
  enabled: boolean;
  resolved_path?: string;
  path?: string;
  device?: string;
  alpha?: number;
  topn?: number;
  batch?: number;
  maxlen?: number;
}

export interface EvaluationMetrics {
  mrr: number;
  hit1: number;
  hit3?: number;
  hit5?: number;
  hit10?: number;
  evaluated_count: number;
}

export interface BaselineComparison {
  ok: boolean;
  delta?: {
    mrr: number;
    hit1: number;
  };
}

export interface SmokeTestResult {
  ok: boolean;
  logged: boolean;
  results_count: number;
  reranked: boolean;
  event_id?: string;
  error?: string;
}

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
      await fetch(`${this.apiBase}/reranker/click`, {
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
  async submitFeedback(feedback: FeedbackSignal): Promise<void> {
    const response = await fetch(`${this.apiBase}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event_id: feedback.eventId,
        signal: feedback.signal,
        note: feedback.note
      })
    });

    if (!response.ok) {
      throw new Error('Failed to save feedback');
    }
  }

  /**
   * Mine triplets from user feedback
   */
  async mineTriplets(): Promise<{ ok: boolean; output?: string; error?: string }> {
    const response = await fetch(`${this.apiBase}/reranker/mine`, {
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
  async trainModel(options: TrainingOptions = {}): Promise<{ ok: boolean; output?: string; error?: string }> {
    const response = await fetch(`${this.apiBase}/reranker/train`, {
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
  async evaluateModel(): Promise<{ ok: boolean; output?: string; error?: string }> {
    const response = await fetch(`${this.apiBase}/reranker/evaluate`, {
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
  async getStatus(): Promise<RerankerStatus> {
    try {
      const response = await fetch(`${this.apiBase}/reranker/status`);
      const data = await response.json();
      return data;
    } catch (error) {
      return {
        running: false,
        progress: 0,
        task: '',
        message: '',
        result: undefined
      };
    }
  }

  /**
   * Get reranker configuration info
   */
  async getInfo(): Promise<RerankerInfo> {
    const response = await fetch(`${this.apiBase}/reranker/info`);
    if (!response.ok) {
      throw new Error('Failed to get reranker info');
    }
    return await response.json();
  }

  /**
   * Get query logs count
   */
  async getLogsCount(): Promise<{ count: number }> {
    const response = await fetch(`${this.apiBase}/reranker/logs/count`);
    return await response.json();
  }

  /**
   * Get triplets count
   */
  async getTripletsCount(): Promise<{ count: number }> {
    const response = await fetch(`${this.apiBase}/reranker/triplets/count`);
    return await response.json();
  }

  /**
   * Get cost statistics
   */
  async getCosts(): Promise<{ total_24h: number; avg_per_query: number }> {
    const response = await fetch(`${this.apiBase}/reranker/costs`);
    return await response.json();
  }

  /**
   * Get no-hit queries (queries that returned no results)
   */
  async getNoHits(): Promise<{ queries: Array<{ query: string; ts: string }> }> {
    const response = await fetch(`${this.apiBase}/reranker/nohits`);
    return await response.json();
  }

  /**
   * Get query logs
   */
  async getLogs(): Promise<{ logs: any[] }> {
    const response = await fetch(`${this.apiBase}/reranker/logs`);
    return await response.json();
  }

  /**
   * Download query logs
   */
  async downloadLogs(): Promise<Blob> {
    const response = await fetch(`${this.apiBase}/reranker/logs/download`);
    if (!response.ok) {
      throw new Error('Failed to download logs');
    }
    return await response.blob();
  }

  /**
   * Clear all query logs
   */
  async clearLogs(): Promise<void> {
    const response = await fetch(`${this.apiBase}/reranker/logs/clear`, {
      method: 'POST'
    });
    if (!response.ok) {
      throw new Error('Failed to clear logs');
    }
  }

  /**
   * Setup nightly automation job
   */
  async setupNightlyJob(time: string): Promise<{ ok: boolean; error?: string }> {
    const response = await fetch(`${this.apiBase}/reranker/cron/setup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ time })
    });
    return await response.json();
  }

  /**
   * Remove nightly automation job
   */
  async removeNightlyJob(): Promise<{ ok: boolean; error?: string }> {
    const response = await fetch(`${this.apiBase}/reranker/cron/remove`, {
      method: 'POST'
    });
    return await response.json();
  }

  /**
   * Save current model as baseline
   */
  async saveBaseline(): Promise<{ ok: boolean; error?: string }> {
    const response = await fetch(`${this.apiBase}/reranker/baseline/save`, {
      method: 'POST'
    });
    return await response.json();
  }

  /**
   * Compare current model with baseline
   */
  async compareBaseline(): Promise<BaselineComparison> {
    const response = await fetch(`${this.apiBase}/reranker/baseline/compare`);
    return await response.json();
  }

  /**
   * Rollback to baseline model
   */
  async rollbackModel(): Promise<{ ok: boolean; error?: string }> {
    const response = await fetch(`${this.apiBase}/reranker/rollback`, {
      method: 'POST'
    });
    return await response.json();
  }

  /**
   * Run smoke test
   */
  async runSmokeTest(query: string): Promise<SmokeTestResult> {
    const response = await fetch(`${this.apiBase}/reranker/smoketest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query })
    });
    return await response.json();
  }

  /**
   * Parse evaluation metrics from output string
   */
  parseMetrics(output: string): EvaluationMetrics | null {
    const mrrMatch = output.match(/MRR@all:\s*([\d\.]+)/);
    const hit1Match = output.match(/Hit@1:\s*([\d\.]+)/);
    const hit3Match = output.match(/Hit@3:\s*([\d\.]+)/);
    const hit5Match = output.match(/Hit@5:\s*([\d\.]+)/);
    const hit10Match = output.match(/Hit@10:\s*([\d\.]+)/);
    const evalMatch = output.match(/Evaluated on (\d+) items/);

    if (!mrrMatch) return null;

    return {
      mrr: parseFloat(mrrMatch[1]),
      hit1: hit1Match ? parseFloat(hit1Match[1]) : 0,
      hit3: hit3Match ? parseFloat(hit3Match[1]) : undefined,
      hit5: hit5Match ? parseFloat(hit5Match[1]) : undefined,
      hit10: hit10Match ? parseFloat(hit10Match[1]) : undefined,
      evaluated_count: evalMatch ? parseInt(evalMatch[1]) : 0
    };
  }

  /**
   * Parse triplet mining result
   */
  parseMiningResult(output: string): { triplets: number; queries: number } | null {
    const match = output.match(/mined (\d+) triplets from (\d+) query events/);
    if (!match) return null;

    return {
      triplets: parseInt(match[1]),
      queries: parseInt(match[2])
    };
  }

  /**
   * Parse training result
   */
  parseTrainingResult(output: string): { accuracy: number } | null {
    const match = output.match(/dev pairwise accuracy: ([\d\.]+)/);
    if (!match) return null;

    return {
      accuracy: parseFloat(match[1])
    };
  }
}
