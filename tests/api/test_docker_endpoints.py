from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

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
