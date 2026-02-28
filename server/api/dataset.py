from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from starlette.responses import FileResponse

from server.models.eval import DatasetEntry
from server.models.tribrid_config_model import CorpusScope

router = APIRouter(tags=["dataset"])

# Ruff B008: avoid function calls in argument defaults (FastAPI Depends()).
_CORPUS_SCOPE_DEP = Depends()

_ROOT = Path(__file__).resolve().parents[2]
_DATASET_DIR = _ROOT / "data" / "eval_datasets"
_LEGACY_DATASET_DIR = _ROOT / "data" / "eval_dataset"


def _safe_corpus_id(corpus_id: str) -> str:
    raw = str(corpus_id or "").strip()
    if not raw:
        raise HTTPException(status_code=422, detail="Missing corpus_id (or legacy repo_id)")
    # Percent-encoding is injective for corpus IDs, so distinct IDs map to
    # distinct filenames (unlike regex replacement).
    safe = quote(raw, safe="._-")
    if not safe:
        raise HTTPException(status_code=422, detail=f"Invalid corpus_id: {raw!r}")
    return safe


def _legacy_safe_corpus_id(corpus_id: str) -> str:
    raw = str(corpus_id or "").strip()
    if not raw:
        raise HTTPException(status_code=422, detail="Missing corpus_id (or legacy repo_id)")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    if not safe:
        raise HTTPException(status_code=422, detail=f"Invalid corpus_id: {raw!r}")
    return safe


def _dataset_dir() -> Path:
    _DATASET_DIR.mkdir(parents=True, exist_ok=True)
    return _DATASET_DIR


def _dataset_path_for_corpus(corpus_id: str) -> Path:
    return _dataset_dir() / f"{_safe_corpus_id(corpus_id)}.json"


def _legacy_dataset_path_for_corpus(corpus_id: str) -> Path:
    safe = _legacy_safe_corpus_id(corpus_id)
    canonical_default = _ROOT / "data" / "eval_datasets"
    if _DATASET_DIR != canonical_default:
        return (_DATASET_DIR.parent / "eval_dataset") / f"{safe}.json"
    return _LEGACY_DATASET_DIR / f"{safe}.json"


def _resolve_corpus_id(*, corpus_id: str | None = None, repo_id: str | None = None) -> str:
    resolved = str(corpus_id or repo_id or "").strip()
    if not resolved:
        raise HTTPException(status_code=422, detail="Missing corpus_id (or legacy repo_id)")
    return resolved


def _dataset_path(repo_id: str) -> Path:
    # Backward-compatible helper kept for older imports/tests.
    return _dataset_path_for_corpus(repo_id)


def _load_dataset(corpus_id: str | None = None, repo_id: str | None = None) -> list[DatasetEntry]:
    resolved_corpus_id = _resolve_corpus_id(corpus_id=corpus_id, repo_id=repo_id)
    path = _dataset_path_for_corpus(resolved_corpus_id)
    if not path.exists():
        legacy = _legacy_dataset_path_for_corpus(resolved_corpus_id)
        if legacy.exists():
            try:
                raw_legacy = legacy.read_text(encoding="utf-8")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(raw_legacy, encoding="utf-8")
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to migrate legacy dataset for corpus_id={resolved_corpus_id}: {e}",
                ) from e
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read dataset for corpus_id={resolved_corpus_id}: {e}") from e
    if not isinstance(raw, list):
        raise HTTPException(
            status_code=500,
            detail=f"Invalid dataset format for corpus_id={resolved_corpus_id} (expected list)",
        )
    entries: list[DatasetEntry] = []
    for item in raw:
        try:
            entries.append(DatasetEntry.model_validate(item))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Invalid dataset entry in corpus_id={resolved_corpus_id}: {e}",
            ) from e
    return entries


def _save_dataset(entries: list[DatasetEntry], corpus_id: str | None = None, repo_id: str | None = None) -> None:
    resolved_corpus_id = _resolve_corpus_id(corpus_id=corpus_id, repo_id=repo_id)
    path = _dataset_path_for_corpus(resolved_corpus_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [e.model_dump(mode="json") for e in entries]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _require_repo_id(scope: CorpusScope) -> str:
    repo_id = scope.resolved_repo_id
    if not repo_id:
        # 422 matches FastAPI's typical “missing required field” semantics
        raise HTTPException(status_code=422, detail="Missing corpus_id (or legacy repo_id)")
    return repo_id


@router.get("/dataset", response_model=list[DatasetEntry])
async def list_dataset(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> list[DatasetEntry]:
    repo_id = _require_repo_id(scope)
    return _load_dataset(corpus_id=repo_id)


@router.post("/dataset", response_model=DatasetEntry)
async def add_dataset_entry(
    entry: DatasetEntry,
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> DatasetEntry:
    repo_id = _require_repo_id(scope)
    entries = _load_dataset(corpus_id=repo_id)
    if any(e.entry_id == entry.entry_id for e in entries):
        raise HTTPException(status_code=409, detail=f"entry_id={entry.entry_id} already exists")
    entries.append(entry)
    _save_dataset(entries, corpus_id=repo_id)
    return entry


@router.put("/dataset/{entry_id}", response_model=DatasetEntry)
async def update_dataset_entry(
    entry_id: str,
    entry: DatasetEntry,
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> DatasetEntry:
    repo_id = _require_repo_id(scope)
    entries = _load_dataset(corpus_id=repo_id)
    idx = next((i for i, e in enumerate(entries) if e.entry_id == entry_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"entry_id={entry_id} not found")

    # Preserve the original created_at for stability
    existing = entries[idx]
    updated = entry.model_copy(update={"entry_id": entry_id, "created_at": existing.created_at})
    entries[idx] = updated
    _save_dataset(entries, corpus_id=repo_id)
    return updated


@router.delete("/dataset/{entry_id}")
async def delete_dataset_entry(
    entry_id: str,
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> dict[str, Any]:
    repo_id = _require_repo_id(scope)
    entries = _load_dataset(corpus_id=repo_id)
    before = len(entries)
    entries = [e for e in entries if e.entry_id != entry_id]
    after = len(entries)
    if before == after:
        raise HTTPException(status_code=404, detail=f"entry_id={entry_id} not found")
    _save_dataset(entries, corpus_id=repo_id)
    return {"ok": True, "deleted": before - after}


@router.post("/dataset/import")
async def import_dataset(
    file: UploadFile,
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> list[DatasetEntry]:
    repo_id = _require_repo_id(scope)
    raw_bytes = await file.read()
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="Expected a JSON array of dataset entries")

    entries: list[DatasetEntry] = []
    for item in raw:
        entries.append(DatasetEntry.model_validate(item))

    _save_dataset(entries, corpus_id=repo_id)
    return entries


@router.get("/dataset/export")
async def export_dataset(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> FileResponse:
    repo_id = _require_repo_id(scope)
    path = _dataset_path_for_corpus(repo_id)
    if not path.exists():
        _save_dataset([], corpus_id=repo_id)
    return FileResponse(path)
