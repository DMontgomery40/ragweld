import { useState, useEffect, useCallback, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { SearchResult, SettingSearchItem } from '../types';
import { useAPI } from './useAPI';

/**
 * useGlobalSearch Hook
 * Converts search.js functionality to React
 *
 * Features:
 * - Ctrl+K / Cmd+K hotkey to open search modal
 * - Live search through all GUI settings
 * - Backend API search integration
 * - Auto-navigation to settings when clicked
 */
/**
 * ---agentspec
 * what: |
 *   Custom React hook that manages global search functionality across the application.
 *   Accepts no parameters; returns an object containing: isOpen (boolean), query (string), results (SearchResult array), settingsIndex (SettingSearchItem array), loading (boolean), cursor (number for keyboard navigation), and control functions (setIsOpen, setQuery, setResults, setSettingsIndex, setLoading, setCursor).
 *   Maintains search state including query text, result list, settings index, loading state, and keyboard cursor position for result navigation.
 *   Handles in-flight request cancellation via AbortController to prevent race conditions when query changes rapidly; initializes empty results and cursor at 0.
 *
 * why: |
 *   Centralizes search state management into a reusable hook to avoid prop drilling and duplicate logic across components.
 *   AbortController pattern prevents stale results from overwriting newer queries when user types quickly.
 *   Separates search UI state (isOpen, cursor) from data state (query, results, settingsIndex) for cleaner component composition.
 *
 * guardrails:
 *   - DO NOT remove abortControllerRef without replacing with equivalent request cancellation mechanism; rapid queries will cause race conditions and display stale results
 *   - ALWAYS call abortControllerRef.current?.abort() before initiating new searches to cancel pending requests
 *   - NOTE: cursor state assumes results array is stable; if results are mutated externally, cursor may point to invalid indices
 *   - ASK USER: Confirm whether settingsIndex should be populated on hook initialization or lazily loaded on first search, as current implementation leaves it empty until explicitly set
 * ---/agentspec
 */
export function useGlobalSearch() {
  const { api } = useAPI();
  const navigate = useNavigate();
  const location = useLocation();
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [settingsIndex, setSettingsIndex] = useState<SettingSearchItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [cursor, setCursor] = useState(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Build index of all settings in the GUI
  const buildSettingsIndex = useCallback(() => {
    const index: SettingSearchItem[] = [];

    try {
      const sections = document.querySelectorAll('.settings-section');
      sections.forEach(sec => {
        const titleEl = sec.querySelector('h3');
        const title = (titleEl?.textContent || '').toLowerCase();

        const inputGroups = sec.querySelectorAll('.input-group');
        inputGroups.forEach(group => {
          const labelEl = group.querySelector('label');
          const label = (labelEl?.textContent || '').trim();

          const input = group.querySelector('input, select, textarea');
          if (!input) return;

          const name = (input as HTMLInputElement).name || (input as HTMLInputElement).id || '';
          const placeholder = (input as HTMLInputElement).getAttribute('placeholder') || '';
          const content = (title + ' ' + label + ' ' + name + ' ' + placeholder).toLowerCase();

          index.push({
            label: label || name,
            title,
            name,
            placeholder,
            element: input as HTMLElement,
            content
          });
        });
      });

      setSettingsIndex(index);
      console.log('[useGlobalSearch] Built settings index:', index.length, 'items');
    } catch (error) {
      console.error('[useGlobalSearch] Error building settings index:', error);
    }
  }, []);

  // Initialize settings index
  useEffect(() => {
    // Build index after initial render
    const timer = setTimeout(buildSettingsIndex, 500);

    return () => {
      clearTimeout(timer);
    };
  }, [buildSettingsIndex]);

  // Rebuild index on route changes (React Router)
  useEffect(() => {
    const t = window.setTimeout(buildSettingsIndex, 150);
    return () => window.clearTimeout(t);
  }, [buildSettingsIndex, location.pathname, location.search]);

  // Keyboard shortcut: Ctrl+K or Cmd+K
  useEffect(() => {
    /**
     * ---agentspec
     * what: |
     *   Handles keyboard events for a command palette or search modal component.
     *   Takes a KeyboardEvent parameter and checks for two specific key combinations: Ctrl/Cmd+K to open the modal, and Escape to close it.
     *   Calls preventDefault() on Ctrl/Cmd+K to prevent default browser behavior, then sets isOpen state to true.
     *   For Escape key, closes the modal by setting isOpen to false only if the modal is already open (isOpen === true).
     *   No return value; operates entirely through side effects on component state and event handling.
     *
     * why: |
     *   Centralizes keyboard interaction logic for a modal/command palette, providing a standard UX pattern (Cmd+K to open, Esc to close).
     *   Prevents default browser behavior for Ctrl/Cmd+K to avoid conflicts with browser shortcuts (e.g., browser search).
     *   The isOpen guard on Escape prevents unnecessary state updates and allows nested modals to handle Escape independently.
     *
     * guardrails:
     *   - DO NOT remove the e.preventDefault() call on Ctrl/Cmd+K; without it, browser shortcuts will conflict and create confusing UX
     *   - ALWAYS check isOpen before closing on Escape to allow event bubbling in nested modal scenarios and prevent unintended closures
     *   - NOTE: This handler does not distinguish between Ctrl (Windows/Linux) and Cmd (Mac); both trigger the same behavior, which is intentional for cross-platform consistency
     *   - ASK USER: Before adding additional keyboard shortcuts, confirm whether they should preventDefault() and whether they need isOpen guards for nested modal support
     * ---/agentspec
     */
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setIsOpen(true);
      }

      // Close on Escape
      if (e.key === 'Escape' && isOpen) {
        setIsOpen(false);
        setQuery('');
        setResults([]);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  // Search settings locally
  const searchSettings = useCallback((q: string): SearchResult[] => {
    if (!q.trim()) return [];

    const searchTerm = q.trim().toLowerCase();
    const filtered = settingsIndex.filter(item =>
      item.content.includes(searchTerm)
    );

    return filtered.slice(0, 15).map(item => ({
      file_path: item.label,
      start_line: 0,
      end_line: 0,
      language: 'setting',
      rerank_score: 1.0,
      label: item.label,
      title: item.title,
      name: item.name,
      element: item.element
    }));
  }, [settingsIndex]);

  // Search backend API
  const searchBackend = useCallback(async (q: string): Promise<SearchResult[]> => {
    if (!q.trim()) return [];

    try {
      // Cancel previous request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      abortControllerRef.current = new AbortController();

      const response = await fetch(
        api(`/search?q=${encodeURIComponent(q)}&top_k=15`),
        { signal: abortControllerRef.current.signal }
      );

      if (!response.ok) {
        throw new Error(`Search failed: ${response.statusText}`);
      }

      const data = await response.json();
      return data.results || [];
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        return [];
      }
      console.error('[useGlobalSearch] Backend search error:', error);
      return [];
    }
  }, [api]);

  // Combined search (settings + backend)
  const search = useCallback(async (q: string) => {
    setQuery(q);

    if (!q.trim()) {
      setResults([]);
      setLoading(false);
      return;
    }

    setLoading(true);

    try {
      // Search settings first (instant)
      const settingsResults = searchSettings(q);

      // Search backend (async)
      const backendResults = await searchBackend(q);

      // Combine results: settings first, then backend code results
      const combined = [...settingsResults];

      // Add backend results that aren't duplicates
      backendResults.forEach(br => {
        if (!combined.some(sr => sr.file_path === br.file_path)) {
          combined.push(br);
        }
      });

      setResults(combined.slice(0, 15));
      setCursor(0);
    } catch (error) {
      console.error('[useGlobalSearch] Search error:', error);
    } finally {
      setLoading(false);
    }
  }, [searchSettings, searchBackend]);

  // Navigate to a search result
  const navigateToResult = useCallback((result: SearchResult) => {
    if (result.element) {
      // GUI setting - navigate and highlight
      const tabContent = result.element.closest('.tab-content');
      const tabId = tabContent ? (tabContent as HTMLElement).id.replace('tab-', '') : '';

      // Capture stable lookup info before navigation (DOM nodes may be replaced)
      const el = result.element as HTMLElement;
      const elementId = el.id || '';
      const elementName = (el as HTMLInputElement).name || '';

      // If the setting is within a known subtab, preserve it via query string.
      let nextPath = tabId ? `/${tabId}` : location.pathname;
      if (tabId === 'rag') {
        const subtabEl = el.closest('.rag-subtab-content') as HTMLElement | null;
        const subtabId =
          subtabEl && typeof subtabEl.id === 'string' && subtabEl.id.startsWith('tab-rag-')
            ? subtabEl.id.replace('tab-rag-', '')
            : '';
        if (subtabId) nextPath = `/rag?subtab=${encodeURIComponent(subtabId)}`;
      }

      if (nextPath !== location.pathname + location.search) {
        navigate(nextPath);
      }

      // Highlight and scroll once the DOM is settled on the target route
      window.setTimeout(() => {
        let target: HTMLElement | null = null;
        if (elementId) {
          try {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const esc = (CSS as any)?.escape ? (CSS as any).escape(elementId) : elementId;
            target = document.getElementById(elementId) || (document.querySelector(`#${esc}`) as HTMLElement | null);
          } catch {
            target = document.getElementById(elementId);
          }
        }
        if (!target && elementName) {
          try {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const esc = (CSS as any)?.escape ? (CSS as any).escape(elementName) : elementName;
            target = document.querySelector(`[name="${esc}"]`) as HTMLElement | null;
          } catch {
            target = document.querySelector(`[name="${elementName}"]`) as HTMLElement | null;
          }
        }

        if (!target) return;
        target.classList.add('search-hit');
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        window.setTimeout(() => target?.classList.remove('search-hit'), 1200);
      }, 200);
    } else {
      // Code file - could open in editor or show preview
      console.log('[useGlobalSearch] Navigate to file:', result.file_path);
    }

    // Close modal
    setIsOpen(false);
    setQuery('');
    setResults([]);
  }, [location.pathname, location.search, navigate]);

  // Keyboard navigation in results
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (results.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setCursor(prev => Math.min(prev + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setCursor(prev => Math.max(prev - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (results[cursor]) {
        navigateToResult(results[cursor]);
      }
    }
  }, [results, cursor, navigateToResult]);

  return {
    isOpen,
    setIsOpen,
    query,
    setQuery,
    results,
    loading,
    cursor,
    search,
    navigateToResult,
    handleKeyDown,
    settingsCount: settingsIndex.length
  };
}
