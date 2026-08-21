"""Pytest service-capability gates for honest local and strict integration runs."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass

import asyncpg
import httpx
import pytest
from neo4j import GraphDatabase


@dataclass(frozen=True)
class ServiceCapability:
    service: str
    available: bool
    reason: str


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
    values = os.environ if env is None else env
    url = str(values.get("QDRANT_URL") or "http://127.0.0.1:56333").rstrip("/")
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


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "requires_postgres: requires a live authenticated PostgreSQL connection")
    config.addinivalue_line("markers", "requires_neo4j: requires a live authenticated Neo4j connection")
    config.addinivalue_line("markers", "requires_pg_search: requires the optional ParadeDB pg_search extension")
    config.addinivalue_line("markers", "requires_qdrant: requires a live Qdrant vector-store service")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    required: dict[str, list[pytest.Item]] = {"postgres": [], "neo4j": [], "qdrant": []}
    for item in items:
        if item.get_closest_marker("requires_postgres") is not None:
            required["postgres"].append(item)
        if item.get_closest_marker("requires_neo4j") is not None:
            required["neo4j"].append(item)
        if item.get_closest_marker("requires_qdrant") is not None:
            required["qdrant"].append(item)

    probes = {
        "postgres": probe_postgres,
        "neo4j": probe_neo4j,
        "qdrant": probe_qdrant,
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

    for name, capability in unavailable.items():
        skip = pytest.mark.skip(reason=capability.reason)
        for item in required[name]:
            item.add_marker(skip)
