"""Integration tests for the graph pipeline."""

import pytest

from server.models.graph import Community, Entity, Relationship


@pytest.mark.integration
def test_entity_creation() -> None:
    """Test creating graph entities."""
    entity = Entity(
        entity_id="func-123",
        name="calculate_total",
        entity_type="function",
        file_path="cart.py",
        description="Calculates the total price of items in cart",
        properties={"parameters": ["items"], "returns": "float"},
    )

    assert entity.entity_id == "func-123"
    assert entity.entity_type == "function"


@pytest.mark.integration
def test_relationship_creation() -> None:
    """Test creating relationships between entities."""
    rel = Relationship(
        source_id="class-cart",
        target_id="func-calculate",
        relation_type="contains",
        weight=1.0,
        properties={"visibility": "public"},
    )

    assert rel.relation_type == "contains"
    assert rel.source_id == "class-cart"


@pytest.mark.integration
def test_community_creation() -> None:
    """Test creating community summaries."""
    community = Community(
        community_id="comm-shopping",
        name="Shopping Cart Module",
        summary="Handles cart operations including adding items, calculating totals, and checkout",
        member_ids=["class-cart", "func-add", "func-remove", "func-total"],
        level=0,
    )

    assert len(community.member_ids) == 4
    assert community.level == 0


@pytest.mark.integration
def test_graph_serialization() -> None:
    """Test that graph structures serialize correctly."""
    entities = [
        Entity(
            entity_id=f"e{i}",
            name=f"Entity{i}",
            entity_type="function",
            file_path="test.py",
            description=None,
        )
        for i in range(3)
    ]

    relationships = [
        Relationship(
            source_id="e0",
            target_id="e1",
            relation_type="calls",
        ),
        Relationship(
            source_id="e1",
            target_id="e2",
            relation_type="calls",
        ),
    ]

    # Test JSON serialization
    for entity in entities:
        json_str = entity.model_dump_json()
        restored = Entity.model_validate_json(json_str)
        assert restored.entity_id == entity.entity_id

    for rel in relationships:
        json_str = rel.model_dump_json()
        restored = Relationship.model_validate_json(json_str)
        assert restored.source_id == rel.source_id
