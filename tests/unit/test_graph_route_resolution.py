"""Every graph URL the operator's browser builds must resolve to the endpoint it names.

Code-graph entity ids are corpus-relative source paths (`server/retrieval/rerank.py::Reranker`)
and carry `/` and `::`. The predecessor of this file matched each route's ``path_regex`` in
isolation, which is not how a request is routed: Starlette walks ``router.routes`` in
declaration order and takes the first FULL match. A greedy ``{entity_id:path}`` segment
declared before its own ``/neighbors`` and ``/relationships`` siblings therefore swallowed
their suffixes into the id, and every code entity 404ed with "Entity not found" while the
bare-entity URL returned 200 (drive finding C-33 / M-01).

Two guards: the concrete matrix of URLs the frontend builds, and the class-level invariant
that no route in the router can be shadowed by a greedy path parameter.
"""

from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Match

from server.api.graph import (
    get_entity,
    get_entity_neighbors,
    get_entity_relationships,
    get_graph_stats,
    get_repo_subgraph,
    list_communities,
    list_entities,
    router,
)

CORPUS = "ragweld_code"
# Real ids from the live `ragweld_code` graph: both a `/`-and-`::` code id and a plain one.
CODE_ENTITY_ID = "server/retrieval/rerank.py::Reranker"
METHOD_ENTITY_ID = "server/services/traces.py::TraceStore.add_event"
PLAIN_ENTITY_ID = "apollo_11"

# (url path, query string, expected endpoint function, expected path params)
ROUTING_MATRIX = [
    (f"/graph/{CORPUS}/entity", f"entity_id={CODE_ENTITY_ID}", get_entity, {"corpus_id": CORPUS}),
    (
        f"/graph/{CORPUS}/entity/neighbors",
        f"entity_id={CODE_ENTITY_ID}&max_hops=2&limit=200",
        get_entity_neighbors,
        {"corpus_id": CORPUS},
    ),
    (
        f"/graph/{CORPUS}/entity/relationships",
        f"entity_id={METHOD_ENTITY_ID}",
        get_entity_relationships,
        {"corpus_id": CORPUS},
    ),
    (
        "/graph/nasa-apollo-11/entity/neighbors",
        f"entity_id={PLAIN_ENTITY_ID}",
        get_entity_neighbors,
        {"corpus_id": "nasa-apollo-11"},
    ),
    (f"/graph/{CORPUS}/entities", "q=reranker&limit=200", list_entities, {"corpus_id": CORPUS}),
    (f"/graph/{CORPUS}/subgraph", "limit=200", get_repo_subgraph, {"corpus_id": CORPUS}),
    (f"/graph/{CORPUS}/communities", "", list_communities, {"corpus_id": CORPUS}),
    (f"/graph/{CORPUS}/stats", "", get_graph_stats, {"corpus_id": CORPUS}),
]


def _resolve(
    path: str, query: str = "", method: str = "GET"
) -> tuple[APIRoute | None, dict[str, str]]:
    """Route exactly as Starlette does: first FULL match in declaration order."""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [],
        "root_path": "",
    }
    for route in router.routes:
        match, child = route.matches(scope)
        if match is Match.FULL:
            return route, dict(child.get("path_params") or {})
    return None, {}


@pytest.mark.parametrize(
    ("path", "query", "endpoint", "path_params"),
    ROUTING_MATRIX,
    ids=[m[0].replace("/", "_") + ("_q" if m[1] else "") for m in ROUTING_MATRIX],
)
def test_frontend_graph_urls_resolve_to_their_endpoint(
    path: str, query: str, endpoint: object, path_params: dict[str, str]
) -> None:
    route, resolved = _resolve(path, query)
    assert route is not None, f"{path} matches no graph route"
    assert route.endpoint is endpoint, (
        f"{path} resolved to {route.path} ({route.endpoint.__name__}), expected {endpoint.__name__}"  # type: ignore[attr-defined]
    )
    assert resolved == path_params


def test_entity_id_never_travels_as_a_path_segment() -> None:
    """A `/`-bearing id in the path is what broke M-01; the contract must forbid it."""
    for route in router.routes:
        assert isinstance(route, APIRoute)
        assert "entity_id" not in route.path, (
            f"{route.path} carries the entity id in the path; ids contain '/' and '::' "
            "and must be passed as a query parameter"
        )


def test_no_route_is_shadowed_by_a_greedy_path_parameter() -> None:
    """Class-level guard: a `{x:path}` segment must not be able to swallow a sibling route.

    `{x:path}` compiles to `.*`, so any route whose literal prefix matches an earlier
    greedy route's prefix is unreachable. Checked against real resolution rather than
    by reading the regex, so it holds for whatever converters are in use.
    """
    routes = [r for r in router.routes if isinstance(r, APIRoute)]
    for route in routes:
        sample = re.sub(r"\{[^}]+\}", "sample", route.path)
        method = next(iter(sorted(route.methods or {"GET"})))
        resolved, _ = _resolve(sample, method=method)
        assert resolved is not None, f"{route.path} matches nothing for {sample}"
        assert resolved is route, f"{route.path} is shadowed: {sample} resolves to {resolved.path}"
