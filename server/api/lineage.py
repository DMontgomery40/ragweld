from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from server.api.dataset import _dataset_path_for_corpus, _load_dataset
from server.lineage import current_bundle, ensure_current_bundle, list_aliases, list_bundles, load_bundle, set_alias
from server.models.tribrid_config_model import (
    CorpusScope,
    LineageAliasName,
    LineageAliasUpdateRequest,
    LineageAliasesResponse,
    LineageBundle,
    LineageBundleListResponse,
    LineageBundleSnapshotRequest,
    LineageBundleSnapshotResponse,
)
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(prefix="/api/lineage", tags=["lineage"])

# Ruff B008: avoid function calls in argument defaults (FastAPI Depends()).
_CORPUS_SCOPE_DEP = Depends()


async def _scoped_bundle(scope: CorpusScope) -> LineageBundle:
    repo_id = scope.resolved_repo_id
    if not repo_id:
        raise HTTPException(status_code=422, detail="Missing corpus_id (or legacy repo_id)")
    try:
        cfg = await load_scoped_config(repo_id=repo_id)
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    dataset = _load_dataset(corpus_id=repo_id)
    return ensure_current_bundle(
        repo_id=repo_id,
        cfg=cfg,
        dataset_rows=[row.model_dump(mode="json", by_alias=True) for row in dataset],
        dataset_path=str(_dataset_path_for_corpus(repo_id)),
    )


async def _require_repo_id(scope: CorpusScope) -> str:
    repo_id = scope.resolved_repo_id
    if not repo_id:
        raise HTTPException(status_code=422, detail="Missing corpus_id (or legacy repo_id)")
    try:
        await load_scoped_config(repo_id=repo_id)
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return repo_id


@router.get("/current", response_model=LineageBundle)
async def get_current_lineage(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> LineageBundle:
    repo_id = await _require_repo_id(scope)
    bundle = current_bundle(repo_id)
    if bundle is not None:
        return bundle
    return await _scoped_bundle(scope)


@router.get("/bundles", response_model=LineageBundleListResponse)
async def get_bundles(
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
    limit: int = Query(default=50, ge=1, le=200),
) -> LineageBundleListResponse:
    repo_id = await _require_repo_id(scope)
    return LineageBundleListResponse(ok=True, bundles=list_bundles(repo_id=repo_id, limit=limit))


@router.get("/bundle/{bundle_id}", response_model=LineageBundle)
async def get_bundle(bundle_id: str, scope: CorpusScope = _CORPUS_SCOPE_DEP) -> LineageBundle:
    repo_id = await _require_repo_id(scope)
    try:
        return load_bundle(repo_id=repo_id, bundle_id=bundle_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/aliases", response_model=LineageAliasesResponse)
async def get_aliases(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> LineageAliasesResponse:
    repo_id = await _require_repo_id(scope)
    return LineageAliasesResponse(ok=True, aliases=list_aliases(repo_id=repo_id))


@router.post("/aliases/{alias}", response_model=LineageAliasesResponse)
async def update_alias(
    alias: LineageAliasName,
    body: LineageAliasUpdateRequest,
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> LineageAliasesResponse:
    repo_id = await _require_repo_id(scope)
    try:
        set_alias(repo_id=repo_id, alias=alias, bundle_id=body.bundle_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return LineageAliasesResponse(ok=True, aliases=list_aliases(repo_id=repo_id))


@router.post("/bundle/snapshot", response_model=LineageBundleSnapshotResponse)
async def snapshot_bundle(
    body: LineageBundleSnapshotRequest | None = None,
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> LineageBundleSnapshotResponse:
    bundle = await _scoped_bundle(scope)
    aliases = []
    for alias in list((body.set_aliases if body is not None else []) or []):
        aliases.append(set_alias(repo_id=str(bundle.repo_id), alias=alias, bundle_id=bundle.bundle_id))
    return LineageBundleSnapshotResponse(ok=True, bundle=bundle, aliases=aliases)
