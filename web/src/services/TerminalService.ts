/**
 * Terminal Service - Real-time log streaming via SSE
 * Connects to backend endpoints for REAL logs, not fake placeholder shit
 */

import { apiUrl } from '@/api/client';

/**
 * A stream error marked `(retrying)` is a transient status, not a failure.
 *
 * The producer is still connected and still trying (the Loki tail while the box is busy
 * re-resolves for two minutes before it gives up), so rendering it as a red ERROR made a
 * self-healing stream look dead until the operator reloaded the page. The marker is part of
 * the SSE contract with those producers, not a guess about wording.
 */
export function isTransientStreamStatus(message: unknown): boolean {
  return typeof message === 'string' && /\(retrying\)\s*$/.test(message.trim());
}

interface TerminalInstance {
  id: string;
  sse?: EventSource;
  onLine?: (line: string) => void;
  onProgress?: (percent: number, message: string) => void;
  onError?: (error: string) => void;
  onComplete?: () => void;
  onCancelled?: () => void;
}

class TerminalServiceClass {
  private terminals: Map<string, TerminalInstance> = new Map();

  /**
   * Stream evaluation run logs (raw stdout) via dedicated SSE endpoint
   */
  streamEvalRun(
    terminalId: string,
    params: {
      corpus_id: string;
      use_multi?: boolean;
      final_k?: number;
      sample_limit?: number;
      onLine?: (line: string) => void;
      onProgress?: (percent: number, message: string) => void;
      onError?: (error: string) => void;
      onComplete?: () => void;
    }
  ): void {
    // Close existing connection if any
    this.disconnect(terminalId);

    const { onLine, onProgress, onError, onComplete, ...queryParams } = params;
    const qs = new URLSearchParams();
    Object.entries(queryParams).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        const encoded = typeof value === 'boolean' ? (value ? 1 : 0) : value;
        qs.append(key, String(encoded));
      }
    });
    const url = apiUrl(`/api/eval/run/stream${qs.toString() ? `?${qs.toString()}` : ''}`);
    console.log('[TerminalService] Creating EventSource for URL:', url);

    const sse = new EventSource(url);
    const terminal: TerminalInstance = { id: terminalId, sse, onLine, onProgress, onError, onComplete };

    sse.onopen = () => {
      console.log('[TerminalService] SSE connection opened for', terminalId);
    };

    sse.onmessage = (event) => {
      console.log('[TerminalService] SSE message received:', event.data);
      try {
        const data = JSON.parse(event.data);
        switch (data.type) {
          case 'log':
            onLine?.(data.message);
            break;
          case 'progress':
            onProgress?.(data.percent, data.message || '');
            break;
          case 'error':
            onError?.(data.message);
            onLine?.(`\x1b[31mERROR: ${data.message}\x1b[0m`);
            break;
          case 'complete':
            onComplete?.();
            this.disconnect(terminalId);
            break;
          default:
            if (data.message) {
              onLine?.(data.message);
            }
        }
      } catch (_) {
        onLine?.(event.data);
      }
    };

    sse.onerror = (error) => {
      console.error(`[TerminalService] SSE error for ${terminalId}:`, error);
      onError?.('Connection lost');
      this.disconnect(terminalId);
    };

    this.terminals.set(terminalId, terminal);
  }

  /**
   * Stream indexer run with raw logs and progress
   */
  streamIndexRun(
    terminalId: string,
    params: {
      repo?: string;
      skip_dense?: boolean;
      enrich?: boolean;
      onLine?: (line: string) => void;
      onProgress?: (percent: number, message: string) => void;
      onError?: (error: string) => void;
      onComplete?: () => void;
      onCancelled?: () => void;
    }
  ): void {
    const { onLine, onProgress, onError, onComplete, onCancelled, ...queryParams } = params;

    // Backend SSE for index logs is:
    //   GET /api/stream/operations/index?corpus_id=...
    // (CorpusScope also accepts legacy repo/repo_id query params.)
    const qs = new URLSearchParams();
    Object.entries(queryParams).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        const encoded = typeof value === 'boolean' ? (value ? 1 : 0) : value;
        if (key === 'repo') {
          qs.append('corpus_id', String(encoded));
        } else {
          qs.append(key, String(encoded));
        }
      }
    });

    const endpoint = `operations/index${qs.toString() ? `?${qs.toString()}` : ''}`;
    this.connectToStream(terminalId, endpoint, { onLine, onProgress, onError, onComplete, onCancelled });
  }

  /**
   * Connect to a log stream via SSE
   */
  connectToStream(
    terminalId: string,
    endpoint: string,
    callbacks: {
      onLine?: (line: string) => void;
      onProgress?: (percent: number, message: string) => void;
      onError?: (error: string) => void;
      /** A `(retrying)` status: the stream is still open and the producer is still trying. */
      onTransient?: (message: string) => void;
      onComplete?: () => void;
      onCancelled?: () => void;
    }
  ): void {
    // Close existing connection if any
    this.disconnect(terminalId);

    const url = apiUrl(`/api/stream/${endpoint}`);
    const sse = new EventSource(url);

    const terminal: TerminalInstance = {
      id: terminalId,
      sse,
      ...callbacks
    };

    // Handle incoming messages
    sse.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        // Handle different message types
        switch (data.type) {
          case 'log':
            if (callbacks.onLine) {
              callbacks.onLine(data.message);
            }
            break;

          case 'progress':
            if (callbacks.onProgress) {
              callbacks.onProgress(data.percent, data.message || '');
            }
            break;

          case 'error':
            if (isTransientStreamStatus(data.message)) {
              // Muted, not red, and no onError: the stream is still open.
              if (callbacks.onTransient) {
                callbacks.onTransient(data.message);
              }
              if (callbacks.onLine) {
                callbacks.onLine(`\x1b[90m${data.message}\x1b[0m`);
              }
              break;
            }
            if (callbacks.onError) {
              callbacks.onError(data.message);
            }
            if (callbacks.onLine) {
              callbacks.onLine(`\x1b[31mERROR: ${data.message}\x1b[0m`);
            }
            break;

          case 'complete':
            if (callbacks.onComplete) {
              callbacks.onComplete();
            }
            this.disconnect(terminalId);
            break;

          case 'cancelled':
            if (callbacks.onCancelled) {
              callbacks.onCancelled();
            }
            this.disconnect(terminalId);
            break;

          default:
            // Default to treating as log line
            if (callbacks.onLine && data.message) {
              callbacks.onLine(data.message);
            }
        }
      } catch (e) {
        // If not JSON, treat as plain text log
        if (callbacks.onLine) {
          callbacks.onLine(event.data);
        }
      }
    };

    sse.onerror = (error) => {
      console.error(`[TerminalService] SSE error for ${terminalId}:`, error);
      if (callbacks.onError) {
        callbacks.onError('Connection lost');
      }
      this.disconnect(terminalId);
    };

    this.terminals.set(terminalId, terminal);
  }

  /**
   * Disconnect a terminal
   */
  disconnect(terminalId: string): void {
    const terminal = this.terminals.get(terminalId);
    if (terminal?.sse) {
      terminal.sse.close();
    }
    this.terminals.delete(terminalId);
  }
}

export const TerminalService = new TerminalServiceClass();
