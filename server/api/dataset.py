from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from starlette.responses import FileResponse

from server.models.eval import DatasetEntry
from server.models.tribrid_config_model import CorpusScope

router = APIRouter(tags=["dataset"])

_ROOT = Path(__file__).resolve().parents[2]
_DATASET_DIR = _ROOT / "data" / "eval_dataset"


def _dataset_path(repo_id: str) -> Path:
    _DATASET_DIR.mkdir(parents=True, exist_ok=True)
    safe = repo_id.strip()
    return _DATASET_DIR / f"{safe}.json"


def _load_dataset(repo_id: str) -> list[DatasetEntry]:
    path = _dataset_path(repo_id)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read dataset for repo_id={repo_id}: {e}") from e
    if not isinstance(raw, list):
        raise HTTPException(status_code=500, detail=f"Invalid dataset format for repo_id={repo_id} (expected list)")
    entries: list[DatasetEntry] = []
    for item in raw:
        try:
            entries.append(DatasetEntry.model_validate(item))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Invalid dataset entry in repo_id={repo_id}: {e}") from e
    return entries


def _save_dataset(repo_id: str, entries: list[DatasetEntry]) -> None:
    path = _dataset_path(repo_id)
    payload = [e.model_dump(mode="json") for e in entries]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _require_repo_id(scope: CorpusScope) -> str:
    repo_id = scope.resolved_repo_id
    if not repo_id:
        # 422 matches FastAPI's typical “missing required field” semantics
        raise HTTPException(status_code=422, detail="Missing corpus_id (or legacy repo_id)")
    return repo_id


@router.get("/dataset", response_model=list[DatasetEntry])
async def list_dataset(scope: CorpusScope = Depends()) -> list[DatasetEntry]:
    repo_id = _require_repo_id(scope)
    return _load_dataset(repo_id)


@router.post("/dataset", response_model=DatasetEntry)
async def add_dataset_entry(
    entry: DatasetEntry,
    scope: CorpusScope = Depends(),
) -> DatasetEntry:
    repo_id = _require_repo_id(scope)
    entries = _load_dataset(repo_id)
    if any(e.entry_id == entry.entry_id for e in entries):
        raise HTTPException(status_code=409, detail=f"entry_id={entry.entry_id} already exists")
    entries.append(entry)
    _save_dataset(repo_id, entries)
    return entry


@router.put("/dataset/{entry_id}", response_model=DatasetEntry)
async def update_dataset_entry(
    entry_id: str,
    entry: DatasetEntry,
    scope: CorpusScope = Depends(),
) -> DatasetEntry:
    repo_id = _require_repo_id(scope)
    entries = _load_dataset(repo_id)
    idx = next((i for i, e in enumerate(entries) if e.entry_id == entry_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"entry_id={entry_id} not found")

    # Preserve the original created_at for stability
    existing = entries[idx]
    updated = entry.model_copy(update={"entry_id": entry_id, "created_at": existing.created_at})
    entries[idx] = updated
    _save_dataset(repo_id, entries)
    return updated


@router.delete("/dataset/{entry_id}")
async def delete_dataset_entry(
    entry_id: str,
    scope: CorpusScope = Depends(),
) -> dict[str, Any]:
    repo_id = _require_repo_id(scope)
    entries = _load_dataset(repo_id)
    before = len(entries)
    entries = [e for e in entries if e.entry_id != entry_id]
    after = len(entries)
    if before == after:
        raise HTTPException(status_code=404, detail=f"entry_id={entry_id} not found")
    _save_dataset(repo_id, entries)
    return {"ok": True, "deleted": before - after}


@router.post("/dataset/import")
async def import_dataset(
    file: UploadFile,
    scope: CorpusScope = Depends(),
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

    _save_dataset(repo_id, entries)
    return entries


@router.get("/dataset/export")
async def export_dataset(scope: CorpusScope = Depends()) -> FileResponse:
    repo_id = _require_repo_id(scope)
    path = _dataset_path(repo_id)
    if not path.exists():
        _save_dataset(repo_id, [])
    return FileResponse(path)
