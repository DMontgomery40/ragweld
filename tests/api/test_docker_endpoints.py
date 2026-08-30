from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.responses import StreamingResponse

from server.api import docker as docker_api
from server.main import app

MANAGED_ID = "a" * 64
FOREIGN_ID = "b" * 64
UNLABELED_ID = "c" * 64


def _container_line(
    container_id: str,
    *,
    name: str,
    project: str,
    service: str,
    managed: str,
    state: str = "running",
) -> str:
    return "\t".join(
        (
            container_id,
            "example:latest",
            name,
            state,
            "Up 2 minutes" if state == "running" else "Exited (0) 1 minute ago",
            "127.0.0.1:5432->5432/tcp",
            project,
            service,
            managed,
        )
    )


@contextmanager
def _controlled_docker_cli(
    tmp_path: Path,
    *,
    duplicate_postgres: bool = False,
    context_endpoint: str = "unix:///Users/test/.colima/ragweld/docker.sock",
) -> Iterator[Path]:
    """Run the real subprocess boundary against a deterministic Docker CLI executable."""
    action_log = tmp_path / "docker-actions.jsonl"
    state_path = tmp_path / "docker-state.json"
    rows = [
        _container_line(
            MANAGED_ID,
            name="ragweld-postgres-1",
            project="ragweld",
            service="postgres",
            managed="true",
        ),
        _container_line(
            FOREIGN_ID,
            name="other-grafana-1",
            project="other",
            service="grafana",
            managed="true",
        ),
        _container_line(
            UNLABELED_ID,
            name="ragweld-neo4j-spoof",
            project="",
            service="neo4j",
            managed="",
        ),
    ]
    inspections = {
        MANAGED_ID: {
            "id": MANAGED_ID,
            "project": "ragweld",
            "service": "postgres",
            "managed": "true",
        },
        FOREIGN_ID: {
            "id": FOREIGN_ID,
            "project": "other",
            "service": "grafana",
            "managed": "true",
        },
        UNLABELED_ID: {
            "id": UNLABELED_ID,
            "project": "",
            "service": "neo4j",
            "managed": "",
        },
    }
    if duplicate_postgres:
        duplicate_id = "d" * 64
        rows.append(
            _container_line(
                duplicate_id,
                name="ragweld-postgres-2",
                project="ragweld",
                service="postgres",
                managed="true",
                state="exited",
            )
        )
        inspections[duplicate_id] = {
            "id": duplicate_id,
            "project": "ragweld",
            "service": "postgres",
            "managed": "true",
        }

    state_path.write_text(
        json.dumps(
            {
                "rows": rows,
                "inspections": inspections,
                "logs": {MANAGED_ID: "postgres ready\n"},
                "action_log": str(action_log),
                "context_endpoint": context_endpoint,
            }
        ),
        encoding="utf-8",
    )

    executable = tmp_path / "docker"
    executable.write_text(
        f"""#!{sys.executable}
import json
import os
import sys

state = json.loads(open(os.environ["RAGWELD_TEST_DOCKER_STATE"], encoding="utf-8").read())
args = sys.argv[1:]
if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
    print("Docker authority override leaked into command environment", file=sys.stderr)
    raise SystemExit(86)
if args[:2] == ["context", "inspect"]:
    print(state["context_endpoint"])
elif args[:1] == ["info"]:
    print("26.1.0")
elif args[:1] == ["ps"]:
    print("\\n".join(state["rows"]))
elif args[:1] == ["inspect"]:
    container_id = args[-1]
    item = state["inspections"].get(container_id)
    if item is None:
        print("not found", file=sys.stderr)
        raise SystemExit(1)
    print("\\t".join((item["id"], item["project"], item["service"], item["managed"])))
elif args[:1] in (["start"], ["stop"], ["restart"]):
    with open(state["action_log"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps(args) + "\\n")
elif args[:1] == ["logs"]:
    container_id = args[-1]
    print(state["logs"].get(container_id, ""), end="")
else:
    print("unsupported docker command: " + repr(args), file=sys.stderr)
    raise SystemExit(2)
""",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    previous_path = os.environ.get("PATH")
    previous_state = os.environ.get("RAGWELD_TEST_DOCKER_STATE")
    previous_docker_host = os.environ.get("DOCKER_HOST")
    previous_docker_context = os.environ.get("DOCKER_CONTEXT")
    os.environ["PATH"] = f"{tmp_path}{os.pathsep}{previous_path or ''}"
    os.environ["RAGWELD_TEST_DOCKER_STATE"] = str(state_path)
    os.environ["DOCKER_HOST"] = "tcp://foreign-daemon.invalid:2375"
    os.environ["DOCKER_CONTEXT"] = "foreign-context-override"
    try:
        yield action_log
    finally:
        if previous_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = previous_path
        if previous_state is None:
            os.environ.pop("RAGWELD_TEST_DOCKER_STATE", None)
        else:
            os.environ["RAGWELD_TEST_DOCKER_STATE"] = previous_state
        if previous_docker_host is None:
            os.environ.pop("DOCKER_HOST", None)
        else:
            os.environ["DOCKER_HOST"] = previous_docker_host
        if previous_docker_context is None:
            os.environ.pop("DOCKER_CONTEXT", None)
        else:
            os.environ["DOCKER_CONTEXT"] = previous_docker_context


@pytest.mark.asyncio
async def test_services_and_status_expose_only_exact_ragweld_owned_containers(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    # Catches removing any of the project, ownership-label, or service-allowlist checks.
    with _controlled_docker_cli(tmp_path):
        services_response = await client.get("/api/docker/services")
        status_response = await client.get("/api/docker/status")

    assert services_response.status_code == 200
    assert services_response.json() == {
        "containers": [
            {
                "id": MANAGED_ID,
                "short_id": MANAGED_ID[:12],
                "name": "ragweld-postgres-1",
                "image": "example:latest",
                "state": "running",
                "status": "Up 2 minutes",
                "ports": "127.0.0.1:5432->5432/tcp",
                "compose_project": "ragweld",
                "compose_service": "postgres",
                "managed": True,
            }
        ]
    }
    assert status_response.status_code == 200
    assert status_response.json() == {
        "running": True,
        "runtime": "docker 26.1.0",
        "project_name": "ragweld",
        "containers_count": 1,
    }


@pytest.mark.asyncio
async def test_service_action_revalidates_ownership_and_uses_full_container_id(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    # Catches acting on a display name/short ID or skipping inspect-time ownership validation.
    with _controlled_docker_cli(tmp_path) as action_log:
        response = await client.post("/api/docker/services/postgres/restart")

    assert response.status_code == 200
    assert response.json() == {"success": True, "service": "postgres", "action": "restart"}
    actions = [json.loads(line) for line in action_log.read_text(encoding="utf-8").splitlines()]
    assert actions == [["restart", "--", MANAGED_ID]]


@pytest.mark.asyncio
async def test_foreign_unlabeled_unknown_and_ambiguous_services_fail_closed(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    # Catches substring/name-prefix fallbacks and arbitrary compose-service control.
    with _controlled_docker_cli(tmp_path, duplicate_postgres=True) as action_log:
        foreign = await client.post("/api/docker/services/grafana/stop")
        unlabeled = await client.post("/api/docker/services/neo4j/start")
        unknown = await client.post("/api/docker/services/not-a-service/start")
        ambiguous = await client.post("/api/docker/services/postgres/restart")

    assert foreign.status_code == 404
    assert unlabeled.status_code == 404
    assert unknown.status_code == 404
    assert ambiguous.status_code == 409
    assert not action_log.exists()


@pytest.mark.asyncio
async def test_service_logs_use_generated_response_contract(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    # Catches reintroducing arbitrary container-addressed log access or a handwritten wire shape.
    with _controlled_docker_cli(tmp_path):
        response = await client.get("/api/docker/services/postgres/logs?tail=10")
        openapi = (await client.get("/openapi.json")).json()

    assert response.status_code == 200
    assert response.json() == {"success": True, "logs": "postgres ready\n", "error": None}
    schema = openapi["paths"]["/api/docker/services/{service}/logs"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert schema == {"$ref": "#/components/schemas/DockerServiceLogsResponse"}


@pytest.mark.asyncio
async def test_docker_control_routes_reject_nonlocal_clients(tmp_path: Path) -> None:
    # Catches relying on CORS or launcher bind addresses as the only control-plane boundary.
    with _controlled_docker_cli(tmp_path):
        transport = ASGITransport(app=app, client=("192.0.2.10", 43120))
        async with AsyncClient(transport=transport, base_url="http://ragweld.test") as remote_client:
            responses = [
                await remote_client.get("/api/docker/status"),
                await remote_client.get("/api/docker/services"),
                await remote_client.post("/api/docker/services/postgres/restart"),
                await remote_client.get("/api/docker/services/postgres/logs"),
            ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]


@pytest.mark.asyncio
async def test_docker_control_routes_reject_selected_remote_context(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    # Catches trusting a user-selected ssh/tcp Docker context after env overrides are stripped.
    with _controlled_docker_cli(tmp_path, context_endpoint="ssh://builder.example/run/docker.sock") as action_log:
        responses = [
            await client.get("/api/docker/status"),
            await client.get("/api/docker/services"),
            await client.post("/api/docker/services/postgres/restart"),
            await client.get("/api/docker/services/postgres/logs"),
        ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]
    assert not action_log.exists()


@pytest.mark.asyncio
async def test_arbitrary_container_and_legacy_routes_are_removed(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    # Catches restoring host-wide inventory, arbitrary IDs, destructive remove/pause, or aliases.
    with _controlled_docker_cli(tmp_path):
        responses = [
            await client.get("/api/docker/containers"),
            await client.get("/api/docker/containers/all"),
            await client.post(f"/api/docker/container/{FOREIGN_ID}/start"),
            await client.post(f"/api/docker/container/{FOREIGN_ID}/pause"),
            await client.post(f"/api/docker/container/{FOREIGN_ID}/unpause"),
            await client.post(f"/api/docker/container/{FOREIGN_ID}/remove"),
            await client.get(f"/api/docker/container/{FOREIGN_ID}/logs"),
            await client.post(f"/api/docker/{FOREIGN_ID}/restart"),
            await client.get(f"/api/docker/{FOREIGN_ID}/logs"),
        ]

    assert [response.status_code for response in responses] == [404] * len(responses)


# ==============================================================================
# Loki resolver + tail (F12): a busy box must not read as "Loki not reachable"
# ==============================================================================
#
# `_resolve_loki_base_url` probed `/ready` on every single call with a 0.6s timeout. Under a
# Docling re-index that probe times out, so `/api/loki/status` and `/api/stream/loki/tail`
# both answered "not reachable" while Loki was up, and the Chat log panel stayed stuck on
# that error until the page was reloaded.
#
# Every server below is a real `http.server` on an ephemeral port: the resolver runs its real
# httpx probe against it, so nothing here can pass on a stub that agrees with itself.


class _LokiStubHandler(BaseHTTPRequestHandler):
    """The two Loki routes the resolver and the tail actually call."""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's interface
        path = self.path.split("?", 1)[0]
        server = cast(Any, self.server)
        if path == "/ready":
            server.ready_hits += 1
            # A stall accepts the connection and then does not answer: Loki up, box busy.
            # Interruptible so teardown never waits it out.
            stall = float(server.ready_stall_s)
            if stall > 0:
                server.stop_event.wait(stall)
            status = int(server.ready_status)
            self._respond(status, b"ready\n" if status == 200 else b"not ready\n", "text/plain")
            return
        if path == "/loki/api/v1/query_range":
            server.query_hits += 1
            stall = float(server.query_stall_s)
            if stall > 0:
                server.stop_event.wait(stall)
            payload = json.dumps(
                {
                    "status": "success",
                    "data": {
                        "resultType": "streams",
                        "result": [
                            {
                                "stream": {"compose_service": "api"},
                                "values": [[str(ts), line] for ts, line in server.entries],
                            }
                        ],
                    },
                }
            ).encode()
            self._respond(200, payload, "application/json")
            return
        self._respond(404, b"", "text/plain")

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        """Keep the real server out of the pytest log."""


@contextmanager
def _loki_stub(*, ready_status: int = 200, entries: list[tuple[int, str]] | None = None) -> Iterator[Any]:
    """A real Loki-shaped HTTP server on an ephemeral port, stopped on exit.

    `LOKI_BASE_URL` points at it for the duration and is restored afterwards, using the same
    save/restore this file already applies to the Docker CLI environment. The Loki tests
    therefore patch nothing at all, which is what takes this file off the zero-mock
    allowlist in `scripts/check_banned.py`.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LokiStubHandler)
    server.ready_hits = 0  # type: ignore[attr-defined]
    server.query_hits = 0  # type: ignore[attr-defined]
    server.ready_status = ready_status  # type: ignore[attr-defined]
    server.ready_stall_s = 0.0  # type: ignore[attr-defined]
    server.query_stall_s = 0.0  # type: ignore[attr-defined]
    server.stop_event = threading.Event()  # type: ignore[attr-defined]
    server.entries = list(entries or [])  # type: ignore[attr-defined]
    server.base_url = f"http://127.0.0.1:{server.server_address[1]}"  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    previous_base_url = os.environ.get("LOKI_BASE_URL")
    os.environ["LOKI_BASE_URL"] = server.base_url
    try:
        yield server
    finally:
        if previous_base_url is None:
            os.environ.pop("LOKI_BASE_URL", None)
        else:
            os.environ["LOKI_BASE_URL"] = previous_base_url
        server.stop_event.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(autouse=True)
def reset_loki_resolver_cache() -> Iterator[None]:
    """The resolved URL is process-wide, so a leaked entry would answer the next test."""
    docker_api._LOKI_BASE_CACHE = None
    try:
        yield
    finally:
        docker_api._LOKI_BASE_CACHE = None


def _sse_payloads(chunks: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[len("data: ") :]))
    return out


def _local_tail_request() -> Request:
    """A real local Starlette request for the tail endpoint (it refuses remote clients)."""

    async def _receive() -> dict[str, Any]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/stream/loki/tail",
            "raw_path": b"/api/stream/loki/tail",
            "root_path": "",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 54321),
            "server": ("127.0.0.1", 58012),
        },
        receive=_receive,
    )


async def _drain_tail(
    response: StreamingResponse,
    *,
    limit: int,
    stop_type: str | None = None,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Read SSE payloads off the real tail stream until `stop_type`, `limit` or the timeout."""
    payloads: list[dict[str, Any]] = []
    iterator = response.body_iterator

    async def _read() -> None:
        async for chunk in iterator:
            payloads.extend(_sse_payloads([chunk if isinstance(chunk, str) else chunk.decode()]))
            if stop_type is not None and any(p.get("type") == stop_type for p in payloads):
                return
            if len(payloads) >= limit:
                return

    try:
        await asyncio.wait_for(_read(), timeout=timeout)
    except TimeoutError:
        pass
    finally:
        await cast(Any, iterator).aclose()
    return payloads


@pytest.mark.asyncio
async def test_the_resolver_caches_the_reachable_loki_and_rides_out_a_probe_outage() -> None:
    """The whole defect: one slow probe made a live Loki read as unreachable."""
    with _loki_stub() as stub:

        assert await docker_api._resolve_loki_base_url() == stub.base_url
        assert stub.ready_hits == 1

        # A second caller is answered from the cache, not from another probe.
        assert await docker_api._resolve_loki_base_url() == stub.base_url
        assert stub.ready_hits == 1

    # The probe would now fail outright (the server is gone); the cache still answers, which
    # is exactly what a probe timing out under load must look like.
    assert await docker_api._resolve_loki_base_url() == stub.base_url


@pytest.mark.asyncio
async def test_the_cached_loki_url_expires_and_is_probed_again() -> None:
    """The cache is a five-minute shock absorber, not a permanent answer."""
    with _loki_stub() as stub:

        assert await docker_api._resolve_loki_base_url(cache_ttl_s=0.2) == stub.base_url
        assert stub.ready_hits == 1

        await asyncio.sleep(0.3)

        assert await docker_api._resolve_loki_base_url(cache_ttl_s=0.2) == stub.base_url
        assert stub.ready_hits == 2


@pytest.mark.asyncio
async def test_a_connection_failure_against_the_cached_loki_drops_it(
    client: AsyncClient,
) -> None:
    """A cached URL that cannot be connected to is wrong, and must not be kept for 5 minutes."""
    with _loki_stub() as stub:
        ok = await client.get("/api/loki/status")
        assert ok.status_code == 200
        assert ok.json() == {"reachable": True, "url": stub.base_url, "status": "ok"}
        assert docker_api._LOKI_BASE_CACHE is not None

    gone = await client.get("/api/loki/status")
    assert gone.status_code == 200
    assert gone.json()["reachable"] is False
    assert docker_api._LOKI_BASE_CACHE is None


@pytest.mark.asyncio
async def test_a_slow_but_reachable_loki_keeps_the_cached_url(
    client: AsyncClient,
) -> None:
    """The exact F12 condition: Loki is up, the box is too busy to answer the probe in time.

    A timeout is the one failure this cache exists to absorb, and `httpx.TimeoutException`
    is a subclass of `httpx.TransportError` -- so the invalidation clause written for
    "could not connect at all" also fired on "answered too slowly", tearing the cache down
    under exactly the load it was built for and putting the next caller back on the full
    candidate probe.
    """
    with _loki_stub() as stub:
        assert (await client.get("/api/loki/status")).json()["reachable"] is True
        assert docker_api._LOKI_BASE_CACHE is not None

        # The connection is accepted; the answer never arrives inside the probe budget.
        stub.ready_stall_s = 30.0
        busy = await client.get("/api/loki/status")

    payload = busy.json()
    assert payload["reachable"] is False
    assert payload["url"] == stub.base_url
    assert "Timeout" in payload["status"], payload
    assert docker_api._LOKI_BASE_CACHE is not None, "a busy probe must not tear down the cache"


@pytest.mark.asyncio
async def test_a_loki_status_error_response_keeps_the_cached_url(
    client: AsyncClient,
) -> None:
    """A 503 from Loki says the URL is right and Loki is busy: only transport failures invalidate."""
    with _loki_stub() as stub:
        assert (await client.get("/api/loki/status")).json()["reachable"] is True

        stub.ready_status = 503
        busy = await client.get("/api/loki/status")
        assert busy.json() == {"reachable": False, "url": stub.base_url, "status": "status_503"}
        assert docker_api._LOKI_BASE_CACHE is not None


@pytest.mark.asyncio
async def test_the_tail_retries_the_resolver_and_recovers_without_a_reconnect() -> None:
    """The stuck panel: the tail ended on the first failed resolve and never came back."""
    with _loki_stub(ready_status=503, entries=[(1_700_000_000_000_000_000, "hello from loki")]) as stub:

        response = docker_api._loki_tail_response(
            _local_tail_request(),
            query='{ragweld_service="api"}',
            start_ms=1_700_000_000_000,
            end_ms=None,
            limit=100,
            poll_ms=250,
            probe_timeout_s=0.3,
            retry_seconds=0.2,
            retry_budget_seconds=30.0,
        )

        async def _heal() -> None:
            await asyncio.sleep(0.6)
            stub.ready_status = 200

        healer = asyncio.create_task(_heal())
        try:
            payloads = await _drain_tail(response, limit=40, stop_type="log", timeout=25.0)
        finally:
            healer.cancel()

    retrying = [p for p in payloads if p.get("type") == "error"]
    assert retrying, payloads
    assert all(p["message"] == "Loki not reachable (retrying)" for p in retrying), payloads
    # The stream stayed open across the outage and delivered real Loki lines afterwards.
    logs = [p for p in payloads if p.get("type") == "log"]
    assert logs, payloads
    assert "hello from loki" in logs[0]["message"]
    assert not [p for p in payloads if p.get("type") == "complete"], payloads


@pytest.mark.asyncio
async def test_the_tail_route_refuses_a_remote_client() -> None:
    """The route is a thin wrapper now, and the localhost guard lives only on it."""
    transport = ASGITransport(app=app, client=("192.0.2.10", 43120))
    async with AsyncClient(transport=transport, base_url="http://ragweld.test") as remote_client:
        response = await remote_client.get(
            "/api/stream/loki/tail", params={"query": '{ragweld_service="api"}'}
        )

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_a_slow_query_range_keeps_the_cached_url() -> None:
    """The tail's guard inherits the same subclass trap as `loki_status`.

    A `query_range` that times out ends this poll, but it does not say the URL is wrong --
    and dropping the cache there would send the next resolve back through every candidate
    on a box that is already too busy to answer.
    """
    with _loki_stub(entries=[(1_700_000_000_000_000_000, "hello from loki")]) as stub:
        assert await docker_api._resolve_loki_base_url() == stub.base_url
        assert docker_api._LOKI_BASE_CACHE is not None

        stub.query_stall_s = 30.0
        response = docker_api._loki_tail_response(
            _local_tail_request(),
            query='{ragweld_service="api"}',
            start_ms=1_700_000_000_000,
            end_ms=None,
            limit=100,
            poll_ms=250,
            query_timeout_s=0.3,
        )
        payloads = await _drain_tail(response, limit=10, stop_type="complete", timeout=25.0)

    errors = [p.get("message") for p in payloads if p.get("type") == "error"]
    assert errors and "Loki tail error" in str(errors[0]), payloads
    assert docker_api._LOKI_BASE_CACHE is not None, "a slow query must not tear down the cache"


@pytest.mark.asyncio
async def test_the_tail_gives_up_after_the_retry_budget() -> None:
    """Retrying forever would be its own lie: past the budget the stream says so and ends."""
    with _loki_stub(ready_status=503):
        response = docker_api._loki_tail_response(
            _local_tail_request(),
            query='{ragweld_service="api"}',
            start_ms=1_700_000_000_000,
            end_ms=None,
            limit=100,
            poll_ms=250,
            probe_timeout_s=0.3,
            retry_seconds=0.2,
            retry_budget_seconds=1.0,
        )
        payloads = await _drain_tail(response, limit=50, timeout=25.0)

    messages = [p.get("message") for p in payloads if p.get("type") == "error"]
    assert messages.count("Loki not reachable (retrying)") >= 2, payloads
    assert messages[-1] == "Loki not reachable", payloads
    assert payloads[-1] == {"type": "complete"}, payloads


@pytest.mark.asyncio
async def test_dev_status_reports_the_built_bundle_instead_of_a_red_missing_dev_server(
    client: AsyncClient,
) -> None:
    """A dev-only Vite probe must not read as an outage on a deployed host.

    The drive found "Frontend - stopped" in red, and "Host frontend (Vite) -
    Not running", while that very frontend was serving the page through Caddy:
    the probe checks a local dev server that is legitimately absent here, so the
    row was red permanently and by design.
    """

    bundle = Path(docker_api.__file__).resolve().parents[2] / "web" / "dist" / "index.html"
    if not bundle.is_file():
        pytest.skip("this checkout has no built frontend bundle to report")

    response = await client.get("/api/dev/status")
    assert response.status_code == 200, response.text
    data = response.json()

    if data["frontend_running"]:
        # A dev server really is up on this host; then that is what must be reported.
        assert data["frontend_mode"] == "dev_server"
        return

    assert data["frontend_mode"] == "built_bundle"
    assert data["frontend_bundle_path"] == "web/dist"
    assert data["frontend_bundle_built_at"]
    assert any("built bundle at web/dist" in line for line in data["details"])
    assert not any(line.startswith("No Vite dev server and no built bundle") for line in data["details"])
