from __future__ import annotations

from collections.abc import Iterator

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
    ConnectionError,
    TimeoutError,
    OSError,
)

_NEO4J_UNAVAILABLE = (
    neo4j_exceptions.ServiceUnavailable,
    neo4j_exceptions.SessionExpired,
    ConnectionError,
    TimeoutError,
    OSError,
)


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
    return any(isinstance(item, _POSTGRES_UNAVAILABLE) for item in _exception_chain(exc))


def is_neo4j_unavailable(exc: BaseException) -> bool:
    return any(isinstance(item, _NEO4J_UNAVAILABLE) for item in _exception_chain(exc))


def is_required_dependency_unavailable(exc: BaseException) -> bool:
    return is_postgres_unavailable(exc) or is_neo4j_unavailable(exc)
