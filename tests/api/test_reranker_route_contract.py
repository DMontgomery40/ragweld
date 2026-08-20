from __future__ import annotations


async def test_unimplemented_triplet_crud_routes_are_absent(client) -> None:
    from server.main import app

    paths = app.openapi()["paths"]
    assert "/api/reranker/triplets/count" in paths
    assert "/api/reranker/triplets/{repo_id}" not in paths

    get_response = await client.get("/api/reranker/triplets/example-corpus")
    post_response = await client.post(
        "/api/reranker/triplets/example-corpus",
        params={"query": "q", "positive": "p", "negative": "n"},
    )
    assert get_response.status_code == 404
    assert post_response.status_code == 404
