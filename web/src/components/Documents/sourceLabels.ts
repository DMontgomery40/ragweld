import type { ChunkMatch, ChunkProvenance, PageRegion } from '@/types/generated';

/** True when the citation has real page regions to draw (Docling PDF provenance). */
export function hasPageRegions(source: ChunkMatch): boolean {
  const prov = source.provenance;
  return Boolean(
    prov && prov.extraction === 'docling' && typeof prov.page_start === 'number' && (prov.regions?.length ?? 0) > 0,
  );
}

export function regionsForPage(prov: ChunkProvenance | null | undefined, page: number): PageRegion[] {
  return (prov?.regions ?? []).filter((r) => r.page === page);
}

export function distinctRegionPages(prov: ChunkProvenance | null | undefined): number[] {
  return Array.from(new Set((prov?.regions ?? []).map((r) => r.page))).sort((a, b) => a - b);
}

/** "p. 3" / "p. 3–4" for page-anchored citations, "L 12–40" for line-anchored ones. */
export function formatSourceLocation(source: ChunkMatch): string {
  const prov = source.provenance;
  if (prov && typeof prov.page_start === 'number' && typeof prov.page_end === 'number') {
    return prov.page_start === prov.page_end ? `p. ${prov.page_start}` : `p. ${prov.page_start}–${prov.page_end}`;
  }
  if (prov && prov.extraction === 'docling' && source.file_path.toLowerCase().endsWith('.pdf')) {
    return 'page unknown (re-index)';
  }
  if (prov && prov.extraction === 'docling') {
    // docx/pptx/xlsx/html: chunk lines index the captured markdown, not pages.
    return source.start_line === source.end_line
      ? `markdown L ${source.start_line}`
      : `markdown L ${source.start_line}–${source.end_line}`;
  }
  return source.start_line === source.end_line
    ? `L ${source.start_line}`
    : `L ${source.start_line}–${source.end_line}`;
}

export function corpusIdOf(source: ChunkMatch): string {
  const raw = source.metadata?.corpus_id;
  return typeof raw === 'string' ? raw.trim() : '';
}

export function charSpanOf(source: ChunkMatch): { start: number; end: number } | null {
  const start = source.metadata?.char_start;
  const end = source.metadata?.char_end;
  if (typeof start === 'number' && typeof end === 'number' && end >= start) return { start, end };
  return null;
}
