import type { PageRegion } from '@/types/generated';

export const REGION_INK = '#d97706';
export const REGION_FILL = 'rgba(245, 158, 11, 0.28)';

/** Draw normalized page regions over a positioned page image (coordinates are fractions of the page). */
export function RegionOverlay({ regions, thin }: { regions: PageRegion[]; thin?: boolean }) {
  return (
    <>
      {regions.map((r, i) => (
        <div
          key={`${r.page}-${i}`}
          data-testid="document-region"
          aria-hidden="true"
          style={{
            position: 'absolute',
            left: `${r.left * 100}%`,
            top: `${r.top * 100}%`,
            width: `${Math.max(0, r.right - r.left) * 100}%`,
            height: `${Math.max(0, r.bottom - r.top) * 100}%`,
            // Highlighter amber, not the slate accent: the marks sit on white paper and must
            // read at dpr 1 (border >= 3:1 against white; fill stays translucent over the text).
            border: `${thin ? 1 : 2}px solid ${REGION_INK}`,
            background: REGION_FILL,
            borderRadius: '2px',
            pointerEvents: 'none',
            boxSizing: 'border-box',
          }}
        />
      ))}
    </>
  );
}
