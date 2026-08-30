/**
 * The one marker the API substitutes for a credential it will not put on the wire.
 *
 * `server/api/config.py` withholds `indexing.postgres_url`'s password and the
 * authorization value in `tracing.otlp_headers`, replacing each with this exact string,
 * and puts the stored value back when a write returns it unchanged. Surfaces that render
 * those fields import this rather than spelling the literal, and
 * `tests/api/test_config_redaction.py` pins the two sides together so neither can drift.
 */
export const SECRET_REDACTED = '[redacted]';
