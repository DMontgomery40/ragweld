import type { EvalDoc, EvalExpectedLocation } from '@/types/generated';

// Pure helpers for eval expected locations (page/line spans per expected path) and the
// chunk-level match labels of the eval drill-down. No runtime imports: this module is also
// exercised by the node:test unit suite (web/tests/unit) outside the browser bundle.

export type LocationUnit = EvalExpectedLocation['unit'];

/** One form row: the unit select plus the start/end inputs, as typed. */
export type LocationDraft = {
  unit: '' | LocationUnit;
  start: string;
  end: string;
};

export const EMPTY_DRAFT: LocationDraft = { unit: '', start: '', end: '' };

export function parseExpectedPaths(text: string): string[] {
  const out: string[] = [];
  for (const raw of String(text || '').split(',')) {
    const path = raw.trim();
    if (path && !out.includes(path)) out.push(path);
  }
  return out;
}

function positiveInt(text: string): number | null {
  const trimmed = String(text || '').trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isSafeInteger(value) && value >= 1 ? value : null;
}

/**
 * Build the typed expected locations for `paths` from the form drafts (keyed by path).
 * A path whose draft has no unit stays file-only. An empty end means a single page/line.
 */
export function buildExpectedLocations(
  paths: string[],
  drafts: Record<string, LocationDraft>,
): { locations: EvalExpectedLocation[]; error: string | null } {
  const locations: EvalExpectedLocation[] = [];
  for (const path of paths) {
    const draft = drafts[path];
    if (!draft || !draft.unit) continue;
    const start = positiveInt(draft.start);
    if (start === null) {
      return { locations: [], error: `${path}: enter a first ${draft.unit} of 1 or more` };
    }
    const end = draft.end.trim() ? positiveInt(draft.end) : start;
    if (end === null) {
      return { locations: [], error: `${path}: the last ${draft.unit} must be a whole number of 1 or more` };
    }
    if (end < start) {
      return { locations: [], error: `${path}: the last ${draft.unit} (${end}) is before the first (${start})` };
    }
    locations.push({ path, unit: draft.unit, start, end });
  }
  return { locations, error: null };
}

export function draftsFromLocations(locations: EvalExpectedLocation[] | undefined): Record<string, LocationDraft> {
  const drafts: Record<string, LocationDraft> = {};
  for (const location of locations ?? []) {
    drafts[location.path] = { unit: location.unit, start: String(location.start), end: String(location.end) };
  }
  return drafts;
}

export function formatLocation(location: Pick<EvalExpectedLocation, 'unit' | 'start' | 'end'>): string {
  const single = location.start === location.end;
  if (location.unit === 'page') return single ? `p. ${location.start}` : `pp. ${location.start}–${location.end}`;
  return single ? `line ${location.start}` : `lines ${location.start}–${location.end}`;
}

export function locationFor(
  locations: EvalExpectedLocation[] | undefined,
  path: string,
): EvalExpectedLocation | undefined {
  return (locations ?? []).find((location) => location.path === path);
}

/** Where a retrieved chunk sits: its pages when it has page provenance, else its lines. */
export function formatDocSpan(doc: Pick<EvalDoc, 'start_line' | 'end_line' | 'page_start' | 'page_end'>): string {
  if (doc.page_start != null && doc.page_end != null) {
    return formatLocation({ unit: 'page', start: doc.page_start, end: doc.page_end });
  }
  if (doc.start_line != null && doc.start_line > 0) {
    const end = doc.end_line != null && doc.end_line >= doc.start_line ? doc.end_line : doc.start_line;
    return formatLocation({ unit: 'line', start: doc.start_line, end });
  }
  return '';
}

export type DocMatchTone = 'hit' | 'near' | 'none';

/** Drill-down label for how one retrieved chunk scored (null when it is not in an expected file). */
export function docMatchLabel(match: EvalDoc['match']): { label: string; tone: DocMatchTone } | null {
  switch (match) {
    case 'location':
      return { label: 'location match', tone: 'hit' };
    case 'file':
      return { label: 'file match', tone: 'hit' };
    case 'outside_location':
      return { label: 'right file, wrong span', tone: 'near' };
    case 'no_page_provenance':
      return { label: 'right file, no page data', tone: 'near' };
    default:
      return null;
  }
}

/** Entries that count toward the headline metrics. */
export function scoredEntries(run: { total?: number; uninformative_count?: number } | null | undefined): number {
  if (!run) return 0;
  return Math.max(0, (run.total ?? 0) - (run.uninformative_count ?? 0));
}
