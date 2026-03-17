from server.api.index import _derive_post_index_dense_retrieval_queries
from server.models.index import Chunk


def _chunk(chunk_id: str, content: str, *, file_path: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        content=content,
        file_path=file_path,
        start_line=1,
        end_line=5,
        language="python",
        token_count=32,
        metadata={},
    )


def test_derive_post_index_dense_retrieval_queries_prefers_real_chunk_content_then_keywords() -> None:
    queries = _derive_post_index_dense_retrieval_queries(
        repo_id="ragweld",
        repo_path="/tmp/ragweld",
        corpus_name="ragweld",
        corpus_description="retrieval workbench",
        corpus_meta={"keywords": ["pgvector", "grafana", "pgvector"]},
        sample_chunks=[
            _chunk("c1", "def build_vector_index(repo_id): return repo_id", file_path="server/api/index.py"),
            _chunk("c2", "grafana dashboard preset codex-session-ingest", file_path="web/src/components/Grafana/GrafanaConfig.tsx"),
        ],
        max_queries=4,
    )

    assert len(queries) == 4
    assert len({q.lower() for q in queries}) == 4
    assert queries[0].startswith("def build_vector_index")
    assert any("grafana" in q.lower() for q in queries)
    assert any("pgvector" in q.lower() for q in queries)
