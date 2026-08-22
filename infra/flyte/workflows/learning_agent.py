"""Flyte workflow for Ragweld Learning Agent runs.

This module is registered into the Compose-owned Flyte control plane by
``scripts/flyte_register_learning_agent.sh``. The host API launches the
``learning-agent-train`` launch plan for every run that selects
``training.ragweld_agent_workflow_backend=flyte``; Flyte then owns the
execution lifecycle (QUEUED/RUNNING/SUCCEEDED/FAILED/ABORTED).

The training itself cannot run inside the Flyte pod: the ``mlx_qwen3``
execution backend only exists on the Apple Silicon host. The task therefore
hands the run to the host API's execute boundary and tracks it to a terminal
state, so the Flyte execution phase is the workflow truth while the host run
record stays the training truth. Nothing here fakes a result: a failed or
cancelled host run fails the Flyte execution with the exact reason.

Only the standard library is used at task time so the stock flytekit image
can execute it without a custom build.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from flytekit import LaunchPlan, current_context, task, workflow

LAUNCH_PLAN_NAME = "learning-agent-train"
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_POLL_INTERVAL_SECONDS = 5.0
_MAX_CONSECUTIVE_POLL_FAILURES = 12


def _request(method: str, url: str, payload: dict | None = None, *, timeout: float = 30.0) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


@task(retries=0)
def execute_learning_agent_run(
    run_id: str,
    corpus_id: str,
    callback_base_url: str,
    execution_backend: str,
) -> str:
    """Drive one host-side Learning Agent run to completion.

    Returns a JSON summary string on success; raises on any non-completed
    terminal status so the Flyte execution fails honestly.
    """

    base = str(callback_base_url or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("callback_base_url is empty; the Flyte task cannot reach the Ragweld API.")
    execution_name = current_context().execution_id.name
    print(
        f"[ragweld] execution={execution_name} run_id={run_id} corpus_id={corpus_id} "
        f"execution_backend={execution_backend} callback={base}"
    )

    try:
        started = _request(
            "POST",
            f"{base}/api/agent/train/run/{run_id}/execute",
            {"workflow_run_id": execution_name},
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Ragweld refused to execute run {run_id} (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ragweld API unreachable at {base} from the Flyte task: {exc.reason}") from exc
    print(f"[ragweld] execute accepted: {json.dumps(started)}")

    status = ""
    run: dict = {}
    failures = 0
    while True:
        try:
            run = _request("GET", f"{base}/api/agent/train/run/{run_id}")
            failures = 0
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failures += 1
            if failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise RuntimeError(
                    f"Lost contact with the Ragweld API while tracking run {run_id}: {exc}"
                ) from exc
            time.sleep(_POLL_INTERVAL_SECONDS)
            continue
        status = str(run.get("status") or "")
        if status in _TERMINAL_STATUSES:
            break
        time.sleep(_POLL_INTERVAL_SECONDS)

    summary = run.get("summary") or {}
    if status != "completed":
        raise RuntimeError(f"Learning Agent run {run_id} ended with status={status}")
    return json.dumps(
        {
            "run_id": run_id,
            "corpus_id": corpus_id,
            "status": status,
            "execution_backend": str(run.get("execution_backend") or execution_backend),
            "primary_metric": run.get("primary_metric"),
            "primary_metric_best": summary.get("primary_metric_best"),
            "primary_metric_final": summary.get("primary_metric_final"),
            "tracking_run_id": run.get("tracking_run_id"),
        },
        sort_keys=True,
    )


@workflow
def learning_agent_train(
    run_id: str,
    corpus_id: str,
    callback_base_url: str,
    execution_backend: str,
) -> str:
    return execute_learning_agent_run(
        run_id=run_id,
        corpus_id=corpus_id,
        callback_base_url=callback_base_url,
        execution_backend=execution_backend,
    )


learning_agent_train_lp = LaunchPlan.get_or_create(
    workflow=learning_agent_train,
    name=LAUNCH_PLAN_NAME,
)
