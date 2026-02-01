import subprocess

import pytest
from _pytest.monkeypatch import MonkeyPatch
from httpx import AsyncClient

import server.api.docker as docker_api


@pytest.mark.asyncio
async def test_docker_status_running(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    async def fake_run_cmd_async(
        args: list[str], *, timeout_s: int, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="25.0.0\n", stderr="")
        if args[:3] == ["docker", "ps", "-aq"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="a\nb\n", stderr="")
        raise AssertionError(f"Unexpected docker args: {args}")

    monkeypatch.setattr(docker_api, "_run_cmd_async", fake_run_cmd_async)

    res = await client.get("/api/docker/status")
    assert res.status_code == 200
    data = res.json()
    assert data["running"] is True
    assert data["containers_count"] == 2
    assert "docker" in str(data.get("runtime") or "").lower()


@pytest.mark.asyncio
async def test_docker_status_not_running(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    async def fake_run_cmd_async(
        args: list[str], *, timeout_s: int, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="Cannot connect")
        raise AssertionError(f"Unexpected docker args: {args}")

    monkeypatch.setattr(docker_api, "_run_cmd_async", fake_run_cmd_async)

    res = await client.get("/api/docker/status")
    assert res.status_code == 200
    data = res.json()
    assert data["running"] is False
    assert data["containers_count"] == 0


@pytest.mark.asyncio
async def test_list_docker_containers(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    line = (
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\t"
        "postgres:16\t"
        "tribrid-postgres\t"
        "running\t"
        "Up 2 minutes\t"
        "0.0.0.0:5432->5432/tcp\t"
        "com.docker.compose.project=tribrid,com.docker.compose.service=postgres\n"
    )

    async def fake_run_cmd_async(
        args: list[str], *, timeout_s: int, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        if args[:3] == ["docker", "ps", "-a"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=line, stderr="")
        raise AssertionError(f"Unexpected docker args: {args}")

    monkeypatch.setattr(docker_api, "_run_cmd_async", fake_run_cmd_async)

    res = await client.get("/api/docker/containers")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data.get("containers"), list)
    assert len(data["containers"]) == 1
    c0 = data["containers"][0]
    assert c0["name"] == "tribrid-postgres"
    assert c0["image"] == "postgres:16"
    assert c0["compose_project"] == "tribrid"
    assert c0["compose_service"] == "postgres"


@pytest.mark.asyncio
async def test_container_logs_success(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    async def fake_run_cmd_async(
        args: list[str], *, timeout_s: int, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["docker", "logs"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="hello\nworld\n", stderr="")
        raise AssertionError(f"Unexpected docker args: {args}")

    monkeypatch.setattr(docker_api, "_run_cmd_async", fake_run_cmd_async)

    res = await client.get("/api/docker/container/tribrid-postgres/logs?tail=10")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "hello" in data["logs"]


@pytest.mark.asyncio
async def test_container_start_success(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    async def fake_run_cmd_async(
        args: list[str], *, timeout_s: int, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["docker", "start"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        raise AssertionError(f"Unexpected docker args: {args}")

    monkeypatch.setattr(docker_api, "_run_cmd_async", fake_run_cmd_async)

    res = await client.post("/api/docker/container/tribrid-postgres/start")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True

