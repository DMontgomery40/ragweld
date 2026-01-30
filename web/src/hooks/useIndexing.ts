import { useState, useCallback } from 'react';
import { useAPI } from './useAPI';

/**
 * useIndexing Hook
 * Manages indexing state and operations for RAG repositories
 * Handles start/stop indexing, progress tracking, and status updates
 */

export interface IndexStatus {
  isRunning: boolean;
  progress: number;
  currentRepo: string;
  message: string;
  error?: string;
}

/**
 * ---agentspec
 * what: |
 *   React hook that manages code repository indexing state and progress tracking.
 *   Takes no parameters; uses useAPI() hook to access the API client.
 *   Returns an object containing: isIndexing (boolean), progress (0-100 number), currentRepo (string), statusMessage (string), and indexStatus (Record mapping repo names to IndexStatus objects).
 *   Maintains local state for indexing operations and provides real-time progress updates during repository scanning/indexing.
 *   Handles multiple repositories with individual status tracking; progress represents overall indexing completion percentage.
 *
 * why: |
 *   Centralizes indexing state management to avoid prop-drilling through component tree.
 *   Separates indexing logic from UI components, allowing multiple components to subscribe to the same indexing state.
 *   Tracks per-repository status independently while maintaining aggregate progress, enabling granular error handling and user feedback.
 *
 * guardrails:
 *   - DO NOT call this hook outside of React functional components; it depends on React hooks context
 *   - ALWAYS initialize indexStatus as empty object to prevent undefined errors when accessing repo entries
 *   - NOTE: This hook does not trigger indexing itself; it only manages state—caller must invoke API methods to start indexing
 *   - NOTE: Progress state is not automatically reset; caller must explicitly call setProgress(0) when starting new indexing session
 *   - ASK USER: Confirm whether indexStatus should persist across component remounts or reset on unmount before adding useEffect cleanup logic
 * ---/agentspec
 */
export function useIndexing() {
  const { api } = useAPI();
  const [isIndexing, setIsIndexing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentRepo, setCurrentRepo] = useState('');
  const [statusMessage, setStatusMessage] = useState('');
  const [indexStatus, setIndexStatus] = useState<Record<string, IndexStatus>>({});

  /**
   * Start indexing a repository
   */
  const startIndexing = useCallback(async (
    repo: string,
    options: {
      skipDense?: boolean;
      enrichChunks?: boolean;
      embeddingType?: string;
    } = {}
  ): Promise<void> => {
    setIsIndexing(true);
    setCurrentRepo(repo);
    setProgress(0);
    setStatusMessage('Starting indexing...');

    try {
      const params = new URLSearchParams({
        repo,
        skip_dense: options.skipDense ? '1' : '0',
        enrich_chunks: options.enrichChunks ? '1' : '0',
        ...(options.embeddingType && { embedding_type: options.embeddingType })
      });

      const response = await fetch(api(`/index/start?${params}`), {
        method: 'POST'
      });

      if (!response.ok) {
        throw new Error(`Failed to start indexing: ${response.statusText}`);
      }

      const data = await response.json();
      setStatusMessage(data.message || 'Indexing started');

      // Start polling for progress
      pollIndexProgress(repo);
    } catch (error) {
      setIsIndexing(false);
      setStatusMessage(`Error: ${error instanceof Error ? error.message : 'Unknown error'}`);
      throw error;
    }
  }, [api]);

  /**
   * Stop indexing process
   */
  const stopIndexing = useCallback(async (): Promise<void> => {
    try {
      const response = await fetch(api('/index/stop'), {
        method: 'POST'
      });

      if (!response.ok) {
        throw new Error(`Failed to stop indexing: ${response.statusText}`);
      }

      setIsIndexing(false);
      setStatusMessage('Indexing stopped');
    } catch (error) {
      setStatusMessage(`Error stopping: ${error instanceof Error ? error.message : 'Unknown error'}`);
      throw error;
    }
  }, [api]);

  /**
   * Poll for indexing progress
   */
  const pollIndexProgress = useCallback((repo: string) => {
    const interval = setInterval(async () => {
      try {
        const response = await fetch(api(`/index/status/${repo}`));
        if (!response.ok) {
          clearInterval(interval);
          setIsIndexing(false);
          return;
        }

        const status = await response.json();

        setProgress(status.progress || 0);
        setStatusMessage(status.message || '');

        // Update index status
        setIndexStatus(prev => ({
          ...prev,
          [repo]: {
            isRunning: status.running || false,
            progress: status.progress || 0,
            currentRepo: repo,
            message: status.message || '',
            error: status.error
          }
        }));

        // Check if complete
        if (status.complete || status.progress >= 100 || !status.running) {
          clearInterval(interval);
          setIsIndexing(false);
          setProgress(100);
          setStatusMessage(status.message || 'Indexing complete');
        }
      } catch (error) {
        clearInterval(interval);
        setIsIndexing(false);
        setStatusMessage(`Error: ${error instanceof Error ? error.message : 'Unknown error'}`);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [api]);

  /**
   * Get index info for a repository
   */
  const getIndexInfo = useCallback(async (repo: string): Promise<any> => {
    try {
      const response = await fetch(api(`/index/info/${repo}`));
      if (!response.ok) {
        throw new Error(`Failed to get index info: ${response.statusText}`);
      }
      return await response.json();
    } catch (error) {
      console.error('Error getting index info:', error);
      return null;
    }
  }, [api]);

  /**
   * Apply an index profile
   */
  const applyIndexProfile = useCallback(async (profile: string): Promise<void> => {
    try {
      const response = await fetch(api(`/index/profile/${profile}`), {
        method: 'POST'
      });

      if (!response.ok) {
        throw new Error(`Failed to apply profile: ${response.statusText}`);
      }

      const data = await response.json();
      setStatusMessage(data.message || `Profile ${profile} applied`);
    } catch (error) {
      setStatusMessage(`Error: ${error instanceof Error ? error.message : 'Unknown error'}`);
      throw error;
    }
  }, [api]);

  return {
    isIndexing,
    progress,
    currentRepo,
    statusMessage,
    indexStatus,
    startIndexing,
    stopIndexing,
    getIndexInfo,
    applyIndexProfile
  };
}
