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

  const getActiveCorpusId = useCallback((): string => {
    try {
      const u = new URL(window.location.href);
      return (
        u.searchParams.get('corpus') ||
        u.searchParams.get('repo') ||
        localStorage.getItem('tribrid_active_corpus') ||
        localStorage.getItem('tribrid_active_repo') ||
        ''
      ).trim();
    } catch {
      return (
        localStorage.getItem('tribrid_active_corpus') ||
        localStorage.getItem('tribrid_active_repo') ||
        ''
      ).trim();
    }
  }, []);

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

    const corpusId = getActiveCorpusId();
    if (!corpusId) return [];

    try {
      // Cancel previous request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      abortControllerRef.current = new AbortController();

      const response = await fetch(
        api('/search'),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            corpus_id: corpusId,
            query: q,
            top_k: 15,
          }),
          signal: abortControllerRef.current.signal,
        }
      );

      if (!response.ok) {
        throw new Error(`Search failed: ${response.statusText}`);
      }

      const data = await response.json();
      const matches = Array.isArray(data?.matches) ? data.matches : [];
      return matches.map((match: any) => ({
        file_path: String(match?.file_path || ''),
        start_line: Number(match?.start_line || 0),
        end_line: Number(match?.end_line || 0),
        language: String(match?.language || ''),
        rerank_score: Number(match?.score || 0),
      }));
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        return [];
      }
      console.error('[useGlobalSearch] Backend search error:', error);
      return [];
    }
  }, [api, getActiveCorpusId]);

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
