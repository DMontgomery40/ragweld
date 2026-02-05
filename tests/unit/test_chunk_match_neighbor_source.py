from __future__ import annotations

import pytest

from server.models.tribrid_config_model import ChunkMatch


def test_chunk_match_rejects_neighbor_source() -> None:
    with pytest.raises(Exception):
        ChunkMatch(
            chunk_id="c1",
            content="hello",
            file_path="doc.txt",
            start_line=1,
            end_line=1,
            language=None,
            score=0.0,
            source="neighbor",  # type: ignore[arg-type]
            metadata={"corpus_id": "test", "neighbor_of": "seed"},
        )
