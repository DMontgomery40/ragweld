"""The one place credentials are withheld from anything that leaves the process.

`GET /api/config` shipped `indexing.postgres_url` -- a DSN with an embedded
username/password pair -- into client-side JS on every page load (M-89), and
`tracing.otlp_headers` carried whatever authorization header an operator typed into the
config form. The same two values also ride along in the config snapshot every eval,
synthetic, reranker and agent run record pins, and those records are served to the
browser too, so the redaction cannot live in one router.

This module is that single home. `server/api/config.py` and every run-record route import
from here; nothing re-implements the rule. Two directions:

* **out** -- `redact_config_secrets` / `redacted_config_snapshot` / `redact_config_record`
  replace each credential with `SECRET_REDACTED` on a COPY. Always a copy: `load_config`
  hands out a shared object and redacting it in place would poison the in-process config
  and eventually write the marker to disk.
* **in** -- `restore_config_secrets` puts the stored value back when a write returns one
  still wearing the marker, and raises `SecretMarkerWriteError` when there is nothing
  behind it rather than persisting the literal.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from server.models.tribrid_config_model import ConfigRegistryResponse, TriBridConfig

#
# `GET /api/config` shipped `indexing.postgres_url` -- a DSN with an embedded
# username/password pair -- into client-side JS on every page load (M-89), and rendered
# it into a plain text input on Infrastructure > Paths & Stores where it sat in clear on
# screen and in every screenshot (M-88). `tracing.otlp_headers` had the same shape: its
# placeholder invites `Authorization=Bearer ...` and whatever is typed there is stored in
# config and rendered back to anyone who opens the page (M-90).
#
# The credential never leaves the server. The operator keeps every non-secret part of the
# value -- host, port, database, user, and any header that is not an authorization -- so
# the field stays editable, and a value that comes back still wearing the marker is
# restored from what is on disk. That round trip is the whole contract: there is no second
# code path, no "unredacted" mode and no client-side toggle.

SECRET_REDACTED = "[redacted]"

# Header names whose VALUE is a credential. Everything else (X-Scope-OrgID and friends)
# stays visible and editable, which is the point: only the auth material is withheld.
_SECRET_HEADER_NAMES = ("authorization", "proxy-authorization", "api-key", "x-api-key")


def _is_secret_header_name(name: str) -> bool:
    lowered = name.strip().lower()
    if lowered in _SECRET_HEADER_NAMES:
        return True
    return any(token in lowered for token in ("token", "secret", "password", "apikey"))


# The password runs to the LAST `@` before the host, not the first: a password may contain
# a literal `@` (percent-encoding is the norm, but the boundary must not assume it), and a
# lazy match left the tail of such a password in the clear -- `u:p@ss@host` redacted to
# `[redacted]@ss@host`. `[^/]*` with a greedy match and a `@` that is not followed by
# another `@` before the host takes the whole userinfo.
_DSN_CREDENTIALS_RE = re.compile(r"^(?P<head>[a-zA-Z0-9+.\-]+://[^/@]*?:)(?P<password>[^/]*)(?P<tail>@)(?=[^/@]*(?:[/?#]|$))")


def _redact_dsn_password(dsn: str) -> str:
    """Replace only the password component of a URL-shaped DSN."""
    if not dsn:
        return dsn
    return _DSN_CREDENTIALS_RE.sub(lambda m: f"{m.group('head')}{SECRET_REDACTED}{m.group('tail')}", dsn, count=1)


def _dsn_password(dsn: str) -> str | None:
    match = _DSN_CREDENTIALS_RE.search(dsn or "")
    return match.group("password") if match else None


class SecretMarkerWriteError(ValueError):
    """A write tried to persist the redaction marker itself as a credential."""


def _restore_dsn_password(incoming: str, stored: str) -> str:
    """Put the stored password back when the client returned the marker.

    A marker with nothing behind it is refused rather than stored. Typing `[redacted]`
    into a NEW DSN is the obvious thing to do after seeing it on an existing one, and
    silently persisting that literal would set the password to a string that looks like a
    withheld secret and is not one.
    """
    if _dsn_password(incoming) != SECRET_REDACTED:
        return incoming
    stored_password = _dsn_password(stored)
    if stored_password is None:
        raise SecretMarkerWriteError(
            f"{SECRET_REDACTED!r} is the marker for a withheld password, not a password. "
            "There is no stored value to keep here -- type the real password, or leave "
            "the field empty."
        )
    return _DSN_CREDENTIALS_RE.sub(
        lambda m: f"{m.group('head')}{stored_password}{m.group('tail')}", incoming, count=1
    )


def _split_headers(raw: str) -> list[tuple[str, str | None]]:
    """Parse a `k=v,k=v` header string, keeping malformed entries as (text, None)."""
    entries: list[tuple[str, str | None]] = []
    for part in (raw or "").split(","):
        if not part.strip():
            continue
        name, sep, value = part.partition("=")
        entries.append((name, value) if sep else (part, None))
    return entries


def _join_headers(entries: list[tuple[str, str | None]]) -> str:
    return ",".join(name if value is None else f"{name}={value}" for name, value in entries)


def _redact_headers(raw: str) -> str:
    if not raw:
        return raw
    return _join_headers(
        [
            (name, SECRET_REDACTED if value is not None and _is_secret_header_name(name) else value)
            for name, value in _split_headers(raw)
        ]
    )


def _restore_headers(incoming: str, stored: str) -> str:
    if not incoming:
        return incoming
    stored_by_name = {
        name.strip().lower(): value for name, value in _split_headers(stored) if value is not None
    }
    restored: list[tuple[str, str | None]] = []
    for name, value in _split_headers(incoming):
        if value == SECRET_REDACTED:
            kept = stored_by_name.get(name.strip().lower())
            if kept is None:
                raise SecretMarkerWriteError(
                    f"{name.strip()} was set to {SECRET_REDACTED!r}, which is the marker "
                    "for a withheld value, not a value. There is no stored header to keep "
                    "-- type the real one, or remove the entry."
                )
            restored.append((name, kept))
        else:
            restored.append((name, value))
    return _join_headers(restored)


def redact_config_secrets(config: TriBridConfig) -> TriBridConfig:
    """Return a copy of `config` with every credential replaced by the marker.

    Always a copy: `load_config` hands out a shared object, and redacting it in place
    would poison the in-process config and eventually write the marker to disk.
    """
    safe = config.model_copy(deep=True)
    safe.indexing.postgres_url = _redact_dsn_password(safe.indexing.postgres_url)
    safe.tracing.otlp_headers = _redact_headers(safe.tracing.otlp_headers)
    return safe


def restore_config_secrets(incoming: TriBridConfig, stored: TriBridConfig) -> TriBridConfig:
    """Put back any credential the client returned still wearing the marker.

    Covers PUT as well as PATCH: "Apply All Changes" PUTs whatever the browser holds,
    which is the redacted document it was served.
    """
    merged = incoming.model_copy(deep=True)
    merged.indexing.postgres_url = _restore_dsn_password(
        merged.indexing.postgres_url, stored.indexing.postgres_url
    )
    merged.tracing.otlp_headers = _restore_headers(
        merged.tracing.otlp_headers, stored.tracing.otlp_headers
    )
    return merged


def redact_registry_defaults(registry: ConfigRegistryResponse) -> ConfigRegistryResponse:
    """The registry publishes each field's default; two of them are credential-shaped."""
    safe = registry.model_copy(deep=True)
    for field in safe.fields:
        if not isinstance(field.default, str) or not field.default:
            continue
        if field.path == "indexing.postgres_url":
            field.default = _redact_dsn_password(field.default)
        elif field.path == "tracing.otlp_headers":
            field.default = _redact_headers(field.default)
    return safe

# ---------------------------------------------------------------------------
# Run records
# ---------------------------------------------------------------------------
#
# Every eval / synthetic / reranker / agent run pins the configuration that governed it,
# nested (`model_dump`) and flat (`to_flat_dict`), and those records are served to the
# browser by their run-detail routes. `to_flat_dict` carries `POSTGRES_URL` and
# `OTLP_HEADERS` verbatim, so a snapshot is exactly as sensitive as `/api/config` is.
#
# Two seams, because records already on disk were written before this existed:
#   * write -- `redacted_config_snapshot` is the ONLY way a route should build the pair,
#     so no call site can redact one form and forget the other;
#   * read  -- `redact_config_record` cleans a stored record on its way out.

_FLAT_SECRET_KEYS = ("POSTGRES_URL", "OTLP_HEADERS")


def redacted_config_snapshot(config: TriBridConfig) -> tuple[dict[str, Any], dict[str, Any]]:
    """The (nested, flat) config snapshot a run record pins, with credentials withheld."""
    safe = redact_config_secrets(config)
    return safe.model_dump(mode="json"), safe.to_flat_dict()


def redact_config_record(
    nested: dict[str, Any] | None,
    flat: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Withhold credentials from a config snapshot that is already stored.

    Operates on the dict shapes rather than on `TriBridConfig`, because a record written
    by an older build may not validate against the current model and must still be served
    without its credentials.
    """
    safe_nested = deepcopy(nested) if nested else {}
    indexing = safe_nested.get("indexing")
    if isinstance(indexing, dict) and isinstance(indexing.get("postgres_url"), str):
        indexing["postgres_url"] = _redact_dsn_password(indexing["postgres_url"])
    tracing = safe_nested.get("tracing")
    if isinstance(tracing, dict) and isinstance(tracing.get("otlp_headers"), str):
        tracing["otlp_headers"] = _redact_headers(tracing["otlp_headers"])

    safe_flat = deepcopy(flat) if flat else {}
    for key in _FLAT_SECRET_KEYS:
        value = safe_flat.get(key)
        if not isinstance(value, str):
            continue
        safe_flat[key] = (
            _redact_dsn_password(value) if key == "POSTGRES_URL" else _redact_headers(value)
        )
    return safe_nested, safe_flat


def redact_run_record(run: Any) -> Any:
    """Withhold credentials from a run record in place, whatever its model.

    Every run model spells the pair `config_snapshot` / `config`; anything that carries
    those two attributes is cleaned the same way, so a new run family is covered by
    calling this in its loader rather than by extending a list of types here.
    """
    if run is None:
        return run
    nested = getattr(run, "config_snapshot", None)
    flat = getattr(run, "config", None)
    if nested is None and flat is None:
        return run
    safe_nested, safe_flat = redact_config_record(
        nested if isinstance(nested, dict) else None,
        flat if isinstance(flat, dict) else None,
    )
    if isinstance(nested, dict):
        run.config_snapshot = safe_nested
    if isinstance(flat, dict):
        run.config = safe_flat
    return run
