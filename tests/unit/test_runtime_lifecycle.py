from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    if env:
        merged.update(env)
    if env and "RAGWELD_RUNTIME_DIR" in env:
        return subprocess.run(args, cwd=ROOT, env=merged, text=True, capture_output=True, check=False)
    with tempfile.TemporaryDirectory(prefix="ragweld-runtime-test-") as runtime_dir:
        merged["RAGWELD_RUNTIME_DIR"] = runtime_dir
        return subprocess.run(args, cwd=ROOT, env=merged, text=True, capture_output=True, check=False)


def _unused_tcp_port() -> int:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    return port


def _spawn_node_listener(cwd: Path) -> tuple[subprocess.Popen[bytes], int]:
    port = _unused_tcp_port()
    process = subprocess.Popen(
        [
            "node",
            "-e",
            "require('net').createServer(() => {}).listen(Number(process.argv[1]), '127.0.0.1')",
            str(port),
        ],
        cwd=cwd,
    )
    return process, port


def _wait_until_owned_process_is_visible(pid: int, cwd: Path, port: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        cwd_result = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            text=True,
            capture_output=True,
            check=False,
        )
        port_result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            text=True,
            capture_output=True,
            check=False,
        )
        if f"n{cwd}" in cwd_result.stdout and str(pid) in port_result.stdout.splitlines():
            return
        time.sleep(0.05)
    raise AssertionError(f"process {pid} never became observable on {port} in {cwd}")


def _fake_runtime_tools(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "docker.log"
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
if [[ "${1:-}" == "info" ]]; then exit 0; fi
if [[ "${1:-} ${2:-}" == "context inspect" ]]; then printf 'unix:///tmp/fake-docker.sock\n'; exit 0; fi
if [[ "${1:-}" == "ps" ]]; then [[ "${FAKE_DOCKER_PS_FAIL:-0}" == "1" ]] && exit 7; [[ -n "${FAKE_DOCKER_CONTAINER_ID:-}" ]] && printf '%s\n' "$FAKE_DOCKER_CONTAINER_ID"; exit 0; fi
if [[ "${1:-}" == "inspect" ]]; then printf '%s\n' "${FAKE_DOCKER_INSPECT_LABELS:-ragweld|true|postgres}"; exit 0; fi
if [[ "${1:-} ${2:-}" == "volume ls" ]]; then [[ "${FAKE_DOCKER_VOLUME_FAIL:-0}" == "1" ]] && exit 8; [[ -n "${FAKE_DOCKER_VOLUMES:-}" ]] && printf '%s\n' "$FAKE_DOCKER_VOLUMES"; exit 0; fi
if [[ "${1:-}" == "compose" ]]; then exit 0; fi
exit 1
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    for name in ("lsof", "pgrep"):
        tool = bin_dir / name
        tool.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        tool.chmod(0o755)
    return bin_dir, log_path


def test_start_rejects_foreign_compose_project_before_runtime_mutation() -> None:
    result = _run(
        "bash",
        "start.sh",
        "--check",
        "--no-docker",
        "--no-backend",
        "--no-frontend",
        env={"COMPOSE_PROJECT_NAME": "foreign"},
    )

    assert result.returncode != 0
    assert "COMPOSE_PROJECT_NAME must be 'ragweld'" in result.stderr


def test_start_rejects_a_concurrent_lifecycle_command(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    lock_dir = runtime_dir / "lifecycle.lock"
    lock_dir.mkdir(parents=True)
    (lock_dir / "owner").write_text(f"{os.getpid()}\n", encoding="utf-8")

    result = _run(
        "bash",
        "start.sh",
        "--check",
        "--no-docker",
        "--no-backend",
        "--no-frontend",
        env={"RAGWELD_RUNTIME_DIR": str(runtime_dir)},
    )

    assert result.returncode != 0
    assert "another Ragweld lifecycle command is active" in result.stderr


@pytest.mark.parametrize(("backend_pid", "frontend_pid"), [("1234", ""), ("", "5678")])
def test_single_component_external_stop_is_released_cleanly(
    tmp_path: Path,
    backend_pid: str,
    frontend_pid: str,
) -> None:
    runtime_dir = tmp_path / "runtime"
    result = _run(
        "bash",
        "-c",
        (
            "ROOT_DIR=$1; RAGWELD_RUNTIME_DIR=$2; source scripts/runtime_lifecycle.sh; "
            "owned_host_records_released $3 $4"
        ),
        "lifecycle-check",
        str(ROOT),
        str(runtime_dir),
        backend_pid,
        frontend_pid,
    )

    assert result.returncode == 0, result.stderr


def test_start_check_rejects_busy_frontend_port() -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    try:
        result = _run(
            "bash",
            "start.sh",
            "--check",
            "--no-docker",
            "--no-backend",
            env={"FRONTEND_PORT": str(port)},
        )
    finally:
        listener.close()

    assert result.returncode != 0
    assert f"Frontend port {port} is already in use" in result.stderr


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("BACKEND_PORT", "not-a-port", "Backend port must be numeric"),
        ("BACKEND_PORT", "1023", "Backend port must be between 1024 and 65535"),
        ("BACKEND_PORT", "65536", "Backend port must be between 1024 and 65535"),
        ("FRONTEND_PORT", "not-a-port", "Frontend port must be numeric"),
        ("FRONTEND_PORT", "1023", "Frontend port must be between 1024 and 65535"),
        ("FRONTEND_PORT", "65536", "Frontend port must be between 1024 and 65535"),
    ],
)
def test_start_rejects_invalid_host_ports(name: str, value: str, message: str) -> None:
    result = _run(
        "bash",
        "start.sh",
        "--check",
        "--no-docker",
        "--no-backend",
        "--no-frontend",
        env={name: value},
    )

    assert result.returncode != 0
    assert message in result.stderr


def test_start_rejects_equal_backend_and_frontend_ports() -> None:
    result = _run(
        "bash",
        "start.sh",
        "--check",
        "--no-docker",
        env={"BACKEND_PORT": "56001", "FRONTEND_PORT": "56001"},
    )

    assert result.returncode != 0
    assert "Backend and frontend ports must be different" in result.stderr


def test_caller_backend_port_survives_a_dotenv_that_sets_a_different_one() -> None:
    """A real `.env` (this repo's own, or an operator's) commonly hardcodes
    BACKEND_PORT for the deployed default. `start.sh` sources `.env` with
    `source .env` -- a plain shell source overwrites an already-exported
    variable -- so without care, `.env`'s value would silently clobber a
    caller-provided BACKEND_PORT override on every run, not just this test
    fixture. Caller-provided environment must win over `.env`."""
    caller_port = _unused_tcp_port()

    result = _run(
        "bash",
        "start.sh",
        "--check",
        "--no-docker",
        "--no-frontend",
        "--no-local-model",
        env={"BACKEND_PORT": str(caller_port)},
    )

    assert result.returncode == 0, result.stderr
    assert f"--port {caller_port}" in result.stdout


def test_vite_and_launcher_use_namespaced_strict_ports() -> None:
    from server.models.tribrid_config_model import DockerConfig

    start = (ROOT / "start.sh").read_text(encoding="utf-8")
    vite = (ROOT / "web" / "vite.config.ts").read_text(encoding="utf-8")
    active_config = json.loads((ROOT / "tribrid_config.json").read_text(encoding="utf-8"))
    docker_config = DockerConfig()

    assert 'BACKEND_PORT="${BACKEND_PORT:-58012}"' in start
    assert 'FRONTEND_PORT="${FRONTEND_PORT:-55173}"' in start
    assert "--strictPort" in start
    assert "strictPort: true" in vite
    assert "env.FRONTEND_PORT || 55173" in vite
    assert "--reload" not in start
    assert docker_config.dev_backend_port == 58012
    assert docker_config.dev_frontend_port == 55173
    assert active_config["docker"]["dev_backend_port"] == 58012
    assert active_config["docker"]["dev_frontend_port"] == 55173


def test_active_runtime_surfaces_do_not_advertise_legacy_app_ports() -> None:
    active_paths = [
        "start.sh",
        ".env.example",
        "tribrid_config.json",
        "web/vite.config.ts",
        "web/src/api/client.ts",
        "web/src/hooks/useAPI.ts",
        "web/src/stores/useRepoStore.ts",
        "playwright.config.ts",
        "playwright.exhaustive.config.ts",
        "web/tests/e2e/exhaustive/harness.ts",
        "web/tests/e2e/exhaustive/chat_reliability.spec.ts",
        "web/tests/e2e/exhaustive/README.md",
        "scripts/automation_bootstrap.sh",
        "scripts/acceptance_epstein.sh",
        "scripts/quick_setup.py",
    ]

    for relative_path in active_paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "127.0.0.1:8012" not in source, relative_path
        assert "localhost:8012" not in source, relative_path
        assert "127.0.0.1:5173" not in source, relative_path
        assert "localhost:5173" not in source, relative_path


def test_stop_only_signals_a_recorded_owned_frontend(tmp_path: Path) -> None:
    if shutil.which("node") is None or shutil.which("lsof") is None:
        pytest.skip("node and lsof are required for the real process-ownership check")

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    owned, owned_port = _spawn_node_listener(ROOT / "web")
    unrecorded, unrecorded_port = _spawn_node_listener(ROOT / "web")
    try:
        _wait_until_owned_process_is_visible(owned.pid, ROOT / "web", owned_port)
        _wait_until_owned_process_is_visible(unrecorded.pid, ROOT / "web", unrecorded_port)
        (runtime_dir / "frontend.pid").write_text(f"{owned.pid}|{owned_port}\n", encoding="utf-8")
        result = _run(
            "bash",
            "stop.sh",
            "--no-docker",
            env={"RAGWELD_RUNTIME_DIR": str(runtime_dir)},
        )
        owned.wait(timeout=10)

        assert result.returncode == 0, result.stderr
        assert unrecorded.poll() is None
        assert not (runtime_dir / "frontend.pid").exists()
        again = _run(
            "bash",
            "stop.sh",
            "--no-docker",
            env={"RAGWELD_RUNTIME_DIR": str(runtime_dir)},
        )
        assert again.returncode == 0
    finally:
        for proc in (owned, unrecorded):
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)


def test_reset_refuses_live_listener_without_pid_metadata(tmp_path: Path) -> None:
    if shutil.which("lsof") is None:
        pytest.skip("lsof is required for the real listener check")

    runtime_dir = tmp_path / "runtime"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    try:
        result = _run(
            "bash",
            "reset-data.sh",
            "--confirm=DELETE-RAGWELD-DATA",
            env={
                "RAGWELD_RUNTIME_DIR": str(runtime_dir),
                "BACKEND_PORT": str(port),
                "FRONTEND_PORT": str(port + 1),
            },
        )
    finally:
        listener.close()

    assert result.returncode != 0
    assert "resolved-port listeners remain active" in result.stderr


def test_stop_refuses_forged_pid_metadata(tmp_path: Path) -> None:
    if shutil.which("node") is None or shutil.which("lsof") is None:
        pytest.skip("node and lsof are required for the real process-ownership check")

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    foreign, foreign_port = _spawn_node_listener(ROOT)
    try:
        _wait_until_owned_process_is_visible(foreign.pid, ROOT, foreign_port)
        (runtime_dir / "frontend.pid").write_text(f"{foreign.pid}|{foreign_port}\n", encoding="utf-8")
        result = _run(
            "bash",
            "stop.sh",
            "--no-docker",
            env={"RAGWELD_RUNTIME_DIR": str(runtime_dir)},
        )

        assert result.returncode == 0
        assert foreign.poll() is None
        assert "Refusing to signal unowned frontend" in result.stderr
        assert not (runtime_dir / "frontend.pid").exists()
    finally:
        foreign.terminate()
        foreign.wait(timeout=10)


def test_reset_requires_exact_confirmation_and_is_not_called_by_normal_lifecycle() -> None:
    result = _run("bash", "reset-data.sh")
    start = (ROOT / "start.sh").read_text(encoding="utf-8")
    stop = (ROOT / "stop.sh").read_text(encoding="utf-8")

    assert result.returncode != 0
    assert "--confirm=DELETE-RAGWELD-DATA" in result.stderr
    assert "reset-data.sh" not in start
    assert "reset-data.sh" not in stop
    assert "down --volumes" not in stop
    assert "ragweld_compose stop" in stop


def test_stop_and_confirmed_reset_use_exact_fixed_project_docker_actions(tmp_path: Path) -> None:
    bin_dir, log_path = _fake_runtime_tools(tmp_path)
    runtime_dir = tmp_path / "runtime"
    shared_env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(log_path),
        "RAGWELD_RUNTIME_DIR": str(runtime_dir),
        "FAKE_DOCKER_VOLUMES": "ragweld_postgres_data",
    }

    stop_result = _run("bash", "stop.sh", env=shared_env)
    assert stop_result.returncode == 0, stop_result.stderr
    stop_log = log_path.read_text(encoding="utf-8")
    assert "compose --project-name ragweld" in stop_log
    assert stop_log.rstrip().endswith("stop")
    assert "down --volumes" not in stop_log

    log_path.write_text("", encoding="utf-8")
    reset_result = _run(
        "bash",
        "reset-data.sh",
        "--confirm=DELETE-RAGWELD-DATA",
        env=shared_env,
    )
    assert reset_result.returncode == 0, reset_result.stderr
    reset_log = log_path.read_text(encoding="utf-8")
    assert "compose --project-name ragweld" in reset_log
    assert reset_log.rstrip().endswith("down --volumes --remove-orphans")
    assert "colima" not in reset_log


def test_reset_rejects_container_outside_exact_managed_scope(tmp_path: Path) -> None:
    bin_dir, log_path = _fake_runtime_tools(tmp_path)
    result = _run(
        "bash",
        "reset-data.sh",
        "--confirm=DELETE-RAGWELD-DATA",
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_DOCKER_LOG": str(log_path),
            "RAGWELD_RUNTIME_DIR": str(tmp_path / "runtime"),
            "FAKE_DOCKER_CONTAINER_ID": "abc123",
            "FAKE_DOCKER_INSPECT_LABELS": "ragweld|false|postgres",
        },
    )

    assert result.returncode != 0
    assert "exact Ragweld ownership boundary" in result.stderr
    assert "down --volumes --remove-orphans" not in log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("failure_env", "message"),
    [
        ({"FAKE_DOCKER_PS_FAIL": "1"}, "unable to enumerate Ragweld project containers"),
        ({"FAKE_DOCKER_VOLUME_FAIL": "1"}, "unable to enumerate Ragweld project volumes"),
    ],
)
def test_reset_fails_closed_when_docker_enumeration_fails(
    tmp_path: Path,
    failure_env: dict[str, str],
    message: str,
) -> None:
    bin_dir, log_path = _fake_runtime_tools(tmp_path)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(log_path),
        "RAGWELD_RUNTIME_DIR": str(tmp_path / "runtime"),
        **failure_env,
    }
    result = _run(
        "bash",
        "reset-data.sh",
        "--confirm=DELETE-RAGWELD-DATA",
        env=env,
    )

    assert result.returncode != 0
    assert message in result.stderr
    assert "down --volumes --remove-orphans" not in log_path.read_text(encoding="utf-8")
