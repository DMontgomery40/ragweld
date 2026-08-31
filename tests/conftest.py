"""Pytest fixtures for TriBridRAG tests."""

import asyncio
import os
import shutil
import tempfile
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from server.gateway_catalog import warm_gateway_catalog

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Test processes never attach the continuous-profiling agent, even when the
# copied runtime config carries a Pyroscope server URL.
os.environ.setdefault("RAGWELD_DISABLE_PROFILING", "1")

_TEST_CONFIG_RUNTIME_DIR: str | None = None
if os.environ.get("RAGWELD_STRICT_INTEGRATION", "").strip() == "1":
    strict_config_raw = os.environ.get("RAGWELD_CONFIG_PATH", "").strip()
    if not strict_config_raw:
        raise RuntimeError("Strict integration requires a private RAGWELD_CONFIG_PATH")
    strict_config_path = Path(strict_config_raw).expanduser().resolve()
    strict_runtime_raw = os.environ.get("RAGWELD_INTEGRATION_RUNTIME_DIR", "").strip()
    if not strict_runtime_raw:
        raise RuntimeError("Strict integration requires a launcher-owned runtime directory")
    strict_runtime_dir = Path(strict_runtime_raw).expanduser().resolve()
    if strict_config_path.parent != strict_runtime_dir:
        raise RuntimeError("Strict integration config must be inside its launcher-owned runtime directory")
    try:
        strict_runtime_dir.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        pass
    else:
        raise RuntimeError("Strict integration refuses config paths inside the repository")
else:
    _TEST_CONFIG_RUNTIME_DIR = tempfile.mkdtemp(prefix="ragweld-pytest-config-")
    test_config_path = Path(_TEST_CONFIG_RUNTIME_DIR) / "tribrid_config.json"
    shutil.copy2(PROJECT_ROOT / "tribrid_config.json", test_config_path)
    test_config_path.chmod(0o600)
    os.environ["RAGWELD_CONFIG_PATH"] = str(test_config_path)
    os.environ["RAGWELD_SOURCE_CONFIG_PATH"] = str(PROJECT_ROOT / "tribrid_config.json")
    os.environ["RAGWELD_INTEGRATION_RUNTIME_DIR"] = _TEST_CONFIG_RUNTIME_DIR

# Tests receive integration configuration explicitly. Never leak a developer
# .env into collection or use its mere presence as a readiness signal.
os.environ["RAGWELD_LOAD_DOTENV"] = "0"
# The clean-start gateway uses a deterministic local client key. Individual
# fail-closed tests explicitly remove it when exercising the missing-key path.
os.environ.setdefault("LITELLM_API_KEY", "sk-ragweld-test")

pytest_plugins = ("tests.service_requirements",)

from server.config import DEFAULT_CONFIG_PATH  # noqa: E402
from server.main import app  # noqa: E402
from server.models.tribrid_config_model import TriBridConfig  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def cleanup_private_test_config() -> Generator[None, None, None]:
    yield
    if _TEST_CONFIG_RUNTIME_DIR is not None:
        shutil.rmtree(_TEST_CONFIG_RUNTIME_DIR, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def reap_leaked_test_corpora() -> Generator[None, None, None]:
    """Delete stale test corpora from the live registry at session start and end.

    API tests that create corpora leak them into the operator's registry when a
    run aborts. This reaps rows with a recognized test-corpus prefix that are old
    enough that no concurrent session can still own them, with a Postgres-only
    cascade (no Neo4j credentials, so it never 503s the way `DELETE /api/corpora`
    would). It is best-effort and never fails the session; an unconfigured or
    unreachable Postgres simply reaps nothing.
    """
    from tests.corpus_reaper import reap_quietly

    started = reap_quietly()
    if started:
        print(f"\n[corpus-reaper] session start: reaped {len(started)} stale test corpora: {started}")
    try:
        yield
    finally:
        ended = reap_quietly()
        if ended:
            print(f"\n[corpus-reaper] session end: reaped {len(ended)} stale test corpora: {ended}")


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Create async test client (ASGITransport does not run the lifespan, so warm the catalog here)."""
    await asyncio.to_thread(warm_gateway_catalog)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def test_config() -> TriBridConfig:
    """Create test configuration.

    Uses the validated config model's default_factory for all values.
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
def isolate_runtime_config_file() -> Generator[None, None, None]:
    """Keep the pytest-owned runtime config stable across tests.

    Some config endpoint tests persist updates. Snapshot and restore the private
    runtime file each test so the tracked operator config is never a test target.
    """
    config_path = DEFAULT_CONFIG_PATH
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


@pytest.fixture(autouse=True)
def isolate_synthetic_runs_root() -> Generator[None, None, None]:
    """Keep synthetic run directories out of the live `data/synthetic_runs` store during tests.

    Same seam as the lineage root: the API under test writes run.json/artifacts wherever
    `server.synthetic.storage.runs_dir()` points, and a crashed test must never leave
    `pytest_*` run directories behind in the operator's store.
    """
    old = os.environ.get("RAGWELD_SYNTHETIC_RUNS_ROOT")
    tmp_dir = tempfile.mkdtemp(prefix="ragweld-synthetic-runs-tests-")
    os.environ["RAGWELD_SYNTHETIC_RUNS_ROOT"] = tmp_dir
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("RAGWELD_SYNTHETIC_RUNS_ROOT", None)
        else:
            os.environ["RAGWELD_SYNTHETIC_RUNS_ROOT"] = old
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolate_lineage_root() -> Generator[None, None, None]:
    """Keep lineage output out of the repo worktree during tests."""
    old = os.environ.get("RAGWELD_LINEAGE_ROOT")
    tmp_dir = tempfile.mkdtemp(prefix="ragweld-lineage-tests-")
    os.environ["RAGWELD_LINEAGE_ROOT"] = tmp_dir
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("RAGWELD_LINEAGE_ROOT", None)
        else:
            os.environ["RAGWELD_LINEAGE_ROOT"] = old
        shutil.rmtree(tmp_dir, ignore_errors=True)
