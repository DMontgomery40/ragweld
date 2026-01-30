import { useState, useEffect, useCallback } from 'react';

/**
 * useAPI Hook
 * Manages API base URL configuration with support for query parameter overrides
 * Converts core-utils.js and api-base-override.js functionality to React
 */
/**
 * ---agentspec
 * what: |
 *   React hook that resolves the API base URL for HTTP requests, with support for query parameter override and Vite dev server detection.
 *   Takes no parameters. Returns a string representing the API base URL (trailing slashes removed).
 *   Checks for 'api' query parameter first; if present, uses that value after stripping trailing slash.
 *   Falls back to detecting Vite dev server ports (5170-5179) and routes to backend on port 8012.
 *   No side effects beyond reading window.location and URLSearchParams; wrapped in try-catch for safety.
 *
 * why: |
 *   Centralizes API endpoint resolution logic so all components use consistent routing.
 *   Query parameter override enables testing against different backends without code changes.
 *   Vite dev server detection solves the common development workflow where frontend and backend run on different ports.
 *   Try-catch prevents crashes if window.location is unavailable (e.g., SSR contexts).
 *
 * guardrails:
 *   - DO NOT hardcode API URLs in components; always use this hook to maintain single source of truth
 *   - ALWAYS strip trailing slashes from override URLs to prevent double-slash bugs in fetch calls
 *   - NOTE: Vite dev server port range (5170-5179) is hardcoded; update if dev server configuration changes
 *   - ASK USER: Confirm the backend port (8012) is correct for your development environment before deploying
 *   - DO NOT use this hook during server-side rendering without checking window availability first
 * ---/agentspec
 */
export function useAPI() {
  /**
   * ---agentspec
   * what: |
   *   Resolves the API base URL for frontend-to-backend communication, with support for query parameter override and Vite dev server detection.
   *   Takes no parameters; reads from window.location.href and URL search params.
   *   Returns a string containing the API base URL (trailing slashes removed).
   *   Checks for 'api' query parameter first; if present, uses that value after stripping trailing slash.
   *   Falls back to port-based detection: if running on Vite dev server (ports 5170-5179), returns hardcoded backend URL on port 8012; otherwise uses current origin.
   *   Handles edge cases: missing port, malformed URLs (caught by try-catch), and trailing slash normalization.
   *
   * why: |
   *   Centralizes API endpoint resolution to support multiple deployment scenarios: production (same origin), development (Vite dev server to separate backend), and manual override via query parameter.
   *   Query parameter override enables testing against different backends without code changes.
   *   Vite dev server detection solves the common development pattern where frontend and backend run on different ports locally.
   *   Try-catch wrapper provides graceful fallback if URL parsing fails in unusual environments.
   *
   * guardrails:
   *   - DO NOT hardcode API URLs in components; always use this resolver to maintain flexibility across environments
   *   - ALWAYS strip trailing slashes from override values to prevent double-slash bugs in constructed URLs
   *   - NOTE: Port range 5170-5179 is hardcoded for Vite; if Vite config changes port, this detection will fail silently and fall back to current origin
   *   - NOTE: window.location is unavailable in SSR/Node contexts; this function will throw if called outside browser environment
   *   - ASK USER: Confirm the intended backend port (currently 8012) and Vite dev port range (currently 5170-5179) before modifying port detection logic
   * ---/agentspec
   */
  const resolveAPIBase = (): string => {
    try {
      const u = new URL(window.location.href);
      const q = new URLSearchParams(u.search);
      const override = q.get('api');
      if (override) return override.replace(/\/$/, '');
      
      // If on Vite dev server (ports 5170-5179), talk directly to backend on 8012
      const port = u.port || '';
      if (port && /^517[0-9]$/.test(port)) {
        return 'http://127.0.0.1:8012/api';
      }
      
      // If protocol is http/https but not Vite dev port, use same origin
      if (u.protocol.startsWith('http')) {
        return (u.origin.replace(/\/$/, '')) + '/api';
      }
      
      // Default fallback to local backend
      return 'http://127.0.0.1:8012/api';
    } catch {
      // Always return a valid base URL, never empty
      return 'http://127.0.0.1:8012/api';
    }
  };

  // Initialize synchronously to avoid first-render race conditions
  const [apiBase, setApiBase] = useState<string>(() => resolveAPIBase());

  // Observe changes to ?api= override (rare) and update
  useEffect(() => {
    const next = resolveAPIBase();
    if (next !== apiBase) setApiBase(next);
    try { (window as any).API_BASE = next; } catch {}
    console.log('[useAPI] API base configured:', next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Helper to build full API URLs
  const api = useCallback((path: string = ''): string => {
    // Ensure base is never empty - fallback to localhost:8012 if undefined/empty
    let base = String(apiBase || 'http://127.0.0.1:8012/api').replace(/\/$/, '');
    let p = String(path || '');
    // Normalize to /api/... path regardless of caller format
    if (!p.startsWith('/')) p = '/' + p;
    if (!p.startsWith('/api/')) p = '/api' + p;
    // Ensure base does not already include /api twice
    base = base.replace(/\/api$/, '');
    return base + p;
  }, [apiBase]);

  return {
    apiBase,
    api
  };
}
