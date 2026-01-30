import { useState, useCallback, useMemo } from 'react';
import { MCPRagService, MCPRagResponse, MCPRagResult } from '../services/MCPRagService';
import { useAPI } from './useAPI';

/**
 * useMCPRag Hook
 * React hook for MCP RAG search operations
 * Converted from /web/src/modules/mcp_rag.js
 */
/**
 * ---agentspec
 * what: |
 *   Custom React hook that provides MCP (Model Context Protocol) RAG (Retrieval-Augmented Generation) search functionality.
 *   Takes no parameters; uses apiBase from useAPI() context to initialize MCPRagService.
 *   Returns an object containing: isSearching (boolean), results (MCPRagResult[] array), error (string | null), and an implied search function (incomplete in provided code).
 *   Manages three pieces of state: loading indicator, search results array, and error messages.
 *   Edge case: If apiBase changes, service is recreated via useMemo dependency; if search is called before service initializes, behavior is undefined.
 *
 * why: |
 *   Encapsulates MCP RAG service initialization and state management into a reusable hook to avoid boilerplate in components.
 *   Uses useMemo to prevent unnecessary service recreation on every render, improving performance.
 *   Separates concerns: API context handling, service instantiation, and UI state are isolated within the hook.
 *
 * guardrails:
 *   - DO NOT expose the MCPRagService instance directly; only expose state and a search method to maintain encapsulation
 *   - ALWAYS include a search function in the return object; the current code is incomplete and missing the actual search handler
 *   - NOTE: The hook is incomplete; the JSDoc comment is cut off and no search/mutation function is defined or returned
 *   - ASK USER: Confirm the intended signature of the search function (parameters, return type, error handling) before completing this hook
 * ---/agentspec
 */
export function useMCPRag() {
  const { apiBase } = useAPI();
  const service = useMemo(() => new MCPRagService(apiBase), [apiBase]);

  const [isSearching, setIsSearching] = useState(false);
  const [results, setResults] = useState<MCPRagResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  /**
   * Execute RAG search
   */
  const search = useCallback(async (
    query: string,
    options: {
      repo?: string;
      top_k?: number;
      force_local?: boolean;
    } = {}
  ): Promise<MCPRagResponse> => {
    setIsSearching(true);
    setError(null);

    try {
      const response = await service.search(query, options);

      if (response.results) {
        setResults(response.results);
      }

      if (response.error) {
        setError(response.error);
      }

      return response;
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Search failed';
      setError(errorMsg);
      throw err;
    } finally {
      setIsSearching(false);
    }
  }, [service]);

  /**
   * Format results for display
   */
  const formatResults = useCallback((resultsToFormat?: MCPRagResult[]): string[] => {
    const data = resultsToFormat || results;
    return service.formatResults(data);
  }, [service, results]);

  /**
   * Clear results
   */
  const clearResults = useCallback(() => {
    setResults([]);
    setError(null);
  }, []);

  return {
    isSearching,
    results,
    error,
    search,
    formatResults,
    clearResults
  };
}
