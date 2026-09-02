"""Answer-lane retrieval either succeeds or raises.

``retrieve_best_effort`` used to convert any retrieval exception it did not recognise
into an empty chunk list plus a ``retrieval_error`` debug entry, and its callers then
generated an answer with no context at all (``has_rag_context=False``) and returned 200.
A caller could not tell that retrieval had failed. Every retrieval failure now leaves
this function as the exception it is, so the API and the MCP answer tool report it.
"""

from __future__ import annotations

import pytest

from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import FusionConfig, TriBridConfig
from server.services.answer_service import retrieve_best_effort

QUESTION = "Which plane management company did Barry Cohen consider switching to?"


class _StoreBrokenFusion:
    """A FusionProtocol whose search fails the way a store would, with an unrecognised type."""

    last_debug: dict[str, object] = {}

    async def search(
        self,
        corpus_ids: list[str],
        query: str,
        config: FusionConfig,
        *,
        include_vector: bool = True,
        include_sparse: bool = True,
        include_graph: bool = True,
        top_k: int | None = None,
        cache_mode: str = "default",
        cache_namespace: str = "search",
    ) -> list[ChunkMatch]:
        raise LookupError(f"collection for {corpus_ids[0]} is missing its sparse generation")


@pytest.mark.asyncio
async def test_an_unrecognised_retrieval_failure_propagates_instead_of_becoming_no_context() -> None:
    with pytest.raises(LookupError, match="sparse generation"):
        await retrieve_best_effort(
            query=QUESTION,
            corpus_id="epstein-files-public",
            config=TriBridConfig(),
            fusion=_StoreBrokenFusion(),
        )
