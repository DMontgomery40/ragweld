import { useState, useCallback, useMemo, useEffect } from 'react';
import { KeywordsService, KeywordsCatalog } from '../services/KeywordsService';
import { useAPI } from './useAPI';

/**
 * useKeywords Hook
 * React hook for managing discriminative keywords
 * Converted from /web/src/modules/keywords.js
 */
/**
 * ---agentspec
 * what: |
 *   React hook that manages keyword catalog state and provides access to a KeywordsService instance.
 *   Takes no parameters; uses apiBase from useAPI() context to initialize KeywordsService via useMemo.
 *   Returns an object containing: catalog (KeywordsCatalog | null), isLoading (boolean), and service (KeywordsService).
 *   Initializes catalog as null and isLoading as false on mount.
 *   Memoizes service creation to prevent unnecessary reinstantiation when apiBase remains stable.
 *
 * why: |
 *   Centralizes keyword catalog management in a reusable hook to avoid duplicating state logic across components.
 *   Memoization of KeywordsService ensures the service instance is only recreated when apiBase changes, reducing unnecessary object allocations.
 *   Separating service creation from state management allows components to access both the service and catalog state through a single hook.
 *
 * guardrails:
 *   - DO NOT call useKeywords() outside of React components; it violates the Rules of Hooks
 *   - ALWAYS ensure useAPI() is available in the component tree before calling useKeywords()
 *   - NOTE: catalog state is initialized as null; components must handle null checks before rendering catalog data
 *   - ASK USER: Confirm the intended behavior for error handling when KeywordsService initialization fails or apiBase is undefined
 * ---/agentspec
 */
export function useKeywords() {
  const { apiBase } = useAPI();
  const service = useMemo(() => new KeywordsService(apiBase), [apiBase]);

  const [catalog, setCatalog] = useState<KeywordsCatalog | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  /**
   * Load keywords catalog
   */
  const loadKeywords = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await service.loadKeywords();
      setCatalog(data);
    } catch (error) {
      console.error('[useKeywords] Failed to load keywords:', error);
    } finally {
      setIsLoading(false);
    }
  }, [service]);

  /**
   * Filter keywords
   */
  const filterKeywords = useCallback((
    category: string = 'all',
    filter: string = '',
    excludeSet: Set<string> = new Set()
  ): string[] => {
    if (!catalog) return [];
    return service.filterKeywords(catalog, category, filter, excludeSet);
  }, [catalog, service]);

  /**
   * Get keyword count
   */
  const getCount = useCallback((): number => {
    return catalog?.keywords?.length || 0;
  }, [catalog]);

  /**
   * Initialize on mount
   */
  useEffect(() => {
    loadKeywords();
  }, [loadKeywords]);

  return {
    catalog,
    isLoading,
    loadKeywords,
    filterKeywords,
    getCount
  };
}
