/**
 * Where a registered config path lives in the operator UI.
 *
 * The Admin Advanced explorer is the fallback and can render every registered path, but a
 * path with a purpose-built card belongs on that card: a global-search hit for
 * `indexing.figures.*` opened a raw registry row, which left the Figures & Vision panel
 * unreachable from search (2026-08-30 drive, F4).
 *
 * Deliberately React-free and dependency-free, and NOT in `configControlPlane.tsx`: that
 * module imports `@/hooks`, which re-exports `useGlobalSearch`, so putting the map there
 * would close an import cycle that Vite's dev server tolerates and a flattened production
 * chunk does not.
 */
export type ConfigDeepLink = {
  /** Route to open. */
  pathname: string;
  /** Query params that select the surface within that route (the active corpus is added by the caller). */
  params: Record<string, string>;
  /** `data-testid` of the control this path renders as, when the card exposes one. */
  testId: string | null;
  /** Where the result row says the hit will take the operator. */
  location: string;
};

const FIGURES_PREFIX = 'indexing.figures.';

export function configDeepLink(path: string): ConfigDeepLink | null {
  const dotted = String(path || '').trim();
  if (dotted.startsWith(FIGURES_PREFIX)) {
    const leaf = dotted.slice(FIGURES_PREFIX.length);
    return {
      pathname: '/rag',
      params: { subtab: 'indexing', component: 'figures' },
      // Every `IndexingFiguresConfig` field is rendered with `figures-<leaf-with-hyphens>`;
      // a nested path below a leaf has no control of its own, so it only opens the card.
      testId: leaf && !leaf.includes('.') ? `figures-${leaf.replace(/_/g, '-')}` : null,
      location: 'RAG · Indexing · Figures & Vision',
    };
  }
  return null;
}
