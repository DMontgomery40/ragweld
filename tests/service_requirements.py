"""Pytest service-capability gates for honest local and strict integration runs.

Mark only tests that issue real provider calls with requires_model_gateway.
They require explicit LITELLM_BASE_URL/LITELLM_API_KEY and the selected
GRAPH_E2E_KG_MODEL in the authenticated model listing. Collection never generates
text. Unconfigured capabilities skip ordinary CI and fail strict acceptance;
explicitly configured model gateway failures always fail collection;
local HTTP contract fixtures must remain unmarked.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote

import asyncpg
import httpx
import pytest
from neo4j import GraphDatabase


@dataclass(frozen=True)
class ServiceCapability:
    service: str
    available: bool
    reason: str


# Optional service/infra variables that are absent on a machine which has not
# configured that backend. A test that reads one directly must skip cleanly with
# the exact missing name rather than raise KeyError mid-run. `test_optional_service_env_access`
# is the source invariant that forbids bare `os.environ[...]` reads of these in tests.
OPTIONAL_SERVICE_ENV_VARS: frozenset[str] = frozenset(
    {
        "POSTGRES_DSN",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "QDRANT_URL",
        "FLYTE_ADMIN_URL",
        "LOKI_BASE_URL",
    }
)


def postgres_dsn_from_env(env: Mapping[str, str] | None = None) -> str | None:
    """Return an explicit DSN or safely compose one from configured components.

    The capability probe already treats ``POSTGRES_HOST`` plus the standard
    component variables as a configured integration service.  Tests that ask
    for ``POSTGRES_DSN`` must resolve the same configuration instead of probing
    successfully and then skipping.  User, password, and database components
    are URL-escaped so credentials containing DSN punctuation remain valid.
    """
    values = os.environ if env is None else env
    explicit = str(values.get("POSTGRES_DSN") or "").strip()
    if explicit:
        return explicit
    host = str(values.get("POSTGRES_HOST") or "").strip()
    if not host:
        return None
    port = str(values.get("POSTGRES_PORT") or "5432").strip()
    user = quote(str(values.get("POSTGRES_USER") or "postgres"), safe="")
    password = quote(str(values.get("POSTGRES_PASSWORD") or "postgres"), safe="")
    database = quote(str(values.get("POSTGRES_DB") or "tribrid_rag"), safe="")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def qdrant_url_from_env(env: Mapping[str, str] | None = None) -> str:
    """The Qdrant base URL the harness talks to: ``QDRANT_URL`` or the Compose default."""
    values = os.environ if env is None else env
    return str(values.get("QDRANT_URL") or "http://127.0.0.1:56333").rstrip("/")


def require_env(name: str) -> str:
    """Return env var `name`, or `pytest.skip` with the exact missing variable.

    The integration lane connects to real Postgres/Neo4j/Qdrant. On a box that
    has not configured one of those, the variable is simply unset; reading it as
    `os.environ[name]` raises `KeyError` and reports as an error, not a skip.
    This turns the same condition into an honest skip naming the one variable to
    set, and never runs beside heavy live work because the skip fires first.
    """
    value = postgres_dsn_from_env() if name == "POSTGRES_DSN" else os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not set; integration service not configured for this run")
    return value


def _strict_mode() -> bool:
    value = os.environ.get("RAGWELD_STRICT_INTEGRATION", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def probe_postgres(
    env: Mapping[str, str] | None = None,
    *,
    timeout_seconds: float = 1.0,
) -> ServiceCapability:
    values = os.environ if env is None else env
    host = values.get("POSTGRES_HOST", "127.0.0.1")
    port_text = values.get("POSTGRES_PORT", "5432")
    try:
        port = int(port_text)
    except ValueError:
        return ServiceCapability(
            service="PostgreSQL",
            available=False,
            reason=f"Invalid POSTGRES_PORT: {port_text!r}",
        )
    dsn = values.get("POSTGRES_DSN")
    if not dsn and not values.get("POSTGRES_HOST"):
        return ServiceCapability(
            service="PostgreSQL",
            available=False,
            reason="PostgreSQL integration is not configured; use scripts/test_integration.sh or set POSTGRES_DSN/POSTGRES_HOST.",
        )
    database = values.get("POSTGRES_DB", "tribrid_rag")
    user = values.get("POSTGRES_USER", "postgres")
    password = values.get("POSTGRES_PASSWORD", "postgres")

    async def _connect() -> None:
        kwargs: dict[str, object] = {"timeout": timeout_seconds}
        if dsn:
            kwargs["dsn"] = dsn
        else:
            kwargs.update(
                {
                    "host": host,
                    "port": port,
                    "database": database,
                    "user": user,
                    "password": password,
                }
            )
        connection = await asyncpg.connect(**kwargs)
        try:
            await connection.execute("SELECT 1")
        finally:
            await connection.close()

    try:
        asyncio.run(_connect())
    except Exception as exc:
        return ServiceCapability(
            service="PostgreSQL",
            available=False,
            reason=f"PostgreSQL is unavailable at {host}:{port} ({type(exc).__name__})",
        )
    return ServiceCapability(
        service="PostgreSQL",
        available=True,
        reason=f"PostgreSQL is reachable at {host}:{port}",
    )


def probe_neo4j(
    env: Mapping[str, str] | None = None,
    *,
    timeout_seconds: float = 1.0,
) -> ServiceCapability:
    values = os.environ if env is None else env
    uri = values.get("NEO4J_URI")
    if not uri:
        return ServiceCapability(
            service="Neo4j",
            available=False,
            reason="Neo4j integration is not configured; use scripts/test_integration.sh or set NEO4J_URI.",
        )
    user = values.get("NEO4J_USER", "neo4j")
    password = values.get("NEO4J_PASSWORD", "password")
    driver = None
    try:
        driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            connection_timeout=timeout_seconds,
        )
        driver.verify_connectivity()
    except Exception as exc:
        return ServiceCapability(
            service="Neo4j",
            available=False,
            reason=f"Neo4j is unavailable at {uri} ({type(exc).__name__})",
        )
    finally:
        if driver is not None:
            driver.close()
    return ServiceCapability(service="Neo4j", available=True, reason=f"Neo4j is reachable at {uri}")


def probe_qdrant(
    env: Mapping[str, str] | None = None,
    *,
    timeout_seconds: float = 1.0,
) -> ServiceCapability:
    url = qdrant_url_from_env(env)
    try:
        response = httpx.get(f"{url}/readyz", timeout=timeout_seconds)
        ok = response.status_code < 500
    except Exception as exc:
        return ServiceCapability(
            service="Qdrant",
            available=False,
            reason=f"Qdrant is unavailable at {url} ({type(exc).__name__})",
        )
    if not ok:
        return ServiceCapability(
            service="Qdrant",
            available=False,
            reason=f"Qdrant at {url} responded {response.status_code}",
        )
    return ServiceCapability(service="Qdrant", available=True, reason=f"Qdrant is reachable at {url}")


def probe_flyte(
    env: Mapping[str, str] | None = None,
    *,
    timeout_seconds: float = 1.0,
) -> ServiceCapability:
    values = os.environ if env is None else env
    url = str(values.get("FLYTE_ADMIN_URL") or "http://127.0.0.1:30080").rstrip("/")
    try:
        response = httpx.get(f"{url}/healthcheck", timeout=timeout_seconds)
        ok = response.status_code < 400
    except Exception as exc:
        return ServiceCapability(
            service="Flyte",
            available=False,
            reason=f"Flyte admin is unavailable at {url} ({type(exc).__name__}); start it with ./start.sh --with-flyte",
        )
    if not ok:
        return ServiceCapability(
            service="Flyte",
            available=False,
            reason=f"Flyte admin at {url} responded {response.status_code}",
        )
    return ServiceCapability(service="Flyte", available=True, reason=f"Flyte admin is reachable at {url}")


def probe_model_gateway(
    env: Mapping[str, str] | None = None, *, timeout_seconds: float = 2.0,
) -> ServiceCapability:
    """Verify authenticated model availability without issuing a generation request."""
    from server.model_policy import ensure_model_allowed

    values = os.environ if env is None else env
    base = str(values.get("LITELLM_BASE_URL") or "").strip().rstrip("/")
    key = str(values.get("LITELLM_API_KEY") or "").strip()
    model = str(values.get("GRAPH_E2E_KG_MODEL") or "openai.gpt-5.6-luna").strip()
    if not base or not key:
        return ServiceCapability("Model gateway", False, "Model gateway not configured: LITELLM_BASE_URL and LITELLM_API_KEY are required")
    try:
        ensure_model_allowed(model)
        response = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=timeout_seconds)
        if response.status_code != 200:
            return ServiceCapability("Model gateway", False, f"Authenticated model listing returned HTTP {response.status_code}")
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not any(isinstance(row, dict) and row.get("id") == model for row in rows):
            return ServiceCapability("Model gateway", False, f"Configured model {model!r} is absent from the authenticated model listing")
    except Exception as exc:
        return ServiceCapability("Model gateway", False, f"Model gateway probe failed: {type(exc).__name__}")
    return ServiceCapability("Model gateway", True, f"Authenticated model gateway lists {model!r}")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "requires_model_gateway: requires an authenticated real model gateway; missing capability fails strict integration")
    config.addinivalue_line("markers", "requires_postgres: requires a live authenticated PostgreSQL connection")
    config.addinivalue_line("markers", "requires_neo4j: requires a live authenticated Neo4j connection")
    config.addinivalue_line("markers", "requires_qdrant: requires a live Qdrant vector-store service")
    config.addinivalue_line("markers", "requires_flyte: requires the live Compose-owned Flyte control plane")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    required: dict[str, list[pytest.Item]] = {"postgres": [], "neo4j": [], "qdrant": [], "flyte": [], "model_gateway": []}
    for item in items:
        if item.get_closest_marker("requires_model_gateway") is not None:
            required["model_gateway"].append(item)
        if item.get_closest_marker("requires_postgres") is not None:
            required["postgres"].append(item)
        if item.get_closest_marker("requires_neo4j") is not None:
            required["neo4j"].append(item)
        if item.get_closest_marker("requires_qdrant") is not None:
            required["qdrant"].append(item)
        if item.get_closest_marker("requires_flyte") is not None:
            required["flyte"].append(item)

    probes = {
        "postgres": probe_postgres,
        "neo4j": probe_neo4j,
        "qdrant": probe_qdrant,
        "flyte": probe_flyte,
        "model_gateway": probe_model_gateway,
    }
    unavailable: dict[str, ServiceCapability] = {}
    for name, marked_items in required.items():
        if not marked_items:
            continue
        capability = probes[name]()
        if not capability.available:
            unavailable[name] = capability

    if unavailable and _strict_mode():
        details = "; ".join(capability.reason for capability in unavailable.values())
        raise pytest.UsageError(f"Strict integration requirements unavailable: {details}")

    if "model_gateway" in unavailable and str(os.environ.get("LITELLM_BASE_URL") or "").strip():
        raise pytest.UsageError(f"Configured model gateway unavailable: {unavailable['model_gateway'].reason}")

    for name, capability in unavailable.items():
        skip = pytest.mark.skip(reason=capability.reason)
        for item in required[name]:
            item.add_marker(skip)
