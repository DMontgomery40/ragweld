from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from server.config import load_config

router = APIRouter(tags=["reranker"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_path(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for _ in f)


@router.get("/reranker/status")
async def get_reranker_status() -> dict[str, Any]:
    # Minimal status shape expected by the UI polling loop.
    return {
        "running": False,
        "progress": 0,
        "task": "",
        "message": "",
        "result": None,
        "live_output": [],
    }


@router.get("/reranker/info")
async def get_reranker_info() -> dict[str, Any]:
    """Return current reranker runtime/config info (no secrets)."""
    cfg = load_config()
    mode = (cfg.reranking.reranker_mode or "none").lower()
    enabled = mode != "none"

    if mode == "learning":
        path = cfg.training.tribrid_reranker_model_path
    elif mode == "local":
        path = cfg.reranking.reranker_local_model
    elif mode == "cloud":
        path = cfg.reranking.reranker_cloud_model
    else:
        path = ""

    return {
        "enabled": enabled,
        "reranker_mode": mode,
        "reranker_cloud_provider": cfg.reranking.reranker_cloud_provider,
        "reranker_cloud_model": cfg.reranking.reranker_cloud_model,
        "reranker_local_model": cfg.reranking.reranker_local_model,
        "path": path,
        "resolved_path": path,
        "device": "cpu",
        "alpha": cfg.reranking.tribrid_reranker_alpha,
        "topn": cfg.reranking.tribrid_reranker_topn,
        "batch": cfg.reranking.tribrid_reranker_batch,
        "maxlen": cfg.reranking.tribrid_reranker_maxlen,
        "snippet_chars": cfg.reranking.rerank_input_snippet_chars,
        "trust_remote_code": bool(cfg.reranking.transformers_trust_remote_code),
    }


@router.post("/reranker/mine")
async def mine_triplets() -> dict[str, Any]:
    """Mine triplets from logs (minimal file-backed implementation)."""
    cfg = load_config()
    log_path = _resolve_path(cfg.tracing.tribrid_log_path)
    triplets_path = _resolve_path(cfg.training.tribrid_triplets_path)
    triplets_path.parent.mkdir(parents=True, exist_ok=True)

    created = 0
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
        for i, line in enumerate([ln for ln in lines if ln.strip()][:10]):
            try:
                query = json.loads(line).get("query")
            except Exception:
                query = None
            item = {
                "query": query or f"query_{i}",
                "positive": "positive_placeholder",
                "negative": "negative_placeholder",
            }
            with triplets_path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(item) + "\n")
            created += 1

    return {
        "ok": True,
        "output": f"Mined {created} triplets into {cfg.training.tribrid_triplets_path}",
    }


@router.post("/reranker/train")
async def train_reranker(options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Train the learning reranker (minimal stub)."""
    cfg = load_config()
    options = options or {}
    epochs = options.get("epochs", cfg.training.reranker_train_epochs)
    batch_size = options.get("batch_size", cfg.training.reranker_train_batch)
    max_length = options.get("max_length", cfg.reranking.tribrid_reranker_maxlen)
    return {
        "ok": True,
        "output": (
            "Training started (stub).\n"
            f"model_path={cfg.training.tribrid_reranker_model_path}\n"
            f"epochs={epochs} batch_size={batch_size} max_length={max_length}\n"
        ),
    }


@router.post("/reranker/evaluate")
async def evaluate_reranker() -> dict[str, Any]:
    """Evaluate the learning reranker (minimal stub)."""
    return {
        "ok": True,
        "output": "MRR: 0.00\nHit@1: 0.00\nHit@3: 0.00\nHit@5: 0.00\n",
    }


@router.get("/reranker/logs/count")
async def get_logs_count() -> dict[str, Any]:
    cfg = load_config()
    log_path = _resolve_path(cfg.tracing.tribrid_log_path)
    return {"count": _count_lines(log_path)}


@router.get("/reranker/triplets/count")
async def get_triplets_count() -> dict[str, Any]:
    cfg = load_config()
    triplets_path = _resolve_path(cfg.training.tribrid_triplets_path)
    return {"count": _count_lines(triplets_path)}


@router.get("/reranker/costs")
async def get_costs() -> dict[str, Any]:
    # Placeholder until cost accounting is implemented.
    return {"total_24h": 0.0, "avg_per_query": 0.0}


@router.get("/reranker/nohits")
async def get_nohits() -> dict[str, Any]:
    # Placeholder until we log no-hit events explicitly.
    return {"queries": []}


@router.get("/reranker/logs")
async def get_logs(limit: int = 200) -> dict[str, Any]:
    cfg = load_config()
    log_path = _resolve_path(cfg.tracing.tribrid_log_path)
    if not log_path.exists():
        return {"logs": []}
    try:
        lines = [line.strip() for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        lines = []
    tail = lines[-limit:]
    parsed: list[Any] = []
    for line in tail:
        try:
            parsed.append(json.loads(line))
        except Exception:
            parsed.append({"raw": line})
    return {"logs": parsed}


@router.get("/reranker/logs/download")
async def download_logs() -> FileResponse:
    cfg = load_config()
    log_path = _resolve_path(cfg.tracing.tribrid_log_path)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="No logs file found")
    return FileResponse(
        str(log_path),
        media_type="application/jsonl",
        filename=log_path.name,
    )


@router.post("/reranker/logs/clear")
async def clear_logs() -> dict[str, Any]:
    cfg = load_config()
    log_path = _resolve_path(cfg.tracing.tribrid_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
    return {"ok": True}


@router.get("/reranker/triplets/{repo_id}", response_model=list[dict[str, Any]])
async def get_triplets(repo_id: str, limit: int = 100) -> list[dict[str, Any]]:
    raise HTTPException(status_code=501, detail="Triplets endpoint not implemented yet")


@router.post("/reranker/triplets/{repo_id}")
async def add_triplet(repo_id: str, query: str, positive: str, negative: str) -> dict[str, Any]:
    raise HTTPException(status_code=501, detail="Triplets endpoint not implemented yet")


@router.post("/reranker/promote")
async def promote_model(model_path: str) -> dict[str, Any]:
    raise HTTPException(status_code=501, detail="Promote endpoint not implemented yet")
