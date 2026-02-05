from __future__ import annotations

import time

import pytest


@pytest.mark.asyncio
async def test_prompts_list_update_reset(client, tmp_path) -> None:
    corpus_id = f"test_prompts_{int(time.time() * 1000)}"

    # Create a real corpus so corpus-scoped config exists.
    create = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(tmp_path), "description": None},
    )
    assert create.status_code == 200

    try:
        r = await client.get("/api/prompts", params={"corpus_id": corpus_id})
        assert r.status_code == 200
        data = r.json()

        prompts = data.get("prompts") or {}
        meta = data.get("metadata") or {}

        assert "main_rag_chat" in prompts
        assert "eval_analysis" in prompts
        assert "semantic_kg_extraction" in prompts
        assert "chat.system_prompt_base" in prompts
        assert "chat.system_prompt_direct" in prompts
        assert "chat.system_prompt_rag_suffix" in prompts
        assert "chat.system_prompt_recall_suffix" in prompts

        assert "main_rag_chat" in meta
        assert "eval_analysis" in meta
        assert "semantic_kg_extraction" in meta
        assert "chat.system_prompt_base" in meta
        assert "chat.system_prompt_direct" in meta
        assert "chat.system_prompt_rag_suffix" in meta
        assert "chat.system_prompt_recall_suffix" in meta

        # Chat prompts are read-only in this tab and should include a link to Chat Settings.
        chat_meta = meta["chat.system_prompt_direct"]
        assert chat_meta.get("editable") is False
        assert isinstance(chat_meta.get("link_route"), str) and chat_meta["link_route"]

        # Attempting to edit chat prompts via /api/prompts is rejected.
        put_chat = await client.put(
            "/api/prompts/chat.system_prompt_direct",
            params={"corpus_id": corpus_id},
            json={"value": "nope"},
        )
        assert put_chat.status_code == 403

        # Update a system prompt and verify persistence.
        original = str(prompts.get("query_rewrite") or "")
        updated = original + "\n\n# pytest"

        put = await client.put(
            "/api/prompts/query_rewrite",
            params={"corpus_id": corpus_id},
            json={"value": updated},
        )
        assert put.status_code == 200
        assert put.json().get("ok") is True

        after_put = await client.get("/api/prompts", params={"corpus_id": corpus_id})
        assert after_put.status_code == 200
        assert (after_put.json().get("prompts") or {}).get("query_rewrite") == updated

        # Reset restores the original LAW default.
        reset = await client.post("/api/prompts/reset/query_rewrite", params={"corpus_id": corpus_id})
        assert reset.status_code == 200
        assert reset.json().get("ok") is True

        after_reset = await client.get("/api/prompts", params={"corpus_id": corpus_id})
        assert after_reset.status_code == 200
        assert (after_reset.json().get("prompts") or {}).get("query_rewrite") == original
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
