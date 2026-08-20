from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from server.api.dataset import _dataset_path_for_corpus, _load_dataset
from server.api.dependency_errors import (
    DEPENDENCY_UNAVAILABLE_RESPONSES,
    dependency_unavailable_http_exception,
    raise_postgres_unavailable_if_applicable,
)
from server.dependency_errors import DependencyUnavailableError
from server.lineage import (
    current_bundle,
    ensure_current_bundle,
    list_aliases,
    list_bundles,
    load_bundle,
    set_alias,
)
from server.models.tribrid_config_model import (
    CorpusScope,
    LineageAliasesResponse,
    LineageAliasName,
    LineageAliasUpdateRequest,
    LineageBundle,
    LineageBundleListResponse,
    LineageBundleSnapshotRequest,
    LineageBundleSnapshotResponse,
)
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(prefix="/api/lineage", tags=["lineage"], responses=DEPENDENCY_UNAVAILABLE_RESPONSES)

# Ruff B008: avoid function calls in argument defaults (FastAPI Depends()).
_CORPUS_SCOPE_DEP = Depends()


def _raise_lineage_store_unavailable_if_applicable(exc: BaseException, *, boundary: str) -> None:
    if isinstance(exc, DependencyUnavailableError) and exc.dependency == "lineage_store":
        raise dependency_unavailable_http_exception("lineage_store", boundary=boundary, exc=exc) from exc


async def _scoped_bundle(scope: CorpusScope) -> LineageBundle:
    repo_id = scope.resolved_repo_id
    if not repo_id:
        raise HTTPException(status_code=422, detail="Missing corpus_id (or legacy repo_id)")
    try:
        cfg = await load_scoped_config(repo_id=repo_id)
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise_postgres_unavailable_if_applicable(e, boundary="Lineage API")
        raise
    dataset = _load_dataset(corpus_id=repo_id)
    try:
        return ensure_current_bundle(
            repo_id=repo_id,
            cfg=cfg,
            dataset_rows=[row.model_dump(mode="json", by_alias=True) for row in dataset],
            dataset_path=str(_dataset_path_for_corpus(repo_id)),
        )
    except Exception as e:
        _raise_lineage_store_unavailable_if_applicable(e, boundary="Lineage API current bundle")
        raise


async def _require_repo_id(scope: CorpusScope) -> str:
    repo_id = scope.resolved_repo_id
    if not repo_id:
        raise HTTPException(status_code=422, detail="Missing corpus_id (or legacy repo_id)")
    try:
        await load_scoped_config(repo_id=repo_id)
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise_postgres_unavailable_if_applicable(e, boundary="Lineage API")
        raise
    return repo_id


@router.get("/current", response_model=LineageBundle)
async def get_current_lineage(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> LineageBundle:
    repo_id = await _require_repo_id(scope)
    try:
        bundle = current_bundle(repo_id)
        if bundle is not None:
            return bundle
        return await _scoped_bundle(scope)
    except Exception as e:
        _raise_lineage_store_unavailable_if_applicable(e, boundary="Lineage API current bundle")
        raise


@router.get("/bundles", response_model=LineageBundleListResponse)
async def get_bundles(
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
    limit: int = Query(default=50, ge=1, le=200),
) -> LineageBundleListResponse:
    repo_id = await _require_repo_id(scope)
    try:
        return LineageBundleListResponse(ok=True, bundles=list_bundles(repo_id=repo_id, limit=limit))
    except Exception as e:
        _raise_lineage_store_unavailable_if_applicable(e, boundary="Lineage API bundle list")
        raise


@router.get("/bundle/{bundle_id}", response_model=LineageBundle)
async def get_bundle(bundle_id: str, scope: CorpusScope = _CORPUS_SCOPE_DEP) -> LineageBundle:
    repo_id = await _require_repo_id(scope)
    try:
        return load_bundle(repo_id=repo_id, bundle_id=bundle_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        _raise_lineage_store_unavailable_if_applicable(e, boundary="Lineage API bundle read")
        raise


@router.get("/aliases", response_model=LineageAliasesResponse)
async def get_aliases(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> LineageAliasesResponse:
    repo_id = await _require_repo_id(scope)
    try:
        return LineageAliasesResponse(ok=True, aliases=list_aliases(repo_id=repo_id))
    except Exception as e:
        _raise_lineage_store_unavailable_if_applicable(e, boundary="Lineage API alias list")
        raise


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
    except Exception as e:
        _raise_lineage_store_unavailable_if_applicable(e, boundary="Lineage API alias update")
        raise
    try:
        return LineageAliasesResponse(ok=True, aliases=list_aliases(repo_id=repo_id))
    except Exception as e:
        _raise_lineage_store_unavailable_if_applicable(e, boundary="Lineage API alias update")
        raise


@router.post("/bundle/snapshot", response_model=LineageBundleSnapshotResponse)
async def snapshot_bundle(
    body: LineageBundleSnapshotRequest | None = None,
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> LineageBundleSnapshotResponse:
    bundle = await _scoped_bundle(scope)
    aliases = []
    try:
        for alias in list((body.set_aliases if body is not None else []) or []):
            aliases.append(set_alias(repo_id=str(bundle.repo_id), alias=alias, bundle_id=bundle.bundle_id))
    except Exception as e:
        _raise_lineage_store_unavailable_if_applicable(e, boundary="Lineage API bundle snapshot")
        raise
    return LineageBundleSnapshotResponse(ok=True, bundle=bundle, aliases=aliases)
