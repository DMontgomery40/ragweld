import type { IndexRunConflictResponse, PersistedStateCorruptDetail } from '@/types/generated';

/**
 * Render a typed index-fence 409 body as one operator-readable sentence.
 *
 * Every route that refuses a corpus held by a live index run answers the same envelope
 * (`IndexRunConflictResponse`), so every caller renders it the same way instead of showing
 * the operator the raw JSON of `{"detail": {...}}`. Returns null when the body is not one
 * of those envelopes, which lets each caller keep its own wording for that case.
 *
 * `stage` is what the holding run last reported doing, which is the difference between
 * "this run is converting a scanned PDF, wait" and "this run is wedged, stop it".
 */
export function describeIndexRunConflict(body: string): string | null {
  let parsed: IndexRunConflictResponse | null = null;
  try {
    parsed = JSON.parse(body) as IndexRunConflictResponse;
  } catch {
    return null;
  }
  const detail = parsed?.detail;
  if (detail?.code === 'index_run_in_progress') {
    const started = new Date(detail.started_at).toLocaleTimeString();
    const heartbeat = new Date(detail.heartbeat_at).toLocaleTimeString();
    const doing = detail.stage ? ` Last step: ${detail.stage}.` : '';
    return (
      `${detail.message} Run ${detail.run_id} on ${detail.owner} started ${started} ` +
      `(${detail.phase ?? 'building'}, last heartbeat ${heartbeat}).${doing} ${detail.operator_hint}`
    );
  }
  if (detail?.code === 'index_fence_corrupt') {
    return `${detail.message} ${detail.operator_hint}`;
  }
  const corrupt = parsed?.detail as PersistedStateCorruptDetail | undefined;
  if (corrupt?.code === 'persisted_state_corrupt') {
    return `${corrupt.message} ${corrupt.operator_hint}`;
  }
  return null;
}
