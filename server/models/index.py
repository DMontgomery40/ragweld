"""Index-related models - Re-exported from THE LAW.

All domain models are defined in tribrid_config_model.py (THE LAW).
This file re-exports them for backwards compatibility.
"""
from server.models.tribrid_config_model import (
    Chunk,
    IndexRequest,
    IndexStats,
    IndexStatus,
)

__all__ = ["Chunk", "IndexRequest", "IndexStats", "IndexStatus"]
