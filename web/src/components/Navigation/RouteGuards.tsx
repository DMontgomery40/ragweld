// URL-state guards that belong to the shell rather than to any one tab.
//
// `CorpusParamGuard` — `?corpus=<unknown>` used to 404 the config call, silently swap
// in the default corpus and leave the bad value in the address bar until the next
// navigation put it back (M-127). The store canonicalises the corpus with a raw
// `history.replaceState`, which React Router never sees, so the correction has to be
// re-applied through the router or the router's own stale search string restores it.
//
// `DocumentTitle` — `index.html` ships a static "ragweld" title, so every tab of a
// multi-tab operator session looked identical in the tab strip and in history (M-159).

import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getRouteByPath } from '@/config/routes';
import { useRepoStore } from '@/stores/useRepoStore';
import { showToast } from '@/utils/toast';

export function CorpusParamGuard() {
  const location = useLocation();
  const navigate = useNavigate();
  const repos = useRepoStore((s) => s.repos);
  const initialized = useRepoStore((s) => s.initialized);
  const activeRepo = useRepoStore((s) => s.activeRepo);
  const announced = useRef<string | null>(null);

  useEffect(() => {
    // Before the registry is known every value is "unknown"; wait for the real answer.
    if (!initialized || repos.length === 0) return;

    const params = new URLSearchParams(location.search || '');
    const requested = String(params.get('corpus') || params.get('repo') || '').trim();
    if (!requested) {
      announced.current = null;
      return;
    }
    const known = repos.some(
      (r) => r.corpus_id === requested || r.slug === requested || r.name === requested
    );
    if (known) {
      announced.current = null;
      return;
    }

    if (announced.current !== requested) {
      announced.current = requested;
      showToast(
        activeRepo
          ? `No corpus named "${requested}". Showing ${activeRepo} instead.`
          : `No corpus named "${requested}".`,
        'error'
      );
    }

    params.delete('repo');
    if (activeRepo) params.set('corpus', activeRepo);
    else params.delete('corpus');
    const search = params.toString();
    const next = search ? `?${search}` : '';
    // Bail when the correction is a no-op. This effect is keyed on `location.search`, so
    // navigating to an identical search would re-fire it forever -- which is exactly what
    // happens if `activeRepo` is itself a value the registry does not contain.
    if (next === (location.search || '')) return;
    navigate({ pathname: location.pathname, search: next }, { replace: true });
  }, [activeRepo, initialized, location.pathname, location.search, navigate, repos]);

  return null;
}

/** The visible label of the active subtab, or '' when the route has none selected. */
function subtabTitle(pathname: string, search: string): string {
  const route = getRouteByPath(pathname);
  if (!route) return '';
  const id = new URLSearchParams(search || '').get('subtab');
  if (!id) return '';
  return route.subtabs?.find((s) => s.id === id)?.title ?? '';
}

export function DocumentTitle() {
  const location = useLocation();
  const activeRepo = useRepoStore((s) => s.activeRepo);

  useEffect(() => {
    const route = getRouteByPath(location.pathname);
    const sub = subtabTitle(location.pathname, location.search);
    const where = route ? [route.label, sub].filter(Boolean).join(' · ') : 'Page not found';
    document.title = activeRepo ? `${where} — ${activeRepo} — ragweld` : `${where} — ragweld`;
  }, [activeRepo, location.pathname, location.search]);

  return null;
}
