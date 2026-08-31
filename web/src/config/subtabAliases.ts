// Renamed subtab slugs, mapped to their current canonical id.
//
// When a subtab is renamed, existing bookmarks, runbooks and deep links still carry the old
// slug. Without this map `useSubtab` treats the old value as an unknown slug: it bounces to the
// tab's default and shows an error toast, so `?subtab=learning-ranker` looked like a broken link
// to Learning Reranker while quietly showing the default subtab. This map lets the old slug
// resolve transparently to the new one (the URL is corrected to the canonical slug, no toast).
//
// NOTE FOR check_banned: this is the ONE place in web/src where a pre-rename slug containing a
// banned term ("ranker") may appear. The banned-term invariant test path-exempts this file
// because the map exists precisely to keep the old, now-renamed slug resolving. Do not add live
// copy here — only historical slug -> canonical slug pairs.
export const SUBTAB_ALIASES: Record<string, string> = {
  'learning-ranker': 'learning-reranker',
};

/** Resolve a renamed subtab slug to its canonical id, or null when there is no alias. */
export function resolveSubtabAlias(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const key = String(raw).trim();
  return Object.prototype.hasOwnProperty.call(SUBTAB_ALIASES, key) ? SUBTAB_ALIASES[key] : null;
}
