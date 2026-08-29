"""Code-graph entity ids are corpus-relative paths (`server/x.py::Class.method`); the entity routes must match them."""

from __future__ import annotations

from fastapi.routing import APIRoute

from server.api.graph import router

CODE_ENTITY_ID = "server/services/traces.py::TraceStore.add_event"


def _route(path_suffix: str) -> APIRoute:
    for route in router.routes:
        if isinstance(route, APIRoute) and route.path.endswith(path_suffix) and "{entity_id" in route.path:
            return route
    raise AssertionError(f"no entity route ending in {path_suffix!r}")


def test_entity_routes_match_ids_containing_slashes() -> None:
    for suffix, tail in (("/entity/{entity_id:path}", ""), ("/relationships", "/relationships"), ("/neighbors", "/neighbors")):
        route = _route(suffix)
        match = route.path_regex.match(f"/graph/ragweld_code/entity/{CODE_ENTITY_ID}{tail}")
        assert match is not None, f"{route.path} rejects {CODE_ENTITY_ID!r}"
        assert match.group("entity_id") == CODE_ENTITY_ID
        assert match.group("corpus_id") == "ragweld_code"


def test_entity_routes_still_match_plain_ids() -> None:
    route = _route("/neighbors")
    match = route.path_regex.match("/graph/nasa-apollo-11/entity/apollo_11/neighbors")
    assert match is not None and match.group("entity_id") == "apollo_11"
