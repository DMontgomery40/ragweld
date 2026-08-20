"""Graph-related registered boundary model exports.

These public schemas currently aggregate through tribrid_config_model.py.
This file re-exports them for backwards compatibility.
"""
from server.models.tribrid_config_model import (
    Community,
    Entity,
    GraphNeighborsResponse,
    GraphStats,
    Relationship,
)

__all__ = ["Entity", "Relationship", "Community", "GraphStats", "GraphNeighborsResponse"]
