import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getRouteByPath } from '@/config/routes';
import { resolveSubtabAlias } from '@/config/subtabAliases';
import { useDockStore } from '@/stores/useDockStore';
import { showToast } from '@/utils/toast';

export type UseSubtabOptions<T extends string = string> = {
  /**
   * The current top-level route path (e.g. "/rag", "/dashboard").
   * Used to derive allowed subtabs from `config/routes.ts` unless `allowedSubtabs` is provided.
   */
  routePath: string;
  /** Default subtab id (must be a member of allowed subtabs). */
  defaultSubtab: T;
  /** Query parameter name. Defaults to "subtab". */
  param?: string;
  /**
   * Optional explicit allowlist override. If omitted, the hook uses `routes.ts` subtabs for `routePath`.
   */
  allowedSubtabs?: readonly T[];
  /**
   * When the URL is missing/invalid, write the default subtab into the URL.
   * Uses `replace: true` to avoid polluting history.
   */
  ensureInUrl?: boolean;
  /**
   * When the user changes subtabs via `setSubtab`, should navigation replace history?
   * Default: false (so browser back/forward can traverse subtab changes).
   */
  replaceOnChange?: boolean;
};

export function useSubtab<T extends string = string>({
  routePath,
  defaultSubtab,
  param = 'subtab',
  allowedSubtabs,
  ensureInUrl = true,
  replaceOnChange = false,
}: UseSubtabOptions<T>) {
  const location = useLocation();
  const navigate = useNavigate();
  const isDockContext = (location as any)?.key === 'dock';

  const allowed = useMemo<readonly T[]>(() => {
    if (allowedSubtabs && allowedSubtabs.length) return allowedSubtabs;
    const route = getRouteByPath(routePath);
    const ids = (route?.subtabs ?? []).map((s) => s.id);
    return ids as unknown as readonly T[];
  }, [allowedSubtabs, routePath]);

  const allowedSet = useMemo(() => new Set<string>((allowed as readonly unknown[]).map(String)), [allowed]);

  const params = useMemo(() => new URLSearchParams(location.search || ''), [location.search]);
  const raw = params.get(param);
  const rawValid = Boolean(raw && allowedSet.has(raw));
  // A renamed slug (its former value listed in subtabAliases) resolves to its canonical id so
  // old bookmarks/links land on the right subtab instead of the default with an error toast.
  const aliasTarget = rawValid ? null : resolveSubtabAlias(raw);
  const aliasValid = Boolean(aliasTarget && allowedSet.has(aliasTarget));
  const isValid = rawValid || aliasValid;

  const effective = (rawValid ? raw : aliasValid ? aliasTarget : defaultSubtab) as T;
  // DockView supplies the persisted dock target as a virtual location. Keeping a second
  // local subtab made chooser changes update the title while content stayed on the old
  // valid tab, and lost in-dock navigation on reload and Swap (S45).
  const activeSubtab = effective;

  const setSubtab = useCallback(
    (nextSubtab: T, opts?: { replace?: boolean }) => {
      if (!allowed.length) return;
      const next = allowedSet.has(String(nextSubtab)) ? String(nextSubtab) : String(defaultSubtab);
      const nextParams = new URLSearchParams(location.search || '');
      nextParams.set(param, next);
      if (isDockContext) {
        const { docked, setDocked } = useDockStore.getState();
        if (!docked || docked.path !== location.pathname) return;
        const route = getRouteByPath(routePath);
        setDocked({
          ...docked,
          search: `?${nextParams.toString()}`,
          subtabTitle: route?.subtabs?.find((tab) => tab.id === next)?.title,
        }, { rememberLast: false });
        return;
      }
      navigate(
        { pathname: location.pathname, search: `?${nextParams.toString()}` },
        { replace: opts?.replace ?? replaceOnChange }
      );
    },
    [allowed.length, allowedSet, defaultSubtab, isDockContext, location.pathname, location.search, navigate, param, replaceOnChange, routePath]
  );

  // A slug the operator actually typed (or followed from a runbook, doc or bookmark)
  // and that this route does not have used to be swallowed: the URL was rewritten to
  // the default subtab with no notice, so `?subtab=reranker` looked exactly like a
  // working link to Reranker while showing Data Quality (M-126, M-159/X-03). Announce
  // it once per bad value; an absent param is not a mistake and stays silent.
  const announcedSubtab = useRef<string | null>(null);
  useEffect(() => {
    if (isDockContext) return;
    if (!allowed.length) return;
    const typed = String(raw || '').trim();
    // Clearing on a valid slug too, so pasting the same bad slug a second time in one
    // mount is announced again rather than silently corrected.
    if (!typed || isValid) {
      announcedSubtab.current = null;
      return;
    }
    const key = `${routePath}:${typed}`;
    if (announcedSubtab.current === key) return;
    announcedSubtab.current = key;
    const route = getRouteByPath(routePath);
    const landing =
      (route?.subtabs ?? []).find((s) => s.id === String(defaultSubtab))?.title || String(defaultSubtab);
    const known = (route?.subtabs ?? []).map((s) => s.id).join(', ');
    showToast(
      `No "${typed}" tab on ${route?.label || routePath}. Showing ${landing}. Valid values: ${known}.`,
      'error'
    );
  }, [allowed.length, defaultSubtab, isDockContext, isValid, raw, routePath]);

  // Ensure the URL always contains a valid canonical ?subtab=... for deep-linking. When the raw
  // slug is a renamed alias, `effective` is the canonical id, so the address bar is corrected to
  // the new slug (silently, no toast); when it is missing/invalid, `effective` is the default.
  useEffect(() => {
    if (!ensureInUrl) return;
    if (isDockContext) return;
    if (!allowed.length) return;
    if (rawValid) return;
    const nextParams = new URLSearchParams(location.search || '');
    nextParams.set(param, String(effective));
    navigate({ pathname: location.pathname, search: `?${nextParams.toString()}` }, { replace: true });
  }, [allowed.length, effective, ensureInUrl, isDockContext, rawValid, location.pathname, location.search, navigate, param]);

  return {
    activeSubtab,
    setSubtab,
    allowedSubtabs: allowed,
    rawSubtab: raw,
  };
}
