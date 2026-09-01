from __future__ import annotations

from types import SimpleNamespace

from server.config import load_config
from server.services.rag import build_chat_debug_info


def test_chat_debug_uses_truthful_qdrant_seeded_graph_counts() -> None:
    fusion = SimpleNamespace(
        last_debug={
            "fusion_vector_enabled": True,
            "fusion_sparse_enabled": True,
            "fusion_graph_enabled": True,
            "fusion_vector_results": 3,
            "fusion_sparse_results": 2,
            "fusion_graph_qdrant_seed_chunks": 5,
            "fusion_graph_resolved_entities": 7,
            "fusion_graph_relationship_expansion_hits": 4,
            "fusion_graph_community_expansion_hits": 0,
            "fusion_graph_hydrated_chunks": 4,
        }
    )

    debug = build_chat_debug_info(
        config=load_config(),
        fusion=fusion,
        include_vector=True,
        include_sparse=True,
        include_graph=True,
        top_k=10,
        sources=[],
    ).model_dump(mode="json")

    assert "graph_entity_hits" not in debug
    assert debug["graph_qdrant_seed_chunks"] == 5
    assert debug["graph_resolved_entities"] == 7
    assert debug["graph_relationship_expansion_hits"] == 4
    assert debug["graph_community_expansion_hits"] == 0
    assert debug["graph_hydrated_chunks"] == 4
