"""Generation gateway catalog: the one mapping from catalog rows to LiteLLM aliases.

``data/models.json`` is the source of truth for every generation route the
application can select. Every generation-only row carries a ``gateway_alias``
(the application-visible LiteLLM alias) and a ``gateway_upstream`` (the LiteLLM
``litellm_params.model``). This module renders those rows into
``infra/litellm-config.yaml`` and joins live LiteLLM discovery back to the
catalog so operator surfaces show provider, name, pricing and context for every
alias. The YAML is generated output; it is never hand-edited.

Invariants enforced by :func:`gateway_rows` (fail closed, never silently skip):

- every GEN-only row has both gateway fields (no unserved generation rows);
- rows validate as :class:`ModelCatalogEntry`;
- OpenRouter rows: ``gateway_alias == alias(model)`` and
  ``gateway_upstream == "openrouter/" + model``;
- exactly one local serving row (``provider == ragweld``,
  ``gateway_alias == ragweld-local``, ``gateway_upstream == openai/ragweld-local``);
- aliases are unique and lowercase.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from server.models.runtime_gateway import validate_litellm_alias
from server.models.tribrid_config_model import ModelCatalogEntry

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "data" / "models.json"
WEB_CATALOG_PATH = REPO_ROOT / "web" / "public" / "models.json"
LITELLM_CONFIG_PATH = REPO_ROOT / "infra" / "litellm-config.yaml"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_UPSTREAM_PREFIX = "openrouter/"
OPENROUTER_API_KEY_REF = "os.environ/OPENROUTER_API_KEY"
META_ROUTER_PROVIDER = "openrouter"  # openrouter/auto, openrouter/free, ... resolve per request

LOCAL_GATEWAY_ALIAS = "ragweld-local"
LOCAL_GATEWAY_PROVIDER = "ragweld"
LOCAL_GATEWAY_UPSTREAM = "openai/ragweld-local"
# The LiteLLM container reaches the host `local-model` serving process (started by
# ./start.sh when chat.vllm is enabled) through the Docker host gateway. Which backend
# serves it, and whether the lane is on, is runtime truth (/api/runtime-capabilities
# generation.local_serving), never a property of the catalog row.
LOCAL_GATEWAY_BASE_URL = "http://host.docker.internal:58080/v1"

GENERATED_HEADER = (
    "# GENERATED from data/models.json by scripts/generate_litellm_config.py. DO NOT HAND-EDIT.\n"
    "# Every GEN catalog row with a gateway_alias becomes one model_list entry; regenerate after\n"
    "# `uv run python scripts/refresh_models_catalog.py --apply` or any catalog edit.\n"
)

_ALIAS_SEPARATOR_RE = re.compile(r"[/:]")


class GatewayCatalogError(ValueError):
    """Raised when the catalog cannot be rendered into a valid gateway config."""


@dataclass(frozen=True, slots=True)
class GatewayRow:
    """One catalog-backed LiteLLM alias."""

    alias: str
    upstream: str
    provider: str
    model: str
    base_url: str | None
    display_name: str | None
    context: int | None
    input_per_1k: float | None
    output_per_1k: float | None
    supports_vision: bool


def gateway_alias_for_openrouter_id(model_id: str) -> str:
    """Derive the application-visible alias for one OpenRouter model id.

    ``openai/gpt-5.4-mini`` becomes ``openai.gpt-5.4-mini`` and the variant
    ``qwen/qwen3-coder:free`` becomes ``qwen.qwen3-coder.free``. Aliases are
    lowercase and never contain ``/`` or ``:`` so they cannot be mistaken for a
    direct provider id.
    """

    raw = str(model_id or "").strip()
    provider, separator, slug = raw.partition("/")
    if not separator or not provider.strip() or not slug.strip():
        raise GatewayCatalogError(f"OpenRouter model id must be <provider>/<model>: {raw!r}")
    if provider.strip().lower() == META_ROUTER_PROVIDER:
        raise GatewayCatalogError(
            f"{raw!r} is an OpenRouter meta-router, not a fixed model; it cannot be a gateway route"
        )
    alias = _ALIAS_SEPARATOR_RE.sub(".", raw).lower()
    try:
        return validate_litellm_alias(alias, allow_empty=False)
    except ValueError as error:
        raise GatewayCatalogError(f"cannot derive a LiteLLM alias from {raw!r}: {error}") from error


def openrouter_upstream_for_id(model_id: str) -> str:
    return f"{OPENROUTER_UPSTREAM_PREFIX}{str(model_id or '').strip()}"


def _catalog_rows(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    rows = catalog.get("models")
    if not isinstance(rows, list):
        raise GatewayCatalogError("catalog must contain a top-level 'models' list")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise GatewayCatalogError(f"catalog models[{index}] is not an object")
    return list(rows)


def _is_generation_only(entry: ModelCatalogEntry) -> bool:
    return set(entry.components) == {"GEN"}


def _validate_row(row: dict[str, Any]) -> ModelCatalogEntry:
    try:
        return ModelCatalogEntry.model_validate(row)
    except ValueError as error:
        identity = f"{row.get('provider')}/{row.get('model')}"
        raise GatewayCatalogError(f"{identity}: invalid catalog row: {error}") from error


def gateway_rows(catalog: dict[str, Any]) -> list[GatewayRow]:
    """Return every gateway-served GEN row, validated, local alias first."""

    rows: list[GatewayRow] = []
    seen: set[str] = set()
    local_rows = 0
    for raw in _catalog_rows(catalog):
        entry = _validate_row(raw)
        identity = f"{entry.provider}/{entry.model}"
        has_gateway = entry.gateway_alias is not None or entry.gateway_upstream is not None
        if not has_gateway:
            if _is_generation_only(entry):
                raise GatewayCatalogError(
                    f"{identity}: generation rows must be gateway-served (gateway_alias + gateway_upstream missing)"
                )
            continue
        if "GEN" not in entry.components:
            raise GatewayCatalogError(f"{identity}: gateway fields are only valid on GEN rows")
        alias = str(entry.gateway_alias or "").strip()
        upstream = str(entry.gateway_upstream or "").strip()
        if not alias or not upstream:
            raise GatewayCatalogError(f"{identity}: gateway_alias and gateway_upstream must both be set")
        try:
            alias = validate_litellm_alias(alias, allow_empty=False)
        except ValueError as error:
            raise GatewayCatalogError(f"{identity}: invalid gateway_alias {alias!r}: {error}") from error
        if alias != alias.lower():
            raise GatewayCatalogError(f"{identity}: gateway_alias must be lowercase ({alias!r})")
        if alias in seen:
            raise GatewayCatalogError(f"{identity}: duplicate gateway_alias {alias!r}")
        seen.add(alias)

        base_url = str(entry.base_url or "").strip() or None
        if upstream.startswith(OPENROUTER_UPSTREAM_PREFIX):
            expected_alias = gateway_alias_for_openrouter_id(entry.model)
            if alias != expected_alias:
                raise GatewayCatalogError(
                    f"{identity}: gateway_alias {alias!r} does not match the model id (expected {expected_alias!r})"
                )
            if upstream != openrouter_upstream_for_id(entry.model):
                raise GatewayCatalogError(f"{identity}: gateway_upstream {upstream!r} does not match the model id")
            if entry.provider.strip().lower() != entry.model.split("/", 1)[0].lower():
                raise GatewayCatalogError(f"{identity}: provider must equal the OpenRouter id prefix")
        elif alias == LOCAL_GATEWAY_ALIAS:
            if entry.provider != LOCAL_GATEWAY_PROVIDER or upstream != LOCAL_GATEWAY_UPSTREAM:
                raise GatewayCatalogError(
                    f"{identity}: the local serving row must be provider={LOCAL_GATEWAY_PROVIDER!r} "
                    f"with gateway_upstream={LOCAL_GATEWAY_UPSTREAM!r}"
                )
            if not base_url:
                raise GatewayCatalogError(f"{identity}: the local serving row requires base_url")
            local_rows += 1
        else:
            raise GatewayCatalogError(
                f"{identity}: gateway_upstream must be openrouter/<id> or the {LOCAL_GATEWAY_ALIAS} vLLM row"
            )

        if entry.context is None or int(entry.context) <= 0:
            raise GatewayCatalogError(
                f"{identity}: gateway rows must carry a positive context window (prompt budgeting fails closed without it)"
            )

        rows.append(
            GatewayRow(
                alias=alias,
                upstream=upstream,
                provider=entry.provider,
                model=entry.model,
                base_url=base_url,
                display_name=entry.display_name,
                context=entry.context,
                input_per_1k=entry.input_per_1k,
                output_per_1k=entry.output_per_1k,
                supports_vision=entry.supports_vision,
            )
        )

    if local_rows != 1:
        raise GatewayCatalogError(f"catalog must contain exactly one {LOCAL_GATEWAY_ALIAS} vLLM serving row")

    rows.sort(key=lambda item: (0 if item.alias == LOCAL_GATEWAY_ALIAS else 1, item.alias))
    return rows


def gateway_rows_by_alias(catalog: dict[str, Any]) -> dict[str, GatewayRow]:
    return {row.alias: row for row in gateway_rows(catalog)}


def _litellm_params(row: GatewayRow) -> dict[str, str]:
    if row.upstream.startswith(OPENROUTER_UPSTREAM_PREFIX):
        return {"model": row.upstream, "api_key": OPENROUTER_API_KEY_REF}
    return {"model": row.upstream, "api_base": str(row.base_url), "api_key": "none"}


def build_model_list(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Render LiteLLM ``model_list`` entries from the catalog."""

    return [{"model_name": row.alias, "litellm_params": _litellm_params(row)} for row in gateway_rows(catalog)]


def build_litellm_config(catalog: dict[str, Any]) -> dict[str, Any]:
    """Render the complete LiteLLM proxy config document (no retries, no fallbacks)."""

    return {
        "model_list": build_model_list(catalog),
        "litellm_settings": {
            "num_retries": 0,
            "fallbacks": [],
            "context_window_fallbacks": [],
            "callbacks": ["prometheus"],
            "require_auth_for_metrics_endpoint": False,
        },
        "router_settings": {"num_retries": 0},
        "general_settings": {
            "master_key": "os.environ/LITELLM_MASTER_KEY",
            "store_model_in_db": False,
        },
    }


def render_litellm_config(catalog: dict[str, Any]) -> str:
    body = yaml.safe_dump(build_litellm_config(catalog), sort_keys=False, allow_unicode=True, width=200)
    return GENERATED_HEADER + body


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    """Load the catalog document (object root with a ``models`` list)."""

    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("models"), list):
        raise GatewayCatalogError(f"{path} must be a JSON object with a 'models' list")
    return dict(raw)


_CACHE_LOCK = threading.Lock()
_CACHE: dict[Path, tuple[tuple[int, int], dict[str, Any], dict[str, GatewayRow]]] = {}


def _catalog_stamp(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def load_catalog_cached(path: Path = CATALOG_PATH) -> dict[str, Any]:
    """Return the parsed catalog, re-reading only when the file changes on disk.

    Blocking (stat + file read); call from a worker thread inside async handlers.
    """

    stamp = _catalog_stamp(path)
    with _CACHE_LOCK:
        cached = _CACHE.get(path)
        if cached is not None and cached[0] == stamp:
            return cached[1]
    catalog = load_catalog(path)
    rows = {row.alias: row for row in gateway_rows(catalog)}
    with _CACHE_LOCK:
        _CACHE[path] = (stamp, catalog, rows)
    return catalog


def gateway_rows_by_alias_cached(path: Path = CATALOG_PATH) -> dict[str, GatewayRow]:
    """Alias -> GatewayRow for the on-disk catalog, cached by file stamp (blocking)."""

    load_catalog_cached(path)
    with _CACHE_LOCK:
        return dict(_CACHE[path][2])


def gateway_rows_snapshot(path: Path = CATALOG_PATH) -> dict[str, GatewayRow]:
    """Alias -> GatewayRow from memory only; empty until warmed. Never touches disk.

    Safe to call on the event loop. Warm it with :func:`warm_gateway_catalog`
    (startup) or :func:`gateway_rows_by_alias_cached` (worker thread).
    """

    with _CACHE_LOCK:
        cached = _CACHE.get(path)
        return dict(cached[2]) if cached is not None else {}


def gateway_upstream_for_alias(alias: str, path: Path = CATALOG_PATH) -> str:
    """The LiteLLM upstream (``openrouter/<model>`` or ``openai/ragweld-local``) behind an alias.

    Reads the warmed in-memory snapshot only; an alias the catalog does not serve fails
    closed, because the caller is about to choose a request protocol from the answer.
    """
    key = str(alias or "").strip()
    row = gateway_rows_snapshot(path).get(key)
    if row is None:
        raise RuntimeError(f"Gateway alias {key!r} is not in the loaded generation catalog")
    return row.upstream


def warm_gateway_catalog(path: Path = CATALOG_PATH) -> int:
    """Load the catalog into the in-memory snapshot (blocking). Returns the alias count."""

    return len(gateway_rows_by_alias_cached(path))


@contextmanager
def catalog_write_lock(catalog_path: Path = CATALOG_PATH) -> Iterator[None]:
    """Interprocess lock for catalog mutations (API upsert and the refresh CLI share it)."""

    lock_path = catalog_path.with_name(catalog_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a process-unique temp file and rename (never shares a temp name across writers)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def serialize_catalog(catalog: dict[str, Any]) -> str:
    return json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"


def write_catalog_trio(
    catalog: dict[str, Any],
    *,
    canonical_path: Path = CATALOG_PATH,
    mirror_path: Path = WEB_CATALOG_PATH,
    litellm_config_path: Path = LITELLM_CONFIG_PATH,
) -> None:
    """Validate, render, then write catalog + web mirror + generated YAML under the shared lock.

    Everything is validated and rendered before the first byte hits disk. The
    three files are written in sequence (not one transaction); an IO failure in
    the middle is caught by `generate_litellm_config.py --check` and the
    lockstep unit test rather than silently tolerated.
    """

    gateway_rows(catalog)
    catalog_text = serialize_catalog(catalog)
    gateway_text = render_litellm_config(catalog)
    with catalog_write_lock(canonical_path):
        atomic_write_text(canonical_path, catalog_text)
        atomic_write_text(mirror_path, catalog_text)
        litellm_config_path.parent.mkdir(parents=True, exist_ok=True)
        with litellm_config_path.open("w", encoding="utf-8") as handle:  # in place: bind-mounted file
            handle.write(gateway_text)


def write_litellm_config(catalog: dict[str, Any], path: Path = LITELLM_CONFIG_PATH) -> str:
    """Write the rendered config in place.

    The file is bind-mounted into the LiteLLM container, so it is rewritten in
    place (same inode) rather than replaced through a temp file.
    """

    text = render_litellm_config(catalog)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)
    return text
