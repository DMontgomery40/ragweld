from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from server.models.tribrid_config_model import (
    ObservabilityAlertRulesResponse,
    ObservabilityCatalogResponse,
    ObservabilityIncidentsResponse,
    ObservabilityStatusResponse,
    TriBridConfig,
)
from server.observability.alert_rules import build_alert_rules
from server.observability.catalog import build_observability_catalog
from server.observability.incidents import build_observability_incidents
from server.observability.status import build_observability_status
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(prefix="/api/observability", tags=["observability"])


@router.get("/status", response_model=ObservabilityStatusResponse)
async def observability_status(
    repo: str | None = Query(default=None, description="Optional corpus_id to scope config"),
    corpus_id: str | None = Query(default=None, description="Alias for repo"),
    repo_id: str | None = Query(default=None, description="Alias for corpus_id"),
) -> ObservabilityStatusResponse:
    scope_id = (repo or corpus_id or repo_id or "").strip() or None
    try:
        cfg = await load_scoped_config(repo_id=scope_id)
    except CorpusNotFoundError:
        cfg = await load_scoped_config(repo_id=None)
    incidents = await build_observability_incidents(cfg, repo_id=scope_id)
    status = await build_observability_status(cfg, repo_id=scope_id)
    status.incident_count = int(incidents.total_count or 0)
    status.critical_incident_count = int(incidents.critical_count or 0)
    return status


@router.get("/catalog", response_model=ObservabilityCatalogResponse)
async def observability_catalog(
    repo: str | None = Query(default=None, description="Optional corpus_id to scope config"),
    corpus_id: str | None = Query(default=None, description="Alias for repo"),
    repo_id: str | None = Query(default=None, description="Alias for corpus_id"),
) -> ObservabilityCatalogResponse:
    scope_id = (repo or corpus_id or repo_id or "").strip() or None
    try:
        cfg = await load_scoped_config(repo_id=scope_id)
    except CorpusNotFoundError:
        cfg = await load_scoped_config(repo_id=None)
    return build_observability_catalog(cfg)


@router.get("/alert-rules", response_model=ObservabilityAlertRulesResponse)
async def observability_alert_rules(
    repo: str | None = Query(default=None, description="Optional corpus_id to scope config"),
    corpus_id: str | None = Query(default=None, description="Alias for repo"),
    repo_id: str | None = Query(default=None, description="Alias for corpus_id"),
) -> ObservabilityAlertRulesResponse:
    """Alerting rules as Prometheus evaluates them right now (the real alert configuration).

    Reads ``tracing.prometheus_base_url`` from the same config scope the
    Monitoring page saves it to; an unknown corpus is a 404, never a silent
    fall-back to the global config.
    """
    scope_id = (repo or corpus_id or repo_id or "").strip() or None
    try:
        cfg = await load_scoped_config(repo_id=scope_id)
    except CorpusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await build_alert_rules(cfg)


@router.get("/incidents", response_model=ObservabilityIncidentsResponse)
async def observability_incidents(
    repo: str | None = Query(default=None, description="Optional corpus_id to scope incident correlation"),
    corpus_id: str | None = Query(default=None, description="Alias for repo"),
    repo_id: str | None = Query(default=None, description="Alias for corpus_id"),
) -> ObservabilityIncidentsResponse:
    scope_id = (repo or corpus_id or repo_id or "").strip() or None
    try:
        cfg = await load_scoped_config(repo_id=scope_id)
    except CorpusNotFoundError:
        cfg = await load_scoped_config(repo_id=None)
    return await build_observability_incidents(cfg, repo_id=scope_id)
