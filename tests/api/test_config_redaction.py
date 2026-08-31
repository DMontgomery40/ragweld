"""Credentials must not reach the browser through the config wire (M-88, M-89, M-90).

Zero mocks: these drive the real ASGI app against the real scoped-config store, which
`tests/conftest.py` points at a private temp copy of `tribrid_config.json`, and read the
stored value back through `load_scoped_config` -- the same loader the app uses -- rather
than through the redacting endpoint that is under test.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from server.config_redaction import SECRET_REDACTED
from server.models.tribrid_config_model import MCPConfig
from server.services.config_store import get_config as load_scoped_config
from server.services.config_store import save_config as save_scoped_config

REAL_DSN = "postgresql://ragweld_user:s3cr3t-p4ssw0rd@db.internal:5432/tribrid_rag"
REAL_HEADERS = "Authorization=Bearer abc123,X-Scope-OrgID=1"

# Derived from the two constants above, never re-spelled. A hand-written second copy of a
# secret drifts the moment the fixture changes, and a "this value must not appear" net that
# is looking for a string nothing produces any more still reads as a passing test -- the
# worst failure mode a security check has. Parsed independently of
# `server/config_redaction`'s own helpers, so a bug there cannot make the assertions agree
# with it.
REAL_DSN_PASSWORD = REAL_DSN.partition("://")[2].partition("@")[0].partition(":")[2]
REAL_HEADER_VALUE = REAL_HEADERS.split(",")[0].partition("=")[2]
REAL_HEADER_TOKEN = REAL_HEADER_VALUE.split()[-1]


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

    assert REAL_DSN_PASSWORD not in dsn
    assert dsn == f"postgresql://ragweld_user:{SECRET_REDACTED}@db.internal:5432/tribrid_rag"
    # Everything an operator legitimately needs to read stays readable.
    assert "ragweld_user" in dsn and "db.internal:5432" in dsn and "tribrid_rag" in dsn


@pytest.mark.asyncio
async def test_get_config_withholds_only_the_authorization_header(
    client: AsyncClient, seeded_secrets
) -> None:
    body = (await client.get("/api/config")).json()
    headers = body["tracing"]["otlp_headers"]

    assert REAL_HEADER_TOKEN not in headers
    assert headers == f"Authorization={SECRET_REDACTED},X-Scope-OrgID=1"


@pytest.mark.asyncio
async def test_no_credential_appears_anywhere_in_the_config_payload(
    client: AsyncClient, seeded_secrets
) -> None:
    """A whole-payload sweep, so a new credential-shaped field cannot slip past."""
    raw = (await client.get("/api/config")).text
    assert REAL_DSN_PASSWORD not in raw
    assert REAL_HEADER_TOKEN not in raw


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
        f"postgresql://ragweld_user:{REAL_DSN_PASSWORD}@db.example:5432/tribrid_rag"
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


# The advertised-host / DNS-rebinding agreement proof (M-91's second half) lives in
# tests/api/test_mcp_endpoints.py, inside the one test that enters the app lifespan:
# `StreamableHTTPSessionManager.run()` may be called only once per instance, so a second
# `app.router.lifespan_context(app)` entry in the same pytest process raises
# ".run() can only be called once per instance" instead of testing anything.


# ---------------------------------------------------------------------------
# The wave-wide invariant
# ---------------------------------------------------------------------------

# A DSN with a password in it, whatever the password happens to be. Grepping for the
# literal cannot work here: the deployed password is the default `postgres`, which also
# appears as a scheme, a user and a database name, so a substring hit proves nothing and a
# substring miss proves less. This matches the SHAPE and then asks whether the password
# component is the marker.
_DSN_WITH_PASSWORD = re.compile(r"[a-zA-Z0-9+.-]+://[^/@\s\"']*:([^@/\s\"']+)@")

# A header credential does not look like a DSN, so the shape check has to cover it
# separately or an unredacted `OTLP_HEADERS` would sail through a DSN-only sweep.
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+([^\s,\"';]+)")
_AUTHORIZATION_VALUE = re.compile(r"(?i)\bauthorization\s*[=:]\s*([^,\"';]+)")

# Documentation is not a leak. `MCPConfig.require_api_key`'s description is served by
# `/api/config/registry` and reads "Authorization: Bearer $MCP_API_KEY"; a matcher that
# cannot tell that from a real token would fail on prose and teach everyone to ignore it.
_PLACEHOLDER_HINTS = ("...", "\u2026", "$", "<", "{", "*")


def _is_placeholder(token: str) -> bool:
    """True for anything that is documentation rather than a credential.

    Two classes, both observed on the live wire: templated placeholders
    (`Bearer $MCP_API_KEY`) and English prose (the phrase "bearer token" appears in
    `/api/config/readiness` and in a registry field description). A matcher that flags
    either one cries wolf, and a sweep everyone learns to ignore protects nothing.

    The prose rule is "purely alphabetic": a real credential carries digits or symbols.
    An all-letters secret would slip past the SHAPE net, which is why the sweep also
    checks the seeded literals exactly -- see `test_no_api_route_ships_a_credential...`.
    """
    value = token.strip()
    if not value or value == SECRET_REDACTED:
        return True
    if any(hint in value for hint in _PLACEHOLDER_HINTS):
        return True
    return value.isalpha()


def _exposed_credentials(payload: object) -> list[str]:
    """Every credential-shaped value in `payload` that is not the redaction marker.

    Two shapes, because the two secrets this API withholds look nothing alike: a DSN
    password inside a connection string, and an authorization header value.
    """
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, str):
            found.extend(
                m.group(1)
                for m in _DSN_WITH_PASSWORD.finditer(node)
                if m.group(1) != SECRET_REDACTED
            )
            for pattern in (_BEARER_TOKEN, _AUTHORIZATION_VALUE):
                found.extend(
                    m.group(1).strip()
                    for m in pattern.finditer(node)
                    if not _is_placeholder(m.group(1).replace("Bearer", "").replace("bearer", ""))
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


@pytest.fixture
async def sweep_corpus_id(client: AsyncClient) -> AsyncGenerator[str, None]:
    """A corpus the scoped routes will accept, so the sweep actually reaches them.

    Read-only, and taken through the API rather than an internal helper: an existing
    corpus is used rather than provisioned, because the routes that need one are
    corpus-scoped reads and any registered corpus satisfies them. Without this, 24 of the
    64 routes answered 422 for a missing `corpus_id` and were never inspected --
    including `/api/agent/train/runs` and `/api/reranker/train/runs`, two of the families
    this very file is about.
    """
    try:
        listing = await client.get("/api/corpora")
    except Exception:
        yield ""
        return
    if listing.status_code >= 400:
        yield ""
        return
    rows = listing.json()
    if not isinstance(rows, list):
        yield ""
        return
    yield next((str(row.get("corpus_id") or "") for row in rows if row.get("corpus_id")), "")


# How many routes may remain uninspectable. Measured, not guessed: with a corpus seeded the
# sweep reaches 55 of 64 (it reached 40 before the retry). The 9 it cannot are honest --
# 404 where the environment simply has no such record (`/api/eval/results` with no runs,
# the reranker log/profile downloads), 503 from `/api/ready` when a dependency is down, and
# 422 from routes needing a parameter that is not a corpus (`run_id` on the three stream
# routes, `keys` on `/api/secrets/check`).
#
# A ceiling, not an exact match: the count moves between 9 and 11 run to run as transient
# service state changes what answers (`/api/ready` is 503 while a dependency is down, the
# docker and Loki probes come and go). It is set well below the 24 that were skipped before
# the corpus retry, so a change that regresses to the old coverage fails here -- and well
# above the observed band, so a passing suite is not a coin flip.
_MAX_UNINSPECTABLE_ROUTES = 16


@pytest.mark.asyncio
async def test_no_api_route_ships_a_credential_to_the_browser(
    client: AsyncClient, seeded_secrets, sweep_corpus_id: str
) -> None:
    """The sweep IS the invariant: a new carrier fails this without anyone listing it.

    An earlier version walked a hand-written list of a dozen routes and concluded "every
    other route carries no DSN". It was wrong -- the eval, synthetic, reranker and agent
    run records pin a config snapshot and serve it -- and a list could never have found
    that, because the next carrier is always the one not on the list. So this enumerates
    the app's own routing table, retries anything that needs a corpus with one, and
    reports what it still could not reach rather than quietly counting it as clean.
    """
    exposures: dict[str, list[str]] = {}
    inspected: list[str] = []
    uninspectable: dict[str, int] = {}

    for path in _no_parameter_get_routes():
        response = None
        for params in ({}, {"corpus_id": sweep_corpus_id} if sweep_corpus_id else None):
            if params is None:
                continue
            try:
                candidate = await client.get(path, params=params)
            except Exception:
                continue
            response = candidate
            if candidate.status_code < 400:
                break
        if response is None or response.status_code >= 400:
            uninspectable[path] = response.status_code if response is not None else 0
            continue

        inspected.append(path)
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        leaked = _exposed_credentials(payload)
        # Exact net alongside the shape net: the fixture's own secrets, whatever shape
        # they take. This is what would catch an all-alphabetic credential that
        # `_is_placeholder`'s prose rule deliberately lets through.
        body = response.text
        leaked += [
            literal for literal in (REAL_DSN_PASSWORD, REAL_HEADER_VALUE) if literal in body
        ]
        if leaked:
            exposures[path] = leaked

    assert not exposures, (
        "these GET routes ship a credential to the browser: "
        + ", ".join(f"{path} ({len(v)})" for path, v in sorted(exposures.items()))
    )

    # Coverage is part of the invariant. A sweep that silently inspects half the surface
    # is the same false comfort as the hand-written list it replaced.
    assert len(uninspectable) <= _MAX_UNINSPECTABLE_ROUTES, (
        f"the sweep reached only {len(inspected)} of "
        f"{len(inspected) + len(uninspectable)} routes; uninspectable: "
        + ", ".join(f"{path}->{code}" for path, code in sorted(uninspectable.items()))
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

    assert REAL_DSN_PASSWORD not in detail.text
    assert REAL_HEADER_TOKEN not in detail.text
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
        # Every spelling that has been proposed or that a near-miss could produce, with the
        # advertised URL each must yield. The last two rows are the mangling the string-wise
        # guard produced: `https://mcp` matched "/mcp" on the second slash of "//" and lost
        # its scheme separator, and a "/" mount hit the `base[:-0]` whole-slice trap. The
        # mount is now compared as a PATH component, and `MCPConfig.mount_path`'s pattern
        # keeps "/" unsettable so the empty-mount case cannot arise from config at all.
        cases = [
            ("https://mcp-spelling.example", "https://mcp-spelling.example/mcp/"),
            ("https://mcp-spelling.example/mcp", "https://mcp-spelling.example/mcp/"),
            ("https://mcp-spelling.example/mcp/", "https://mcp-spelling.example/mcp/"),
            # A near miss that must NOT be treated as already mounted.
            ("https://mcp-spelling.example/foo-mcp", "https://mcp-spelling.example/foo-mcp/mcp/"),
            # The host itself is the mount name.
            ("https://mcp", "https://mcp/mcp/"),
        ]
        seen: list[tuple[str, str]] = []
        for base, expected in cases:
            edited = original.model_copy(deep=True)
            edited.mcp.public_base_url = base
            await save_scoped_config(edited, repo_id=None)
            http = (
                await client.get("/api/mcp/status", headers={"Host": "mcp-spelling.example"})
            ).json().get("python_http")
            if not http:
                pytest.skip("the MCP HTTP transport is not enabled in this environment")
            seen.append((base, http["url"]))
            assert http["url"] == expected, seen

        # A "/" mount is refused by the model, so the advertised URL can never collapse to
        # "/" -- the second mangling row, closed at the source rather than in the assembly.
        with pytest.raises(ValidationError):
            MCPConfig(mount_path="/")
        with pytest.raises(ValidationError):
            MCPConfig(mount_path="")
    finally:
        await save_scoped_config(original, repo_id=None)


def test_the_sweep_matcher_catches_a_header_credential_and_ignores_prose() -> None:
    """The header net asserted directly, because nothing on the wire leaks one today.

    Removing `_BEARER_TOKEN` / `_AUTHORIZATION_VALUE` leaves the route sweep green -- no
    current route ships a header credential, which is the point of the fix. That makes the
    matcher's own behaviour untested unless it is exercised here, so this pins both halves:
    what it must catch, and the two prose forms actually served today that it must not.
    """
    # What it must catch: an unredacted OTLP_HEADERS value, in either shape it appears in.
    assert _exposed_credentials({"OTLP_HEADERS": REAL_HEADERS})
    assert _exposed_credentials({"config": {"OTLP_HEADERS": "Authorization: Bearer sk-live-9f2"}})
    assert _exposed_credentials(["Authorization=hunter2-plus"])

    # What it must not: the marker, and the prose that `/api/config/readiness` and the
    # registry field descriptions really serve.
    assert _exposed_credentials({"OTLP_HEADERS": f"Authorization={SECRET_REDACTED}"}) == []
    assert _exposed_credentials({"d": "Require `Authorization: Bearer $MCP_API_KEY` for MCP."}) == []
    assert _exposed_credentials({"d": "Supply a bearer token for the collector."}) == []
    assert _exposed_credentials({"d": "Authorization=Bearer ...,X-Scope-OrgID=1"}) == []

    # And the DSN half still works, including the marker case.
    assert _exposed_credentials({"u": REAL_DSN}) == [REAL_DSN_PASSWORD]
    assert _exposed_credentials({"u": f"postgresql://u:{SECRET_REDACTED}@h:5432/d"}) == []


def test_the_fixture_secrets_are_actually_derivable() -> None:
    """The derivation is load-bearing, so it is asserted rather than assumed.

    Every "this must not appear" check in this file looks for `REAL_DSN_PASSWORD` /
    `REAL_HEADER_TOKEN`. If a change to `REAL_DSN` or `REAL_HEADERS` broke the parsing, the
    nets would search for an empty or wrong string, match nothing, and pass -- reporting
    safety they had not checked.
    """
    assert REAL_DSN_PASSWORD == "s3cr3t-p4ssw0rd"
    assert REAL_DSN_PASSWORD in REAL_DSN
    assert REAL_HEADER_VALUE == "Bearer abc123"
    assert REAL_HEADER_TOKEN == "abc123"
    assert REAL_HEADER_VALUE in REAL_HEADERS

    # And each is a credential the matcher recognises, not an artefact of the split.
    assert _exposed_credentials({"u": REAL_DSN}) == [REAL_DSN_PASSWORD]
    assert _exposed_credentials({"h": REAL_HEADERS})

