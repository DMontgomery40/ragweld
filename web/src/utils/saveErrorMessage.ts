// TriBridRAG - one shared presentation for config save failures.
//
// Every config write (per-section PATCH, whole-config PUT, reset) can fail, and the
// operator must see WHAT the server refused -- the field and its bound, or the reason a
// conflict blocked the write -- never axios's opaque `Error: Request failed with status
// code 422`. axios synthesises that string at runtime from `response.status`; the real
// information is in `response.data.detail`, which this module reads and shapes.
//
// The server emits three detail shapes (server/api/config.py):
//   * 422 validation  -> `detail` is a Pydantic dump STRING (dotted-path line + indented
//                        message line ending in `[type=...]`); `configPatchErrors` parses it.
//   * 409 index lock  -> `detail` is a structured DICT with `code`, `changed_legs`,
//                        `expected_contract`, `current_contract`, `required_action`
//                        (`_enforce_index_contract_lock`): the write was refused because the
//                        change would invalidate the stored index.
//   * other 4xx/5xx   -> `detail` is a plain string, or FastAPI's `[{loc,msg,type}]` array.
//
// The one hard invariant: the returned `message` NEVER contains the raw axios status string.
// A caught error with no usable server detail degrades to a plain, status-aware sentence, not
// to `error.message`.

import {
  parseConfigPatchErrors,
  extractPatchErrorDetail,
  type ParsedConfigFieldError,
} from './configPatchErrors';

/** Axios' runtime message for a non-2xx response. Must never reach the operator verbatim. */
const AXIOS_STATUS_MESSAGE = /request failed with status code\s*\d*/i;

export interface IndexContractConflict {
  code?: string;
  /** Which retrieval legs changed contract, e.g. ["dense", "sparse"]. */
  changedLegs: string[];
  /** The server's prescribed remedy (re-index with force, or delete the index first). */
  requiredAction?: string;
  corpusId?: string;
}

export interface SaveErrorPresentation {
  /** Server-authored, human-readable. Guaranteed free of the raw axios status string. */
  message: string;
  /** Per-field validation messages keyed by dotted TriBridConfig path (422). */
  fieldErrors: ParsedConfigFieldError[];
  /** HTTP status, when the error carried a response. */
  status?: number;
  /**
   * True when a 409 refused the write because it would invalidate the stored index. The UI
   * offers a reload-and-retry / re-index affordance rather than a bare error (M-20).
   */
  conflict: boolean;
  /** Structured 409 detail, when `conflict` is true and the body was the index-lock shape. */
  contractConflict?: IndexContractConflict;
}

function statusOf(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null || !('response' in error)) return undefined;
  const response = (error as { response?: unknown }).response;
  if (typeof response !== 'object' || response === null || !('status' in response)) return undefined;
  const status = (response as { status?: unknown }).status;
  return typeof status === 'number' ? status : undefined;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** A generic sentence for a status with no usable detail -- never the axios string. */
function genericForStatus(status: number | undefined): string {
  if (status === undefined) {
    return 'Could not reach the server to save. Check the connection and try again.';
  }
  if (status === 409) {
    return 'This change conflicts with the current server state. Reload the latest config and re-apply.';
  }
  if (status === 422 || status === 400) {
    return 'The server rejected these values. Adjust the highlighted fields and try again.';
  }
  if (status === 404) {
    return 'The target was not found on the server (it may have been removed). Reload and try again.';
  }
  if (status >= 500) {
    return `The server failed to save (HTTP ${status}). Try again; if it persists, check the server logs.`;
  }
  return `The server rejected the save (HTTP ${status}).`;
}

/** Strip the axios status string from a candidate message; empty if that is all it was. */
function sanitize(candidate: string | undefined): string {
  if (!candidate) return '';
  const trimmed = candidate.trim();
  if (!trimmed || AXIOS_STATUS_MESSAGE.test(trimmed)) return '';
  return trimmed;
}

/** Shape a caught config-save error into the one presentation used by the footer and toasts. */
export function formatSaveError(error: unknown): SaveErrorPresentation {
  const status = statusOf(error);
  const detail = extractPatchErrorDetail(error);

  // 409 index-contract lock: structured dict detail.
  const detailRecord = asRecord(detail);
  if (status === 409 && detailRecord && detailRecord.code === 'index_contract_change_requires_reindex') {
    const changedLegs = Array.isArray(detailRecord.changed_legs)
      ? detailRecord.changed_legs.map((l) => String(l))
      : [];
    const requiredAction =
      typeof detailRecord.required_action === 'string' ? detailRecord.required_action : undefined;
    const legs = changedLegs.length ? changedLegs.join(' and ') : 'index';
    const message =
      `This change alters the ${legs} contract of the current index, so the stored index no ` +
      `longer matches the config. ${requiredAction ?? 'Re-index (force) or delete the index first, then apply.'}`;
    return {
      message,
      fieldErrors: [],
      status,
      conflict: true,
      contractConflict: {
        code: String(detailRecord.code),
        changedLegs,
        requiredAction,
        corpusId: typeof detailRecord.corpus_id === 'string' ? detailRecord.corpus_id : undefined,
      },
    };
  }

  // 422 (or any) Pydantic dump string: extract per-field messages.
  if (typeof detail === 'string') {
    const fieldErrors = parseConfigPatchErrors(detail);
    if (fieldErrors.length > 0) {
      const summary = fieldErrors
        .slice(0, 4)
        .map((fe) => `${fe.path}: ${fe.message}`)
        .join('; ');
      const more = fieldErrors.length > 4 ? ` (+${fieldErrors.length - 4} more)` : '';
      return { message: `${summary}${more}`, fieldErrors, status, conflict: status === 409 };
    }
    // A plain string detail the parser did not recognise (a cross-field validator message,
    // a secret-marker error). It is server-authored, so show it -- unless it is empty.
    const sanitized = sanitize(detail);
    if (sanitized) return { message: sanitized, fieldErrors: [], status, conflict: status === 409 };
  }

  // FastAPI's default `[{loc, msg, type}]` array.
  if (Array.isArray(detail)) {
    const fieldErrors: ParsedConfigFieldError[] = [];
    for (const item of detail) {
      const rec = asRecord(item);
      if (!rec) continue;
      const loc = Array.isArray(rec.loc)
        ? rec.loc.filter((p) => p !== 'body').map((p) => String(p)).join('.')
        : '';
      const msg = typeof rec.msg === 'string' ? rec.msg : '';
      if (loc && msg) fieldErrors.push({ path: loc, message: msg });
    }
    if (fieldErrors.length > 0) {
      const summary = fieldErrors
        .slice(0, 4)
        .map((fe) => `${fe.path}: ${fe.message}`)
        .join('; ');
      const more = fieldErrors.length > 4 ? ` (+${fieldErrors.length - 4} more)` : '';
      return { message: `${summary}${more}`, fieldErrors, status, conflict: status === 409 };
    }
  }

  // A dict detail with a plain message field (e.g. {detail: {message: "..."}}).
  if (detailRecord && typeof detailRecord.message === 'string') {
    const sanitized = sanitize(detailRecord.message);
    if (sanitized) return { message: sanitized, fieldErrors: [], status, conflict: status === 409 };
  }

  // No usable detail. Prefer a status-aware sentence over the axios string.
  return { message: genericForStatus(status), fieldErrors: [], status, conflict: status === 409 };
}

/** Convenience: just the operator-facing message string. */
export function saveErrorMessage(error: unknown): string {
  return formatSaveError(error).message;
}
