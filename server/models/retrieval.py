"""Retrieval-related registered boundary model exports.

These public schemas currently aggregate through tribrid_config_model.py.
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
