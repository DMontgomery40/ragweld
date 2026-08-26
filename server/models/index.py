"""Index-domain boundary models.

The index API imports its registered boundary schemas from here; the aggregate
(`tribrid_config_model.py`) remains the composition root that registers them
for TypeScript generation.
"""

from server.models.tribrid_config_model import (
    Chunk,
    IndexDeletionIncompleteDetail,
    IndexDeletionIncompleteResponse,
    IndexFenceCorruptDetail,
    IndexRequest,
    IndexRunConflictDetail,
    IndexRunConflictResponse,
    IndexRunEvent,
    IndexRunSummary,
    IndexStats,
    IndexStatus,
)

__all__ = [
    "Chunk",
    "IndexDeletionIncompleteDetail",
    "IndexDeletionIncompleteResponse",
    "IndexFenceCorruptDetail",
    "IndexRequest",
    "IndexRunConflictDetail",
    "IndexRunConflictResponse",
    "IndexRunEvent",
    "IndexRunSummary",
    "IndexStats",
    "IndexStatus",
]
