from typing import Literal


GraphPolicy = Literal["semantic", "code", "off", "excluded"]


class GraphChunkCeilingExceeded(ValueError):
    pass


def resolve_graph_policy(*, internal: bool, enabled: bool, build_code_graph: bool) -> GraphPolicy:
    if internal:
        return "excluded"
    if not enabled:
        return "off"
    return "code" if build_code_graph else "semantic"


def require_graph_chunk_ceiling(
    *, policy: GraphPolicy | str, eligible_chunks: int, ceiling: int
) -> int:
    if policy != "semantic":
        return 0
    if eligible_chunks > ceiling:
        raise GraphChunkCeilingExceeded(
            f"{eligible_chunks:,} eligible chunks exceeds the semantic graph ceiling of {ceiling:,}; "
            "refusing to slice a partial graph"
        )
    return eligible_chunks
