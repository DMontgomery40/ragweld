import { useCallback, useMemo } from 'react';
import { apiClient, apiUrl } from '@/api/client';

/**
 * useAPI Hook
 * Manages API base URL configuration with support for query parameter overrides
 * Converts core-utils.js and api-base-override.js functionality to React
 */
/**
 * ---agentspec
 * what: |
 *   React hook that exposes the API base URL and URL builder owned by api/client.ts.
 *   Takes no parameters. Returns a string representing the API base URL (trailing slashes removed).
 *   The shared resolver honors an 'api' query override, otherwise uses same-origin /api.
 *   No side effects beyond reading window.location and URLSearchParams; wrapped in try-catch for safety.
 *
 * why: |
 *   Centralizes API endpoint resolution logic so all components use consistent routing.
 *   Query parameter override enables testing against different backends without code changes.
 *   Vite forwards same-origin /api calls to the backend resolved by start.sh.
 *   Try-catch prevents crashes if window.location is unavailable (e.g., SSR contexts).
 *
 * guardrails:
 *   - DO NOT hardcode API URLs in components; always use this hook to maintain single source of truth
 *   - ALWAYS strip trailing slashes from override URLs to prevent double-slash bugs in fetch calls
 *   - NOTE: start.sh and web/vite.config.ts own local port and proxy configuration
 *   - DO NOT use this hook during server-side rendering without checking window availability first
 * ---/agentspec
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
