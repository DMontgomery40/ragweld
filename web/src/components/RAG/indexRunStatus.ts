import type { IndexRunSummary, IndexStatus } from '../../types/generated';

/** Live indexing outranks delayed history; idle status must not erase the last result. */
export function indexRunStatus(
  indexing: boolean,
  current: IndexStatus['status'] | null | undefined,
  saved: IndexRunSummary['status'] | null | undefined,
): string {
  if (indexing) return 'indexing';
  if (current && current !== 'idle') return current;
  return saved ?? current ?? 'idle';
}
