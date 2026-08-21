from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from asyncpg import exceptions as asyncpg_exceptions
from neo4j import exceptions as neo4j_exceptions

_POSTGRES_UNAVAILABLE = (
    asyncpg_exceptions.CannotConnectNowError,
    asyncpg_exceptions.ClientCannotConnectError,
    asyncpg_exceptions.ConnectionDoesNotExistError,
    asyncpg_exceptions.ConnectionFailureError,
    asyncpg_exceptions.ConnectionRejectionError,
    asyncpg_exceptions.PostgresConnectionError,
    asyncpg_exceptions.TooManyConnectionsError,
)

_NEO4J_UNAVAILABLE = (
    neo4j_exceptions.ServiceUnavailable,
    neo4j_exceptions.SessionExpired,
)

_TRANSPORT_UNAVAILABLE = (
    ConnectionError,
    TimeoutError,
)

DependencyName = Literal["postgres", "neo4j", "qdrant", "embedding_provider", "feedback_log", "lineage_store"]


class DependencyUnavailableError(RuntimeError):
    """Internal dependency failure with explicit provenance."""

    def __init__(self, dependency: DependencyName, operation: str) -> None:
        self.dependency = dependency
        self.operation = operation
        super().__init__(f"{dependency} unavailable during {operation}")


def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
    pending = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)


def is_postgres_unavailable(exc: BaseException) -> bool:
    return any(
        (isinstance(item, DependencyUnavailableError) and item.dependency == "postgres")
        or isinstance(item, _POSTGRES_UNAVAILABLE)
        for item in _exception_chain(exc)
    )


def is_neo4j_unavailable(exc: BaseException) -> bool:
    return any(
        (isinstance(item, DependencyUnavailableError) and item.dependency == "neo4j")
        or isinstance(item, _NEO4J_UNAVAILABLE)
        for item in _exception_chain(exc)
    )


def is_transport_unavailable(exc: BaseException) -> bool:
    return any(isinstance(item, _TRANSPORT_UNAVAILABLE) for item in _exception_chain(exc))


def is_required_dependency_unavailable(exc: BaseException) -> bool:
    return any(
        isinstance(item, DependencyUnavailableError)
        or isinstance(item, _POSTGRES_UNAVAILABLE + _NEO4J_UNAVAILABLE)
        for item in _exception_chain(exc)
    )
