from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

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
from server.observability.metrics import LOKI_PROBE_TIMEOUTS_TOTAL

router = APIRouter(tags=["docker"])

_DOCKER_PROJECT: Final = "ragweld"
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
        "authelia-redis",
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


async def _loki_ready_ok(url: str, *, timeout_s: float) -> bool:
    """Probe Loki `/ready`, counting timeouts so a busy box is visible in metrics.

    A timeout means the box is busy, not that Loki is absent, and it is deliberately
    not logged (a log line would restore the journal noise the resolved-URL cache
    exists to remove). The counter is the signal instead. Every other failure — a
    refused connection, a bad status — reads the same "not ready" as before.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.get(url)
            return r.status_code < 500
    except httpx.TimeoutException:
        LOKI_PROBE_TIMEOUTS_TOTAL.inc()
        return False
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


# Loki does not move while the process runs, but the probe that finds it shares a box with
# indexing: under a Docling re-index the 0.6s `/ready` probe timed out and every caller --
# `/api/loki/status` and the chat log tail alike -- reported "Loki not reachable" while Loki
# was up, and the Chat log panel stayed stuck on that error until the page was reloaded.
# Resolve once, keep the answer for this long, and re-probe only when a request against the
# cached URL cannot connect at all.
_LOKI_CACHE_TTL_SECONDS = 300.0

# The probe competes with whatever else the box is doing, and 0.6s was inside the noise of a
# loaded host. An invariant of the resolver, not an operator tunable: a parameter of
# `_resolve_loki_base_url` only so tests can drive it.
_LOKI_PROBE_TIMEOUT_SECONDS = 2.0

# A tail that opens while the box is busy must not end: it says it is retrying and holds the
# stream open until Loki answers, so a busy box self-heals without a page reload. Retrying
# forever would be its own lie, so the budget bounds it. Same kind of invariant as above.
_LOKI_TAIL_RETRY_SECONDS = 10.0
_LOKI_TAIL_RETRY_BUDGET_SECONDS = 120.0

# One `query_range` poll is a bulk read, not a liveness probe, so it gets a longer budget
# than `/ready`. Same kind of invariant as the two above, and a parameter for the same reason.
_LOKI_TAIL_QUERY_TIMEOUT_SECONDS = 10.0

# (base_url, monotonic expiry) for the resolved Loki, process-wide.
_LOKI_BASE_CACHE: tuple[str, float] | None = None


def _loki_candidate_urls() -> list[str]:
    """Return candidate Loki base URLs.

    `LOKI_BASE_URL` is authoritative when it is set: an operator who names Loki means that
    one, and probing local-dev guesses behind it would answer from a different Loki than the
    one configured. The guesses exist only for a local dev stack that sets nothing.
    """
    env = (os.getenv("LOKI_BASE_URL") or "").strip()
    if env:
        candidates = [env]
    else:
        candidates = [
            # Local dev (run on host)
            "http://127.0.0.1:53100",
            # Docker-compose network (backend inside compose)
            "http://loki:3100",
            # Docker Desktop host alias
            "http://host.docker.internal:3100",
        ]

    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        c = (c or "").strip().rstrip("/")
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _cached_loki_base_url() -> str | None:
    """The resolved Loki URL while it is still fresh."""
    cached = _LOKI_BASE_CACHE
    if cached is None:
        return None
    base, expires_at = cached
    if time.monotonic() >= expires_at:
        return None
    return base


def invalidate_loki_base_url(base: str | None = None) -> None:
    """Drop the cached Loki URL after a request against it failed to connect.

    Only a refused/unreachable connection invalidates. Two other failures must not:

    - a 4xx/5xx answer -- a malformed LogQL query, a Loki that is up but not ready -- says
      the URL is right and the request was wrong;
    - a timeout says the box is busy, which is the one condition this cache exists to
      absorb. `httpx.TimeoutException` is a subclass of `httpx.TransportError`, so every
      caller has to exclude it explicitly before the transport clause.

    Dropping the URL for either would put every caller back on the per-call candidate probe
    this cache exists to remove.
    """
    global _LOKI_BASE_CACHE
    cached = _LOKI_BASE_CACHE
    if cached is None:
        return
    if base is not None and cached[0] != str(base).strip().rstrip("/"):
        return
    _LOKI_BASE_CACHE = None


async def _resolve_loki_base_url(
    timeout_s: float | None = None,
    *,
    cache_ttl_s: float | None = None,
) -> str | None:
    """Return the first reachable Loki base URL (or None), cached for `cache_ttl_s`.

    A miss is deliberately not cached: when Loki is genuinely absent the next caller should
    find it as soon as it comes up, and the callers that would otherwise re-probe in a loop
    (the tail) rate-limit themselves.

    The probe budget and the TTL are invariants of the resolver, not operator tunables; they
    are parameters here only so tests can drive them, the same way
    `_run_docling_extraction_locked` takes `heartbeat_seconds`.
    """
    global _LOKI_BASE_CACHE
    cached = _cached_loki_base_url()
    if cached is not None:
        return cached
    probe_timeout = _LOKI_PROBE_TIMEOUT_SECONDS if timeout_s is None else float(timeout_s)
    ttl = _LOKI_CACHE_TTL_SECONDS if cache_ttl_s is None else float(cache_ttl_s)
    for base in _loki_candidate_urls():
        if await _loki_ready_ok(f"{base}/ready", timeout_s=probe_timeout):
            _LOKI_BASE_CACHE = (base, time.monotonic() + ttl)
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

    # A missing dev server is not a fault on a deployed host: there the frontend
    # is a built bundle served by the reverse proxy, and the operator is reading
    # this page through it. Report which of the two is true rather than painting
    # the absent dev server red on every deployment.
    bundle_path = Path(__file__).resolve().parents[2] / "web" / "dist" / "index.html"
    bundle_exists = bundle_path.is_file()
    if frontend_running:
        frontend_mode = "dev_server"
    elif bundle_exists:
        frontend_mode = "built_bundle"
    else:
        frontend_mode = "absent"
    bundle_built_at = (
        datetime.fromtimestamp(bundle_path.stat().st_mtime, tz=UTC) if bundle_exists else None
    )
    if frontend_mode == "built_bundle" and bundle_built_at is not None:
        details.append(
            "No Vite dev server on this host, which is expected on a deployed one: the frontend is "
            f"served from the built bundle at web/dist (built {bundle_built_at.isoformat()})."
        )
    elif frontend_mode == "absent":
        details.append(
            "No Vite dev server and no built bundle at web/dist; run `npm run build` in web/ or start the dev server."
        )

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
        frontend_mode=frontend_mode,  # type: ignore[arg-type]
        frontend_bundle_path="web/dist" if bundle_exists else None,
        frontend_bundle_built_at=bundle_built_at,
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
        async with httpx.AsyncClient(timeout=_LOKI_PROBE_TIMEOUT_SECONDS) as client:
            r = await client.get(f"{base}/ready")
        reachable = r.status_code < 500
        return LokiStatus(
            reachable=bool(reachable),
            url=str(base),
            status=("ok" if reachable else f"status_{r.status_code}"),
        )
    except httpx.TimeoutException as e:
        # Loki accepted the connection and did not answer in time: the box is busy, not the
        # URL wrong. Keeping the cached URL through exactly this is the point of the cache.
        # Must precede the TransportError clause -- TimeoutException is a subclass of it.
        return LokiStatus(reachable=False, url=str(base), status=f"error: {e.__class__.__name__}")
    except httpx.TransportError as e:
        # The cached URL could not be connected to at all, so it is the wrong URL: drop it
        # rather than answer "unreachable" from a stale cache for the rest of the TTL.
        invalidate_loki_base_url(base)
        return LokiStatus(reachable=False, url=str(base), status=f"error: {e.__class__.__name__}")
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
    return _loki_tail_response(
        request, query=query, start_ms=start_ms, end_ms=end_ms, limit=limit, poll_ms=poll_ms
    )


def _loki_tail_response(
    request: Request,
    *,
    query: str,
    start_ms: int | None,
    end_ms: int | None,
    limit: int,
    poll_ms: int,
    probe_timeout_s: float | None = None,
    retry_seconds: float | None = None,
    retry_budget_seconds: float | None = None,
    query_timeout_s: float | None = None,
) -> StreamingResponse:
    """Build the tail's SSE response.

    Split out of the route so its timing invariants can be driven by a test without
    rewriting module state: a FastAPI route turns every extra argument into a query
    parameter, so they cannot live on `loki_tail` itself.
    """
    retry_s = _LOKI_TAIL_RETRY_SECONDS if retry_seconds is None else float(retry_seconds)
    budget_s = (
        _LOKI_TAIL_RETRY_BUDGET_SECONDS if retry_budget_seconds is None else float(retry_budget_seconds)
    )
    query_s = _LOKI_TAIL_QUERY_TIMEOUT_SECONDS if query_timeout_s is None else float(query_timeout_s)

    async def _gen() -> Any:
        # Resolved inside the stream, not above it: a resolve that fails because the box is
        # busy is not the same answer as "Loki is gone", and ending here left the Chat log
        # panel stuck on an error until the operator reloaded the page. Say it is retrying,
        # hold the stream open, and pick Loki up as soon as it answers.
        base = await _resolve_loki_base_url(probe_timeout_s)
        if not base:
            deadline = time.monotonic() + budget_s
            while not base and time.monotonic() < deadline:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Loki not reachable (retrying)'})}\n\n"
                await asyncio.sleep(retry_s)
                if await request.is_disconnected():
                    return
                base = await _resolve_loki_base_url(probe_timeout_s)
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
                async with httpx.AsyncClient(timeout=query_s) as client:
                    r = await client.get(f"{base}/loki/api/v1/query_range", params=params)
                if r.status_code >= 400:
                    raise RuntimeError(f"{r.status_code}: {r.text}")
                payload = r.json()
            except Exception as e:
                # Same ordering trap as `loki_status`: a slow answer from a reachable Loki
                # is a TimeoutException, which is a TransportError, and must not invalidate.
                if isinstance(e, httpx.TransportError) and not isinstance(e, httpx.TimeoutException):
                    invalidate_loki_base_url(base)
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
