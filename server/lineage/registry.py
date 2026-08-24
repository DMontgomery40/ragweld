from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from pydantic import ValidationError

from server.dependency_errors import DependencyUnavailableError
from server.models.tribrid_config_model import (
    BenchmarkRun,
    GitSnapshot,
    GitTrackedFile,
    LineageAlias,
    LineageAliasName,
    LineageAssetKind,
    LineageAssetVersion,
    LineageBundle,
    LineageRef,
    TriBridConfig,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    return _REPO_ROOT


def resolve_project_path(path_str: str) -> Path:
    p = Path(str(path_str or "")).expanduser()
    if not p.is_absolute():
        p = repo_root() / p
    return p


def _raise_lineage_store_error(operation: str, exc: BaseException) -> None:
    raise DependencyUnavailableError("lineage_store", operation) from exc


def _validate_lineage_model(model: Any, payload: dict[str, Any], *, operation: str) -> Any:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        _raise_lineage_store_error(operation, exc)


def lineage_root(root: Path | None = None) -> Path:
    if root is not None:
        base = Path(root)
    else:
        raw = str(os.environ.get("RAGWELD_LINEAGE_ROOT") or "").strip()
        base = resolve_project_path(raw) if raw else (repo_root() / "data" / "lineage")
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _raise_lineage_store_error("Lineage root initialization", exc)
    return base


def _safe_repo_id(repo_id: str) -> str:
    return quote(str(repo_id or "").strip(), safe="._-")


def _assets_dir(kind: LineageAssetKind, *, root: Path | None = None) -> Path:
    d = lineage_root(root) / "assets" / str(kind)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _raise_lineage_store_error("Lineage asset directory access", exc)
    return d


def _asset_path(kind: LineageAssetKind, version_id: str, *, root: Path | None = None) -> Path:
    return _assets_dir(kind, root=root) / f"{version_id}.json"


def _bundles_dir(repo_id: str, *, root: Path | None = None) -> Path:
    d = lineage_root(root) / "bundles" / _safe_repo_id(repo_id)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _raise_lineage_store_error("Lineage bundle directory access", exc)
    return d


def _bundle_path(repo_id: str, bundle_id: str, *, root: Path | None = None) -> Path:
    return _bundles_dir(repo_id, root=root) / f"{bundle_id}.json"


def _aliases_dir(repo_id: str, *, root: Path | None = None) -> Path:
    d = lineage_root(root) / "aliases" / _safe_repo_id(repo_id)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _raise_lineage_store_error("Lineage alias directory access", exc)
    return d


def _alias_path(repo_id: str, alias: LineageAliasName, *, root: Path | None = None) -> Path:
    return _aliases_dir(repo_id, root=root) / f"{alias}.json"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json", by_alias=True)
        except Exception:
            return value.model_dump()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _atomic_write_json(path: Path, payload: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError as exc:
        _raise_lineage_store_error("Lineage store write", exc)


def _read_json_object(path: Path, *, operation: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _raise_lineage_store_error(operation, exc)
    if not isinstance(raw, dict):
        _raise_lineage_store_error(operation, TypeError("Expected JSON object"))
    return cast(dict[str, Any], raw)


def _run_git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd or repo_root()),
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return (1, "")
    return (int(proc.returncode), str(proc.stdout or "").strip())


def collect_git_snapshot(*, root: Path | None = None) -> GitSnapshot:
    base = Path(root or repo_root())
    commit_rc, commit_out = _run_git("rev-parse", "HEAD", cwd=base)
    status_rc, status_out = _run_git("status", "--porcelain=1", "--untracked-files=all", cwd=base)
    if commit_rc != 0 and status_rc != 0:
        return GitSnapshot(commit_sha=None, dirty=False, dirty_paths=[], tracked_files=[])

    dirty_paths: list[str] = []
    tracked_files: list[GitTrackedFile] = []
    for line in [ln for ln in status_out.splitlines() if ln.strip()]:
        status = line[:2].strip() or "??"
        raw_path = ""
        if len(line) >= 3:
            raw_path = (line[3:] if line[2] == " " else line[2:]).strip()
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ", 1)[1].strip()
        if not raw_path:
            continue
        dirty_paths.append(raw_path)
        fs_path = (base / raw_path).resolve()
        exists = fs_path.exists()
        sha = None
        size = None
        if exists and fs_path.is_file():
            try:
                raw = fs_path.read_bytes()
                sha = _sha256_bytes(raw)
                size = len(raw)
            except Exception:
                sha = None
                size = None
        tracked_files.append(
            GitTrackedFile(
                path=raw_path,
                status=status,
                exists=bool(exists),
                sha256=sha,
                bytes=size,
            )
        )

    return GitSnapshot(
        commit_sha=commit_out or None,
        dirty=bool(dirty_paths),
        dirty_paths=dirty_paths,
        tracked_files=tracked_files,
    )


def make_ref(kind: LineageAssetKind, version_id: str, *, label: str | None = None) -> LineageRef:
    return LineageRef(kind=kind, version_id=version_id, label=label)


def _asset_digest_payload(*, kind: LineageAssetKind, repo_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "repo_id": str(repo_id or "").strip() or None,
        "payload": payload,
    }


def _version_id_for(kind: LineageAssetKind, digest: str) -> str:
    return f"{kind}__{digest[:24]}"


def capture_asset_version(
    *,
    kind: LineageAssetKind,
    payload: dict[str, Any],
    repo_id: str | None = None,
    source: str,
    source_paths: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    upstream_refs: list[LineageRef] | None = None,
    git_snapshot: GitSnapshot | None = None,
    root: Path | None = None,
) -> LineageAssetVersion:
    canonical_payload = _asset_digest_payload(kind=kind, repo_id=repo_id, payload=payload)
    digest = _sha256_json(canonical_payload)
    version_id = _version_id_for(kind, digest)
    path = _asset_path(kind, version_id, root=root)
    if path.exists():
        return cast(
            LineageAssetVersion,
            _validate_lineage_model(
                LineageAssetVersion,
                _read_json_object(path, operation="Lineage asset read"),
                operation="Lineage asset read",
            ),
        )

    version = LineageAssetVersion(
        version_id=version_id,
        kind=kind,
        repo_id=repo_id,
        created_at=datetime.now(UTC),
        digest=digest,
        source=source,  # type: ignore[arg-type]
        source_paths=list(source_paths or []),
        git=git_snapshot or collect_git_snapshot(),
        metadata=dict(metadata or {}),
        payload=payload,
        upstream_refs=list(upstream_refs or []),
    )
    _atomic_write_json(path, version.model_dump(mode="json", by_alias=True))
    return version


def load_asset(version_id: str, *, root: Path | None = None) -> LineageAssetVersion:
    kind = version_id.split("__", 1)[0]
    path = _asset_path(cast(LineageAssetKind, kind), version_id, root=root)
    if not path.exists():
        raise FileNotFoundError(f"lineage asset not found: {version_id}")
    return cast(
        LineageAssetVersion,
        _validate_lineage_model(
            LineageAssetVersion,
            _read_json_object(path, operation="Lineage asset read"),
            operation="Lineage asset read",
        ),
    )


def _snapshot_file_entry(path: Path, *, base: Path | None = None) -> dict[str, Any]:
    rel = str(path.relative_to(base)) if base is not None else str(path)
    exists = path.exists()
    size = int(path.stat().st_size) if exists and path.is_file() else 0
    digest = None
    if exists and path.is_file():
        digest = _sha256_bytes(path.read_bytes())
    return {
        "path": rel,
        "exists": bool(exists),
        "bytes": size,
        "sha256": digest,
    }


def snapshot_path(path: Path) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.exists():
        return {"path": str(resolved), "exists": False, "is_dir": False, "entries": []}
    if resolved.is_file():
        entry = _snapshot_file_entry(resolved)
        entry["is_dir"] = False
        return entry

    entries = [
        _snapshot_file_entry(child, base=resolved)
        for child in sorted([p for p in resolved.rglob("*") if p.is_file()], key=lambda p: str(p.relative_to(resolved)))
    ]
    return {
        "path": str(resolved),
        "exists": True,
        "is_dir": True,
        "entries": entries,
    }


def capture_path_version(
    *,
    kind: LineageAssetKind,
    path: Path,
    repo_id: str | None = None,
    source: str,
    metadata: dict[str, Any] | None = None,
    upstream_refs: list[LineageRef] | None = None,
    root: Path | None = None,
) -> LineageAssetVersion:
    resolved = Path(path).resolve()
    payload = snapshot_path(resolved)
    return capture_asset_version(
        kind=kind,
        payload=payload,
        repo_id=repo_id,
        source=source,
        source_paths=[str(resolved)],
        metadata=metadata,
        upstream_refs=upstream_refs,
        root=root,
    )


def build_prompt_set_payload(cfg: TriBridConfig) -> dict[str, Any]:
    chat_fields = [
        "system_prompt_base",
        "system_prompt_rag_suffix",
        "system_prompt_recall_suffix",
        "system_prompt_direct",
        "system_prompt_rag",
        "system_prompt_recall",
        "system_prompt_rag_and_recall",
    ]
    return {
        "system_prompts": cfg.system_prompts.model_dump(mode="json"),
        "chat_prompts": {field: str(getattr(cfg.chat, field, "") or "") for field in chat_fields},
    }


def _active_artifact_path(root: Path) -> Path:
    """The pinned active version under a versioned artifact store root, for identity capture.

    Nothing promoted — or a store the operator must repair — snapshots the store's pointer
    file instead: absent it records `exists: False`, corrupt it records the corrupt bytes.
    Neither case ever snapshots the root tree as if it were an artifact (no flat-layout
    fallback: the store is the only read path).
    """
    from server.training.artifact_store import ArtifactStoreError, pointer_path, resolve_active_artifact_dir

    try:
        active = resolve_active_artifact_dir(root)
    except ArtifactStoreError:
        return pointer_path(root)
    return active if active is not None else pointer_path(root)


def build_runtime_model_set_payload(cfg: TriBridConfig) -> dict[str, Any]:
    reranker_path = _active_artifact_path(
        resolve_project_path(str(getattr(cfg.training, "tribrid_reranker_model_path", "") or ""))
    )
    agent_path = _active_artifact_path(
        resolve_project_path(str(getattr(cfg.training, "ragweld_agent_model_path", "") or ""))
    )
    return {
        "generation": {
            "gen_model": str(getattr(cfg.generation, "gen_model", "") or ""),
            "gen_model_http": str(getattr(cfg.generation, "gen_model_http", "") or ""),
            "gen_model_mcp": str(getattr(cfg.generation, "gen_model_mcp", "") or ""),
            "gen_model_cli": str(getattr(cfg.generation, "gen_model_cli", "") or ""),
            "enrich_model": str(getattr(cfg.generation, "enrich_model", "") or ""),
        },
        "chat": {
            "default_model": str(getattr(cfg.ui, "chat_default_model", "") or ""),
            "litellm_default_model": str(getattr(cfg.chat.litellm, "default_model", "") or ""),
            "vllm_default_model": str(getattr(cfg.chat.vllm, "default_model", "") or ""),
            "vision_model_override": str(getattr(getattr(cfg.chat, "multimodal", None), "vision_model_override", "") or ""),
        },
        "embedding": {
            "embedding_type": str(getattr(cfg.embedding, "embedding_type", "") or ""),
            "embedding_model": str(getattr(cfg.embedding, "embedding_model", "") or ""),
            "embedding_model_local": str(getattr(cfg.embedding, "embedding_model_local", "") or ""),
            "embedding_model_mlx": str(getattr(cfg.embedding, "embedding_model_mlx", "") or ""),
            "voyage_model": str(getattr(cfg.embedding, "voyage_model", "") or ""),
        },
        "reranking": {
            "cloud_provider": str(getattr(cfg.reranking, "reranker_cloud_provider", "") or ""),
            "cloud_model": str(getattr(cfg.reranking, "reranker_cloud_model", "") or ""),
            "active_path": str(reranker_path),
            "active_artifact": snapshot_path(reranker_path),
            "base_model": str(getattr(cfg.training, "learning_reranker_base_model", "") or ""),
        },
        "agent": {
            "backend": str(getattr(cfg.training, "ragweld_agent_backend", "") or ""),
            "base_model": str(getattr(cfg.training, "ragweld_agent_base_model", "") or ""),
            "active_path": str(agent_path),
            "active_artifact": snapshot_path(agent_path),
        },
    }


def capture_prompt_set_version(*, repo_id: str, cfg: TriBridConfig, root: Path | None = None) -> LineageAssetVersion:
    return capture_asset_version(
        kind="prompt_set",
        payload=build_prompt_set_payload(cfg),
        repo_id=repo_id,
        source="runtime",
        metadata={"prompt_count": 16},
        root=root,
    )


def capture_config_snapshot_version(*, repo_id: str, cfg: TriBridConfig, root: Path | None = None) -> LineageAssetVersion:
    return capture_asset_version(
        kind="config_snapshot",
        payload=cfg.model_dump(mode="json"),
        repo_id=repo_id,
        source="runtime",
        root=root,
    )


def capture_spec_snapshot_version(*, root: Path | None = None) -> LineageAssetVersion:
    base = repo_root() / "spec"
    files = []
    for path in sorted([p for p in base.rglob("*") if p.is_file()], key=lambda p: str(p.relative_to(base))):
        files.append(_snapshot_file_entry(path, base=base))
    return capture_asset_version(
        kind="spec_snapshot",
        payload={"root": str(base), "files": files},
        source="git",
        source_paths=[str(base)],
        root=root,
    )


def capture_model_catalog_snapshot_version(*, root: Path | None = None) -> LineageAssetVersion:
    path = repo_root() / "data" / "models.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    payload = raw if isinstance(raw, dict) else {"models": raw}
    return capture_asset_version(
        kind="model_catalog_snapshot",
        payload=cast(dict[str, Any], payload),
        source="git",
        source_paths=[str(path)],
        root=root,
    )


def capture_runtime_model_set_version(*, repo_id: str, cfg: TriBridConfig, root: Path | None = None) -> LineageAssetVersion:
    return capture_asset_version(
        kind="runtime_model_set",
        payload=build_runtime_model_set_payload(cfg),
        repo_id=repo_id,
        source="runtime",
        root=root,
    )


def capture_eval_dataset_version(
    *,
    repo_id: str,
    rows: list[dict[str, Any]],
    source_path: str | None = None,
    root: Path | None = None,
) -> LineageAssetVersion:
    return capture_asset_version(
        kind="eval_dataset",
        payload={"items": rows},
        repo_id=repo_id,
        source="runtime",
        source_paths=[source_path] if source_path else [],
        metadata={"rows": len(rows)},
        root=root,
    )


def _dedupe_refs(refs: list[LineageRef]) -> list[LineageRef]:
    out: list[LineageRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        key = (str(ref.kind), str(ref.version_id))
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _bundle_id_for(payload: dict[str, Any]) -> str:
    digest = _sha256_json(payload)
    return f"bundle__{digest[:24]}"


def load_bundle(repo_id: str, bundle_id: str, *, root: Path | None = None) -> LineageBundle:
    path = _bundle_path(repo_id, bundle_id, root=root)
    if not path.exists():
        raise FileNotFoundError(f"lineage bundle not found: {bundle_id}")
    return cast(
        LineageBundle,
        _validate_lineage_model(
            LineageBundle,
            _read_json_object(path, operation="Lineage bundle read"),
            operation="Lineage bundle read",
        ),
    )


def list_bundles(*, repo_id: str, limit: int = 50, root: Path | None = None) -> list[LineageBundle]:
    out: list[LineageBundle] = []
    for path in sorted(_bundles_dir(repo_id, root=root).glob("*.json"), reverse=True):
        try:
            out.append(load_bundle(repo_id, path.stem, root=root))
        except DependencyUnavailableError:
            raise
        except FileNotFoundError as exc:
            _raise_lineage_store_error("Lineage bundle list", exc)
        if len(out) >= max(1, int(limit)):
            break
    return out


def load_alias(repo_id: str, alias: LineageAliasName, *, root: Path | None = None) -> LineageAlias | None:
    path = _alias_path(repo_id, alias, root=root)
    if not path.exists():
        return None
    return cast(
        LineageAlias,
        _validate_lineage_model(
            LineageAlias,
            _read_json_object(path, operation="Lineage alias read"),
            operation="Lineage alias read",
        ),
    )


def list_aliases(*, repo_id: str, root: Path | None = None) -> list[LineageAlias]:
    out: list[LineageAlias] = []
    for name in ("baseline", "canary", "current", "promoted"):
        alias = load_alias(repo_id, name, root=root)
        if alias is not None:
            out.append(alias)
    return out


class _RepoLineageLock:
    """Reentrant (per thread) interprocess lock for one repository's aliases and bundles.

    Every alias mutation (`create_or_update_bundle`, `set_alias`, `restore_aliases`) takes it, and a
    promotion transaction holds it across snapshot -> write -> compensation, so compensation can
    never overwrite an unrelated concurrent alias move: there are no concurrent alias writers for
    the repository while it is held. Reentrancy lets the transaction's own lineage writes proceed.
    """

    def __init__(self, repo_id: str, root: Path | None) -> None:
        self.path = lineage_root(root) / "locks" / f"{_safe_repo_id(repo_id)}.lock"
        self._guard = threading.Lock()
        self._owner: int | None = None
        self._depth = 0
        self._handle = None

    def acquire(self) -> None:
        me = threading.get_ident()
        with self._guard:
            if self._owner == me:
                self._depth += 1
                return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        with self._guard:
            self._handle = handle
            self._owner = me
            self._depth = 1

    def release(self) -> None:
        with self._guard:
            if self._owner != threading.get_ident():
                return
            self._depth -= 1
            if self._depth > 0:
                return
            handle, self._handle = self._handle, None
            self._owner = None
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def __enter__(self) -> _RepoLineageLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


_REPO_LOCKS: dict[tuple[str, str], _RepoLineageLock] = {}
_REPO_LOCKS_GUARD = threading.Lock()


def repo_lineage_lock(repo_id: str, *, root: Path | None = None) -> _RepoLineageLock:
    key = (str(lineage_root(root)), _safe_repo_id(repo_id))
    with _REPO_LOCKS_GUARD:
        lock = _REPO_LOCKS.get(key)
        if lock is None:
            lock = _RepoLineageLock(repo_id, root)
            _REPO_LOCKS[key] = lock
        return lock


def snapshot_aliases(
    *, repo_id: str, names: tuple[LineageAliasName, ...], root: Path | None = None
) -> dict[LineageAliasName, str | None]:
    """The bundle each alias points at right now (None when unset), for compensation on rollback."""
    return {name: (alias.bundle_id if (alias := load_alias(repo_id, name, root=root)) is not None else None) for name in names}


def restore_aliases(
    *,
    repo_id: str,
    snapshot: dict[LineageAliasName, str | None],
    only_if_pointing_at: str | None = None,
    root: Path | None = None,
) -> list[LineageAliasName]:
    """Compensate a failed promotion's alias moves and return the aliases that were put back.

    A promotion that is rolled back after `attach_refs_to_current_bundle(..., extra_aliases=("promoted",))`
    must not leave lineage claiming the failed candidate is promoted. Compensation is
    compare-and-swap: an alias is only moved back when it currently points at the failed
    transaction's bundle (`only_if_pointing_at`), or — when that bundle id is unknown because
    the failure happened mid-write — when it no longer matches the snapshot. An alias that a
    concurrent, unrelated update moved elsewhere is left alone.
    """
    restored: list[LineageAliasName] = []
    with repo_lineage_lock(repo_id, root=root):
        for name, bundle_id in snapshot.items():
            restored.extend(_restore_one_alias(repo_id, name, bundle_id, only_if_pointing_at, root))
    return restored


def _restore_one_alias(
    repo_id: str, name: LineageAliasName, bundle_id: str | None, only_if_pointing_at: str | None, root: Path | None
) -> list[LineageAliasName]:
    current = load_alias(repo_id, name, root=root)
    current_id = current.bundle_id if current is not None else None
    if current_id == bundle_id:
        return []  # untouched
    if only_if_pointing_at is not None and current_id != only_if_pointing_at:
        return []  # moved by someone else; not ours to undo
    if bundle_id is not None:
        # The snapshot pointer was valid when taken; compensation must not depend on a bundle
        # re-read succeeding mid-failure, so the alias file is written back directly.
        value = LineageAlias(alias=name, repo_id=repo_id, bundle_id=bundle_id, updated_at=datetime.now(UTC))
        _atomic_write_json(_alias_path(repo_id, name, root=root), value.model_dump(mode="json", by_alias=True))
    else:
        _alias_path(repo_id, name, root=root).unlink(missing_ok=True)
    return [name]


def set_alias(*, repo_id: str, alias: LineageAliasName, bundle_id: str, root: Path | None = None) -> LineageAlias:
    with repo_lineage_lock(repo_id, root=root):
        load_bundle(repo_id, bundle_id, root=root)
        value = LineageAlias(
            alias=alias,
            repo_id=repo_id,
            bundle_id=bundle_id,
            updated_at=datetime.now(UTC),
        )
        _atomic_write_json(_alias_path(repo_id, alias, root=root), value.model_dump(mode="json", by_alias=True))
        return value


def _carry_ref(current: LineageBundle | None, attr: str, incoming: LineageRef | None) -> LineageRef | None:
    if incoming is not None:
        return incoming
    return cast(LineageRef | None, getattr(current, attr, None)) if current is not None else None


def create_or_update_bundle(
    *,
    repo_id: str,
    prompt_set: LineageRef | None = None,
    config_snapshot: LineageRef | None = None,
    spec_snapshot: LineageRef | None = None,
    model_catalog_snapshot: LineageRef | None = None,
    runtime_model_set: LineageRef | None = None,
    eval_dataset: LineageRef | None = None,
    benchmark_runs: list[LineageRef] | None = None,
    eval_runs: list[LineageRef] | None = None,
    synthetic_runs: list[LineageRef] | None = None,
    synthetic_artifacts: list[LineageRef] | None = None,
    published_artifacts: list[LineageRef] | None = None,
    reranker_train_runs: list[LineageRef] | None = None,
    reranker_model_artifacts: list[LineageRef] | None = None,
    agent_train_runs: list[LineageRef] | None = None,
    agent_model_artifacts: list[LineageRef] | None = None,
    metadata: dict[str, Any] | None = None,
    preserve_current: bool = True,
    preserve_attached_refs: bool = False,
    set_aliases_to: tuple[LineageAliasName, ...] = (),
    root: Path | None = None,
) -> tuple[LineageBundle, list[LineageAlias]]:
    # Bundle + alias writes for one repository are serialized with the promotion transactions that
    # compensate them (see `repo_lineage_lock`); the lock is reentrant for the transaction's own writes.
    with repo_lineage_lock(repo_id, root=root):
        return _create_or_update_bundle_locked(repo_id=repo_id, prompt_set=prompt_set, config_snapshot=config_snapshot, spec_snapshot=spec_snapshot, model_catalog_snapshot=model_catalog_snapshot, runtime_model_set=runtime_model_set, eval_dataset=eval_dataset, benchmark_runs=benchmark_runs, eval_runs=eval_runs, synthetic_runs=synthetic_runs, synthetic_artifacts=synthetic_artifacts, published_artifacts=published_artifacts, reranker_train_runs=reranker_train_runs, reranker_model_artifacts=reranker_model_artifacts, agent_train_runs=agent_train_runs, agent_model_artifacts=agent_model_artifacts, metadata=metadata, preserve_current=preserve_current, preserve_attached_refs=preserve_attached_refs, set_aliases_to=set_aliases_to, root=root)


def _create_or_update_bundle_locked(
    *,
    repo_id: str,
    prompt_set: LineageRef | None = None,
    config_snapshot: LineageRef | None = None,
    spec_snapshot: LineageRef | None = None,
    model_catalog_snapshot: LineageRef | None = None,
    runtime_model_set: LineageRef | None = None,
    eval_dataset: LineageRef | None = None,
    benchmark_runs: list[LineageRef] | None = None,
    eval_runs: list[LineageRef] | None = None,
    synthetic_runs: list[LineageRef] | None = None,
    synthetic_artifacts: list[LineageRef] | None = None,
    published_artifacts: list[LineageRef] | None = None,
    reranker_train_runs: list[LineageRef] | None = None,
    reranker_model_artifacts: list[LineageRef] | None = None,
    agent_train_runs: list[LineageRef] | None = None,
    agent_model_artifacts: list[LineageRef] | None = None,
    metadata: dict[str, Any] | None = None,
    preserve_current: bool = True,
    preserve_attached_refs: bool = False,
    set_aliases_to: tuple[LineageAliasName, ...] = (),
    root: Path | None = None,
) -> tuple[LineageBundle, list[LineageAlias]]:
    current_alias = load_alias(repo_id, "current", root=root) if preserve_current else None
    current_bundle = None
    if current_alias is not None:
        try:
            current_bundle = load_bundle(repo_id, current_alias.bundle_id, root=root)
        except DependencyUnavailableError:
            raise
        except FileNotFoundError as exc:
            _raise_lineage_store_error("Lineage current bundle preservation", exc)

    payload = {
        "repo_id": repo_id,
        "prompt_set": _jsonable(_carry_ref(current_bundle, "prompt_set", prompt_set)),
        "config_snapshot": _jsonable(_carry_ref(current_bundle, "config_snapshot", config_snapshot)),
        "spec_snapshot": _jsonable(_carry_ref(current_bundle, "spec_snapshot", spec_snapshot)),
        "model_catalog_snapshot": _jsonable(_carry_ref(current_bundle, "model_catalog_snapshot", model_catalog_snapshot)),
        "runtime_model_set": _jsonable(_carry_ref(current_bundle, "runtime_model_set", runtime_model_set)),
        "eval_dataset": _jsonable(_carry_ref(current_bundle, "eval_dataset", eval_dataset)),
        "benchmark_runs": _jsonable(
            _dedupe_refs(
                (
                    list(getattr(current_bundle, "benchmark_runs", []) or [])
                    if current_bundle is not None and preserve_attached_refs
                    else []
                )
                + list(benchmark_runs or [])
            )
        ),
        "eval_runs": _jsonable(
            _dedupe_refs(
                (
                    list(getattr(current_bundle, "eval_runs", []) or [])
                    if current_bundle is not None and preserve_attached_refs
                    else []
                )
                + list(eval_runs or [])
            )
        ),
        "synthetic_runs": _jsonable(
            _dedupe_refs(
                (
                    list(getattr(current_bundle, "synthetic_runs", []) or [])
                    if current_bundle is not None and preserve_attached_refs
                    else []
                )
                + list(synthetic_runs or [])
            )
        ),
        "synthetic_artifacts": _jsonable(
            _dedupe_refs(
                (
                    list(getattr(current_bundle, "synthetic_artifacts", []) or [])
                    if current_bundle is not None and preserve_attached_refs
                    else []
                )
                + list(synthetic_artifacts or [])
            )
        ),
        "published_artifacts": _jsonable(
            _dedupe_refs(
                (
                    list(getattr(current_bundle, "published_artifacts", []) or [])
                    if current_bundle is not None and preserve_attached_refs
                    else []
                )
                + list(published_artifacts or [])
            )
        ),
        "reranker_train_runs": _jsonable(
            _dedupe_refs(
                (
                    list(getattr(current_bundle, "reranker_train_runs", []) or [])
                    if current_bundle is not None and preserve_attached_refs
                    else []
                )
                + list(reranker_train_runs or [])
            )
        ),
        "reranker_model_artifacts": _jsonable(
            _dedupe_refs(
                (
                    list(getattr(current_bundle, "reranker_model_artifacts", []) or [])
                    if current_bundle is not None and preserve_attached_refs
                    else []
                )
                + list(reranker_model_artifacts or [])
            )
        ),
        "agent_train_runs": _jsonable(
            _dedupe_refs(
                (
                    list(getattr(current_bundle, "agent_train_runs", []) or [])
                    if current_bundle is not None and preserve_attached_refs
                    else []
                )
                + list(agent_train_runs or [])
            )
        ),
        "agent_model_artifacts": _jsonable(
            _dedupe_refs(
                (
                    list(getattr(current_bundle, "agent_model_artifacts", []) or [])
                    if current_bundle is not None and preserve_attached_refs
                    else []
                )
                + list(agent_model_artifacts or [])
            )
        ),
        "metadata": _jsonable(metadata or {}),
    }
    bundle_id = _bundle_id_for(payload)
    path = _bundle_path(repo_id, bundle_id, root=root)
    if path.exists():
        bundle = load_bundle(repo_id, bundle_id, root=root)
    else:
        bundle = LineageBundle(
            bundle_id=bundle_id,
            repo_id=repo_id,
            created_at=datetime.now(UTC),
            prompt_set=cast(LineageRef | None, payload["prompt_set"]),
            config_snapshot=cast(LineageRef | None, payload["config_snapshot"]),
            spec_snapshot=cast(LineageRef | None, payload["spec_snapshot"]),
            model_catalog_snapshot=cast(LineageRef | None, payload["model_catalog_snapshot"]),
            runtime_model_set=cast(LineageRef | None, payload["runtime_model_set"]),
            eval_dataset=cast(LineageRef | None, payload["eval_dataset"]),
            benchmark_runs=cast(list[LineageRef], payload["benchmark_runs"]),
            eval_runs=cast(list[LineageRef], payload["eval_runs"]),
            synthetic_runs=cast(list[LineageRef], payload["synthetic_runs"]),
            synthetic_artifacts=cast(list[LineageRef], payload["synthetic_artifacts"]),
            published_artifacts=cast(list[LineageRef], payload["published_artifacts"]),
            reranker_train_runs=cast(list[LineageRef], payload["reranker_train_runs"]),
            reranker_model_artifacts=cast(list[LineageRef], payload["reranker_model_artifacts"]),
            agent_train_runs=cast(list[LineageRef], payload["agent_train_runs"]),
            agent_model_artifacts=cast(list[LineageRef], payload["agent_model_artifacts"]),
            metadata=cast(dict[str, Any], payload["metadata"]),
        )
        _atomic_write_json(path, bundle.model_dump(mode="json", by_alias=True))

    aliases = [set_alias(repo_id=repo_id, alias=alias, bundle_id=bundle.bundle_id, root=root) for alias in set_aliases_to]
    return (bundle, aliases)


def current_bundle(repo_id: str, *, root: Path | None = None) -> LineageBundle | None:
    alias = load_alias(repo_id, "current", root=root)
    if alias is None:
        return None
    try:
        return load_bundle(repo_id, alias.bundle_id, root=root)
    except DependencyUnavailableError:
        raise
    except FileNotFoundError as exc:
        _raise_lineage_store_error("Lineage current bundle resolution", exc)


def _default_eval_dataset_path(repo_id: str) -> Path:
    return repo_root() / "data" / "eval_datasets" / f"{_safe_repo_id(repo_id)}.json"


def capture_current_state_refs(
    *,
    repo_id: str,
    cfg: TriBridConfig,
    dataset_rows: list[dict[str, Any]] | None = None,
    dataset_path: str | None = None,
    root: Path | None = None,
) -> dict[str, LineageRef | None]:
    prompt_version = capture_prompt_set_version(repo_id=repo_id, cfg=cfg, root=root)
    config_version = capture_config_snapshot_version(repo_id=repo_id, cfg=cfg, root=root)
    spec_version = capture_spec_snapshot_version(root=root)
    catalog_version = capture_model_catalog_snapshot_version(root=root)
    runtime_version = capture_runtime_model_set_version(repo_id=repo_id, cfg=cfg, root=root)

    dataset_ref: LineageRef | None = None
    if dataset_rows is not None:
        rows = list(dataset_rows)
        dataset_version = capture_eval_dataset_version(
            repo_id=repo_id,
            rows=rows,
            source_path=dataset_path or str(_default_eval_dataset_path(repo_id)),
            root=root,
        )
        dataset_ref = make_ref("eval_dataset", dataset_version.version_id, label=f"{len(rows)} rows")

    return {
        "prompt_set": make_ref("prompt_set", prompt_version.version_id),
        "config_snapshot": make_ref("config_snapshot", config_version.version_id),
        "spec_snapshot": make_ref("spec_snapshot", spec_version.version_id),
        "model_catalog_snapshot": make_ref("model_catalog_snapshot", catalog_version.version_id),
        "runtime_model_set": make_ref("runtime_model_set", runtime_version.version_id),
        "eval_dataset": dataset_ref,
    }


def ensure_current_bundle(
    *,
    repo_id: str,
    cfg: TriBridConfig,
    dataset_rows: list[dict[str, Any]] | None = None,
    dataset_path: str | None = None,
    root: Path | None = None,
) -> LineageBundle:
    refs = capture_current_state_refs(repo_id=repo_id, cfg=cfg, dataset_rows=dataset_rows, dataset_path=dataset_path, root=root)
    bundle, _aliases = create_or_update_bundle(
        repo_id=repo_id,
        prompt_set=refs["prompt_set"],
        config_snapshot=refs["config_snapshot"],
        spec_snapshot=refs["spec_snapshot"],
        model_catalog_snapshot=refs["model_catalog_snapshot"],
        runtime_model_set=refs["runtime_model_set"],
        eval_dataset=refs["eval_dataset"],
        preserve_attached_refs=False,
        set_aliases_to=("current",),
        root=root,
    )
    return bundle


def attach_refs_to_current_bundle(
    *,
    repo_id: str,
    cfg: TriBridConfig,
    dataset_rows: list[dict[str, Any]] | None = None,
    dataset_path: str | None = None,
    benchmark_runs: list[LineageRef] | None = None,
    eval_runs: list[LineageRef] | None = None,
    synthetic_runs: list[LineageRef] | None = None,
    synthetic_artifacts: list[LineageRef] | None = None,
    published_artifacts: list[LineageRef] | None = None,
    reranker_train_runs: list[LineageRef] | None = None,
    reranker_model_artifacts: list[LineageRef] | None = None,
    agent_train_runs: list[LineageRef] | None = None,
    agent_model_artifacts: list[LineageRef] | None = None,
    extra_aliases: tuple[LineageAliasName, ...] = (),
    preserve_attached_refs: bool = False,
    root: Path | None = None,
) -> tuple[LineageBundle, list[LineageAlias]]:
    refs = capture_current_state_refs(repo_id=repo_id, cfg=cfg, dataset_rows=dataset_rows, dataset_path=dataset_path, root=root)
    aliases = ("current", *extra_aliases)
    return create_or_update_bundle(
        repo_id=repo_id,
        prompt_set=refs["prompt_set"],
        config_snapshot=refs["config_snapshot"],
        spec_snapshot=refs["spec_snapshot"],
        model_catalog_snapshot=refs["model_catalog_snapshot"],
        runtime_model_set=refs["runtime_model_set"],
        eval_dataset=refs["eval_dataset"],
        benchmark_runs=benchmark_runs,
        eval_runs=eval_runs,
        synthetic_runs=synthetic_runs,
        synthetic_artifacts=synthetic_artifacts,
        published_artifacts=published_artifacts,
        reranker_train_runs=reranker_train_runs,
        reranker_model_artifacts=reranker_model_artifacts,
        agent_train_runs=agent_train_runs,
        agent_model_artifacts=agent_model_artifacts,
        preserve_attached_refs=preserve_attached_refs,
        set_aliases_to=aliases,
        root=root,
    )


def capture_benchmark_run_version(*, run: BenchmarkRun, root: Path | None = None) -> LineageAssetVersion:
    return capture_asset_version(
        kind="benchmark_run",
        payload=run.model_dump(mode="json", by_alias=True),
        repo_id=run.repo_id,
        source="generated",
        metadata={"run_id": run.run_id, "models": len(run.results)},
        root=root,
    )


def capture_eval_run_version(*, run_payload: dict[str, Any], repo_id: str, root: Path | None = None) -> LineageAssetVersion:
    return capture_asset_version(
        kind="eval_run",
        payload=run_payload,
        repo_id=repo_id,
        source="generated",
        metadata={"run_id": str(run_payload.get("run_id") or "")},
        root=root,
    )


def capture_training_run_version(
    *,
    kind: LineageAssetKind,
    run_payload: dict[str, Any],
    repo_id: str,
    payload_extras: dict[str, Any] | None = None,
    root: Path | None = None,
) -> LineageAssetVersion:
    payload = dict(run_payload)
    if payload_extras:
        payload.update(payload_extras)
    return capture_asset_version(
        kind=kind,
        payload=payload,
        repo_id=repo_id,
        source="generated",
        metadata={"run_id": str(payload.get("run_id") or ""), "status": str(payload.get("status") or "")},
        root=root,
    )


def capture_synthetic_run_version(*, run_payload: dict[str, Any], repo_id: str, root: Path | None = None) -> LineageAssetVersion:
    return capture_asset_version(
        kind="synthetic_run",
        payload=run_payload,
        repo_id=repo_id,
        source="generated",
        metadata={"run_id": str(run_payload.get("run_id") or ""), "status": str(run_payload.get("status") or "")},
        root=root,
    )


def capture_synthetic_artifact_version(
    *,
    repo_id: str,
    artifact_kind: str,
    path: str,
    run_id: str,
    root: Path | None = None,
) -> LineageAssetVersion:
    return capture_path_version(
        kind="synthetic_artifact",
        path=Path(path),
        repo_id=repo_id,
        source="generated",
        metadata={"artifact_kind": artifact_kind, "run_id": run_id},
        root=root,
    )


def capture_published_artifact_version(
    *,
    repo_id: str,
    artifact_kind: str,
    source_path: str,
    target_path: str | None,
    root: Path | None = None,
) -> LineageAssetVersion:
    def _snapshot_runtime_path(path_str: str | None) -> dict[str, Any] | None:
        raw = str(path_str or "").strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        if not path.is_absolute():
            head = raw.split("/", 1)[0]
            if ":" in head:
                return None
            path = repo_root() / path
        return snapshot_path(path.resolve())

    payload = {
        "artifact_kind": artifact_kind,
        "source_path": source_path,
        "target_path": target_path,
        "source_snapshot": _snapshot_runtime_path(source_path),
        "target_snapshot": _snapshot_runtime_path(target_path),
    }
    return capture_asset_version(
        kind="published_artifact",
        payload=payload,
        repo_id=repo_id,
        source="published",
        source_paths=[p for p in [source_path, target_path] if p],
        metadata={"artifact_kind": artifact_kind},
        root=root,
    )
