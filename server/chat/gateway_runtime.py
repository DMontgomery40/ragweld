"""Resolve the single LiteLLM generation boundary for host and container runs."""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit


def resolve_litellm_base_url(
    *,
    configured_url: str,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Return a normalized OpenAI-compatible LiteLLM `/v1` base URL.

    Deployment wiring wins over persisted config so the same application code
    works on the host and inside Compose. Invalid URLs fail closed rather than
    silently routing to another provider.
    """

    env = os.environ if environ is None else environ
    raw = str(env.get("LITELLM_BASE_URL") or configured_url or "").strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path != "/v1":
        raise RuntimeError("LiteLLM base URL must be an absolute http(s) URL ending in /v1")
    return raw


def resolve_litellm_api_key(*, environ: Mapping[str, str] | None = None) -> str:
    """Return the API-to-gateway client key without reading upstream secrets."""

    env = os.environ if environ is None else environ
    key = str(env.get("LITELLM_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("LITELLM_API_KEY is required for the generation gateway")
    return key

