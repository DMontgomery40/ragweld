from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from server.config import load_config
from server.models.tribrid_config_model import (
    DevStackStatusResponse,
    DockerContainer,
    DockerContainersResponse,
    DockerServiceLogsResponse,
    DockerStatus,
    LokiStatus,
    TriBridConfig,
)

router = APIRouter(tags=["docker"])

_DOCKER_PROJECT = "ragweld"
_DOCKER_MANAGED_LABEL = "io.ragweld.managed"
_DOCKER_MANAGED_VALUE = "true"
_DOCKER_SERVICES = frozenset(
    {
        "api",
        "grafana",
        "loki",
        "neo4j",
        "postgres",
        "postgres-exporter",
        "prometheus",
        "promtail",
        "tempo",
        "caddy",
        "authelia",
        "cloudflared",
        "alloy",
        "mimir",
        "pyroscope",
        "alertmanager",
        "langfuse",
        "langfuse-worker",
        "langfuse-postgres",
        "langfuse-clickhouse",
        "langfuse-redis",
        "langfuse-minio",
        "litellm",
        "qdrant",
        "mlflow",
        "flyte",
    }
)
_DOCKER_ACTIONS = frozenset({"start", "stop", "restart"})
_FULL_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")


def _is_local_client(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1"}


def _ensure_local_request(request: Request) -> None:
    if not _is_local_client(request):
        raise HTTPException(status_code=403, detail="Local runtime diagnostics are only available from localhost.")


def _resolve_dev_ports() -> tuple[int, int]:
    """Resolve dev ports with env override, then config defaults."""
    try:
        cfg = load_config()
        cfg_front = int(getattr(cfg.docker, "dev_frontend_port", 55173))
        cfg_back = int(getattr(cfg.docker, "dev_backend_port", 58012))
    except Exception:
        cfg_front, cfg_back = 55173, 58012

    frontend_port = int(os.getenv("FRONTEND_PORT") or cfg_front)
    backend_port = int(os.getenv("BACKEND_PORT") or cfg_back)
    return frontend_port, backend_port


async def _http_ok(url: str, timeout_s: float = 1.5) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.get(url)
            # Treat any non-5xx response as “reachable”.
            return r.status_code < 500
    except Exception:
        return False


def _docker_env() -> dict[str, str]:
    """Build a local-context Docker CLI environment without remote-daemon authority."""
    env = os.environ.copy()
    env.pop("DOCKER_HOST", None)
    env.pop("DOCKER_CONTEXT", None)
    return env


async def _ensure_local_docker_context(*, timeout_s: int, env: dict[str, str]) -> None:
    """Reject selected Docker contexts that address a remote daemon."""
    try:
        result = await _run_cmd_async(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            timeout_s=timeout_s,
            env=env,
        )
    except FileNotFoundError:
        return
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Docker context could not be inspected.").strip()
        raise HTTPException(status_code=503, detail=detail)
    endpoint = (result.stdout or "").strip().lower()
    if not endpoint.startswith(("unix://", "npipe://")):
        raise HTTPException(status_code=403, detail="Ragweld Docker control requires a local Docker context.")


def _loki_candidate_urls() -> list[str]:
    """Return candidate Loki base URLs (best-effort, local-dev oriented)."""
    env = (os.getenv("LOKI_BASE_URL") or "").strip()
    candidates = []
    if env:
        candidates.append(env)
    # Local dev (run on host)
    candidates.append("http://127.0.0.1:53100")
    # Docker-compose network (backend inside compose)
    candidates.append("http://loki:3100")
    # Docker Desktop host alias
    candidates.append("http://host.docker.internal:3100")

    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        c = (c or "").strip().rstrip("/")
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


async def _resolve_loki_base_url(timeout_s: float = 0.6) -> str | None:
    """Return the first reachable Loki base URL (or None)."""
    for base in _loki_candidate_urls():
        if await _http_ok(f"{base}/ready", timeout_s=timeout_s):
            return base
    return None


def _run_cmd(args: list[str], *, timeout_s: int, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command (sync).

    IMPORTANT: This must never raise TimeoutExpired inside request handlers.
    """
    try:
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        # Return a synthetic failure result rather than raising.
        stdout_raw = e.stdout
        stderr_raw = e.stderr
        stdout: str = stdout_raw.decode() if isinstance(stdout_raw, bytes) else (stdout_raw or "")
        stderr: str = stderr_raw.decode() if isinstance(stderr_raw, bytes) else (stderr_raw or f"Command timed out after {timeout_s}s")
        return subprocess.CompletedProcess(args=args, returncode=124, stdout=stdout, stderr=stderr)


async def _run_cmd_async(
    args: list[str], *, timeout_s: int, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command off the event loop."""
    return await asyncio.to_thread(_run_cmd, args, timeout_s=timeout_s, env=env)


async def _docker_running(*, timeout_s: int, env: dict[str, str] | None) -> tuple[bool, str]:
    try:
        info = await _run_cmd_async(
            ["docker", "info", "--format", "{{.ServerVersion}}"], timeout_s=timeout_s, env=env
        )
    except FileNotFoundError:
        return False, "docker"

    if info.returncode != 0:
        return False, "docker"

    ver = (info.stdout or "").strip()
    return True, f"docker{(' ' + ver) if ver else ''}".strip()


def _parse_managed_service(line: str) -> dict[str, Any] | None:
    parts = line.split("\t")
    if len(parts) < 9:
        return None
    cid, image, name, state, status, ports, compose_project, compose_service, managed = parts[:9]
    cid = cid.strip().lower()
    compose_project = compose_project.strip()
    compose_service = compose_service.strip()
    managed = managed.strip()
    if not _FULL_CONTAINER_ID.fullmatch(cid):
        return None
    if compose_project != _DOCKER_PROJECT or managed != _DOCKER_MANAGED_VALUE:
        return None
    if compose_service not in _DOCKER_SERVICES:
        return None
    return {
        "id": cid,
        "short_id": cid[:12],
        "name": name,
        "image": image,
        "state": (state or "").lower() or "unknown",
        "status": status,
        "ports": ports,
        "compose_project": compose_project,
        "compose_service": compose_service,
        "managed": True,
    }


async def _list_managed_services(*, timeout_s: int, env: dict[str, str] | None) -> list[dict[str, Any]]:
    """List only exactly labelled, allowlisted services in the Ragweld Compose project."""
    try:
        res = await _run_cmd_async(
            [
                "docker",
                "ps",
                "-a",
                "--no-trunc",
                "--filter",
                f"label=com.docker.compose.project={_DOCKER_PROJECT}",
                "--filter",
                f"label={_DOCKER_MANAGED_LABEL}={_DOCKER_MANAGED_VALUE}",
                "--format",
                (
                    '{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.State}}\t{{.Status}}\t{{.Ports}}\t'
                    '{{.Label "com.docker.compose.project"}}\t'
                    '{{.Label "com.docker.compose.service"}}\t'
                    f'{{{{.Label "{_DOCKER_MANAGED_LABEL}"}}}}'
                ),
            ],
            timeout_s=timeout_s,
            env=env,
        )
    except FileNotFoundError:
        return []
    if res.returncode != 0:
        return []

    containers: list[dict[str, Any]] = []
    for line in (res.stdout or "").splitlines():
        parsed = _parse_managed_service(line)
        if parsed is not None:
            containers.append(parsed)
    return containers


def _validate_service(service: str) -> str:
    if service not in _DOCKER_SERVICES:
        raise HTTPException(status_code=404, detail="Ragweld Docker service not found.")
    return service


async def _resolve_managed_service_id(
    service: str,
    *,
    timeout_s: int,
    env: dict[str, str] | None,
) -> str:
    """Resolve a service to one immutable full ID, then revalidate its ownership labels."""
    service = _validate_service(service)
    matches = [
        item
        for item in await _list_managed_services(timeout_s=timeout_s, env=env)
        if item["compose_service"] == service
    ]
    if not matches:
        raise HTTPException(status_code=404, detail="Ragweld Docker service not found.")
    if len(matches) != 1:
        raise HTTPException(status_code=409, detail="Ragweld Docker service ownership is ambiguous.")

    candidate_id = str(matches[0]["id"])
    inspect_format = (
        '{{.Id}}\t{{index .Config.Labels "com.docker.compose.project"}}\t'
        '{{index .Config.Labels "com.docker.compose.service"}}\t'
        f'{{{{index .Config.Labels "{_DOCKER_MANAGED_LABEL}"}}}}'
    )
    try:
        result = await _run_cmd_async(
            ["docker", "inspect", "--format", inspect_format, candidate_id],
            timeout_s=timeout_s,
            env=env,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Docker CLI is unavailable.") from exc
    if result.returncode != 0:
        raise HTTPException(status_code=404, detail="Ragweld Docker service not found.")

    parts = (result.stdout or "").strip().split("\t")
    if len(parts) != 4:
        raise HTTPException(status_code=404, detail="Ragweld Docker service ownership could not be verified.")
    inspected_id, project, inspected_service, managed = (part.strip() for part in parts)
    inspected_id = inspected_id.lower()
    if (
        not _FULL_CONTAINER_ID.fullmatch(inspected_id)
        or inspected_id != candidate_id
        or project != _DOCKER_PROJECT
        or inspected_service != service
        or managed != _DOCKER_MANAGED_VALUE
    ):
        raise HTTPException(status_code=404, detail="Ragweld Docker service ownership could not be verified.")
    return inspected_id


# ============================================================================
# Docker runtime endpoints (used by Docker tab + dashboard)
# ============================================================================


@router.get("/docker/status", response_model=DockerStatus)
async def get_docker_status(request: Request) -> DockerStatus:
    _ensure_local_request(request)
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_status_timeout", 5))
        list_timeout = int(getattr(cfg.docker, "docker_container_list_timeout", 10))
    except Exception:
        cfg = TriBridConfig()
        timeout, list_timeout = 5, 10

    env = _docker_env()
    await _ensure_local_docker_context(timeout_s=timeout, env=env)
    running, runtime = await _docker_running(timeout_s=timeout, env=env)
    containers = await _list_managed_services(timeout_s=list_timeout, env=env) if running else []
    return DockerStatus(
        running=bool(running),
        runtime=str(runtime or ""),
        project_name=_DOCKER_PROJECT,
        containers_count=len(containers),
    )


@router.get("/docker/services", response_model=DockerContainersResponse)
async def list_docker_services(request: Request) -> DockerContainersResponse:
    _ensure_local_request(request)
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_container_list_timeout", 10))
    except Exception:
        cfg = TriBridConfig()
        timeout = 10
    env = _docker_env()
    await _ensure_local_docker_context(timeout_s=timeout, env=env)
    container_dicts = await _list_managed_services(timeout_s=timeout, env=env)
    containers = [DockerContainer.model_validate(c) for c in container_dicts]
    return DockerContainersResponse(containers=containers)


@router.post("/docker/services/{service}/{action}")
async def control_docker_service(request: Request, service: str, action: str) -> dict[str, Any]:
    _ensure_local_request(request)
    service = _validate_service(service)
    if action not in _DOCKER_ACTIONS:
        raise HTTPException(status_code=404, detail="Ragweld Docker action not found.")
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_container_action_timeout", 30))
    except Exception:
        cfg = TriBridConfig()
        timeout = 30
    env = _docker_env()
    await _ensure_local_docker_context(timeout_s=timeout, env=env)
    container_id = await _resolve_managed_service_id(service, timeout_s=timeout, env=env)
    try:
        result = await _run_cmd_async(["docker", action, "--", container_id], timeout_s=timeout, env=env)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Docker CLI is unavailable.") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"Failed to {action} Ragweld service.").strip()
        raise HTTPException(status_code=502, detail=detail)
    return {"success": True, "service": service, "action": action}


@router.get("/docker/services/{service}/logs", response_model=DockerServiceLogsResponse)
async def get_docker_service_logs(
    request: Request,
    service: str,
    tail: int | None = Query(default=None, ge=10, le=1000),
) -> DockerServiceLogsResponse:
    _ensure_local_request(request)
    service = _validate_service(service)
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_container_list_timeout", 10))
        default_tail = int(getattr(cfg.docker, "docker_logs_tail", 100))
        timestamps = bool(getattr(cfg.docker, "docker_logs_timestamps", True))
    except Exception:
        cfg = TriBridConfig()
        timeout, default_tail, timestamps = 10, 100, True

    env = _docker_env()
    await _ensure_local_docker_context(timeout_s=timeout, env=env)
    effective_tail = int(tail or default_tail)
    container_id = await _resolve_managed_service_id(service, timeout_s=timeout, env=env)

    args = ["docker", "logs", "--tail", str(effective_tail)]
    if timestamps:
        args.append("--timestamps")
    args.extend(["--", container_id])
    try:
        res = await _run_cmd_async(args, timeout_s=timeout, env=env)
    except FileNotFoundError as e:
        return DockerServiceLogsResponse(success=False, logs="", error=str(e))
    if res.returncode != 0:
        error = (res.stderr or res.stdout or "Failed to fetch logs").strip()
        return DockerServiceLogsResponse(success=False, logs="", error=error)
    return DockerServiceLogsResponse(success=True, logs=res.stdout or "", error=None)


# ============================================================================
# Dev Stack orchestration endpoints
# ============================================================================


@router.get("/dev/status", response_model=DevStackStatusResponse)
async def get_dev_stack_status() -> DevStackStatusResponse:
    frontend_port, backend_port = _resolve_dev_ports()
    # NOTE: In dev, users may reach services via localhost, 127.0.0.1, or ::1.
    # When the backend is containerized, reaching a host-side dev server may require host.docker.internal.
    def _url_host(host: str) -> str:
        return f"[{host}]" if ":" in host and not host.startswith("[") else host

    hosts = ["127.0.0.1", "localhost", "::1"]
    try:
        if Path("/.dockerenv").exists():
            hosts.append("host.docker.internal")
    except Exception:
        pass

    async def _probe_first_ok(urls: list[str], *, label: str) -> tuple[bool, str | None, list[str]]:
        for idx, url in enumerate(urls):
            ok = await _http_ok(url, timeout_s=1.0)
            if ok:
                if idx == 0:
                    return True, url, []
                return True, url, [f"{label} reachable at {url} (preferred {urls[0]} failed)"]
        return False, None, [f"{label} not reachable at {u}" for u in urls]

    details: list[str] = []

    frontend_probe_urls = [f"http://{_url_host(h)}:{frontend_port}/web/" for h in hosts]
    frontend_running, resolved_frontend_url, frontend_details = await _probe_first_ok(
        frontend_probe_urls, label="Frontend"
    )
    details.extend(frontend_details)

    backend_health_urls = [f"http://{_url_host(h)}:{backend_port}/api/health" for h in hosts]
    backend_running, resolved_backend_health, backend_details = await _probe_first_ok(
        backend_health_urls, label="Backend"
    )
    details.extend(backend_details)

    # Surface URLs that match the chosen reachable host (best-effort).
    frontend_url = resolved_frontend_url or frontend_probe_urls[0]
    backend_url = (
        (resolved_backend_health or backend_health_urls[0]).replace("/api/health", "/api")
        if (resolved_backend_health or backend_health_urls)
        else None
    )

    return DevStackStatusResponse(
        frontend_running=frontend_running,
        backend_running=backend_running,
        frontend_port=frontend_port,
        backend_port=backend_port,
        frontend_url=frontend_url,
        backend_url=backend_url,
        details=details,
    )


# ==============================================================================
# Loki proxy + streaming (dev tooling)
# ==============================================================================


@router.get("/loki/status", response_model=LokiStatus)
async def loki_status(request: Request) -> LokiStatus:
    """Check whether Loki is reachable (local dev)."""
    _ensure_local_request(request)
    base = await _resolve_loki_base_url()
    if not base:
        return LokiStatus(reachable=False, url=None, status="unreachable")

    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(f"{base}/ready")
        reachable = r.status_code < 500
        return LokiStatus(
            reachable=bool(reachable),
            url=str(base),
            status=("ok" if reachable else f"status_{r.status_code}"),
        )
    except Exception as e:
        return LokiStatus(reachable=False, url=str(base), status=f"error: {e.__class__.__name__}")


@router.get("/stream/loki/tail")
async def loki_tail(
    request: Request,
    query: str = Query(..., description="LogQL query"),
    start_ms: int | None = Query(default=None, ge=0, description="Start time (epoch ms)"),
    end_ms: int | None = Query(default=None, ge=0, description="Optional end time (epoch ms)"),
    limit: int = Query(default=2000, ge=1, le=10000, description="Max log lines per poll"),
    poll_ms: int = Query(default=1000, ge=250, le=5000, description="Polling interval (ms)"),
) -> StreamingResponse:
    """SSE stream of Loki logs using incremental query_range polling.

    Emits TerminalService-compatible SSE events:
    - {"type":"log","message":"..."}
    - {"type":"error","message":"..."}
    - {"type":"complete"}
    """
    _ensure_local_request(request)
    base = await _resolve_loki_base_url()

    async def _gen() -> Any:
        if not base:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Loki not reachable'})}\n\n"
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"
            return

        now_ns = int(time.time() * 1_000_000_000)
        cursor_ns = int(start_ms * 1_000_000) if start_ms is not None else now_ns - int(30 * 1_000_000_000)
        end_ns_static = int(end_ms * 1_000_000) if end_ms is not None else None

        # Deduplicate a small sliding window to avoid repeated lines between polls.
        seen_order: deque[tuple[int, str, str]] = deque()
        seen_set: set[tuple[int, str, str]] = set()
        max_seen = 5000

        idle_rounds = 0

        while True:
            if await request.is_disconnected():
                break

            end_ns = end_ns_static if end_ns_static is not None else int(time.time() * 1_000_000_000)
            params = {
                "query": query,
                "start": str(cursor_ns),
                "end": str(end_ns),
                "limit": str(int(limit)),
                "direction": "forward",
            }

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(f"{base}/loki/api/v1/query_range", params=params)
                if r.status_code >= 400:
                    raise RuntimeError(f"{r.status_code}: {r.text}")
                payload = r.json()
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': f'Loki tail error: {e}'})}\n\n"
                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                break

            results = (payload.get("data") or {}).get("result") or []
            entries: list[tuple[int, str, str]] = []

            for stream in results:
                labels = stream.get("stream") or {}
                service = (
                    labels.get("compose_service")
                    or labels.get("container")
                    or labels.get("job")
                    or labels.get("app")
                    or "log"
                )
                for pair in stream.get("values") or []:
                    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                        continue
                    ts_raw, line = pair
                    try:
                        ts_ns = int(ts_raw)
                    except Exception:
                        continue
                    entries.append((ts_ns, str(service), str(line)))

            entries.sort(key=lambda x: x[0])

            emitted = 0
            max_ts = cursor_ns
            for ts_ns, service, line in entries:
                key = (ts_ns, service, line)
                if key in seen_set:
                    max_ts = max(max_ts, ts_ns)
                    continue

                seen_set.add(key)
                seen_order.append(key)
                if len(seen_order) > max_seen:
                    old = seen_order.popleft()
                    seen_set.discard(old)

                max_ts = max(max_ts, ts_ns)
                emitted += 1
                yield f"data: {json.dumps({'type': 'log', 'message': f'[{service}] {line}'})}\n\n"

            cursor_ns = max(cursor_ns, max_ts)

            # If bounded by end_ms, close after a short idle window beyond end time.
            if end_ns_static is not None:
                if emitted == 0:
                    idle_rounds += 1
                else:
                    idle_rounds = 0
                if (int(time.time() * 1_000_000_000) >= end_ns_static) and idle_rounds >= 2:
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    break

            await asyncio.sleep(poll_ms / 1000)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
