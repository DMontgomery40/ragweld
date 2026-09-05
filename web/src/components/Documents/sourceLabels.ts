import type { ChunkMatch, ChunkProvenance, PageRegion } from '@/types/generated';
import type { DocumentSource } from '@/stores/useDockStore';

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
export function formatSourceLocation(source: DocumentSource): string {
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

/**
 * Local view model for `Chunk.metadata["figure"]` (the indexer's `FigureAnnotation`).
 * `ChunkMatch.metadata` is `Record<string, unknown>` on the wire, so this stays a local
 * read shape — it is not a generated contract and must not be treated as one.
 */
type FigureMetadataView = { kind?: unknown };

/**
 * "Figure", or "Figure · chart" when the vision model named a kind, for a citation whose
 * chunk is a figure description rather than page text. Null for every other citation.
 */
export function figureBadgeLabel(source: Pick<DocumentSource, 'metadata'>): string | null {
  if (source.metadata?.chunk_kind !== 'figure') return null;
  const raw = source.metadata?.figure;
  const figure: FigureMetadataView | null =
    typeof raw === 'object' && raw !== null && !Array.isArray(raw) ? (raw as FigureMetadataView) : null;
  const kind = typeof figure?.kind === 'string' ? figure.kind.trim() : '';
  return kind && kind !== 'other' ? `Figure · ${kind}` : 'Figure';
}

export function charSpanOf(source: Pick<DocumentSource, 'metadata'>): { start: number; end: number } | null {
  const start = source.metadata?.char_start;
  const end = source.metadata?.char_end;
  if (typeof start === 'number' && typeof end === 'number' && end >= start) return { start, end };
  return null;
}
