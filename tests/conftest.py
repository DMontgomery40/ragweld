"""Pytest fixtures for TriBridRAG tests."""

import asyncio
from pathlib import Path
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from server.main import app
from server.models.tribrid_config_model import TriBridConfig


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def test_config() -> TriBridConfig:
    """Create test configuration.

    Uses THE LAW's default_factory for all values.
    The comprehensive TriBridConfig provides sensible defaults for testing.
    """
    return TriBridConfig()


@pytest.fixture
def sample_code() -> str:
    """Sample code for testing."""
    return '''
def fibonacci(n: int) -> int:
    """Calculate the nth Fibonacci number."""
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


class Calculator:
    """Simple calculator class."""

    def add(self, a: int, b: int) -> int:
        return a + b

    def subtract(self, a: int, b: int) -> int:
        return a - b
'''


@pytest.fixture(autouse=True)
def isolate_tracked_config_file() -> Generator[None, None, None]:
    """Keep tracked tribrid_config.json stable across tests.

    Some config endpoint tests persist updates to the real config path. Snapshot
    and restore the file each test so local worktrees and automation runs do not
    end with dirty tracked config.
    """
    config_path = Path("tribrid_config.json")
    existed = config_path.exists()
    original = config_path.read_text(encoding="utf-8") if existed else None
    try:
        yield
    finally:
        # Reset process-wide config store so no mutated in-memory config leaks
        # across tests after file restore.
        try:
            import server.services.config_store as config_store

            if config_store._store is not None:
                config_store._store.clear_cache()
            config_store._store = None
        except Exception:
            pass

        if existed:
            try:
                current = config_path.read_text(encoding="utf-8") if config_path.exists() else None
            except Exception:
                current = None
            if current != original:
                config_path.write_text(str(original), encoding="utf-8")
        elif config_path.exists():
            try:
                config_path.unlink()
            except Exception:
                pass
