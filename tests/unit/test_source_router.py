"""Tests for chat source routing (ActiveSources -> corpus_ids)."""

from server.chat.source_router import resolve_sources
from server.models.chat_config import ActiveSources


def test_resolve_sources_dedupes_and_filters_empty() -> None:
    sources = ActiveSources(corpus_ids=["", "a", "a", "b", " ", "b"])
    assert resolve_sources(sources) == ["a", "b"]


def test_resolve_sources_preserves_order() -> None:
    sources = ActiveSources(corpus_ids=["b", "a", "b", "c"])
    assert resolve_sources(sources) == ["b", "a", "c"]

