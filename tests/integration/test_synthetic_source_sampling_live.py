"""Live Postgres: synthetic source selection sees the whole corpus, not a head-truncated slice.

Regression: candidates were fetched ``ORDER BY file_path, start_line LIMIT max_source_chunks*8``,
so a long single-file corpus only ever offered the first pages (cover, front matter, report
number) to the question generator. Chunks are seeded as real rows under a ``pytest_`` corpus;
nothing is mocked.
"""

from __future__ import annotations

import uuid

import pytest

from server.config import load_config
from server.db.postgres import PostgresClient
from server.models.index import Chunk
from server.models.tribrid_config_model import SyntheticRunStartRequest
from server.synthetic.recipes import select_source_chunks
from tests.service_requirements import require_env

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]

CHUNK_COUNT = 320
LINES_PER_CHUNK = 10
DOC = "A11_MissionReport.pdf"


async def test_selection_draws_from_across_a_long_single_document() -> None:
    corpus_id = f"pytest_synth_sampling_{uuid.uuid4().hex[:8]}"
    dsn = require_env("POSTGRES_DSN")
    pg = PostgresClient(dsn)
    await pg.connect()
    try:
        await pg.upsert_chunks(
            corpus_id,
            [
                Chunk(
                    chunk_id=f"{corpus_id}_{index:04d}",
                    content=f"Mission report section {index}: descent, landing and surface operations detail.",
                    file_path=DOC,
                    start_line=index * LINES_PER_CHUNK + 1,
                    end_line=index * LINES_PER_CHUNK + LINES_PER_CHUNK,
                )
                for index in range(CHUNK_COUNT)
            ],
        )
        cfg = load_config()
        cfg.indexing.postgres_url = dsn
        cfg.chunk_summaries.exclude_dirs = []
        cfg.chunk_summaries.exclude_patterns = []
        cfg.chunk_summaries.exclude_keywords = []

        def request(seed: int) -> SyntheticRunStartRequest:
            return SyntheticRunStartRequest(
                repo_id=corpus_id,
                max_source_chunks=10,
                seed=seed,
                generator_model="openai.gpt-6-luna",
            )

        picked = await select_source_chunks(repo_id=corpus_id, cfg=cfg, request=request(1337))
        assert len(picked) == 10
        total_lines = CHUNK_COUNT * LINES_PER_CHUNK
        starts = sorted(chunk.start_line for chunk in picked)
        # max_source_chunks*8 = 80 head chunks is the first quarter; the draw must reach past it.
        quarters = {(start - 1) * 4 // total_lines for start in starts}
        assert quarters == {0, 1, 2, 3}, starts
        assert all(chunk.content for chunk in picked), "selected chunks carry their content"

        again = await select_source_chunks(repo_id=corpus_id, cfg=cfg, request=request(1337))
        assert [c.chunk_id for c in again] == [c.chunk_id for c in picked]
        other_seed = await select_source_chunks(repo_id=corpus_id, cfg=cfg, request=request(7))
        assert [c.chunk_id for c in other_seed] != [c.chunk_id for c in picked]

        # Content keyword exclusions still apply after the whole-corpus draw.
        cfg.chunk_summaries.exclude_keywords = ["section 1"]
        filtered = await select_source_chunks(repo_id=corpus_id, cfg=cfg, request=request(1337))
        assert len(filtered) == 10
        assert not any("section 1" in chunk.content for chunk in filtered)
    finally:
        await pg.delete_corpus_with_data(corpus_id)
        await pg.disconnect()
