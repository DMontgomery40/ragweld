// TriBridRAG - PATCH /api/config/{section} failure parsing.
//
// `update_config_section` (server/api/config.py) re-validates the whole merged section
// against `TriBridConfig` and, on rejection, raises `HTTPException(422, detail=str(e))` where
// `e` is a Pydantic `ValidationError` -- a human-readable dump, not FastAPI's structured
// `[{loc, msg, type}]` body. Each error in that dump is an unindented dotted-path line
// (e.g. "enrichment.max_chunk_summaries") followed by an indented message line ending in
// `[type=...]`. The path is relative to `TriBridConfig` itself, so it already matches a
// `NumberField`'s `configPath` prop with no extra keying.
//
// Every bound this migration set on a `NumberField` now equals the field's Pydantic `ge`/`le`
// (`test_every_number_field_advertises_its_pydantic_bounds`), so a bounds-only 422 should be
// structurally unreachable through the UI. This stays a defensive path for whatever a bound
// cannot express (cross-field `model_validator`s, secret-marker failures) -- its failure mode
// is silence, not noise: an unparsed detail yields no field errors and the existing generic
// `error` string still populates, so a format change degrades gracefully instead of showing
// nothing.

export interface ParsedConfigFieldError {
  /** Dotted TriBridConfig path, e.g. "enrichment.max_chunk_summaries". */
  path: string;
  /** The constraint message, e.g. "Input should be less than or equal to 500". */
  message: string;
}

/** One unindented "a.b.c" line followed by an indented "<message> [type=...]" line. */
const FIELD_ERROR_LINE = /^([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)\n[ \t]+(.+?)[ \t]*\[type=/gm;

/**
 * Parse a config PATCH failure's `detail` into per-field messages.
 *
 * Returns `[]` for anything that is not a plain string or does not match the expected shape
 * (a differently-shaped `detail`, a non-validation 4xx/5xx) -- callers keep showing the
 * generic error message in that case rather than nothing at all.
 */
export function parseConfigPatchErrors(detail: unknown): ParsedConfigFieldError[] {
  if (typeof detail !== 'string' || !detail) return [];
  const errors: ParsedConfigFieldError[] = [];
  for (const match of detail.matchAll(FIELD_ERROR_LINE)) {
    errors.push({ path: match[1], message: match[2].trim() });
  }
  return errors;
}

/** The raw `detail` payload of an axios error response, if it has one. */
export function extractPatchErrorDetail(error: unknown): unknown {
  if (typeof error !== 'object' || error === null || !('response' in error)) return undefined;
  const response = (error as { response?: unknown }).response;
  if (typeof response !== 'object' || response === null || !('data' in response)) return undefined;
  const data = (response as { data?: unknown }).data;
  if (typeof data !== 'object' || data === null || !('detail' in data)) return undefined;
  return (data as { detail?: unknown }).detail;
}
