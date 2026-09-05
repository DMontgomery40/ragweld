from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from httpx import AsyncClient

from server.db.postgres import PostgresClient
from server.services.config_store import get_config_store
from tests.service_requirements import require_env
from tests.unit.test_graphrag_schema_transport import proposal_gateway

pytestmark = [pytest.mark.asyncio, pytest.mark.requires_postgres]


@pytest.fixture(autouse=True)
def _corpus_scoped_gateway_environment() -> Iterator[None]:
    original = os.environ.pop("LITELLM_BASE_URL", None)
    try:
        yield
    finally:
        if original is not None:
            os.environ["LITELLM_BASE_URL"] = original


async def _create_corpus(client: AsyncClient, path: Path, gateway_url: str) -> str:
    assert not os.environ.get("LITELLM_BASE_URL"), "controlled HTTP fixtures require the corpus-scoped gateway URL"
    corpus_id = f"pytest_schema_transport_{uuid4().hex[:8]}"
    (path / "mission.md").write_text("The orbital survey mission uses a radar altimeter. The altimeter measures surface altitude.")
    created = await client.post("/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": str(path)})
    assert created.status_code in (200, 201), created.text
    chat = await client.patch(f"/api/config/chat?corpus_id={corpus_id}", json={"litellm": {"base_url": gateway_url}})
    assert chat.status_code == 200, chat.text
    graph = await client.patch(f"/api/config/graph_indexing?corpus_id={corpus_id}", json={
        "enabled": True, "build_code_graph": False, "semantic_kg_llm_model": "openai.gpt-5.6-sol",
    })
    assert graph.status_code == 200, graph.text
    return corpus_id


@pytest.mark.parametrize("observation", [0, 1])
@pytest.mark.parametrize("stage", ["corpus", "config_corpus", "config_json", "proposal"])
async def test_saved_proposal_postgres_disconnect_is_typed_at_each_observation(
    client: AsyncClient, tmp_path: Path, observation: int, stage: str,
) -> None:
    """Queue real SQL locks to advance one read, then kill only its owned backend.

    Each observation reads corpus context, checks the scoped config's corpus,
    and retrieves the proposal. Config JSON is uncached at both observations.
    No application callable or database result is replaced by this fixture.
    """
    corpus_id = await _create_corpus(client, tmp_path, "http://127.0.0.1:1/v1")
    store = get_config_store()
    store.clear_cache(corpus_id)
    postgres = PostgresClient(require_env("POSTGRES_DSN"))
    await postgres.connect()  # Schema bootstrap precedes the selective SELECT locks.
    controls = [await asyncpg.connect(require_env("POSTGRES_DSN")) for _ in range(2)]
    control_pids = [connection.get_server_pid() for connection in controls]
    transactions = [None, None]
    pending = None
    queued = None

    async def blocked_reader(table: str) -> int:
        async with asyncio.timeout(5):
            while True:
                await controls[holder].execute("SELECT pg_stat_clear_snapshot()")
                rows = await controls[holder].fetch(
                    "SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
                    "AND wait_event_type='Lock' AND NOT (pid=ANY($1::int[])) "
                    "AND query LIKE $2",
                    control_pids,
                    "%SELECT config FROM corpus_configs%" if table == "corpus_configs"
                    else "%SELECT repo_id, name, root_path%",
                )
                if rows:
                    assert len(rows) == 1, "the fixture must identify exactly one owned reader"
                    return rows[0]["pid"]
                assert pending is not None and not pending.done()
                await asyncio.sleep(0.01)

    try:
        holder = 0
        transactions[holder] = controls[holder].transaction()
        await transactions[holder].start()
        await controls[holder].execute("LOCK TABLE corpora IN ACCESS EXCLUSIVE MODE")
        pending = asyncio.create_task(client.get(f"/api/index/{corpus_id}/graph-schema/proposal"))
        target = observation * 3 + {"corpus": 1, "config_corpus": 2, "config_json": 2, "proposal": 3}[stage]
        for ordinal in range(1, target + 1):
            victim = await blocked_reader("corpora")
            if ordinal == 3:
                # The first config has already been consumed. Force an actual
                # config JSON read in the second observation as well.
                store.clear_cache(corpus_id)
            if ordinal == target:
                break
            next_holder = 1 - holder
            transactions[next_holder] = controls[next_holder].transaction()
            await transactions[next_holder].start()
            queued = asyncio.create_task(controls[next_holder].execute("LOCK TABLE corpora IN ACCESS EXCLUSIVE MODE"))
            async with asyncio.timeout(5):
                while True:
                    await controls[holder].execute("SELECT pg_stat_clear_snapshot()")
                    if await controls[holder].fetchval(
                        "SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=$1", control_pids[next_holder],
                    ):
                        break
                    await asyncio.sleep(0.01)
            # The exclusive waiter queues behind the current SELECT, so the
            # following SELECT cannot race past the next controlled barrier.
            await transactions[holder].rollback()
            transactions[holder] = None
            await queued
            queued = None
            holder = next_holder
        if stage == "config_json":
            next_holder = 1 - holder
            transactions[next_holder] = controls[next_holder].transaction()
            await transactions[next_holder].start()
            await controls[next_holder].execute("LOCK TABLE corpus_configs IN ACCESS EXCLUSIVE MODE")
            await transactions[holder].rollback()
            transactions[holder] = None
            holder = next_holder
            victim = await blocked_reader("corpus_configs")
        assert victim not in control_pids
        assert await controls[holder].fetchval("SELECT pg_terminate_backend($1)", victim)
        response = await asyncio.wait_for(pending, 5)
        assert response.status_code == 503, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "dependency_unavailable"
        assert detail["dependency"] == "postgres"
        assert detail["retryable"] is True
        assert detail["operation"] == "get_graph_schema_proposal"
        assert "operator_hint" in detail
        assert require_env("POSTGRES_DSN") not in response.text
    finally:
        if queued is not None:
            queued.cancel()
            await asyncio.gather(queued, return_exceptions=True)
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        for connection, transaction in zip(controls, transactions, strict=True):
            if transaction is not None:
                await transaction.rollback()
            await connection.close()
        await postgres.disconnect()
        store.clear_cache(corpus_id)
        await client.delete(f"/api/corpora/{corpus_id}")


async def test_proposal_deadline_includes_locked_postgres_persistence(
    client: AsyncClient, tmp_path: Path,
) -> None:
    """The gateway answers promptly, but an actual row lock delays the final write."""
    with proposal_gateway("valid") as (url, requests):
        corpus_id = await _create_corpus(client, tmp_path, url)
        connection = await asyncpg.connect(require_env("POSTGRES_DSN"))
        pending = None
        transaction = None
        try:
            endpoint = f"/api/index/{corpus_id}/graph-schema/proposal"
            first = await client.post(endpoint, json={"force_refresh": True})
            assert first.status_code == 200, first.text
            first_attempt = await client.get(f"/api/index/{corpus_id}/runs/{first.json()['accounting_run_id']}")
            assert first_attempt.status_code == 200, first_attempt.text
            assert first.json()["accounting_started_at"] == first_attempt.json()["started_at"]
            configured = await client.patch(f"/api/config/graph_indexing?corpus_id={corpus_id}", json={"schema_proposal_timeout_s": 5})
            assert configured.status_code == 200, configured.text
            before = await connection.fetchval("SELECT meta FROM corpora WHERE repo_id=$1", corpus_id)
            async with AsyncClient() as control:
                await control.post(f"{url}/__fixture__/scenario", json={"scenario": "held_valid"})
                requests.clear()
                started = asyncio.get_running_loop().time()
                pending = asyncio.create_task(client.post(endpoint, json={"force_refresh": True}))
                async with asyncio.timeout(3):
                    while not requests:
                        await asyncio.sleep(0.01)
                transaction = connection.transaction()
                await transaction.start()
                await connection.fetchval("SELECT meta FROM corpora WHERE repo_id=$1 FOR UPDATE", corpus_id)
                await control.post(f"{url}/__fixture__/release", json={})
                # Keep the lock through the response: the deadline must cancel the
                # blocked native SQL transaction, not merely its provider request.
                response = await asyncio.wait_for(pending, timeout=7)
            assert response.status_code == 504, response.text
            assert asyncio.get_running_loop().time() - started < 7
            detail = response.json()["detail"]
            assert detail["code"] == "graph_schema_deadline_exceeded"
            assert detail["accounting_run_id"] != first.json()["accounting_run_id"]
            attempt = await client.get(f"/api/index/{corpus_id}/runs/{detail['accounting_run_id']}")
            assert attempt.status_code == 200, attempt.text
            assert detail["accounting_started_at"] == attempt.json()["started_at"]
            assert attempt.json()["status"] == "error"
            checkpoint = attempt.json()["accounting"]["census"]["schema_proposal"]
            assert checkpoint["started_requests"] == checkpoint["completed_requests"] == 1
            assert checkpoint["inflight"] == checkpoint["active_producers"] == 0
            assert await connection.fetchval("SELECT meta FROM corpora WHERE repo_id=$1", corpus_id) == before
            await transaction.rollback()
            transaction = None
            # Cancellation must not leave a deferred write that wins when unlocked.
            assert await connection.fetchval("SELECT meta FROM corpora WHERE repo_id=$1", corpus_id) == before
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            if transaction is not None:
                await transaction.rollback()
            await connection.close()
            await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.parametrize("config_delay", [2, 6])
async def test_proposal_config_loading_consumes_the_scoped_total_budget(
    client: AsyncClient, tmp_path: Path, config_delay: int,
) -> None:
    with proposal_gateway("held_valid") as (url, requests):
        corpus_id = await _create_corpus(client, tmp_path, url)
        configured = await client.patch(f"/api/config/graph_indexing?corpus_id={corpus_id}", json={"schema_proposal_timeout_s": 5})
        assert configured.status_code == 200, configured.text
        connection = await asyncpg.connect(require_env("POSTGRES_DSN"))
        transaction = connection.transaction()
        pending = None
        try:
            await transaction.start()
            await connection.execute("LOCK TABLE corpora IN ACCESS EXCLUSIVE MODE")
            started = asyncio.get_running_loop().time()
            pending = asyncio.create_task(client.post(f"/api/index/{corpus_id}/graph-schema/proposal", json={"force_refresh": True}))
            # This is an actual config/corpus SELECT blocked by our table lock.
            async with asyncio.timeout(2):
                while not await connection.fetchval("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND pid<>pg_backend_pid())"):
                    await asyncio.sleep(0.01)
            await asyncio.sleep(config_delay)
            assert not requests
            await transaction.rollback()
            transaction = None
            response = await asyncio.wait_for(pending, timeout=6)
            elapsed = asyncio.get_running_loop().time() - started
            assert response.status_code == 504, response.text
            expected_duration = max(5, config_delay)
            assert expected_duration - 0.5 <= elapsed < expected_duration + 1.5, f"config time was not charged to the 5s total: {elapsed}"
            assert len(requests) == (1 if config_delay < 5 else 0)
            attempt_id = response.json()["detail"]["accounting_run_id"]
            retained = await client.get(f"/api/index/{corpus_id}/runs/{attempt_id}")
            assert retained.status_code == 200
            assert response.json()["detail"]["accounting_started_at"] == retained.json()["started_at"]
            assert retained.json()["status"] == "error"
            if config_delay >= 5:
                # No model dispatch occurred before we discovered the expired
                # scoped budget, so retain the attempt without inventing a census.
                assert retained.json()["accounting"] is None
        finally:
            if transaction is not None:
                await transaction.rollback()
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            async with AsyncClient() as control:
                await control.post(f"{url}/__fixture__/release", json={})
            await connection.close()
            await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.parametrize(("scenario", "status", "code"), [
    ("malformed", 502, "graph_schema_generation_failed"),
    ("truncated", 502, "graph_schema_generation_failed"),
    ("oversized", 502, "graph_schema_generation_failed"),
    ("429", 502, "graph_schema_generation_failed"),
    ("503", 502, "graph_schema_generation_failed"),
    ("disconnect", 502, "graph_schema_generation_failed"),
    ("slow", 504, "graph_schema_deadline_exceeded"),
])
async def test_proposal_failure_is_typed_and_preserves_the_previous_proposal(
    client: AsyncClient, tmp_path: Path, scenario: str, status: int, code: str,
) -> None:
    with proposal_gateway("valid") as (url, _requests):
        corpus_id = await _create_corpus(client, tmp_path, url)
        try:
            endpoint = f"/api/index/{corpus_id}/graph-schema/proposal"
            first = await client.post(endpoint, json={"force_refresh": True})
            assert first.status_code == 200, first.text
            first_payload = first.json()
            first_attempt = await client.get(f"/api/index/{corpus_id}/runs/{first_payload['accounting_run_id']}")
            assert first_attempt.status_code == 200, first_attempt.text
            assert first_payload["accounting_started_at"] == first_attempt.json()["started_at"]
            cached = await client.post(endpoint, json={"force_refresh": False})
            assert cached.status_code == 200, cached.text
            assert cached.json()["accounting_run_id"] == first_payload["accounting_run_id"]
            assert cached.json()["accounting_started_at"] == first_payload["accounting_started_at"]
            async with AsyncClient() as control:
                await control.post(f"{url}/__fixture__/scenario", json={"scenario": scenario})
            configured = await client.patch(f"/api/config/graph_indexing?corpus_id={corpus_id}", json={"schema_proposal_timeout_s": 5})
            assert configured.status_code == 200, configured.text
            started = asyncio.get_running_loop().time()
            failed = await client.post(endpoint, json={"force_refresh": True})
            elapsed = asyncio.get_running_loop().time() - started
            assert failed.status_code == status, failed.text
            assert failed.json()["detail"]["code"] == code
            assert "operator_hint" in failed.json()["detail"]
            attempt_id = failed.json()["detail"]["accounting_run_id"]
            assert attempt_id and attempt_id != first.json()["accounting_run_id"]
            attempt = await client.get(f"/api/index/{corpus_id}/runs/{attempt_id}")
            assert attempt.status_code == 200, attempt.text
            saved_attempt = attempt.json()
            assert saved_attempt["run_kind"] == "schema_proposal"
            assert saved_attempt["status"] == "error"
            assert failed.json()["detail"]["accounting_started_at"] == saved_attempt["started_at"]
            assert saved_attempt["accounting"]["session_id"] == attempt_id
            assert saved_attempt["accounting"]["gateway_base_url"] == url.removesuffix("/v1")
            census = saved_attempt["accounting"]["census"]["schema_proposal"]
            assert census["started_requests"] == census["completed_requests"] == 1
            assert census["inflight"] == census["active_producers"] == 0
            latest_attempt = await client.get(f"/api/index/{corpus_id}/runs/latest", params={"run_kind": "schema_proposal"})
            assert latest_attempt.status_code == 200 and latest_attempt.json()["run_id"] == attempt_id
            assert "PRIVATE PROVIDER DETAIL" not in failed.text
            assert elapsed < 7
            pg = PostgresClient(require_env("POSTGRES_DSN"))
            await pg.connect()
            try:
                persisted = await pg.get_graph_schema_proposal(corpus_id)
                assert persisted is not None
                assert persisted.schema_hash == first.json()["schema_hash"]
                assert persisted.created_at.isoformat() == first.json()["created_at"].replace("Z", "+00:00")
            finally:
                await pg.disconnect()
        finally:
            await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.parametrize("changed_context", ["output_budget", "proposal_reasoning", "policy"])
async def test_inflight_proposal_cannot_persist_after_its_context_changes(
    client: AsyncClient, tmp_path: Path, changed_context: str,
) -> None:
    with proposal_gateway("held_valid") as (url, requests):
        corpus_id = await _create_corpus(client, tmp_path, url)
        pending = asyncio.create_task(client.post(f"/api/index/{corpus_id}/graph-schema/proposal", json={"force_refresh": True}))
        try:
            async with asyncio.timeout(30):
                while not requests:
                    await asyncio.sleep(0.01)
            changes = {
                "output_budget": {"schema_proposal_max_output_tokens": 8192},
                "proposal_reasoning": {"schema_proposal_reasoning_effort": "high"},
                "policy": {"enabled": False},
            }[changed_context]
            configured = await client.patch(f"/api/config/graph_indexing?corpus_id={corpus_id}", json=changes)
            assert configured.status_code == 200, configured.text
            async with AsyncClient() as control:
                await control.post(f"{url}/__fixture__/release", json={})
            response = await pending
            assert response.status_code == 409, response.text
            detail = response.json()["detail"]
            assert detail["code"] == "graph_schema_context_changed"
            attempt = await client.get(f"/api/index/{corpus_id}/runs/{detail['accounting_run_id']}")
            assert attempt.status_code == 200, attempt.text
            assert detail["accounting_started_at"] == attempt.json()["started_at"]
            pg = PostgresClient(require_env("POSTGRES_DSN"))
            await pg.connect()
            try:
                assert await pg.get_graph_schema_proposal(corpus_id) is None
            finally:
                await pg.disconnect()
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.parametrize("effort", [None, "minimal", "low", "medium", "high", "xhigh"])
async def test_proposal_uses_its_own_persisted_reasoning_effort(
    client: AsyncClient, tmp_path: Path, effort: str | None,
) -> None:
    with proposal_gateway("valid") as (url, requests):
        corpus_id = await _create_corpus(client, tmp_path, url)
        try:
            changes = {"semantic_kg_reasoning_effort": "high"}
            if effort is not None:
                changes["schema_proposal_reasoning_effort"] = effort
            configured = await client.patch(f"/api/config/graph_indexing?corpus_id={corpus_id}", json=changes)
            assert configured.status_code == 200, configured.text
            proposal = await client.post(f"/api/index/{corpus_id}/graph-schema/proposal", json={"force_refresh": True})
            assert proposal.status_code == 200, proposal.text
            assert len(requests) == 1
            assert requests[0]["reasoning"] == {"effort": effort or "low"}
            reloaded = await client.get(f"/api/config?corpus_id={corpus_id}")
            assert reloaded.status_code == 200, reloaded.text
            assert reloaded.json()["graph_indexing"]["schema_proposal_reasoning_effort"] == (effort or "low")
            assert reloaded.json()["graph_indexing"]["semantic_kg_reasoning_effort"] == "high"
        finally:
            await client.delete(f"/api/corpora/{corpus_id}")
