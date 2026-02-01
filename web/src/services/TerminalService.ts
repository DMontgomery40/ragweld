/**
 * Terminal Service - Real-time log streaming via SSE
 * Connects to backend endpoints for REAL logs, not fake placeholder shit
 */

import { apiUrl } from '@/api/client';

interface TerminalInstance {
  id: string;
  sse?: EventSource;
  onLine?: (line: string) => void;
  onProgress?: (percent: number, message: string) => void;
  onError?: (error: string) => void;
  onComplete?: () => void;
}

class TerminalServiceClass {
  private terminals: Map<string, TerminalInstance> = new Map();
  private baseUrl: string;

  constructor() {
    // Use relative URL to avoid CORS issues and work with the same origin
    this.baseUrl = '';
  }

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
    }
  ): void {
    const { onLine, onProgress, onError, onComplete, ...queryParams } = params;

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
    this.connectToStream(terminalId, endpoint, { onLine, onProgress, onError, onComplete });
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
      onComplete?: () => void;
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
   * Connect to WebSocket for bidirectional communication
   */
  connectWebSocket(
    terminalId: string,
    endpoint: string,
    callbacks: {
      onLine?: (line: string) => void;
      onProgress?: (percent: number, message: string) => void;
      onError?: (error: string) => void;
      onComplete?: () => void;
    }
  ): void {
    const wsUrl = `${this.baseUrl.replace('http', 'ws')}/ws/${endpoint}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log(`[TerminalService] WebSocket connected for ${terminalId}`);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        switch (data.type) {
          case 'log':
            callbacks.onLine?.(data.message);
            break;
          case 'progress':
            callbacks.onProgress?.(data.percent, data.message);
            break;
          case 'error':
            callbacks.onError?.(data.message);
            callbacks.onLine?.(`\x1b[31mERROR: ${data.message}\x1b[0m`);
            break;
          case 'complete':
            callbacks.onComplete?.();
            ws.close();
            break;
        }
      } catch (e) {
        callbacks.onLine?.(event.data);
      }
    };

    ws.onerror = (error) => {
      console.error(`[TerminalService] WebSocket error for ${terminalId}:`, error);
      callbacks.onError?.('Connection failed');
    };

    ws.onclose = () => {
      console.log(`[TerminalService] WebSocket closed for ${terminalId}`);
      this.terminals.delete(terminalId);
    };

    // Store WebSocket reference
    this.terminals.set(terminalId, {
      id: terminalId,
      ...callbacks
    });
  }

  /**
   * Stream logs from a specific operation
   */
  streamOperation(
    terminalId: string,
    operation: string,
    callbacks: {
      onLine?: (line: string) => void;
      onProgress?: (percent: number, message: string) => void;
      onError?: (error: string) => void;
      onComplete?: () => void;
      [key: string]: any; // Allow additional params like backend
    }
  ): void {
    const { onLine, onProgress, onError, onComplete, ...params } = callbacks;
    const queryParams = params && Object.keys(params).length ? '?' + new URLSearchParams(params).toString() : '';
    const endpoint = `operations/${operation}${queryParams}`;

    this.connectToStream(terminalId, endpoint, {
      onLine,
      onProgress,
      onError,
      onComplete
    });
  }

  /**
   * Stream Docker logs
   */
  streamDockerLogs(terminalId: string, container?: string): void {
    const endpoint = container ? `docker/logs/${container}` : 'docker/logs';

    this.connectToStream(terminalId, endpoint, {
      onLine: (line) => {
        const terminal = (window as any)[`terminal_${terminalId}`];
        terminal?.appendLine?.(line);
      }
    });
  }

  /**
   * Stream build logs (cards, reranker, etc)
   */
  streamBuildLogs(
    terminalId: string,
    buildType: 'cards' | 'reranker' | 'index',
    repo?: string
  ): void {
    const endpoint = `builds/${buildType}${repo ? `?repo=${encodeURIComponent(repo)}` : ''}`;

    this.connectToStream(terminalId, endpoint, {
      onLine: (line) => {
        const terminal = (window as any)[`terminal_${terminalId}`];
        terminal?.appendLine?.(line);
      },
      onProgress: (percent, message) => {
        const terminal = (window as any)[`terminal_${terminalId}`];
        terminal?.updateProgress?.(percent, message);

        // Update progress elements if they exist
        const progressBar = document.querySelector(`#${buildType}-progress-bar`);
        if (progressBar) {
          (progressBar as HTMLElement).style.width = `${percent}%`;
        }
        const progressText = document.querySelector(`#${buildType}-progress-percent`);
        if (progressText) {
          progressText.textContent = `${Math.round(percent)}%`;
        }
      }
    });
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

  /**
   * Disconnect all terminals
   */
  disconnectAll(): void {
    this.terminals.forEach((_, id) => this.disconnect(id));
  }
}

export const TerminalService = new TerminalServiceClass();
