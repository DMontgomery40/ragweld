"""Ragweld's entrypoint for the Laya System One server.

Upstream ``laya.serve.create_app`` provides the HTTP surface (``POST /v1/systemone``,
``GET /health``). This entrypoint changes how its Router is built and adds ``GET /metrics``.

* One checkpoint, named by ``LAYA_MODELS`` (english | multilingual | typed-decisions), is
  built before the server binds, and it is the only checkpoint that can ever load. Upstream
  sends non-English text to the multilingual checkpoint and builds it beside the resident
  one (``Router.load`` builds before it evicts), which would break the container's memory
  cap. Automatic routing is pinned to the configured checkpoint, and the response's
  ``routing.reason`` says so. A request that explicitly names another checkpoint gets a 422.
* ``/metrics`` exposes the process collector (the container's only process, so its RSS is
  the container's memory), the forward-pass time and the resident checkpoint.

Environment, with the upstream names where one exists:

* ``LAYA_MODELS``: the one checkpoint to serve. Required, exactly one.
* ``LAYA_DEVICE``: torch device (``cpu`` on LXC100).
* ``LAYA_THREADS``: torch intra-op threads. Keep it equal to the container CPU limit.
* ``LAYA_HOST``, ``LAYA_PORT``, ``LAYA_LOG_LEVEL`` and ``LAYA_API_KEY``: as upstream.

``LAYA_PRELOAD`` and ``LAYA_AUTO_TASK`` are not read. The checkpoint is always built first,
so a ``/health`` that answers means the model is resident.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Gauge, Histogram, generate_latest

CHECKPOINTS = ("english", "multilingual", "typed-decisions")

# Upstream accepts 64 questions per request and runs them as one batch. Measured on LXC100
# (4 CPUs, 4 GiB cap, full 512-token state): 16 questions peaked at 3.5 GiB and took 51 s,
# and 64 were OOM-killed. Ragweld sends 1-3 questions per call, so larger requests get a 413.
MAX_QUESTIONS_PER_REQUEST = 8

INFERENCE_SECONDS = Histogram(
    "laya_inference_seconds",
    "Forward-pass time of one /v1/systemone request, excluding the wait for the single inference worker.",
    ["checkpoint", "outcome"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0),
)
CHECKPOINT_RESIDENT = Gauge(
    "laya_checkpoint_resident",
    "1 while the checkpoint is loaded in memory.",
    ["checkpoint"],
)


def configured_checkpoint(environ: Mapping[str, str] = os.environ) -> str:
    raw = str(environ.get("LAYA_MODELS", ""))
    names = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if len(names) != 1 or names[0] not in CHECKPOINTS:
        raise SystemExit(
            f"LAYA_MODELS must name exactly one checkpoint ({', '.join(CHECKPOINTS)}); got {raw!r}"
        )
    return names[0]


class PinnedCheckpoint:
    """Router hook: every request runs on the one resident checkpoint."""

    def __init__(self, checkpoint: str) -> None:
        self.checkpoint = checkpoint

    def on_route(self, ctx: Any) -> None:
        from laya import RouteDecision

        decision = ctx.decision
        if decision["model"] == self.checkpoint:
            return
        reason = str(decision.get("reason") or "")
        if reason.startswith(("explicit model=", "explicit task=")):
            # A ValueError is laya-serve's 422 path: the caller learns what this server holds.
            raise ValueError(
                f"this Laya server serves only the {self.checkpoint!r} checkpoint; "
                f"the request asked for {decision['model']!r}"
            )
        repo, subfolder = ctx.router.models[self.checkpoint]
        ctx.decision = RouteDecision(
            model=self.checkpoint,
            repo=f"{repo}/{subfolder}" if subfolder else repo,
            reason=f"pinned to {self.checkpoint} (automatic routing chose {decision['model']}: {reason})",
            detection=decision.get("detection"),
            workflow=decision.get("workflow"),
        )

    def on_predict_end(self, ctx: Any) -> None:
        if ctx.elapsed_ms is None:
            return
        outcome = "error" if ctx.error is not None else "ok"
        INFERENCE_SECONDS.labels(checkpoint=ctx.model or self.checkpoint, outcome=outcome).observe(
            ctx.elapsed_ms / 1000.0
        )

    def on_load(self, ctx: Any) -> None:
        CHECKPOINT_RESIDENT.labels(checkpoint=ctx.model).set(1)

    def on_evict(self, ctx: Any) -> None:
        CHECKPOINT_RESIDENT.labels(checkpoint=ctx.model).set(0)


def _apply_thread_cap(environ: Mapping[str, str] = os.environ) -> None:
    raw = str(environ.get("LAYA_THREADS", "")).strip()
    if not raw:
        return
    try:
        threads = int(raw)
    except ValueError:
        raise SystemExit(f"LAYA_THREADS must be a positive integer; got {raw!r}") from None
    if threads < 1:
        raise SystemExit(f"LAYA_THREADS must be a positive integer; got {raw!r}")
    import torch

    torch.set_num_threads(threads)


def build_router(checkpoint: str, *, preload: bool = True) -> Any:
    from laya import Router

    _apply_thread_cap()
    router = Router(
        device=os.environ.get("LAYA_DEVICE") or None,
        max_loaded=1,
        default=checkpoint,
        hooks=[PinnedCheckpoint(checkpoint)],
    )
    if preload:
        router.preload([checkpoint])
    return router


def create_app(router: Any) -> Any:
    import laya.serve as laya_serve
    from fastapi import Response

    # Read per request by laya-serve's size guard (_check_request_limits).
    laya_serve.MAX_QUESTIONS = MAX_QUESTIONS_PER_REQUEST
    app = laya_serve.create_app(router=router)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


def main() -> None:
    import uvicorn

    checkpoint = configured_checkpoint()
    raw_port = os.environ.get("LAYA_PORT", "8000")
    try:
        port = int(raw_port)
    except ValueError:
        raise SystemExit(f"LAYA_PORT must be an integer; got {raw_port!r}") from None
    app = create_app(build_router(checkpoint))
    uvicorn.run(
        app,
        host=os.environ.get("LAYA_HOST", "0.0.0.0"),
        port=port,
        log_level=os.environ.get("LAYA_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
