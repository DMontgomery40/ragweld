import { useState, useEffect, useCallback, useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { configApi } from '@/api/config';
import { configDeepLink } from '@/config/configDeepLinks';
import type { ConfigFieldDescriptor } from '@/types/generated';

/**
 * Global settings search (Ctrl+K / Cmd+K).
 *
 * Two indexes, both local:
 * - the config registry (every registered TriBridConfig field with its label,
 *   dotted path, section, owning surface and description) — so a search finds a
 *   setting on any page, not only the one currently rendered;
 * - the controls rendered on the current page — so a hit on this page focuses
 *   the actual input.
 *
 * It never calls the RAG search API: the former implementation ran an
 * /api/search against the active corpus on every keystroke and rendered blank
 * rows for DOM inputs without labels (2026-08-25 drive finding M2).
 */
export type GlobalSearchHit = {
  kind: 'control' | 'config';
  /** Stable identity for keys/dedupe: element name/id for controls, dotted path for config fields. */
  id: string;
  label: string;
  /** Where the hit lives: the page section title for controls, the owning surface + section for config fields. */
  location: string;
  /** Dotted config path (config hits) or the control's name/id. */
  path: string;
  description?: string;
  element?: HTMLElement;
};

type ControlIndexItem = GlobalSearchHit & { kind: 'control'; element: HTMLElement; content: string };
type ConfigIndexItem = GlobalSearchHit & { kind: 'config'; content: string };

const MAX_RESULTS = 20;

function buildConfigIndex(fields: ConfigFieldDescriptor[]): ConfigIndexItem[] {
  return fields.map((field) => {
    const label = String(field.label || field.path).trim();
    const description = String(field.description || '').trim();
    // A path with a purpose-built card names that card, so the row says where it will land
    // rather than naming the registry bucket it happens to be classified under.
    const location =
      configDeepLink(field.path)?.location ?? `${field.ui_surface} · ${field.section}`;
    return {
      kind: 'config',
      id: field.path,
      label,
      location,
      path: field.path,
      description: description || undefined,
      content: `${label} ${field.path} ${field.section} ${field.ui_surface} ${field.integration} ${description}`.toLowerCase(),
    };
  });
}

function buildControlIndex(): ControlIndexItem[] {
  const index: ControlIndexItem[] = [];
  const sections = document.querySelectorAll('.settings-section');
  sections.forEach((sec) => {
    const title = (sec.querySelector('h2, h3')?.textContent || '').trim();
    sec.querySelectorAll('.input-group').forEach((group) => {
      const input = group.querySelector('input, select, textarea') as HTMLElement | null;
      if (!input) return;
      const label = (group.querySelector('label')?.textContent || '').trim();
      const name = (input as HTMLInputElement).name || input.id || '';
      if (!label && !name) return; // nothing a person could recognise in a result row
      const placeholder = input.getAttribute('placeholder') || '';
      index.push({
        kind: 'control',
        id: name || label,
        label: label || name,
        location: title || 'This page',
        path: name,
        element: input,
        content: `${title} ${label} ${name} ${placeholder}`.toLowerCase(),
      });
    });
  });
  return index;
}

/**
 * Highlight and focus a control once the surface that owns it has rendered.
 *
 * Deliberately a bounded poll rather than one fixed timeout: the target card mounts only
 * after the route change and the component switch, and how long that takes depends on what
 * else the box is doing. A fixed delay either fires too early or wastes the wait.
 */
function highlightWhenRendered(testId: string, attempts = 60, intervalMs = 100): void {
  let tries = 0;
  const tick = () => {
    const target = document.querySelector(
      `[data-testid="${CSS.escape(testId)}"]`
    ) as HTMLElement | null;
    if (!target) {
      tries += 1;
      if (tries < attempts) window.setTimeout(tick, intervalMs);
      return;
    }
    target.classList.add('search-hit');
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.focus?.({ preventScroll: true });
    window.setTimeout(() => target.classList.remove('search-hit'), 1200);
  };
  window.setTimeout(tick, 0);
}

export function useGlobalSearch() {
  const navigate = useNavigate();
  const location = useLocation();
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<GlobalSearchHit[]>([]);
  const [controlIndex, setControlIndex] = useState<ControlIndexItem[]>([]);
  const [configIndex, setConfigIndex] = useState<ConfigIndexItem[]>([]);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [cursor, setCursor] = useState(0);

  const rebuildControlIndex = useCallback(() => {
    try {
      setControlIndex(buildControlIndex());
    } catch (error) {
      console.error('[useGlobalSearch] Error building control index:', error);
    }
  }, []);

  // Load the config registry (the source of truth for every setting). No
  // "loaded once" ref: under StrictMode's double effect run that guard let the
  // cancelled first fetch win and the index stayed empty.
  useEffect(() => {
    let cancelled = false;
    configApi
      .registry()
      .then((registry) => {
        if (cancelled) return;
        setConfigIndex(buildConfigIndex(registry.fields || []));
        setIndexError(null);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setIndexError(error instanceof Error ? error.message : 'Failed to load the config registry');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Re-index the current page's controls on route changes.
  useEffect(() => {
    const t = window.setTimeout(rebuildControlIndex, 150);
    return () => window.clearTimeout(t);
  }, [rebuildControlIndex, location.pathname, location.search]);

  // Keyboard shortcut: Ctrl+K or Cmd+K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        rebuildControlIndex();
        setIsOpen(true);
      }
      if (e.key === 'Escape' && isOpen) {
        setIsOpen(false);
        setQuery('');
        setResults([]);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, rebuildControlIndex]);

  const search = useCallback(
    (q: string) => {
      setQuery(q);
      const needle = q.trim().toLowerCase();
      if (!needle) {
        setResults([]);
        setCursor(0);
        return;
      }
      const terms = needle.split(/\s+/).filter(Boolean);
      const matches = (content: string) => terms.every((term) => content.includes(term));
      const controlHits = controlIndex.filter((item) => matches(item.content));
      const seenPaths = new Set(controlHits.map((item) => item.path).filter(Boolean));
      const configHits = configIndex
        .filter((item) => matches(item.content))
        .filter((item) => !seenPaths.has(item.path))
        .sort((a, b) => {
          // Prefer label/path prefix matches over description-only matches.
          const score = (item: ConfigIndexItem) =>
            (item.label.toLowerCase().startsWith(needle) ? 0 : 1) + (item.path.toLowerCase().includes(needle) ? 0 : 1);
          return score(a) - score(b) || a.path.localeCompare(b.path);
        });
      setResults([...controlHits, ...configHits].slice(0, MAX_RESULTS));
      setCursor(0);
    },
    [configIndex, controlIndex]
  );

  const navigateToResult = useCallback(
    (result: GlobalSearchHit) => {
      if (result.kind === 'control' && result.element) {
        const el = result.element;
        const tabContent = el.closest('.tab-content') as HTMLElement | null;
        const tabId = tabContent ? tabContent.id.replace('tab-', '') : '';
        const elementId = el.id || '';
        const elementName = (el as HTMLInputElement).name || '';
        // A control found on the current page is already on the right route: keep
        // the corpus/subtab/query params and only correct the path if it differs.
        const params = new URLSearchParams(location.search);
        let nextPathname = tabId ? `/${tabId}` : location.pathname;
        if (tabId === 'rag') {
          const subtabEl = el.closest('.rag-subtab-content') as HTMLElement | null;
          const subtabId =
            subtabEl && typeof subtabEl.id === 'string' && subtabEl.id.startsWith('tab-rag-')
              ? subtabEl.id.replace('tab-rag-', '')
              : '';
          if (subtabId) {
            nextPathname = '/rag';
            params.set('subtab', subtabId);
          }
        }
        const nextSearch = params.toString();
        const nextPath = nextSearch ? `${nextPathname}?${nextSearch}` : nextPathname;
        if (nextPath !== location.pathname + location.search) navigate(nextPath);
        window.setTimeout(() => {
          let target: HTMLElement | null = null;
          if (elementId) target = document.getElementById(elementId);
          if (!target && elementName) {
            target = document.querySelector(`[name="${CSS.escape(elementName)}"]`) as HTMLElement | null;
          }
          if (!target) return;
          target.classList.add('search-hit');
          target.scrollIntoView({ behavior: 'smooth', block: 'center' });
          target.focus?.({ preventScroll: true });
          window.setTimeout(() => target?.classList.remove('search-hit'), 1200);
        }, 200);
      } else {
        const params = new URLSearchParams(location.search);
        const corpus = params.get('corpus') || params.get('repo');
        const deepLink = configDeepLink(result.path);
        if (deepLink) {
          // The setting has a card of its own: open that, not the raw registry row.
          const target = new URLSearchParams(deepLink.params);
          if (corpus) target.set('corpus', corpus);
          navigate(`${deepLink.pathname}?${target.toString()}`);
          if (deepLink.testId) highlightWhenRendered(deepLink.testId);
        } else {
          // Config field with no dedicated surface: open it in the Admin explorer, filtered
          // to the path, keeping the active corpus in the URL.
          const target = new URLSearchParams({ subtab: 'advanced', q: result.path });
          if (corpus) target.set('corpus', corpus);
          navigate(`/admin?${target.toString()}`);
        }
      }
      setIsOpen(false);
      setQuery('');
      setResults([]);
    },
    [location.pathname, location.search, navigate]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (results.length === 0) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setCursor((prev) => Math.min(prev + 1, results.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setCursor((prev) => Math.max(prev - 1, 0));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (results[cursor]) navigateToResult(results[cursor]);
      }
    },
    [results, cursor, navigateToResult]
  );

  // Re-run the active query when either index arrives after the operator typed
  // (the registry can finish loading after the first keystrokes).
  useEffect(() => {
    if (isOpen && query.trim()) search(query);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configIndex, controlIndex]);

  const settingsCount = useMemo(() => configIndex.length, [configIndex]);

  return {
    isOpen,
    setIsOpen,
    query,
    setQuery,
    results,
    indexError,
    cursor,
    setCursor,
    search,
    navigateToResult,
    handleKeyDown,
    settingsCount,
  };
}
