from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from server.models.tribrid_config_model import (
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
from server.synthetic import orchestrator
from server.synthetic.publish import (
    publish_config_patch,
    publish_eval_dataset,
    publish_keywords,
    publish_semantic_cards,
    publish_triplets,
)
from server.synthetic.storage import events_path

router = APIRouter(tags=["synthetic"])


@router.post("/synthetic/run/start", response_model=SyntheticRun)
async def synthetic_run_start(request: SyntheticRunStartRequest) -> SyntheticRun:
    try:
        return await orchestrator.start_run(request)
    except RuntimeError as e:
        detail = str(e)
        if "already active" in detail:
            raise HTTPException(status_code=409, detail=detail) from e
        raise HTTPException(status_code=400, detail=detail) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/synthetic/runs", response_model=SyntheticRunsResponse)
async def synthetic_runs(
    corpus_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> SyntheticRunsResponse:
    runs = orchestrator.get_runs(corpus_id=corpus_id, limit=limit)
    return SyntheticRunsResponse(ok=True, runs=runs)


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


@router.post("/synthetic/run/{run_id}/publish/triplets", response_model=SyntheticPublishResponse)
async def synthetic_publish_triplets(run_id: str) -> SyntheticPublishResponse:
    try:
        run = orchestrator.get_run(run_id)
        return await publish_triplets(run)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
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
