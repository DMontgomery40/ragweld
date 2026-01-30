import { useState, useEffect, useCallback } from 'react';
import { useUIStore } from '@/stores/useUIStore';

type ThemeMode = 'light' | 'dark' | 'auto';

/**
 * useTheme Hook
 * Manages theme mode (light/dark/auto) with system preference detection
 * Uses UIStore for persisted state, replaces legacy theme.js
 */
/**
 * ---agentspec
 * what: |
 *   React hook that manages theme state with support for 'auto', 'light', and 'dark' modes.
 *   Takes no parameters; initializes theme to 'auto' and resolvedTheme to 'light'.
 *   Returns an object with theme (ThemeMode), setTheme (setter), and resolvedTheme ('light' | 'dark').
 *   The resolveTheme callback converts 'auto' mode to the actual system preference (light or dark).
 *   Handles edge cases: normalizes input to lowercase, defaults to 'auto' if mode is falsy, and gracefully falls back to 'light' for unrecognized values.
 *
 * why: |
 *   Separates user preference (theme) from computed system-aware value (resolvedTheme) to support both explicit and automatic theme selection.
 *   The resolveTheme callback enables lazy resolution of system preferences without requiring immediate DOM or window API access.
 *   This pattern allows components to read the current theme while deferring system detection to effect hooks or event listeners.
 *
 * guardrails:
 *   - DO NOT call resolveTheme directly in render; it should only be invoked in useEffect or event handlers to avoid unnecessary recalculations
 *   - ALWAYS normalize theme input to lowercase before comparison to prevent case-sensitivity bugs
 *   - NOTE: resolvedTheme defaults to 'light' but does not actually detect system preference; system detection logic must be implemented in a separate useEffect hook
 *   - ASK USER: Confirm whether system preference detection (via window.matchMedia or prefers-color-scheme) should be added to this hook or handled by a parent component
 * ---/agentspec
 */
export function useTheme() {
  const [theme, setTheme] = useState<ThemeMode>('auto');
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>('light');

  // Resolve 'auto' to actual light/dark based on system preference
  const resolveTheme = useCallback((mode: ThemeMode): 'light' | 'dark' => {
    const m = String(mode || 'auto').toLowerCase();
    if (m === 'light' || m === 'dark') return m as 'light' | 'dark';

    const prefersDark = window.matchMedia &&
                       window.matchMedia('(prefers-color-scheme: dark)').matches;
    return prefersDark ? 'dark' : 'light';
  }, []);

  // Apply theme to document
  const applyThemeToDocument = useCallback((mode: ThemeMode) => {
    const resolved = resolveTheme(mode);
    try {
      document.documentElement.setAttribute('data-theme', resolved);
      setResolvedTheme(resolved);
    } catch (e) {
      console.warn('[useTheme] Failed to apply theme:', e);
    }

    // Best-effort normalize legacy inline styles to CSS variables
    try {
      const mappings: [string, string][] = [
        ['var(--card-bg)', 'var(--card-bg)'],
        ['var(--code-bg)', 'var(--code-bg)'],
        ['var(--panel)', 'var(--panel-bg)'],
        ['var(--bg-elev2)', 'var(--bg-elev2)'],
        ['var(--line)', 'var(--line)'],
        ['var(--fg-muted)', 'var(--fg-muted)'],
        ['#ddd', 'var(--fg)'],
        ['#ffffff', 'var(--fg)'],
        ['var(--link)', 'var(--link)'],
        ['var(--accent)', 'var(--accent)'],
        ['#ff9b5e', 'var(--accent)'],
        ['var(--err)', 'var(--err)']
      ];

      const selector = mappings.map(([k]) => `[style*="${k}"]`).join(', ');
      const nodes = document.querySelectorAll(selector);

      nodes.forEach(el => {
        let s = el.getAttribute('style') || '';
        mappings.forEach(([k, v]) => {
          s = s.replaceAll(k, v);
        });
        el.setAttribute('style', s);
      });
    } catch {}
  }, [resolveTheme]);

  // Apply theme when mode changes
  const applyTheme = useCallback((newMode: ThemeMode) => {
    try {
      localStorage.setItem('THEME_MODE', newMode);
      setTheme(newMode);
      applyThemeToDocument(newMode);

      // Expose to window for backwards compatibility during migration
      if ((window as any).Theme) {
        (window as any).Theme.currentMode = newMode;
      }
    } catch (e) {
      console.warn('[useTheme] Failed to save theme:', e);
    }
  }, [applyThemeToDocument]);

  // Toggle through theme modes: dark -> light -> auto -> dark
  const toggleTheme = useCallback(() => {
    const next: ThemeMode = theme === 'dark' ? 'light' :
                           theme === 'light' ? 'auto' : 'dark';
    applyTheme(next);
  }, [theme, applyTheme]);

  // Initialize theme from config/localStorage - called by legacy config.js
  const initThemeFromEnv = useCallback((env?: { THEME_MODE?: ThemeMode }) => {
    try {
      const saved = localStorage.getItem('THEME_MODE') as ThemeMode | null;
      const configMode = env?.THEME_MODE;
      const mode = saved || configMode || 'auto';

      setTheme(mode);
      applyThemeToDocument(mode);

      // Sync with UIStore
      useUIStore.getState().setThemeMode(mode);

      // Update selectors if present
      const selTop = document.querySelector('#theme-mode') as HTMLSelectElement | null;
      const selMisc = document.querySelector('#misc-theme-mode') as HTMLSelectElement | null;
      if (selTop) selTop.value = mode;
      if (selMisc) selMisc.value = mode;

      console.log('[useTheme] Initialized from config with mode:', mode);
    } catch (e) {
      console.warn('[useTheme] Failed to initialize from config:', e);
    }
  }, [applyThemeToDocument]);

  // Initialize theme on mount
  useEffect(() => {
    try {
      // Read from UIStore first (persisted), fallback to localStorage
      const storeMode = useUIStore.getState().themeMode;
      const saved = localStorage.getItem('THEME_MODE') as ThemeMode | null;
      const mode = storeMode || saved || 'auto';

      setTheme(mode);
      applyThemeToDocument(mode);

      // Expose to window for backwards compatibility with legacy modules
      (window as any).Theme = {
        resolveTheme,
        applyTheme,
        toggleTheme,
        initThemeFromEnv,
        currentMode: mode
      };

      console.log('[useTheme] Initialized with mode:', mode);
    } catch (e) {
      console.warn('[useTheme] Failed to initialize:', e);
    }
  }, [applyThemeToDocument, resolveTheme, applyTheme, toggleTheme, initThemeFromEnv]);

  // React to system preference changes when in auto mode
  useEffect(() => {
    if (!window.matchMedia) return;

    const mq = window.matchMedia('(prefers-color-scheme: dark)');

    /**
     * ---agentspec
     * what: |
     *   Registers a media query change listener that reapplies the theme when the system preference changes in 'auto' mode.
     *   Takes no parameters; operates on closure variables `theme` and `mq` (MediaQueryList object).
     *   Returns a cleanup function that removes the event listener.
     *   Only triggers theme reapplication if `theme === 'auto'`; does nothing if theme is explicitly set to 'light' or 'dark'.
     *   Edge case: If `mq` is undefined or `addEventListener` fails, the try-catch silently swallows the error without logging or fallback behavior.
     *
     * why: |
     *   Enables responsive theme switching when the system toggles between light/dark mode, but only when the user has selected 'auto' mode.
     *   The cleanup function ensures the listener is removed when the component unmounts, preventing memory leaks and stale closures.
     *   Wrapping in try-catch prevents listener registration failures from crashing the component, though this masks potential bugs.
     *
     * guardrails:
     *   - DO NOT remove the cleanup function return; it is essential for preventing duplicate listeners and memory leaks on re-renders
     *   - ALWAYS verify that `mq` (MediaQueryList) is properly initialized before this code runs; undefined `mq` will silently fail
     *   - NOTE: The try-catch silently fails without logging; consider adding console.error or error tracking for debugging listener registration failures
     *   - ASK USER: Should explicit theme modes ('light'/'dark') also trigger a listener, or is 'auto'-only behavior intentional?
     * ---/agentspec
     */
    const onChange = () => {
      if (theme === 'auto') {
        applyThemeToDocument('auto');
      }
    };

    try {
      mq.addEventListener('change', onChange);
      return () => mq.removeEventListener('change', onChange);
    } catch {
      // Fallback for older browsers
      try {
        mq.addListener(onChange);
        return () => mq.removeListener(onChange);
      } catch {}
    }
  }, [theme, applyThemeToDocument]);

  return {
    theme,
    resolvedTheme,
    applyTheme,
    toggleTheme
  };
}
