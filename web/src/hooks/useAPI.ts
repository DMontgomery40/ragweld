import { useCallback, useMemo } from 'react';
import { apiClient, apiUrl } from '@/api/client';

/**
 * useAPI Hook
 * Manages API base URL configuration with support for query parameter overrides
 * Converts core-utils.js and api-base-override.js functionality to React
 */
export function useAPI() {
  // Single HTTP boundary: `api/client.ts` owns baseURL resolution.
  const apiBase = useMemo(() => String(apiClient.defaults.baseURL || ''), []);

  // Helper to build full API URLs for `fetch(...)` call sites.
  const api = useCallback((path: string = ''): string => apiUrl(path), []);

  return {
    apiBase,
    api
  };
}
