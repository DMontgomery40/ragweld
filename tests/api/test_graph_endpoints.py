"""API tests for graph endpoints."""

import os
import uuid

import pytest
from httpx import AsyncClient

POSTGRES_CONFIGURED = os.environ.get("POSTGRES_HOST") is not None


@pytest.mark.asyncio
async def test_list_entities(client: AsyncClient) -> None:
    """Test GET /api/graph/{repo_id}/entities returns 404 for missing corpus."""
    if not POSTGRES_CONFIGURED:
        pytest.skip("PostgreSQL not configured (set POSTGRES_HOST)")
    missing_repo_id = f"missing-graph-{uuid.uuid4().hex[:10]}"
    response = await client.get(f"/api/graph/{missing_repo_id}/entities")
    assert response.status_code == 404
    assert str(response.json().get("detail") or "").startswith("Corpus not found:")


@pytest.mark.asyncio
async def test_list_entities_filtered(client: AsyncClient) -> None:
    """Test GET /api/graph/{repo_id}/entities with type filter returns 404 for missing corpus."""
    if not POSTGRES_CONFIGURED:
        pytest.skip("PostgreSQL not configured (set POSTGRES_HOST)")
    missing_repo_id = f"missing-graph-{uuid.uuid4().hex[:10]}"
    response = await client.get(
        f"/api/graph/{missing_repo_id}/entities",
        params={"entity_type": "function", "limit": 10},
    )
    assert response.status_code == 404
    assert str(response.json().get("detail") or "").startswith("Corpus not found:")


@pytest.mark.asyncio
async def test_get_entity(client: AsyncClient) -> None:
    """Test GET /api/graph/{repo_id}/entity/{entity_id} returns 404 for missing corpus."""
    if not POSTGRES_CONFIGURED:
        pytest.skip("PostgreSQL not configured (set POSTGRES_HOST)")
    missing_repo_id = f"missing-graph-{uuid.uuid4().hex[:10]}"
    response = await client.get(f"/api/graph/{missing_repo_id}/entity/entity-123")
    assert response.status_code == 404
    assert str(response.json().get("detail") or "").startswith("Corpus not found:")


@pytest.mark.asyncio
async def test_get_entity_relationships(client: AsyncClient) -> None:
    """Test GET /api/graph/{repo_id}/entity/{entity_id}/relationships returns 404 for missing corpus."""
    if not POSTGRES_CONFIGURED:
        pytest.skip("PostgreSQL not configured (set POSTGRES_HOST)")
    missing_repo_id = f"missing-graph-{uuid.uuid4().hex[:10]}"
    response = await client.get(f"/api/graph/{missing_repo_id}/entity/entity-123/relationships")
    assert response.status_code == 404
    assert str(response.json().get("detail") or "").startswith("Corpus not found:")


@pytest.mark.asyncio
async def test_list_communities(client: AsyncClient) -> None:
    """Test GET /api/graph/{repo_id}/communities returns 404 for missing corpus."""
    if not POSTGRES_CONFIGURED:
        pytest.skip("PostgreSQL not configured (set POSTGRES_HOST)")
    missing_repo_id = f"missing-graph-{uuid.uuid4().hex[:10]}"
    response = await client.get(f"/api/graph/{missing_repo_id}/communities")
    assert response.status_code == 404
    assert str(response.json().get("detail") or "").startswith("Corpus not found:")


@pytest.mark.asyncio
async def test_list_communities_by_level(client: AsyncClient) -> None:
    """Test GET /api/graph/{repo_id}/communities with level filter returns 404 for missing corpus."""
    if not POSTGRES_CONFIGURED:
        pytest.skip("PostgreSQL not configured (set POSTGRES_HOST)")
    missing_repo_id = f"missing-graph-{uuid.uuid4().hex[:10]}"
    response = await client.get(
        f"/api/graph/{missing_repo_id}/communities",
        params={"level": 0},
    )
    assert response.status_code == 404
    assert str(response.json().get("detail") or "").startswith("Corpus not found:")


@pytest.mark.asyncio
async def test_get_graph_stats(client: AsyncClient) -> None:
    """Test GET /api/graph/{repo_id}/stats returns 404 for missing corpus."""
    if not POSTGRES_CONFIGURED:
        pytest.skip("PostgreSQL not configured (set POSTGRES_HOST)")
    missing_repo_id = f"missing-graph-{uuid.uuid4().hex[:10]}"
    response = await client.get(f"/api/graph/{missing_repo_id}/stats")
    assert response.status_code == 404
    assert str(response.json().get("detail") or "").startswith("Corpus not found:")


@pytest.mark.asyncio
async def test_graph_query(client: AsyncClient) -> None:
    """Test POST /api/graph/{repo_id}/query returns 404 for missing corpus."""
    if not POSTGRES_CONFIGURED:
        pytest.skip("PostgreSQL not configured (set POSTGRES_HOST)")
    missing_repo_id = f"missing-graph-{uuid.uuid4().hex[:10]}"
    response = await client.post(
        f"/api/graph/{missing_repo_id}/query",
        params={"cypher": "MATCH (n) RETURN n LIMIT 5"},
    )
    assert response.status_code == 404
    assert str(response.json().get("detail") or "").startswith("Corpus not found:")
