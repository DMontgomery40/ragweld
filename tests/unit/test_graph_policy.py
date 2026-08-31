import pytest

from server.indexing.graph_policy import require_graph_chunk_ceiling, resolve_graph_policy


def test_graph_policy_matrix_has_no_internal_or_chunk_only_semantic_trap() -> None:
    assert resolve_graph_policy(internal=True, enabled=True, build_code_graph=False) == "excluded"
    assert resolve_graph_policy(internal=True, enabled=True, build_code_graph=True) == "excluded"
    assert resolve_graph_policy(internal=False, enabled=False, build_code_graph=False) == "off"
    assert resolve_graph_policy(internal=False, enabled=True, build_code_graph=False) == "semantic"
    assert resolve_graph_policy(internal=False, enabled=True, build_code_graph=True) == "code"


def test_semantic_chunk_ceiling_refuses_oversize_scope_instead_of_slicing() -> None:
    assert require_graph_chunk_ceiling(policy="semantic", eligible_chunks=40_000, ceiling=40_000) == 40_000
    with pytest.raises(ValueError, match="40,001 eligible chunks exceeds the semantic graph ceiling of 40,000"):
        require_graph_chunk_ceiling(policy="semantic", eligible_chunks=40_001, ceiling=40_000)


@pytest.mark.parametrize("policy", ["code", "off", "excluded"])
def test_nonsemantic_policy_has_no_semantic_chunk_scope(policy: str) -> None:
    assert require_graph_chunk_ceiling(policy=policy, eligible_chunks=100_000, ceiling=1) == 0
