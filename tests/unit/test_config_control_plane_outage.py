from __future__ import annotations

import pytest

from server.config_control_plane import _resolve_corpus_path
from server.dependency_errors import DependencyUnavailableError


@pytest.mark.asyncio
async def test_retrieval_readiness_does_not_call_postgres_outage_unconfigured() -> None:
    with pytest.raises(DependencyUnavailableError) as caught:
        await _resolve_corpus_path(
            "configured-corpus",
            "postgresql://postgres:postgres@127.0.0.1:1/ragweld_outage",
        )

    assert caught.value.dependency == "postgres"
    assert caught.value.operation == "Config retrieval readiness"
