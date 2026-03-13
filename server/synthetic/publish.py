from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from server.api.dataset import _save_dataset
from server.db.postgres import PostgresClient
from server.lineage import attach_refs_to_current_bundle, capture_published_artifact_version, make_ref
from server.models.tribrid_config_model import (
    ChunkSummariesLastBuild,
    ChunkSummary,
    EvalDatasetItem,
    SyntheticArtifactKind,
    SyntheticConfigPatchResponse,
    SyntheticPublishResponse,
    SyntheticRun,
)
from server.services.config_store import get_config as load_scoped_config

_ROOT = Path(__file__).resolve().parents[2]


def _require_quality_gate(run: SyntheticRun, *, kind: str) -> None:
    passed = bool(getattr(run.summary, "quality_gate_passed", False))
    if passed:
        return
    threshold = getattr(run.summary, "quality_gate_threshold", None)
    top1 = getattr(run.summary, "quality_top1_accuracy", None)
    reason = str(getattr(run.summary, "quality_failure_reason", "") or "").strip()
    if threshold is not None and top1 is not None:
        detail = f"top1={float(top1):.3f} < threshold={float(threshold):.3f}"
    elif reason:
        detail = reason
    else:
        detail = "quality gate has not passed"
    raise RuntimeError(f"QUALITY_GATE_FAILED: cannot publish {kind}: {detail}")


def _resolve_path(path_str: str) -> Path:
    p = Path(str(path_str or "")).expanduser()
    if not p.is_absolute():
        p = _ROOT / p
    return p


def _artifact_path(run: SyntheticRun, kind: SyntheticArtifactKind) -> Path:
    for ref in run.artifacts:
        if ref.kind == kind:
            return Path(ref.path)
    raise FileNotFoundError(f"Artifact missing for kind={kind}")


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


async def publish_eval_dataset(run: SyntheticRun) -> SyntheticPublishResponse:
    _require_quality_gate(run, kind="eval_dataset_json")
    path = _artifact_path(run, "eval_dataset_json")
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise RuntimeError("eval_dataset artifact is not a JSON array")
    entries = [EvalDatasetItem.model_validate(x) for x in raw]
    _save_dataset(entries, corpus_id=run.repo_id)
    target = _ROOT / "data" / "eval_datasets" / f"{run.repo_id}.json"
    cfg = await load_scoped_config(repo_id=run.repo_id)
    version = capture_published_artifact_version(
        repo_id=run.repo_id,
        artifact_kind="eval_dataset_json",
        source_path=str(path),
        target_path=str(target),
    )
    bundle, _aliases = attach_refs_to_current_bundle(
        repo_id=run.repo_id,
        cfg=cfg,
        dataset_rows=[entry.model_dump(mode="json", by_alias=True) for entry in entries],
        dataset_path=str(target),
        published_artifacts=[make_ref("published_artifact", version.version_id)],
    )
    return SyntheticPublishResponse(
        ok=True,
        run_id=run.run_id,
        repo_id=run.repo_id,
        kind="eval_dataset_json",
        target_path=str(target),
        message=f"Published {len(entries)} eval items.",
        bundle_id=bundle.bundle_id,
        lineage_ref=make_ref("published_artifact", version.version_id),
    )


async def publish_semantic_cards(run: SyntheticRun) -> SyntheticPublishResponse:
    path = _artifact_path(run, "semantic_cards_jsonl")
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    summaries = [ChunkSummary.model_validate(json.loads(ln)) for ln in lines]

    cfg = await load_scoped_config(repo_id=run.repo_id)
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        last_build = ChunkSummariesLastBuild(
            repo_id=run.repo_id,
            timestamp=datetime.now(UTC),
            total=len(summaries),
            enriched=sum(1 for s in summaries if str(getattr(s, "card_source", "")).lower() == "llm"),
        )
        await pg.replace_chunk_summaries(run.repo_id, summaries=summaries, last_build=last_build)
    finally:
        await pg.disconnect()

    version = capture_published_artifact_version(
        repo_id=run.repo_id,
        artifact_kind="semantic_cards_jsonl",
        source_path=str(path),
        target_path="postgres:chunk_summaries",
    )
    bundle, _aliases = attach_refs_to_current_bundle(
        repo_id=run.repo_id,
        cfg=cfg,
        published_artifacts=[make_ref("published_artifact", version.version_id)],
    )

    return SyntheticPublishResponse(
        ok=True,
        run_id=run.run_id,
        repo_id=run.repo_id,
        kind="semantic_cards_jsonl",
        target_path="postgres:chunk_summaries",
        message=f"Published {len(summaries)} semantic summaries.",
        bundle_id=bundle.bundle_id,
        lineage_ref=make_ref("published_artifact", version.version_id),
    )


async def publish_keywords(run: SyntheticRun) -> SyntheticPublishResponse:
    path = _artifact_path(run, "keywords_json")
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise RuntimeError("keywords artifact is not a JSON array")
    keywords = [str(x).strip() for x in raw if str(x).strip()]

    cfg = await load_scoped_config(repo_id=run.repo_id)
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        await pg.update_corpus_meta(run.repo_id, {"keywords": keywords})
    finally:
        await pg.disconnect()

    version = capture_published_artifact_version(
        repo_id=run.repo_id,
        artifact_kind="keywords_json",
        source_path=str(path),
        target_path="postgres:corpora.meta.keywords",
    )
    bundle, _aliases = attach_refs_to_current_bundle(
        repo_id=run.repo_id,
        cfg=cfg,
        published_artifacts=[make_ref("published_artifact", version.version_id)],
    )

    return SyntheticPublishResponse(
        ok=True,
        run_id=run.run_id,
        repo_id=run.repo_id,
        kind="keywords_json",
        target_path="postgres:corpora.meta.keywords",
        message=f"Published {len(keywords)} keywords.",
        bundle_id=bundle.bundle_id,
        lineage_ref=make_ref("published_artifact", version.version_id),
    )


async def publish_triplets(run: SyntheticRun) -> SyntheticPublishResponse:
    _require_quality_gate(run, kind="triplets_jsonl")
    path = _artifact_path(run, "triplets_jsonl")
    cfg = await load_scoped_config(repo_id=run.repo_id)
    target = _resolve_path(str(cfg.training.tribrid_triplets_path or "data/training/triplets.jsonl"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    version = capture_published_artifact_version(
        repo_id=run.repo_id,
        artifact_kind="triplets_jsonl",
        source_path=str(path),
        target_path=str(target),
    )
    bundle, _aliases = attach_refs_to_current_bundle(
        repo_id=run.repo_id,
        cfg=cfg,
        published_artifacts=[make_ref("published_artifact", version.version_id)],
    )
    return SyntheticPublishResponse(
        ok=True,
        run_id=run.run_id,
        repo_id=run.repo_id,
        kind="triplets_jsonl",
        target_path=str(target),
        message="Published triplets artifact.",
        bundle_id=bundle.bundle_id,
        lineage_ref=make_ref("published_artifact", version.version_id),
    )


async def publish_config_patch(run: SyntheticRun) -> SyntheticConfigPatchResponse:
    path = _artifact_path(run, "config_patch_json")
    patch = _read_json(path)
    if not isinstance(patch, dict):
        raise RuntimeError("config_patch artifact must be a JSON object")
    cfg = await load_scoped_config(repo_id=run.repo_id)
    version = capture_published_artifact_version(
        repo_id=run.repo_id,
        artifact_kind="config_patch_json",
        source_path=str(path),
        target_path=None,
    )
    bundle, _aliases = attach_refs_to_current_bundle(
        repo_id=run.repo_id,
        cfg=cfg,
        published_artifacts=[make_ref("published_artifact", version.version_id)],
    )
    return SyntheticConfigPatchResponse(
        ok=True,
        run_id=run.run_id,
        repo_id=run.repo_id,
        patch={str(k): v for k, v in patch.items()},
        artifact_path=str(path),
        bundle_id=bundle.bundle_id,
        lineage_ref=make_ref("published_artifact", version.version_id),
    )
