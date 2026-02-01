from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from server.config import load_config
from server.models.tribrid_config_model import DevStackRestartResponse, DevStackStatusResponse, TriBridConfig

router = APIRouter(tags=["docker"])

_DEV_STACK_LOCK = asyncio.Lock()
_DEV_LOCK_PATH = Path("/tmp/tribrid-dev-stack.lock")
_DEV_LOCK_FH: Any | None = None

try:  # pragma: no cover - Windows compatibility
    import fcntl  # type: ignore
except Exception:  # pragma: no cover
    fcntl = None  # type: ignore


def _project_root() -> Path:
    # server/api/docker.py -> server/api -> server -> project root
    return Path(__file__).resolve().parents[2]


def _is_local_client(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1"}


def _ensure_dev_orchestrator_allowed(request: Request) -> None:
    if not _is_local_client(request):
        raise HTTPException(status_code=403, detail="Dev stack control is only allowed from localhost.")

    flag = (os.getenv("TRIBRID_DEV_ORCHESTRATOR") or "").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        raise HTTPException(status_code=403, detail="Dev stack control is disabled (TRIBRID_DEV_ORCHESTRATOR=0).")


def _dev_lock_try_acquire() -> bool:
    """Try to acquire a global dev-stack lock (non-blocking)."""
    global _DEV_LOCK_FH
    if _DEV_LOCK_FH is not None:
        return False
    fh = _DEV_LOCK_PATH.open("a+", encoding="utf-8")
    if fcntl is not None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.close()
            return False
    _DEV_LOCK_FH = fh
    return True


def _dev_lock_release() -> None:
    global _DEV_LOCK_FH
    fh = _DEV_LOCK_FH
    _DEV_LOCK_FH = None
    if not fh:
        return
    try:
        if fcntl is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
    finally:
        try:
            fh.close()
        except Exception:
            pass


def _dev_task_run_and_release(func: Any, *args: Any, **kwargs: Any) -> None:
    try:
        func(*args, **kwargs)
    finally:
        _dev_lock_release()


def _resolve_dev_ports() -> tuple[int, int]:
    """Resolve dev ports with env override, then config defaults."""
    try:
        cfg = load_config()
        cfg_front = int(getattr(cfg.docker, "dev_frontend_port", 5173))
        cfg_back = int(getattr(cfg.docker, "dev_backend_port", 8012))
    except Exception:
        cfg_front, cfg_back = 5173, 8012

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


def _docker_env(cfg: TriBridConfig) -> dict[str, str]:
    """Build env for docker CLI, honoring config overrides (best-effort)."""
    env = os.environ.copy()
    host = (getattr(cfg.docker, "docker_host", "") or "").strip()
    if host:
        env["DOCKER_HOST"] = host
    return env


def _loki_candidate_urls() -> list[str]:
    """Return candidate Loki base URLs (best-effort, local-dev oriented)."""
    env = (os.getenv("LOKI_BASE_URL") or "").strip()
    candidates = []
    if env:
        candidates.append(env)
    # Local dev (run on host)
    candidates.append("http://127.0.0.1:3100")
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
        stdout = e.stdout or ""
        stderr = e.stderr or f"Command timed out after {timeout_s}s"
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


async def _docker_containers_count(*, timeout_s: int, env: dict[str, str] | None) -> int:
    try:
        res = await _run_cmd_async(["docker", "ps", "-aq"], timeout_s=timeout_s, env=env)
    except FileNotFoundError:
        return 0
    if res.returncode != 0:
        return 0
    lines = [ln for ln in (res.stdout or "").splitlines() if ln.strip()]
    return len(lines)


def _parse_labels(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


async def _list_docker_containers(*, timeout_s: int, env: dict[str, str] | None) -> list[dict[str, Any]]:
    """Return containers in the Dashboard/Docker UI shape."""
    try:
        res = await _run_cmd_async(
            [
                "docker",
                "ps",
                "-a",
                "--no-trunc",
                "--format",
                "{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.State}}\t{{.Status}}\t{{.Ports}}\t{{.Labels}}",
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
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        cid, image, name, state, status, ports, labels_raw = parts[:7]
        labels = _parse_labels(labels_raw)
        compose_project = labels.get("com.docker.compose.project")
        compose_service = labels.get("com.docker.compose.service")
        agro_managed = bool(compose_project == "tribrid" or name.startswith("tribrid-"))
        containers.append(
            {
                "id": cid,
                "short_id": cid[:12],
                "name": name,
                "image": image,
                "state": (state or "").lower() or "unknown",
                "status": status,
                "ports": ports,
                "compose_project": compose_project,
                "compose_service": compose_service,
                "agro_managed": agro_managed,
            }
        )
    return containers


def _lsof_listen_pids(port: int) -> list[int]:
    """Best-effort: return PIDs listening on TCP port (macOS/Linux)."""
    try:
        res = _run_cmd(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            timeout_s=2,
        )
    except FileNotFoundError:
        return []
    if res.returncode != 0:
        return []
    pids: list[int] = []
    for ln in (res.stdout or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            pids.append(int(ln))
        except ValueError:
            continue
    return pids


def _terminate_pids(pids: list[int], *, timeout_s: float = 5.0) -> None:
    """Terminate PIDs (SIGTERM then SIGKILL best-effort)."""
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError:
            continue

    # Wait a bit for graceful exit
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        alive = False
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive = True
            except ProcessLookupError:
                continue
            except PermissionError:
                # If we can't check, assume alive to avoid busy loop
                alive = True
        if not alive:
            return
        # short sleep (sync) - only used in background tasks
        time.sleep(0.1)

    # Force kill remaining
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            continue


def _restart_vite_dev_server(*, port: int, timeout_s: int) -> None:
    root = _project_root()
    # Kill anything currently listening on the port.
    pids = _lsof_listen_pids(port)
    if pids:
        _terminate_pids(pids, timeout_s=5.0)

    # Start Vite (detached). Keep stdout/stderr in a predictable log file.
    log_dir = root / ".tests"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "vite-dev.log"
    with log_path.open("a", encoding="utf-8") as logf:
        subprocess.Popen(
            ["npm", "--prefix", "web", "run", "dev", "--", "--port", str(port)],
            cwd=str(root),
            stdout=logf,
            stderr=logf,
            start_new_session=True,
            env=os.environ.copy(),
        )

    # Best-effort: give it a moment to bind before returning
    try:
        subprocess.run(
            ["node", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1, min(5, timeout_s)),
        )
    except Exception:
        pass


def _touch_reload_trigger() -> None:
    """Trigger uvicorn --reload by touching a gitignored file."""
    root = _project_root()
    trigger = root / ".tests" / "dev-reload.trigger"
    trigger.parent.mkdir(parents=True, exist_ok=True)
    trigger.write_text(str(time.time()), encoding="utf-8")


def _clear_python_bytecode_cache() -> None:
    root = _project_root()
    # Clear only safe, repo-owned locations.
    candidates = [
        root / "server",
        root / "tests",
        root / "scripts",
    ]
    for base in candidates:
        if not base.exists():
            continue
        for p in base.rglob("__pycache__"):
            try:
                # Remove directory tree
                for child in p.rglob("*"):
                    try:
                        if child.is_file() or child.is_symlink():
                            child.unlink(missing_ok=True)
                    except Exception:
                        continue
                try:
                    p.rmdir()
                except Exception:
                    pass
            except Exception:
                continue
        for p in base.rglob("*.pyc"):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                continue


# ============================================================================
# Docker runtime endpoints (used by Docker tab + dashboard)
# ============================================================================


@router.get("/docker/status")
async def get_docker_status() -> dict[str, Any]:
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_status_timeout", 5))
        list_timeout = int(getattr(cfg.docker, "docker_container_list_timeout", 10))
    except Exception:
        cfg = TriBridConfig()
        timeout, list_timeout = 5, 10

    env = _docker_env(cfg)
    running, runtime = await _docker_running(timeout_s=timeout, env=env)
    containers_count = await _docker_containers_count(timeout_s=list_timeout, env=env) if running else 0
    return {"running": running, "runtime": runtime, "containers_count": containers_count}


@router.get("/docker/containers")
async def list_docker_containers() -> dict[str, Any]:
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_container_list_timeout", 10))
    except Exception:
        cfg = TriBridConfig()
        timeout = 10
    env = _docker_env(cfg)
    containers = await _list_docker_containers(timeout_s=timeout, env=env)
    return {"containers": containers}


@router.get("/docker/containers/all")
async def list_docker_containers_all() -> dict[str, Any]:
    # Backward-compatible alias used by the Docker tab (axios client).
    return await list_docker_containers()


@router.post("/docker/container/{container_id}/start")
async def start_container(container_id: str) -> dict[str, Any]:
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_container_action_timeout", 30))
    except Exception:
        cfg = TriBridConfig()
        timeout = 30
    try:
        env = _docker_env(cfg)
        res = await _run_cmd_async(["docker", "start", container_id], timeout_s=timeout, env=env)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    if res.returncode != 0:
        raise HTTPException(status_code=500, detail=(res.stderr or res.stdout or "Failed to start container").strip())
    return {"success": True}


@router.post("/docker/container/{container_id}/stop")
async def stop_container(container_id: str) -> dict[str, Any]:
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_container_action_timeout", 30))
    except Exception:
        cfg = TriBridConfig()
        timeout = 30
    try:
        env = _docker_env(cfg)
        res = await _run_cmd_async(["docker", "stop", container_id], timeout_s=timeout, env=env)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    if res.returncode != 0:
        raise HTTPException(status_code=500, detail=(res.stderr or res.stdout or "Failed to stop container").strip())
    return {"success": True}


@router.post("/docker/container/{container_id}/restart")
async def restart_container_by_id(container_id: str) -> dict[str, Any]:
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_container_action_timeout", 30))
    except Exception:
        cfg = TriBridConfig()
        timeout = 30
    try:
        env = _docker_env(cfg)
        res = await _run_cmd_async(["docker", "restart", container_id], timeout_s=timeout, env=env)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    if res.returncode != 0:
        raise HTTPException(
            status_code=500, detail=(res.stderr or res.stdout or "Failed to restart container").strip()
        )
    return {"success": True}


@router.post("/docker/container/{container_id}/pause")
async def pause_container(container_id: str) -> dict[str, Any]:
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_container_action_timeout", 30))
    except Exception:
        cfg = TriBridConfig()
        timeout = 30
    try:
        env = _docker_env(cfg)
        res = await _run_cmd_async(["docker", "pause", container_id], timeout_s=timeout, env=env)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    if res.returncode != 0:
        raise HTTPException(status_code=500, detail=(res.stderr or res.stdout or "Failed to pause container").strip())
    return {"success": True}


@router.post("/docker/container/{container_id}/unpause")
async def unpause_container(container_id: str) -> dict[str, Any]:
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_container_action_timeout", 30))
    except Exception:
        cfg = TriBridConfig()
        timeout = 30
    try:
        env = _docker_env(cfg)
        res = await _run_cmd_async(["docker", "unpause", container_id], timeout_s=timeout, env=env)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    if res.returncode != 0:
        raise HTTPException(status_code=500, detail=(res.stderr or res.stdout or "Failed to unpause container").strip())
    return {"success": True}


@router.post("/docker/container/{container_id}/remove")
async def remove_container(container_id: str) -> dict[str, Any]:
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_container_action_timeout", 30))
    except Exception:
        cfg = TriBridConfig()
        timeout = 30
    try:
        env = _docker_env(cfg)
        res = await _run_cmd_async(["docker", "rm", "-f", container_id], timeout_s=timeout, env=env)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    if res.returncode != 0:
        raise HTTPException(status_code=500, detail=(res.stderr or res.stdout or "Failed to remove container").strip())
    return {"success": True}


@router.get("/docker/container/{container_id}/logs")
async def get_container_logs(
    container_id: str,
    tail: int | None = Query(default=None, ge=10, le=1000),
) -> dict[str, Any]:
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_container_list_timeout", 10))
        default_tail = int(getattr(cfg.docker, "docker_logs_tail", 100))
        timestamps = int(getattr(cfg.docker, "docker_logs_timestamps", 1))
    except Exception:
        cfg = TriBridConfig()
        timeout, default_tail, timestamps = 10, 100, 1

    env = _docker_env(cfg)
    effective_tail = int(tail or default_tail)

    args = ["docker", "logs", "--tail", str(effective_tail)]
    if timestamps:
        args.append("--timestamps")
    args.append(container_id)
    try:
        res = await _run_cmd_async(args, timeout_s=timeout, env=env)
    except FileNotFoundError as e:
        return {"success": False, "logs": "", "error": str(e)}
    if res.returncode != 0:
        return {"success": False, "logs": "", "error": (res.stderr or res.stdout or "Failed to fetch logs").strip()}
    return {"success": True, "logs": res.stdout or ""}


# Legacy aliases (older UI paths)
@router.post("/docker/{container}/restart")
async def restart_container(container: str) -> dict[str, Any]:
    return await restart_container_by_id(container)


@router.get("/docker/{container}/logs")
async def get_container_logs_legacy(container: str, lines: int = 100) -> list[str]:
    res = await get_container_logs(container, tail=lines)
    if not res.get("success"):
        raise HTTPException(status_code=500, detail=res.get("error") or "Failed to fetch logs")
    return str(res.get("logs") or "").splitlines()


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

    frontend_probe_urls = [f"http://{_url_host(h)}:{frontend_port}/web" for h in hosts]
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


@router.post("/dev/frontend/restart", response_model=DevStackRestartResponse)
async def restart_dev_frontend(request: Request, background_tasks: BackgroundTasks) -> DevStackRestartResponse:
    _ensure_dev_orchestrator_allowed(request)
    frontend_port, _backend_port = _resolve_dev_ports()

    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "dev_stack_restart_timeout", 30))
    except Exception:
        timeout = 30

    async with _DEV_STACK_LOCK:
        if not _dev_lock_try_acquire():
            raise HTTPException(status_code=409, detail="A dev stack operation is already in progress.")

        # Run after response so Vite's /api proxy can return successfully before we restart it.
        background_tasks.add_task(
            _dev_task_run_and_release,
            _restart_vite_dev_server,
            port=frontend_port,
            timeout_s=timeout,
        )
        return DevStackRestartResponse(
            success=True,
            message="Frontend restart scheduled",
            frontend_port=frontend_port,
        )


@router.post("/dev/backend/restart", response_model=DevStackRestartResponse)
async def restart_dev_backend(request: Request, background_tasks: BackgroundTasks) -> DevStackRestartResponse:
    _ensure_dev_orchestrator_allowed(request)
    _frontend_port, backend_port = _resolve_dev_ports()

    async with _DEV_STACK_LOCK:
        if not _dev_lock_try_acquire():
            raise HTTPException(status_code=409, detail="A dev stack operation is already in progress.")

        # Touch a file to trigger uvicorn --reload. Run after response to avoid proxy disconnects.
        background_tasks.add_task(_dev_task_run_and_release, _touch_reload_trigger)
        return DevStackRestartResponse(
            success=True,
            message="Backend reload triggered",
            backend_port=backend_port,
        )


@router.post("/dev/backend/clear-cache-restart", response_model=DevStackRestartResponse)
async def clear_cache_and_restart_backend(request: Request, background_tasks: BackgroundTasks) -> DevStackRestartResponse:
    _ensure_dev_orchestrator_allowed(request)
    _frontend_port, backend_port = _resolve_dev_ports()

    async with _DEV_STACK_LOCK:
        if not _dev_lock_try_acquire():
            raise HTTPException(status_code=409, detail="A dev stack operation is already in progress.")

        def _clear_and_reload() -> None:
            _clear_python_bytecode_cache()
            _touch_reload_trigger()

        background_tasks.add_task(_dev_task_run_and_release, _clear_and_reload)
        return DevStackRestartResponse(
            success=True,
            message="Cleared Python bytecode caches and triggered backend reload",
            backend_port=backend_port,
        )


@router.post("/dev/stack/restart", response_model=DevStackRestartResponse)
async def restart_dev_stack(request: Request, background_tasks: BackgroundTasks) -> DevStackRestartResponse:
    _ensure_dev_orchestrator_allowed(request)
    frontend_port, backend_port = _resolve_dev_ports()

    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "dev_stack_restart_timeout", 30))
    except Exception:
        timeout = 30

    async with _DEV_STACK_LOCK:
        if not _dev_lock_try_acquire():
            raise HTTPException(status_code=409, detail="A dev stack operation is already in progress.")

        def _restart_stack() -> None:
            # Order: restart frontend first (UI will go down briefly), then trigger backend reload.
            _restart_vite_dev_server(port=frontend_port, timeout_s=timeout)
            _touch_reload_trigger()

        # Run after response so Vite's /api proxy can return before we restart it.
        background_tasks.add_task(_dev_task_run_and_release, _restart_stack)
        return DevStackRestartResponse(
            success=True,
            message="Full stack restart scheduled",
            frontend_port=frontend_port,
            backend_port=backend_port,
        )


# ==============================================================================
# Loki proxy + streaming (dev tooling)
# ==============================================================================


@router.get("/loki/status")
async def loki_status(request: Request) -> dict[str, Any]:
    """Check whether Loki is reachable (local dev)."""
    _ensure_dev_orchestrator_allowed(request)
    base = await _resolve_loki_base_url()
    if not base:
        return {"reachable": False, "status": "unreachable"}

    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(f"{base}/ready")
        reachable = r.status_code < 500
        return {"reachable": bool(reachable), "url": base, "status": "ok" if reachable else f"status_{r.status_code}"}
    except Exception as e:
        return {"reachable": False, "url": base, "status": f"error: {e.__class__.__name__}"}


@router.get("/loki/query_range")
async def loki_query_range(
    request: Request,
    query: str = Query(..., description="LogQL query"),
    start_ms: int | None = Query(default=None, ge=0, description="Start time (epoch ms)"),
    end_ms: int | None = Query(default=None, ge=0, description="End time (epoch ms)"),
    limit: int = Query(default=2000, ge=1, le=10000, description="Max log lines"),
    direction: str = Query(default="forward", pattern="^(forward|backward)$"),
) -> dict[str, Any]:
    """Proxy Loki query_range (dev tooling)."""
    _ensure_dev_orchestrator_allowed(request)
    base = await _resolve_loki_base_url()
    if not base:
        raise HTTPException(status_code=503, detail="Loki not reachable")

    now_ns = int(time.time() * 1_000_000_000)
    start_ns = int(start_ms * 1_000_000) if start_ms is not None else now_ns - int(60 * 1_000_000_000)
    end_ns = int(end_ms * 1_000_000) if end_ms is not None else now_ns

    params = {"query": query, "start": str(start_ns), "end": str(end_ns), "limit": str(int(limit)), "direction": direction}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{base}/loki/api/v1/query_range", params=params)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Loki query failed: {e}") from e


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
    _ensure_dev_orchestrator_allowed(request)
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
