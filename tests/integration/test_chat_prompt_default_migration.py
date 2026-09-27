"""Retired shipped chat defaults migrate without changing operator prompts."""

import json
from uuid import uuid4

import pytest
import pytest_asyncio

from server.config import DEFAULT_CONFIG_PATH, load_config
from server.models.tribrid_config_model import ChatConfig
from server.services.config_store import ConfigStore


pytestmark = [pytest.mark.asyncio, pytest.mark.requires_postgres]

# Exact defaults shipped at ac428f5, independent of the migration hash registry.
RETIRED_PROMPTS = {
    "system_prompt_rag": """You are a database assistant powered by ragweld, a hybrid retrieval system that combines vector search, keyword search, and knowledge graphs to find relevant database.

The user has selected one or more database repositories to query. You will receive relevant database snippets in <rag_context>...</rag_context> tags.

Each snippet includes:
- File path and line numbers

How to use this context:
- Base your answers on the actual database shown, not assumptions
- Always cite file paths and line numbers when referencing database
- If the retrieved information doesn't fully answer the question, say what's missing
- Don't invent information that isn't in the context
- **Connect related pieces when they appear across multiple snippets** (e.g. if the user asks about a specific database table, and you have information about the table in the context, connect the information to the question)

Be helpful, friendly, and engaging, and base your answers on the actual database information you have.""",
    "system_prompt_rag_and_recall": """You are an agentic RAG database assistant powered by ragweld, a hybrid retrieval system. You have access to both:
1) The user's indexed database repositories
2) Your conversation history with this user (Recall)

database context appears in <rag_context>...</rag_context> tags.
Conversation history appears in <recall_context>...</recall_context> tags.

How to use both:
- Reference past discussions naturally
- Connect them when relevant (e.g., a past decision and the database information that implements it)
- If past context contradicts current database information, acknowledge the change
- Don't say "according to recall" — just incorporate shared knowledge naturally

Be helpful, friendly, and engaging, and base your answers on the actual database information you have.""",
}


@pytest_asyncio.fixture
async def stored_chat_config():
    cfg = load_config()
    store = ConfigStore(cfg.indexing.postgres_url)
    cid = f"pytest_chat_prompt_migration_{uuid4().hex}"
    await store._postgres.connect()
    await store._postgres.upsert_corpus(cid, name=cid, root_path=".")
    try:
        yield store, cid, cfg.model_dump(mode="json")
    finally:
        await store._postgres.delete_corpus(cid)
        await store._postgres.disconnect()


@pytest.mark.parametrize("field", RETIRED_PROMPTS)
async def test_stored_retired_default_migrates_and_persists_once(stored_chat_config, field):
    store, cid, raw = stored_chat_config
    raw["chat"][field] = RETIRED_PROMPTS[field]
    other = next(key for key in RETIRED_PROMPTS if key != field)
    raw["chat"][other] = "Operator-owned instructions for the other context mode."
    raw["chat"]["system_prompt_direct"] = "Operator-owned direct prompt."
    raw["chat"]["system_prompt_recall"] = "Operator-owned recall prompt."
    await store._postgres.upsert_corpus_config_json(cid, raw)
    before = await store._postgres.get_corpus_config_json(cid)
    disk_before = DEFAULT_CONFIG_PATH.read_bytes()

    preview = await store.get(cid, persist=False)
    assert getattr(preview.chat, field) == getattr(ChatConfig(), field)
    assert preview.chat.system_prompt_direct == raw["chat"]["system_prompt_direct"]
    assert preview.chat.system_prompt_recall == raw["chat"]["system_prompt_recall"]
    assert getattr(preview.chat, other) == raw["chat"][other]
    assert await store._postgres.get_corpus_config_json(cid) == before
    assert DEFAULT_CONFIG_PATH.read_bytes() == disk_before
    assert store._cache == {}

    upgraded = await store.get(cid)
    saved = await store._postgres.get_corpus_config_json(cid)
    assert saved is not None
    assert saved["chat"][field] == getattr(ChatConfig(), field)
    assert saved["chat"][other] == raw["chat"][other]
    assert (await store.get(cid)).chat == upgraded.chat
    store.clear_cache(cid)
    assert (await store.get(cid)).chat == upgraded.chat
    assert await store._postgres.get_corpus_config_json(cid) == saved


@pytest.mark.parametrize("field", RETIRED_PROMPTS)
@pytest.mark.parametrize("edit", ["leading_space", "trailing_space", "custom_instruction"])
async def test_stored_operator_edit_of_retired_default_is_preserved(stored_chat_config, field, edit):
    store, cid, raw = stored_chat_config
    old = RETIRED_PROMPTS[field]
    custom = {
        "leading_space": " " + old,
        "trailing_space": old + " ",
        "custom_instruction": old + "\nUse the operator's citation style.",
    }[edit]
    raw["chat"][field] = custom
    await store._postgres.upsert_corpus_config_json(cid, raw)

    loaded = await store.get(cid)

    assert getattr(loaded.chat, field) == custom
    assert (await store._postgres.get_corpus_config_json(cid))["chat"][field] == custom


@pytest.mark.parametrize("field", RETIRED_PROMPTS)
async def test_flat_loader_migrates_only_the_exact_retired_default(tmp_path, field):
    path = tmp_path / "config.json"
    raw = load_config().model_dump(mode="json")
    raw["chat"][field] = RETIRED_PROMPTS[field]
    path.write_text(json.dumps(raw))
    original_bytes = path.read_bytes()

    assert getattr(load_config(path).chat, field) == getattr(ChatConfig(), field)
    assert path.read_bytes() == original_bytes

    raw["chat"][field] += " "
    path.write_text(json.dumps(raw))
    assert getattr(load_config(path).chat, field) == raw["chat"][field]
