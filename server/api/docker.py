from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from server.config import load_config
from server.models.tribrid_config_model import DevStackRestartResponse, DevStackStatusResponse

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


def _run_cmd(args: list[str], *, timeout_s: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


def _docker_running(*, timeout_s: int) -> tuple[bool, str]:
    try:
        info = _run_cmd(["docker", "info", "--format", "{{.ServerVersion}}"], timeout_s=timeout_s)
    except FileNotFoundError:
        return False, "docker"

    if info.returncode != 0:
        return False, "docker"

    ver = (info.stdout or "").strip()
    return True, f"docker{(' ' + ver) if ver else ''}".strip()


def _docker_containers_count(*, timeout_s: int) -> int:
    try:
        res = _run_cmd(["docker", "ps", "-aq"], timeout_s=timeout_s)
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


def _list_docker_containers(*, timeout_s: int) -> list[dict[str, Any]]:
    """Return containers in the Dashboard/Docker UI shape."""
    try:
        res = _run_cmd(
            [
                "docker",
                "ps",
                "-a",
                "--no-trunc",
                "--format",
                "{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.State}}\t{{.Status}}\t{{.Ports}}\t{{.Labels}}",
            ],
            timeout_s=timeout_s,
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
        timeout, list_timeout = 5, 10

    running, runtime = _docker_running(timeout_s=timeout)
    containers_count = _docker_containers_count(timeout_s=list_timeout) if running else 0
    return {"running": running, "runtime": runtime, "containers_count": containers_count}


@router.get("/docker/containers")
async def list_docker_containers() -> dict[str, Any]:
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_container_list_timeout", 10))
    except Exception:
        timeout = 10
    containers = _list_docker_containers(timeout_s=timeout)
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
        timeout = 30
    try:
        res = _run_cmd(["docker", "start", container_id], timeout_s=timeout)
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
        timeout = 30
    try:
        res = _run_cmd(["docker", "stop", container_id], timeout_s=timeout)
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
        timeout = 30
    try:
        res = _run_cmd(["docker", "restart", container_id], timeout_s=timeout)
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
        timeout = 30
    try:
        res = _run_cmd(["docker", "pause", container_id], timeout_s=timeout)
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
        timeout = 30
    try:
        res = _run_cmd(["docker", "unpause", container_id], timeout_s=timeout)
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
        timeout = 30
    try:
        res = _run_cmd(["docker", "rm", "-f", container_id], timeout_s=timeout)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    if res.returncode != 0:
        raise HTTPException(status_code=500, detail=(res.stderr or res.stdout or "Failed to remove container").strip())
    return {"success": True}


@router.get("/docker/container/{container_id}/logs")
async def get_container_logs(container_id: str, tail: int = Query(default=100, ge=1, le=5000)) -> dict[str, Any]:
    try:
        cfg = load_config()
        timeout = int(getattr(cfg.docker, "docker_container_list_timeout", 10))
        timestamps = int(getattr(cfg.docker, "docker_logs_timestamps", 1))
    except Exception:
        timeout, timestamps = 10, 1
    args = ["docker", "logs", "--tail", str(tail)]
    if timestamps:
        args.append("--timestamps")
    args.append(container_id)
    try:
        res = _run_cmd(args, timeout_s=timeout)
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
    frontend_url = f"http://127.0.0.1:{frontend_port}/web"
    backend_url = f"http://127.0.0.1:{backend_port}/api/health"

    details: list[str] = []
    frontend_running = await _http_ok(frontend_url, timeout_s=1.0)
    if not frontend_running:
        details.append(f"Frontend not reachable at {frontend_url}")

    backend_running = await _http_ok(backend_url, timeout_s=1.0)
    if not backend_running:
        details.append(f"Backend not reachable at {backend_url}")

    return DevStackStatusResponse(
        frontend_running=frontend_running,
        backend_running=backend_running,
        frontend_port=frontend_port,
        backend_port=backend_port,
        frontend_url=frontend_url,
        backend_url=f"http://127.0.0.1:{backend_port}/api",
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
