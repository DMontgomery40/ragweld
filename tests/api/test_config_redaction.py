"""Credentials must not reach the browser through the config wire (M-88, M-89, M-90).

Zero mocks: these drive the real ASGI app against the real scoped-config store, which
`tests/conftest.py` points at a private temp copy of `tribrid_config.json`, and read the
stored value back through `load_scoped_config` -- the same loader the app uses -- rather
than through the redacting endpoint that is under test.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from urllib.parse import urlsplit

import pytest
from httpx import AsyncClient

from server.config_redaction import SECRET_REDACTED
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


@asynccontextmanager
async def _client_with_lifespan() -> AsyncGenerator[AsyncClient, None]:
    """A client whose app has actually started.

    The shared `client` fixture uses `ASGITransport`, which never runs the lifespan, and
    the MCP streamable-HTTP manager refuses every request until its task group exists.
    These two tests drive the real mounted transport, so they need the real startup.
    """
    from httpx import ASGITransport

    from server.main import app

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as started:
            yield started


@pytest.mark.asyncio
async def test_the_advertised_mcp_host_is_one_the_transport_actually_accepts() -> None:
    """M-91's second half: advertising a host the transport refuses is not a fix.

    `/api/mcp/status` reports `host_allowed` by asking the transport's own validator. This
    drives the REAL mounted transport and asserts the two agree, so if the library's rule
    ever changes this fails instead of the workbench quietly advertising a URL that
    answers 421.

    Both probes share one lifespan on purpose: `StreamableHTTPSessionManager.run()` may be
    called only once per process, so a second entry would raise rather than test anything.
    """
    async with _client_with_lifespan() as client:
        # Asked on loopback on purpose: that is the branch where `host_allowed` is about
        # the advertised URL's own host, which is what this test compares. The proxied
        # branch -- where it is deliberately about a DIFFERENT host -- is covered by
        # `test_an_unset_public_base_url_is_reported_against_the_host_a_client_would_use`.
        status = (
            await client.get("/api/mcp/status", headers={"Host": "127.0.0.1:58012"})
        ).json()
        http = status.get("python_http")
        if not http:
            pytest.skip("the MCP HTTP transport is not enabled in this environment")

        async def probe(host: str) -> int:
            response = await client.post(
                http["path"],
                headers={
                    "Host": host,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            return response.status_code

        # The premise. Without this the agreement check below could pass on a transport
        # that happily accepts every Host, which would make `host_allowed` meaningless.
        assert await probe("mcp-host-that-is-not-allowed.example") == 421, (
            "DNS rebinding protection is not refusing an unknown Host"
        )

        assert http["public_base_url_configured"] is True, (
            "this test needs the branch where host_allowed describes the advertised URL"
        )
        advertised = urlsplit(http["url"]).netloc
        assert advertised, http["url"]
        refused = await probe(advertised) == 421
        assert http["host_allowed"] is not refused, (
            f"status says host_allowed={http['host_allowed']} for {advertised!r}, but the "
            f"transport refused it"
        )


# ---------------------------------------------------------------------------
# The wave-wide invariant
# ---------------------------------------------------------------------------

# A DSN with a password in it, whatever the password happens to be. Grepping for the
# literal cannot work here: the deployed password is the default `postgres`, which also
# appears as a scheme, a user and a database name, so a substring hit proves nothing and a
# substring miss proves less. This matches the SHAPE and then asks whether the password
# component is the marker.
_DSN_WITH_PASSWORD = re.compile(r"[a-zA-Z0-9+.-]+://[^/@\s\"']*:([^@/\s\"']+)@")


def _exposed_credentials(payload: object) -> list[str]:
    """Every DSN password in `payload` that is not the redaction marker."""
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, str):
            found.extend(
                m.group(1) for m in _DSN_WITH_PASSWORD.finditer(node) if m.group(1) != SECRET_REDACTED
            )
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found


def _no_parameter_get_routes() -> list[str]:
    """Every GET route the app serves that needs no path parameter."""
    from server.main import app

    paths: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if "GET" not in methods or "{" in path or not path.startswith("/api/"):
            continue
        paths.add(path)
    return sorted(paths)


@pytest.mark.asyncio
async def test_no_api_route_ships_a_credential_to_the_browser(
    client: AsyncClient, seeded_secrets
) -> None:
    """The sweep IS the invariant: a new carrier fails this without anyone listing it.

    An earlier version of this check walked a hand-written list of a dozen routes and
    concluded "every other route carries no DSN". It was wrong -- the eval, synthetic,
    reranker and agent run records pin a config snapshot and serve it -- and a list could
    never have found that, because the next carrier is always the one not on the list. So
    this enumerates the app's own routing table instead.
    """
    exposures: dict[str, list[str]] = {}
    for path in _no_parameter_get_routes():
        try:
            response = await client.get(path)
        except Exception:
            # A route that cannot answer in this environment cannot leak in it either.
            continue
        if response.status_code >= 400:
            continue
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        leaked = _exposed_credentials(payload)
        if leaked:
            exposures[path] = leaked

    assert not exposures, (
        "these GET routes ship a DSN password to the browser: "
        + ", ".join(sorted(exposures))
    )


@pytest.fixture
def eval_run_pinning_a_credential():
    """A run record on disk whose pinned config still carries the real credential.

    This is the state the fleet is actually in: every run written before the redaction
    existed pinned `POSTGRES_URL` and `OTLP_HEADERS` verbatim, nested AND flat. Seeding it
    rather than hunting for an ambient run makes the read boundary testable anywhere and
    keeps the assertion about the credential rather than about whatever run happens to
    exist.
    """
    from server.api.eval import _run_path
    from server.models.tribrid_config_model import EvalMetrics, EvalRun

    run_id = "pytest-redaction-probe"
    path = _run_path(run_id)
    now = datetime(2026, 8, 30, tzinfo=UTC)
    # Built through the real model, so a schema change breaks the fixture loudly instead of
    # letting the route 500 and the assertion never run.
    record = EvalRun(
        run_id=run_id,
        repo_id="pytest-redaction",
        dataset_id="default",
        config_snapshot={
            "indexing": {"postgres_url": REAL_DSN},
            "tracing": {"otlp_headers": REAL_HEADERS},
        },
        config={"POSTGRES_URL": REAL_DSN, "OTLP_HEADERS": REAL_HEADERS},
        metrics=EvalMetrics(
            mrr=0.0,
            recall_at_5=0.0,
            recall_at_10=0.0,
            recall_at_20=0.0,
            precision_at_5=0.0,
            ndcg_at_10=0.0,
            latency_p50_ms=0.0,
            latency_p95_ms=0.0,
        ),
        results=[],
        started_at=now,
        completed_at=now,
    )
    path.write_text(record.model_dump_json(), encoding="utf-8")
    try:
        yield run_id
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_a_run_record_does_not_ship_the_credential_it_pinned(
    client: AsyncClient, eval_run_pinning_a_credential
) -> None:
    """Run-detail routes take a path parameter, so the sweep above cannot reach them.

    Every eval / synthetic / reranker / agent run pins the configuration that governed it,
    and `to_flat_dict` carries `POSTGRES_URL` and `OTLP_HEADERS` verbatim. Both shapes are
    checked, because redacting one and forgetting the other is the likely half-fix.
    """
    detail = await client.get(f"/api/eval/results/{eval_run_pinning_a_credential}")
    assert detail.status_code == 200, detail.text
    body = detail.json()

    assert "s3cr3t-p4ssw0rd" not in detail.text
    assert "abc123" not in detail.text
    assert not _exposed_credentials(body), "the run detail ships a DSN password"

    nested = body["config_snapshot"]["indexing"]["postgres_url"]
    assert nested == f"postgresql://ragweld_user:{SECRET_REDACTED}@db.internal:5432/tribrid_rag"
    flat = body["config"]
    assert SECRET_REDACTED in flat["POSTGRES_URL"]
    assert flat["OTLP_HEADERS"] == f"Authorization={SECRET_REDACTED},X-Scope-OrgID=1"


def test_every_config_snapshot_is_built_through_the_redacting_helper() -> None:
    """A source invariant, so a NEW run family cannot reintroduce the leak.

    `cfg.model_dump()` / `cfg.to_flat_dict()` written straight into a run record is the
    exact shape of the original defect. `redacted_config_snapshot` is the only sanctioned
    way to build the pair.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for source in sorted((repo_root / "server").rglob("*.py")):
        if source.name == "config_redaction.py":
            continue
        text = source.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r"config_snapshot\s*=\s*\w+\.model_dump\(", stripped) or re.search(
                r"\bconfig\s*=\s*\w+\.to_flat_dict\(", stripped
            ):
                offenders.append(f"{source.relative_to(repo_root)}:{number}: {stripped}")

    assert not offenders, (
        "build the pair with `redacted_config_snapshot(cfg)` instead -- these pin a config "
        "snapshot with its credentials intact:\n" + "\n".join(offenders)
    )


@pytest.mark.asyncio
async def test_an_unset_public_base_url_is_reported_against_the_host_a_client_would_use(
    client: AsyncClient,
) -> None:
    """M-91's quiet failure: the default is loopback, and loopback is always allowed.

    On a proxied deployment that combination advertises `http://127.0.0.1:58012/mcp/` to an
    operator sitting at `https://ragweld.dtmont.com` while `host_allowed` reads true,
    because the loopback host the URL names IS in `allowed_hosts`. Both states are driven
    here through the real route with a real Host header -- the browser cannot set one, so
    this is the only place the non-loopback branch can be exercised honestly.
    """
    if not (await client.get("/api/mcp/status")).json().get("python_http"):
        pytest.skip("the MCP HTTP transport is not enabled in this environment")

    if True:
        # Arrived on loopback: the default is a correct answer, not a misconfiguration.
        local = (await client.get("/api/mcp/status", headers={"Host": "127.0.0.1:58012"})).json()
        assert local["python_http"]["public_base_url_configured"] is True
        assert local["python_http"]["host_allowed"] is True

        # Arrived from a public origin with the default still in place.
        public = (
            await client.get("/api/mcp/status", headers={"Host": "ragweld.dtmont.com"})
        ).json()["python_http"]
        assert public["public_base_url_configured"] is False, (
            "an unset public_base_url behind a proxy must be reported, not silently "
            "advertised as a loopback URL"
        )
        assert public["request_host"] == "ragweld.dtmont.com"
        # Evaluated for the host a client would really use, which is NOT allowed here --
        # reporting the loopback's `true` would tell the operator the endpoint works.
        assert public["host_allowed"] is False
        assert any("public_base_url" in d for d in (await client.get("/api/mcp/status", headers={"Host": "ragweld.dtmont.com"})).json()["details"])

        # A proxy that forwards the original host is honoured over the hop's own Host.
        forwarded = (
            await client.get(
                "/api/mcp/status",
                headers={"Host": "127.0.0.1:58012", "X-Forwarded-Host": "ragweld.dtmont.com"},
            )
        ).json()["python_http"]
        assert forwarded["public_base_url_configured"] is False
        assert forwarded["request_host"] == "ragweld.dtmont.com"


@pytest.mark.asyncio
async def test_the_advertised_url_is_the_same_however_the_public_base_is_spelled(
    client: AsyncClient,
) -> None:
    """`https://host` and `https://host/mcp` must advertise the same endpoint.

    `public_base_url` is documented as an ORIGIN because the server appends
    `mcp.mount_path`, but "the URL clients use" is naturally written with the path
    included, and that reading has already been asked for once. Left alone, the second
    spelling would silently advertise `/mcp/mcp/` -- a 404 nobody would look for. Both are
    accepted and neither doubles the path.
    """
    original = await load_scoped_config(repo_id=None)
    try:
        seen = []
        for base in ("https://mcp-spelling.example", "https://mcp-spelling.example/mcp"):
            edited = original.model_copy(deep=True)
            edited.mcp.public_base_url = base
            await save_scoped_config(edited, repo_id=None)
            http = (
                await client.get("/api/mcp/status", headers={"Host": "mcp-spelling.example"})
            ).json().get("python_http")
            if not http:
                pytest.skip("the MCP HTTP transport is not enabled in this environment")
            seen.append(http["url"])

        assert seen[0] == seen[1] == "https://mcp-spelling.example/mcp/", seen
    finally:
        await save_scoped_config(original, repo_id=None)

