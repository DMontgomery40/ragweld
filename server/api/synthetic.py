from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from server.api.dependency_errors import (
    DEPENDENCY_UNAVAILABLE_RESPONSES,
    dependency_unavailable_http_exception,
    raise_postgres_unavailable_if_applicable,
)
from server.dependency_errors import DependencyUnavailableError
from server.lineage import list_aliases, set_alias
from server.models.tribrid_config_model import (
    LineageAliasesResponse,
    LineageAliasName,
    OkResponse,
    SyntheticArtifactKind,
    SyntheticArtifactPreviewResponse,
    SyntheticConfigPatchResponse,
    SyntheticPublishResponse,
    SyntheticRun,
    SyntheticRunEvent,
    SyntheticRunsResponse,
    SyntheticRunStartRequest,
)
from server.services.config_store import CorpusNotFoundError
from server.synthetic import orchestrator
from server.synthetic.publish import (
    PublishRollbackError,
    PublishRolledBackError,
    publish_config_patch,
    publish_eval_dataset,
    publish_keywords,
    publish_semantic_cards,
    publish_triplets,
)
from server.synthetic.storage import events_path
from server.training.triplet_rows import TripletRowsCorruptError

router = APIRouter(tags=["synthetic"])


def _promotion_block_reason(run: SyntheticRun) -> str | None:
    """Why this run may not be promoted, or None when it may.

    Mirrors the publish gate (``publish_eval_dataset`` -> ``QUALITY_GATE_FAILED``): a run is
    promotable only when it completed. A gated recipe that fails its quality gate is already
    marked ``status="failed"`` upstream, so a completed run carries ``quality_gate_passed`` of
    True (gated, passed) or None (a recipe that has no gate, e.g. semantic_cards/keywords) —
    both promotable. The explicit ``is False`` branch is defense in depth for a hand-written or
    legacy run.json, and a run never attached to a lineage bundle has nothing to point at.
    """
    if run.status != "completed":
        return (
            f"This run is {run.status}; only a completed run can be promoted. "
            "A run that produced nothing and was never evaluated cannot be an alias target."
        )
    if run.summary.quality_gate_passed is False:
        reason = str(run.summary.quality_failure_reason or "").strip()
        return ("Quality gate did not pass; promotion blocked. " + reason).strip()
    if not str(run.bundle_id or "").strip():
        return "This run is not attached to a lineage bundle, so there is nothing to promote."
    return None


@router.post("/synthetic/run/start", response_model=SyntheticRun, responses=DEPENDENCY_UNAVAILABLE_RESPONSES)
async def synthetic_run_start(request: SyntheticRunStartRequest) -> SyntheticRun:
    try:
        return await orchestrator.start_run(request)
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        detail = str(e)
        if "already active" in detail:
            raise HTTPException(status_code=409, detail=detail) from e
        raise HTTPException(status_code=400, detail=detail) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise_postgres_unavailable_if_applicable(e, boundary="Synthetic run start")
        raise


@router.get("/synthetic/runs", response_model=SyntheticRunsResponse)
async def synthetic_runs(
    corpus_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> SyntheticRunsResponse:
    runs, unreadable = await asyncio.to_thread(orchestrator.get_runs, corpus_id=corpus_id, limit=limit)
    return SyntheticRunsResponse(ok=True, runs=runs, unreadable=unreadable)


@router.get("/synthetic/run/stream")
async def synthetic_run_stream(
    request: Request,
    run_id: str = Query(..., description="Synthetic run identifier"),
) -> StreamingResponse:
    try:
        orchestrator.get_run(run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    path = events_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")

    async def _gen() -> AsyncIterator[str]:
        try:
            lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except Exception:
            lines = []
        for line in lines[-200:]:
            yield f"data: {line}\n\n"

        offset = 0
        try:
            offset = path.stat().st_size
        except Exception:
            offset = 0
        buf = b""

        def _read_new_lines() -> list[str]:
            nonlocal offset, buf
            out: list[str] = []
            try:
                size = path.stat().st_size
            except Exception:
                size = offset

            if size < offset:
                offset = 0
                buf = b""

            if size > offset:
                try:
                    with path.open("rb") as f:
                        f.seek(offset)
                        data = f.read(size - offset)
                    offset = size
                    buf += data
                    while True:
                        idx = buf.find(b"\n")
                        if idx < 0:
                            break
                        line = buf[:idx].decode("utf-8", errors="ignore").strip()
                        buf = buf[idx + 1 :]
                        if line:
                            out.append(line)
                except Exception:
                    return out
            return out

        while True:
            if await request.is_disconnected():
                return

            for line in _read_new_lines():
                yield f"data: {line}\n\n"

            try:
                run = orchestrator.get_run(run_id)
            except FileNotFoundError:
                run = None
            if run is not None and run.status in {"completed", "failed", "cancelled"}:
                # Flush a bounded tail window to catch late writes that can
                # arrive just after run status flips to terminal.
                loop = asyncio.get_running_loop()
                deadline = loop.time() + 1.0
                quiet_for = 0.0
                while loop.time() < deadline and quiet_for < 0.2:
                    emitted = False
                    for line in _read_new_lines():
                        emitted = True
                        yield f"data: {line}\n\n"
                    await asyncio.sleep(0.05)
                    if emitted:
                        quiet_for = 0.0
                    else:
                        quiet_for += 0.05
                tail = buf.decode("utf-8", errors="ignore").strip()
                if tail:
                    buf = b""
                    yield f"data: {tail}\n\n"
                complete_event = SyntheticRunEvent(
                    type="complete",
                    ts=datetime.now(UTC),
                    run_id=run_id,
                    status=run.status,
                )
                yield f"data: {json.dumps(complete_event.model_dump(mode='json', by_alias=True))}\n\n"
                return

            await asyncio.sleep(0.5)

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.get("/synthetic/run/{run_id}", response_model=SyntheticRun)
async def synthetic_run_get(run_id: str) -> SyntheticRun:
    try:
        return orchestrator.get_run(run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/synthetic/run/{run_id}/artifact/preview", response_model=SyntheticArtifactPreviewResponse)
async def synthetic_artifact_preview(
    run_id: str,
    kind: SyntheticArtifactKind,
    limit: int = Query(default=5, ge=1, le=200),
) -> SyntheticArtifactPreviewResponse:
    try:
        run = orchestrator.get_run(run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    artifact_path = None
    for ref in run.artifacts:
        if ref.kind == kind:
            artifact_path = ref.path
            break
    if not artifact_path:
        raise HTTPException(status_code=404, detail=f"Artifact not found for kind={kind}")

    path = Path(artifact_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact file missing: {artifact_path}")

    rows: list[dict[str, object]] = []
    if kind in {"triplets_jsonl", "semantic_cards_jsonl"}:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        for ln in lines[:limit]:
            try:
                obj = json.loads(ln)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append({str(k): v for k, v in obj.items()})
    else:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = None
        if isinstance(payload, list):
            for item in payload[:limit]:
                if isinstance(item, dict):
                    rows.append({str(k): v for k, v in item.items()})
                else:
                    rows.append({"value": item})
        elif isinstance(payload, dict):
            rows.append({str(k): v for k, v in payload.items()})
        elif payload is not None:
            rows.append({"value": payload})

    return SyntheticArtifactPreviewResponse(ok=True, run_id=run_id, kind=kind, rows=rows)


@router.post("/synthetic/run/{run_id}/cancel", response_model=OkResponse)
async def synthetic_run_cancel(run_id: str) -> OkResponse:
    try:
        ok = await orchestrator.cancel_run(run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return OkResponse(ok=bool(ok))


@router.post("/synthetic/run/{run_id}/promote/{alias}", response_model=LineageAliasesResponse)
async def synthetic_run_promote(run_id: str, alias: LineageAliasName) -> LineageAliasesResponse:
    """Point a lineage alias (baseline/canary/current/promoted) at this run's bundle.

    Refused with 409 unless the run completed and passed its quality gate — a failed or
    un-evaluated run produced nothing worth promoting. 404 when the run or its bundle is gone,
    503 when the lineage store is unavailable. This is the gated path the Synthetic Lab uses;
    the generic /lineage/aliases/{alias} endpoint stays available for other bundle sources.
    """
    try:
        run = orchestrator.get_run(run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    reason = _promotion_block_reason(run)
    if reason is not None:
        raise HTTPException(status_code=409, detail=f"PROMOTION_BLOCKED: {reason}")

    repo_id = str(run.repo_id)
    bundle_id = str(run.bundle_id or "").strip()
    try:
        set_alias(repo_id=repo_id, alias=alias, bundle_id=bundle_id)
        return LineageAliasesResponse(ok=True, aliases=list_aliases(repo_id=repo_id))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except DependencyUnavailableError as e:
        if e.dependency == "lineage_store":
            raise dependency_unavailable_http_exception(
                "lineage_store", boundary="Synthetic run promote", exc=e
            ) from e
        raise


@router.post("/synthetic/run/{run_id}/publish/eval_dataset", response_model=SyntheticPublishResponse)
async def synthetic_publish_eval_dataset(run_id: str) -> SyntheticPublishResponse:
    try:
        run = orchestrator.get_run(run_id)
        return await publish_eval_dataset(run)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        if "QUALITY_GATE_FAILED" in str(e):
            raise HTTPException(status_code=409, detail=str(e)) from e
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/synthetic/run/{run_id}/publish/semantic_cards", response_model=SyntheticPublishResponse)
async def synthetic_publish_semantic_cards(run_id: str) -> SyntheticPublishResponse:
    try:
        run = orchestrator.get_run(run_id)
        return await publish_semantic_cards(run)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/synthetic/run/{run_id}/publish/keywords", response_model=SyntheticPublishResponse)
async def synthetic_publish_keywords(run_id: str) -> SyntheticPublishResponse:
    try:
        run = orchestrator.get_run(run_id)
        return await publish_keywords(run)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/synthetic/run/{run_id}/publish/triplets", response_model=SyntheticPublishResponse, responses=DEPENDENCY_UNAVAILABLE_RESPONSES)
async def synthetic_publish_triplets(run_id: str) -> SyntheticPublishResponse:
    """Publish a run's triplets artifact. Status codes say what happened to the live file:
    400 = refused before any change (empty artifact, gate), 409 = corrupt artifact / gate failure,
    503 = the lineage store was unavailable and the previous file was put back, 500 = a
    filesystem failure (body states whether the previous file was restored)."""
    try:
        run = orchestrator.get_run(run_id)
        return await publish_triplets(run)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except TripletRowsCorruptError as e:
        raise HTTPException(status_code=409, detail=f"TRIPLETS_ARTIFACT_CORRUPT: {e}") from e
    except PublishRollbackError as e:
        raise HTTPException(status_code=500, detail=f"PUBLISH_ROLLBACK_FAILED: {e}") from e
    except PublishRolledBackError as e:
        cause = e.__cause__
        if isinstance(cause, DependencyUnavailableError):
            raise dependency_unavailable_http_exception(cause.dependency, boundary="Synthetic triplets publish", exc=cause) from e
        raise HTTPException(status_code=500, detail=f"PUBLISH_ROLLED_BACK: the previous triplets file was put back; {e}") from e
    except Exception as e:
        if "QUALITY_GATE_FAILED" in str(e):
            raise HTTPException(status_code=409, detail=str(e)) from e
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/synthetic/run/{run_id}/publish/config_patch", response_model=SyntheticConfigPatchResponse)
async def synthetic_publish_config_patch(run_id: str) -> SyntheticConfigPatchResponse:
    try:
        run = orchestrator.get_run(run_id)
        return await publish_config_patch(run)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
