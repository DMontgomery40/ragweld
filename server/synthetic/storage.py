from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.models.tribrid_config_model import (
    SyntheticArtifactKind,
    SyntheticArtifactRef,
    SyntheticRun,
    SyntheticRunEvent,
    SyntheticRunMeta,
    SyntheticUnreadableRun,
)

_ROOT = Path(__file__).resolve().parents[2]
_RUNS_DIR = _ROOT / "data" / "synthetic_runs"

# Isolation seam, same contract as RAGWELD_LINEAGE_ROOT: a process that must not
# write into the live synthetic-run store (pytest, disposable integration lanes)
# points this at its own directory. Relative values resolve from the repo root.


def runs_dir() -> Path:
    raw = str(os.environ.get("RAGWELD_SYNTHETIC_RUNS_ROOT") or "").strip()
    base = _RUNS_DIR
    if raw:
        candidate = Path(raw).expanduser()
        base = candidate if candidate.is_absolute() else (_ROOT / candidate)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _normalized_run_id(run_id: str) -> str:
    rid = str(run_id or "").strip()
    if not rid:
        raise ValueError("run_id is required")
    if "/" in rid or "\\" in rid:
        raise ValueError(f"Invalid run_id: {run_id!r}")
    candidate = Path(rid)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError(f"Invalid run_id: {run_id!r}")
    return rid


def run_dir(run_id: str) -> Path:
    base = runs_dir().resolve()
    path = (base / _normalized_run_id(run_id)).resolve()
    try:
        path.relative_to(base)
    except ValueError as e:
        raise ValueError(f"Invalid run_id: {run_id!r}") from e
    return path


def run_json_path(run_id: str) -> Path:
    return run_dir(run_id) / "run.json"


def events_path(run_id: str) -> Path:
    return run_dir(run_id) / "events.jsonl"


def artifacts_dir(run_id: str) -> Path:
    d = run_dir(run_id) / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def artifact_filename(kind: SyntheticArtifactKind) -> str:
    mapping: dict[SyntheticArtifactKind, str] = {
        "eval_dataset_json": "eval_dataset.json",
        "semantic_cards_jsonl": "semantic_cards.jsonl",
        "keywords_json": "keywords.json",
        "triplets_jsonl": "triplets.jsonl",
        "config_patch_json": "config_patch.json",
        "quality_eval_json": "quality_eval.json",
        "report_md": "report.md",
    }
    return mapping[kind]


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json", by_alias=True)
        except Exception:
            return value.model_dump()
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    return value


def save_run(run: SyntheticRun) -> None:
    path = run_json_path(run.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = run.model_dump(mode="json", by_alias=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load_run(run_id: str) -> SyntheticRun:
    path = run_json_path(run_id)
    if not path.exists():
        raise FileNotFoundError(f"run_id={run_id} not found")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SyntheticRun.model_validate(raw)


def append_event(run_id: str, event: SyntheticRunEvent) -> None:
    path = events_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = event.model_dump(mode="json", by_alias=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def list_runs(
    *, corpus_id: str | None = None, limit: int = 50
) -> tuple[list[SyntheticRunMeta], list[SyntheticUnreadableRun]]:
    """Newest runs first, plus every run directory that could not be loaded.

    An unreadable run.json (corrupt, or written by a provider that no longer exists)
    is reported, not skipped: the operator must see that history is missing rather
    than believe the corpus never had runs. When the raw payload still names a corpus
    the entry is attributed to it (and filtered like a readable run); an entry whose
    corpus cannot be read at all is returned under every corpus filter.
    """
    out: list[SyntheticRunMeta] = []
    unreadable: list[SyntheticUnreadableRun] = []
    for d in sorted(runs_dir().iterdir(), key=lambda p: p.name, reverse=True):
        if not d.is_dir():
            continue
        p = d / "run.json"
        if not p.exists():
            # A crash between directory creation and run.json commit leaves an orphan; say so.
            unreadable.append(SyntheticUnreadableRun(run_id=d.name, reason="run.json is missing", corpus_id=None))
            continue
        raw: Any = None
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            run = SyntheticRun.model_validate(raw)
        except Exception as exc:
            claimed = _claimed_corpus(raw)
            if corpus_id and claimed and claimed != str(corpus_id):
                continue
            unreadable.append(SyntheticUnreadableRun(run_id=d.name, reason=_short_reason(exc), corpus_id=claimed))
            continue
        if corpus_id and str(run.repo_id) != str(corpus_id):
            continue
        if len(out) >= max(1, int(limit)):
            continue
        out.append(
            SyntheticRunMeta(
                run_id=run.run_id,
                repo_id=run.repo_id,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                recipe=run.recipe,
                provider=run.provider,
                items_generated=run.summary.items_generated,
                bundle_id=run.bundle_id,
                lineage_ref=run.lineage_ref,
            )
        )
    return out, unreadable


def _claimed_corpus(raw: Any) -> str | None:
    """The corpus a malformed run.json still names, when its payload is at least a JSON object."""
    if not isinstance(raw, dict):
        return None
    for key in ("corpus_id", "repo_id"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _short_reason(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return text if len(text) <= 240 else text[:237] + "..."


def allocate_run_id(repo_id: str, started_at: datetime) -> str:
    base = f"{repo_id}__{started_at.strftime('%Y%m%d_%H%M%S')}"
    run_id = base
    n = 0
    while run_dir(run_id).exists():
        n += 1
        run_id = f"{base}__{n}"
    return run_id


def active_run_id_for_corpus(corpus_id: str) -> str | None:
    cid = str(corpus_id or "").strip()
    if not cid:
        return None
    prefix = f"{cid}__"
    for d in sorted(runs_dir().iterdir(), key=lambda p: p.name, reverse=True):
        if not d.is_dir() or not d.name.startswith(prefix):
            continue
        p = d / "run.json"
        if not p.exists():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            run = SyntheticRun.model_validate(raw)
        except Exception:
            continue
        if str(run.status) in {"queued", "running"}:
            return run.run_id
    return None


def write_artifact(run_id: str, kind: SyntheticArtifactKind, payload: Any) -> SyntheticArtifactRef:
    path = artifacts_dir(run_id) / artifact_filename(kind)
    if kind in {"semantic_cards_jsonl", "triplets_jsonl"}:
        rows = payload if isinstance(payload, list) else []
        lines = [json.dumps(_to_jsonable(row), ensure_ascii=False) for row in rows]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    elif kind in {"eval_dataset_json", "keywords_json", "config_patch_json", "quality_eval_json"}:
        path.write_text(
            json.dumps(_to_jsonable(payload), indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
    elif kind == "report_md":
        path.write_text(str(payload or ""), encoding="utf-8")
    else:
        raise ValueError(f"Unsupported artifact kind: {kind}")

    ts = datetime.now(UTC)
    return SyntheticArtifactRef(
        kind=kind,
        path=str(path),
        bytes=int(path.stat().st_size if path.exists() else 0),
        created_at=ts,
    )
