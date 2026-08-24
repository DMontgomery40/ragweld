from __future__ import annotations

import logging
import os
import threading
import time

from server.models.tribrid_config_model import TriBridConfig

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_STATE: str = "not started"
_STARTED = False


def profiling_disabled_by_env() -> bool:
    """Test lanes keep the agent out of their processes with this switch."""
    return os.environ.get("RAGWELD_DISABLE_PROFILING", "").strip() == "1"


def profiling_state() -> str:
    """Truthful agent state for the observability status surface."""
    return _STATE


def start_profiling(config: TriBridConfig) -> bool:
    """Attach the Pyroscope agent to this process when a server is configured.

    The operator tunable is `tracing.pyroscope_base_url`; whether THIS process
    profiles itself is deployment wiring. A failed attach must never take down
    the API — it is recorded and surfaced through `profiling_state()` so the
    Pyroscope component status can report it instead of implying health.
    """
    global _STATE, _STARTED
    with _LOCK:
        if _STARTED:
            return True
        server = str(config.tracing.pyroscope_base_url or "").strip()
        if not server:
            _STATE = "off (no pyroscope_base_url configured)"
            return False
        if profiling_disabled_by_env():
            _STATE = "off (RAGWELD_DISABLE_PROFILING=1)"
            return False
        try:
            import pyroscope
        except Exception as error:  # pragma: no cover - environment-specific
            _STATE = f"failed (pyroscope SDK unavailable: {error})"
            logger.warning("pyroscope SDK unavailable; continuous profiling stays off: %s", error)
            return False
        try:
            pyroscope.configure(
                application_name="ragweld-api",
                server_address=server.rstrip("/"),
                tags={
                    "service_namespace": "ragweld",
                    "deployment_runtime": "host",
                },
            )
        except Exception as error:  # pragma: no cover - agent/ffi runtime errors
            _STATE = f"failed ({error})"
            logger.warning("pyroscope agent failed to start; continuous profiling stays off: %s", error)
            return False
        _STARTED = True
        # "attached" is all configure() proves; a background one-shot check
        # upgrades the state only after the server actually shows our profiles.
        _STATE = f"attached (pushing to {server.rstrip('/')}; awaiting server confirmation)"
        threading.Thread(
            target=_verify_upload,
            args=(server.rstrip("/"),),
            name="pyroscope-upload-verify",
            daemon=True,
        ).start()
        logger.info("continuous profiling attached (pyroscope at %s)", server)
        return True


def _verify_upload(server: str, *, attempts: int = 6, interval_s: float = 10.0) -> None:
    """Confirm the server received ragweld-api profiles; runs off-loop in a daemon thread."""
    global _STATE
    import httpx

    for _ in range(attempts):
        time.sleep(interval_s)
        try:
            response = httpx.post(
                f"{server}/querier.v1.QuerierService/LabelValues",
                json={"name": "service_name"},
                timeout=5.0,
            )
            names = response.json().get("names", []) if response.status_code == 200 else []
        except Exception:
            continue
        if "ragweld-api" in names:
            with _LOCK:
                _STATE = f"verified (server at {server} reports ragweld-api profiles)"
            return
    with _LOCK:
        _STATE = (
            f"failed (agent attached but {server} shows no ragweld-api profiles "
            f"after {int(attempts * interval_s)}s)"
        )
