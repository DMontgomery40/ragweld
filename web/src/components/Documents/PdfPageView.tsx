import { useMemo, useState } from 'react';
import { documentPageUrl } from '@/api/documents';
import { FigureBadge } from '@/components/Documents/FigureBadge';
import { RegionOverlay } from '@/components/Documents/RegionOverlay';
import { distinctRegionPages, figureBadgeLabel, regionsForPage } from '@/components/Documents/sourceLabels';
import type { ChunkMatch, PageSize } from '@/types/generated';

type Props = {
  corpusId: string;
  path: string;
  pageCount: number;
  pageSizes: PageSize[];
  source: ChunkMatch;
};

const navButton: React.CSSProperties = {
  background: 'var(--bg-elev2)',
  color: 'var(--fg)',
  border: '1px solid var(--line)',
  borderRadius: '6px',
  padding: '6px 10px',
  fontSize: '12.5px',
  fontWeight: 600,
  cursor: 'pointer',
  minHeight: '32px',
};

/** One rendered PDF page at a time with the citation's regions boxed; jump chips per cited page. */
export function PdfPageView({ corpusId, path, pageCount, pageSizes, source }: Props) {
  const prov = source.provenance ?? null;
  const citedPages = useMemo(() => distinctRegionPages(prov), [prov]);
  const [page, setPage] = useState<number>(() => {
    const start = typeof prov?.page_start === 'number' ? prov.page_start : 1;
    return Math.min(Math.max(start, 1), Math.max(pageCount, 1));
  });
  const [loaded, setLoaded] = useState(false);
  const isFigure = figureBadgeLabel(source) !== null;
  const regions = regionsForPage(prov, page);
  const size = pageSizes[page - 1] ?? pageSizes[0];
  const aspect = size ? `${size.width} / ${size.height}` : '612 / 792';

  const go = (next: number) => {
    const clamped = Math.min(Math.max(next, 1), pageCount);
    if (clamped !== page) {
      setLoaded(false);
      setPage(clamped);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '8px 12px',
          borderBottom: '1px solid var(--line)',
          flexWrap: 'wrap',
        }}
      >
        <button type="button" style={navButton} onClick={() => go(page - 1)} disabled={page <= 1} data-testid="document-page-prev">
          ‹ Prev
        </button>
        <span data-testid="document-page-indicator" style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>
          p. {page} / {pageCount}
        </span>
        <button type="button" style={navButton} onClick={() => go(page + 1)} disabled={page >= pageCount} data-testid="document-page-next">
          Next ›
        </button>
        {citedPages.length > 0 ? (
          <span style={{ display: 'flex', gap: '6px', alignItems: 'center', marginLeft: 'auto', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>cited on</span>
            {citedPages.map((p) => (
              <button
                key={p}
                type="button"
                data-testid={`document-page-chip-${p}`}
                onClick={() => go(p)}
                style={{
                  ...navButton,
                  padding: '4px 8px',
                  minHeight: '26px',
                  fontSize: '12px',
                  background: p === page ? 'var(--accent)' : 'var(--bg-elev2)',
                  color: p === page ? 'var(--accent-contrast)' : 'var(--fg)',
                }}
              >
                p. {p}
              </button>
            ))}
          </span>
        ) : null}
      </div>

      <div style={{ flex: '1 1 auto', minHeight: 0, overflow: 'auto', padding: '12px', background: 'var(--bg)' }}>
        <div
          data-testid="document-page-frame"
          style={{
            position: 'relative',
            width: '100%',
            aspectRatio: aspect,
            background: '#ffffff',
            border: '1px solid var(--line)',
            boxShadow: '0 2px 10px rgba(0,0,0,0.35)',
          }}
        >
          <img
            key={page}
            src={documentPageUrl(corpusId, path, page, 'page')}
            alt={`${path} page ${page}`}
            data-testid="document-page-image"
            onLoad={() => setLoaded(true)}
            style={{ display: 'block', width: '100%', height: '100%', opacity: loaded ? 1 : 0.35, transition: 'opacity 120ms' }}
          />
          <RegionOverlay regions={regions} />
        </div>
        <details style={{ marginTop: '12px' }} open>
          <summary style={{ cursor: 'pointer', fontSize: '12.5px', fontWeight: 700, color: 'var(--fg)' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              {isFigure ? 'Figure description' : 'Cited text'}
              <FigureBadge source={source} testId="document-figure-badge" />
            </span>
          </summary>
          <pre
            data-testid="document-cited-text"
            style={{
              margin: '8px 0 0',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontFamily: 'var(--font-mono)',
              fontSize: '12.5px',
              lineHeight: 1.55,
              color: 'var(--fg)',
              background: 'var(--code-bg)',
              padding: '10px',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--line)',
            }}
          >
            {source.content}
          </pre>
        </details>
      </div>
    </div>
  );
}
