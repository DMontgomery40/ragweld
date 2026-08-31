import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getRouteByPath } from '@/config/routes';
import { resolveSubtabAlias } from '@/config/subtabAliases';
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
  const derivedActive = effective;
  const [localSubtab, setLocalSubtab] = useState<T>(derivedActive);

  // In docked native views we must NOT mutate the global URL/history. Instead, keep subtab state local.
  // The docked route is rendered via <Routes location={{ key: 'dock', ... }}>, so we can detect it
  // deterministically without leaking additional props through the component tree.
  useEffect(() => {
    if (!isDockContext) return;
    if (!allowed.length) return;
    // Ensure local subtab is valid; if not, snap to the derived/default value.
    setLocalSubtab((prev) => (allowedSet.has(String(prev)) ? prev : derivedActive));
  }, [allowed.length, allowedSet, derivedActive, isDockContext]);

  const activeSubtab = (isDockContext ? localSubtab : derivedActive) as T;

  const setSubtab = useCallback(
    (nextSubtab: T, opts?: { replace?: boolean }) => {
      if (!allowed.length) return;
      const next = allowedSet.has(String(nextSubtab)) ? String(nextSubtab) : String(defaultSubtab);
      if (isDockContext) {
        setLocalSubtab(next as T);
        return;
      }
      const nextParams = new URLSearchParams(location.search || '');
      nextParams.set(param, next);
      navigate(
        { pathname: location.pathname, search: `?${nextParams.toString()}` },
        { replace: opts?.replace ?? replaceOnChange }
      );
    },
    [allowed.length, allowedSet, defaultSubtab, isDockContext, location.pathname, location.search, navigate, param, replaceOnChange]
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

