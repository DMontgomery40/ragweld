"""Tests for /api/secrets endpoints (no secret values exposed)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from httpx import AsyncClient

from server.main import _load_dotenv_file


@pytest.mark.asyncio
async def test_secrets_check_reflects_process_env(client: AsyncClient) -> None:
    """GET /api/secrets/check returns booleans based on os.environ."""
    key_present = "TRIBRID_TEST_SECRET_PRESENT"
    key_absent = "TRIBRID_TEST_SECRET_ABSENT"

    # Ensure a clean slate for this process.
    os.environ.pop(key_present, None)
    os.environ.pop(key_absent, None)
    os.environ[key_present] = "non-empty"

    try:
        resp = await client.get(f"/api/secrets/check?keys={key_present},{key_absent}")
        assert resp.status_code == 200
        data = resp.json()

        assert data[key_present] is True
        assert data[key_absent] is False
        assert isinstance(data[key_present], bool)
        assert isinstance(data[key_absent], bool)
    finally:
        os.environ.pop(key_present, None)
        os.environ.pop(key_absent, None)


def test_load_dotenv_file_loads_without_override(tmp_path: Path) -> None:
    """Dotenv loader should load a file but never override existing env vars."""
    key = "TRIBRID_DOTENV_TEST_KEY"
    os.environ.pop(key, None)

    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{key}=fromfile\n", encoding="utf-8")

    try:
        loaded = _load_dotenv_file(dotenv)
        assert loaded is True
        assert os.environ.get(key) == "fromfile"

        # Should not override an already-set value.
        os.environ[key] = "existing"
        dotenv.write_text(f"{key}=newvalue\n", encoding="utf-8")
        loaded2 = _load_dotenv_file(dotenv)
        assert loaded2 is True
        assert os.environ.get(key) == "existing"
    finally:
        os.environ.pop(key, None)

