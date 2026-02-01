import axios, { AxiosInstance, AxiosError } from 'axios';

/**
 * Resolve API base URL - same logic as useAPI hook
 * Ensures consistency across axios and fetch-based API calls
 */
function resolveAPIBase(): string {
  try {
    const u = new URL(window.location.href);
    const q = new URLSearchParams(u.search);
    const override = q.get('api');
    if (override) return override.replace(/\/$/, '');
    
    // If on the Vite dev server (ports 5170-5179), use same-origin `/api`
    // so Vite's proxy can forward to the backend without CORS issues.
    const port = u.port || '';
    if (port && /^517[0-9]$/.test(port)) {
      return u.origin + '/api';
    }
    
    // If the protocol is http/https but not Vite dev port, use the same origin
    if (u.protocol.startsWith('http')) {
      return (u.origin.replace(/\/$/, '')) + '/api';
    }
    
    // Default fallback to local backend
    return 'http://127.0.0.1:8012/api';
  } catch {
    // Always return a valid base URL, never empty
    return 'http://127.0.0.1:8012/api';
  }
}

// TODO:  THIS SHOULD BE PYDANTIC
const API_BASE = import.meta.env.VITE_API_BASE || resolveAPIBase();

// Create axios instance with defaults
export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE || 'http://127.0.0.1:8012/api', // Final fallback to prevent empty baseURL
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    console.error('[API Error]', error.message, error.response?.data);
    return Promise.reject(error);
  }
);

// Helper to build API paths for axios (relative to baseURL)
export const api = (path: string): string => {
  return path.startsWith('/') ? path : `/${path}`;
};

// Helper to build full API URLs for fetch
// Handles paths like '/api/models' or '/models' or 'models'
export const apiUrl = (path: string): string => {
  const p = String(path || '');
  // If path starts with /api/, strip it since API_BASE already ends with /api
  if (p.startsWith('/api/')) return `${API_BASE}${p.slice(4)}`;
  // If path starts with /, append directly
  if (p.startsWith('/')) return `${API_BASE}${p}`;
  // Otherwise add leading slash
  return `${API_BASE}/${p}`;
};

// Expose window.CoreUtils for legacy JS modules during migration
// This replaces /modules/core-utils.js
if (typeof window !== 'undefined') {
  // Legacy state object - kept for modules that still access it
  // New code should use Zustand stores (useConfigStore, useRepoStore)
  const legacyState = {
    models: null as any,
    config: null as any,
    profiles: [] as any[],
    defaultProfile: null as any,
  };

  (window as any).CoreUtils = {
    API_BASE,
    api: apiUrl, // Legacy modules expect api() to return full URL
    $: (sel: string) => document.querySelector(sel),
    $$: (sel: string) => Array.from(document.querySelectorAll(sel)),
    state: legacyState
  };

  // Also expose API_BASE directly on window for diagnostics
  (window as any).API_BASE = API_BASE;

  console.log('[CoreUtils] Loaded from TypeScript client - API:', API_BASE);
}
