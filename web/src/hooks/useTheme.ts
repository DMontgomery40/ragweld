import { useState, useEffect, useCallback } from 'react';
import { useUIStore } from '@/stores/useUIStore';

type ThemeMode = 'light' | 'dark' | 'auto';

/**
 * useTheme Hook
 * Manages theme mode (light/dark/auto) with system preference detection
 * Uses UIStore for persisted state, replaces legacy theme.js
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
          // Avoid String.prototype.replaceAll for ES2020 compatibility.
          s = s.split(k).join(v);
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

  // Initialize theme on mount
  useEffect(() => {
    try {
      // Read from UIStore first (persisted), fallback to localStorage
      const storeMode = useUIStore.getState().themeMode;
      const saved = localStorage.getItem('THEME_MODE') as ThemeMode | null;
      const mode = storeMode || saved || 'auto';

      setTheme(mode);
      applyThemeToDocument(mode);

      console.log('[useTheme] Initialized with mode:', mode);
    } catch (e) {
      console.warn('[useTheme] Failed to initialize:', e);
    }
  }, [applyThemeToDocument]);

  // React to system preference changes when in auto mode
  useEffect(() => {
    if (!window.matchMedia) return;

    const mq = window.matchMedia('(prefers-color-scheme: dark)');

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
