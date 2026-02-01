export type DockRenderMode = 'native' | 'iframe';

// Default render mode per top-level route path.
// Forced iframe fallback for tabs that touch window.location / window.history directly.
export const DOCK_DEFAULT_MODE_BY_PATH: Record<string, DockRenderMode> = {
  '/start': 'native',
  '/dashboard': 'native',
  '/chat': 'native',
  '/grafana': 'native',
  '/rag': 'native',
  '/eval': 'iframe',
  '/infrastructure': 'iframe',
  '/admin': 'native',
  '/docker': 'native',
};

// Recommended entries shown at the top of the picker.
export const DOCK_RECOMMENDED_BY_PATH: Record<string, boolean> = {
  '/start': false,
  '/dashboard': true,
  '/chat': true,
  '/grafana': false,
  '/rag': true,
  '/eval': false,
  '/infrastructure': false,
  '/admin': true,
  '/docker': false,
};

