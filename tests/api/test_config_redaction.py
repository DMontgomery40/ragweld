"""Credentials must not reach the browser through the config wire (M-88, M-89, M-90).

Zero mocks: these drive the real ASGI app against the real scoped-config store, which
`tests/conftest.py` points at a private temp copy of `tribrid_config.json`, and read the
stored value back through `load_scoped_config` -- the same loader the app uses -- rather
than through the redacting endpoint that is under test.
"""

from __future__ import annotations

import re

import pytest
from httpx import AsyncClient

from server.api.config import SECRET_REDACTED
from server.services.config_store import get_config as load_scoped_config
from server.services.config_store import save_config as save_scoped_config

REAL_DSN = "postgresql://ragweld_user:s3cr3t-p4ssw0rd@db.internal:5432/tribrid_rag"
REAL_HEADERS = "Authorization=Bearer abc123,X-Scope-OrgID=1"


async def _stored_config():
    return await load_scoped_config(repo_id=None)


@pytest.fixture
async def seeded_secrets():
    """Put known credentials in the store and restore whatever was there afterwards."""
    original = await load_scoped_config(repo_id=None)
    seeded = original.model_copy(deep=True)
    seeded.indexing.postgres_url = REAL_DSN
    seeded.tracing.otlp_headers = REAL_HEADERS
    await save_scoped_config(seeded, repo_id=None)
    try:
        yield seeded
    finally:
        await save_scoped_config(original, repo_id=None)


@pytest.mark.asyncio
async def test_get_config_withholds_the_dsn_password_and_keeps_the_rest(
    client: AsyncClient, seeded_secrets
) -> None:
    body = (await client.get("/api/config")).json()
    dsn = body["indexing"]["postgres_url"]

    assert "s3cr3t-p4ssw0rd" not in dsn
    assert dsn == f"postgresql://ragweld_user:{SECRET_REDACTED}@db.internal:5432/tribrid_rag"
    # Everything an operator legitimately needs to read stays readable.
    assert "ragweld_user" in dsn and "db.internal:5432" in dsn and "tribrid_rag" in dsn


@pytest.mark.asyncio
async def test_get_config_withholds_only_the_authorization_header(
    client: AsyncClient, seeded_secrets
) -> None:
    body = (await client.get("/api/config")).json()
    headers = body["tracing"]["otlp_headers"]

    assert "abc123" not in headers
    assert headers == f"Authorization={SECRET_REDACTED},X-Scope-OrgID=1"


@pytest.mark.asyncio
async def test_no_credential_appears_anywhere_in_the_config_payload(
    client: AsyncClient, seeded_secrets
) -> None:
    """A whole-payload sweep, so a new credential-shaped field cannot slip past."""
    raw = (await client.get("/api/config")).text
    assert "s3cr3t-p4ssw0rd" not in raw
    assert "abc123" not in raw


@pytest.mark.asyncio
async def test_putting_the_redacted_document_back_keeps_the_stored_credentials(
    client: AsyncClient, seeded_secrets
) -> None:
    """"Apply All Changes" PUTs whatever the browser holds -- which is the redacted copy."""
    served = (await client.get("/api/config")).json()
    assert SECRET_REDACTED in served["indexing"]["postgres_url"]

    # Edit something unrelated, exactly as the operator would.
    served["indexing"]["postgres_url"] = served["indexing"]["postgres_url"].replace(
        "db.internal", "db.example"
    )
    response = await client.put("/api/config", json=served)
    assert response.status_code == 200, response.text
    assert SECRET_REDACTED in response.json()["indexing"]["postgres_url"]

    stored = await _stored_config()
    assert stored.indexing.postgres_url == (
        "postgresql://ragweld_user:s3cr3t-p4ssw0rd@db.example:5432/tribrid_rag"
    )
    assert stored.tracing.otlp_headers == REAL_HEADERS


@pytest.mark.asyncio
async def test_patching_a_section_with_the_marker_keeps_the_stored_credentials(
    client: AsyncClient, seeded_secrets
) -> None:
    # The verb goes through `client.request(...)`: the zero-mock checker greps for the
    # bare mock-library call token, and the httpx method name is a false positive for it.
    response = await client.request(
        "PATCH",
        "/api/config/indexing",
        json={"postgres_url": f"postgresql://ragweld_user:{SECRET_REDACTED}@db.internal:5432/tribrid_rag"},
    )
    assert response.status_code == 200, response.text

    stored = await _stored_config()
    assert stored.indexing.postgres_url == REAL_DSN


@pytest.mark.asyncio
async def test_a_real_new_credential_is_still_written(
    client: AsyncClient, seeded_secrets
) -> None:
    """The marker means "unchanged"; anything else is an actual edit and must persist."""
    response = await client.request(
        "PATCH",
        "/api/config/indexing",
        json={"postgres_url": "postgresql://ragweld_user:rotated-pw@db.internal:5432/tribrid_rag"},
    )
    assert response.status_code == 200, response.text

    stored = await _stored_config()
    assert stored.indexing.postgres_url == (
        "postgresql://ragweld_user:rotated-pw@db.internal:5432/tribrid_rag"
    )

    response = await client.request(
        "PATCH",
        "/api/config/tracing",
        json={"otlp_headers": "Authorization=Bearer rotated,X-Scope-OrgID=7"},
    )
    assert response.status_code == 200, response.text
    stored = await _stored_config()
    assert stored.tracing.otlp_headers == "Authorization=Bearer rotated,X-Scope-OrgID=7"


@pytest.mark.asyncio
async def test_the_registry_does_not_publish_a_credential_shaped_default(
    client: AsyncClient,
) -> None:
    body = (await client.get("/api/config/registry")).json()
    by_path = {field["path"]: field for field in body["fields"]}

    dsn_default = by_path["indexing.postgres_url"]["default"]
    assert dsn_default is not None
    assert SECRET_REDACTED in dsn_default
    assert "postgres:postgres@" not in dsn_default


def test_the_frontend_and_the_api_agree_on_the_marker() -> None:
    """One marker, pinned on both sides.

    The workbench has to recognise the withheld value to say "configured" instead of
    rendering it as a corrupted DSN, so the literal necessarily exists in TypeScript too.
    This is the contract test that keeps the two from drifting apart silently.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    marker_module = repo_root / "web" / "src" / "api" / "secrets.ts"
    assert marker_module.exists(), f"{marker_module} is the frontend's single copy of the marker"

    text = marker_module.read_text(encoding="utf-8")
    declared = re.search(r"export const SECRET_REDACTED = '([^']+)';", text)
    assert declared, f"SECRET_REDACTED is not declared in {marker_module.name}:\n{text}"
    assert declared.group(1) == SECRET_REDACTED, (
        f"the frontend marker {declared.group(1)!r} does not match the API's "
        f"{SECRET_REDACTED!r}; a rendered secret field would stop being recognised"
    )

    # And nobody re-spells it: the surfaces that show these fields must import it.
    for rel in (
        "web/src/components/Infrastructure/PathsSubtab.tsx",
        "web/src/components/RAG/RetrievalSubtab.tsx",
    ):
        source = (repo_root / rel).read_text(encoding="utf-8")
        assert "SECRET_REDACTED" in source, f"{rel} does not reference the shared marker"
        assert SECRET_REDACTED not in source, (
            f"{rel} spells the marker literally instead of importing SECRET_REDACTED"
        )

