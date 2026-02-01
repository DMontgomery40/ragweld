import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_eval_run_stream_route_not_shadowed(client: AsyncClient) -> None:
    """Regression test for FastAPI route ordering.

    `/api/eval/run/stream` MUST route to the SSE handler, not the dynamic
    `/api/eval/run/{run_id}` handler (which would treat "stream" as a run_id).
    """

    res = await client.get("/api/eval/run/stream")
    assert res.status_code == 422
    body = res.json()
    assert "Missing corpus_id" in str(body.get("detail", ""))

