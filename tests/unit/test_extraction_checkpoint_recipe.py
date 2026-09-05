from __future__ import annotations

import hashlib
from importlib.metadata import version

import pytest
from neo4j_graphrag.components.schema import GraphSchema, NodeType, PropertyType, RelationshipType

from server.gateway_reasoning import reasoning_model_params
from server.indexing.graphrag_pipeline import extraction_checkpoint_recipe
from server.indexing.graphrag_schema import closed_graph_schema
from server.models.graph_extraction_checkpoint import (
    GraphExtractionCheckpointRecipe,
    graph_extraction_recipe_hash,
)


def _recipe(**changes):
    arguments = dict(
        schema=GraphSchema(node_types=["Mission"], additional_node_types=False),
        prompt_template="Approved mission extraction: {schema} {text} {examples}", examples="",
        route_model="openai.gpt-5.6-sol", route_upstream="openrouter/openai/gpt-5.6-sol",
        route_base_url="http://127.0.0.1:4000/v1", reasoning_effort="low",
    )
    arguments.update(changes)
    return extraction_checkpoint_recipe(**arguments)


def test_recipe_tracks_exact_official_parameters_and_implementation_versions() -> None:
    recipe = _recipe()
    assert recipe.model_parameters == reasoning_model_params(
        reasoning_effort="low", route_upstream="openrouter/openai/gpt-5.6-sol")
    assert recipe.neo4j_graphrag_version == version("neo4j-graphrag")
    assert recipe.prompt_template_sha256 == hashlib.sha256(
        b"Approved mission extraction: {schema} {text} {examples}").hexdigest()
    assert recipe.examples_sha256 == hashlib.sha256(b"").hexdigest()


@pytest.mark.parametrize("changes", [
    {"route_model": "openai.gpt-5.6-luna"},
    {"route_upstream": "openrouter/openai/gpt-5.6-luna"},
    {"route_base_url": "http://127.0.0.1:4001/v1"},
    {"reasoning_effort": "medium"},
    {"prompt_template": "Extract explicit facts only: {schema} {text} {examples}"},
    {"examples": "Apollo 11 used Eagle."},
    {"schema": GraphSchema(node_types=["Mission", "Spacecraft"], additional_node_types=False)},
])
def test_changed_approved_recipe_input_invalidates_reuse(changes) -> None:
    assert graph_extraction_recipe_hash(_recipe(**changes)) != graph_extraction_recipe_hash(_recipe())


@pytest.mark.parametrize("endpoint", [
    "http://credential:secret@127.0.0.1:4000/v1", "http://127.0.0.1/v1?key=secret",
    "http://127.0.0.1/v1#private", "file:///tmp/provider",
])
def test_recipe_refuses_unsanitized_provider_endpoint(endpoint: str) -> None:
    with pytest.raises(ValueError):
        _recipe(route_base_url=endpoint)


def test_explicitly_closed_empty_property_relationship_survives_recipe_persistence() -> None:
    approved = closed_graph_schema(GraphSchema(
        node_types=[NodeType(label=label, properties=[PropertyType(name="name", type="STRING")])
                    for label in ("Mission", "Spacecraft")],
        relationship_types=[RelationshipType(label="USED", properties=[])],
        patterns=[("Mission", "USED", "Spacecraft")],
    ))
    assert approved.relationship_types[0].properties == []
    assert approved.relationship_types[0].additional_properties is False
    recipe = _recipe(schema=approved)
    payload = recipe.model_dump(mode="json")
    assert payload["approved_schema"]["relationship_types"][0]["additional_properties"] is False
    reloaded = GraphExtractionCheckpointRecipe.model_validate(payload)
    assert reloaded.model_dump(mode="json") == payload
    assert reloaded.approved_schema.relationship_types[0].additional_properties is False
    assert graph_extraction_recipe_hash(reloaded) == graph_extraction_recipe_hash(recipe)
