"""Retrieval-related models - Re-exported from THE LAW.

All domain models are defined in tribrid_config_model.py (THE LAW).
This file re-exports them for backwards compatibility.
"""
from server.models.tribrid_config_model import (
    AnswerRequest,
    AnswerResponse,
    ChunkMatch,
    SearchRequest,
    SearchResponse,
)

__all__ = ["ChunkMatch", "SearchRequest", "SearchResponse", "AnswerRequest", "AnswerResponse"]
