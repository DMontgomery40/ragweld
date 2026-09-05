from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.api.chat import set_config, set_fusion
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import FusionConfig

pytestmark = pytest.mark.requires_postgres


class _DeterministicFusion:
    def __init__(self) -> None:
        self.last_debug = {
            "chat_rag_fusion": {
                "rerank_mode": "none",
                "rerank_ok": True,
                "rerank_applied": False,
                "rerank_candidates_reranked": 0,
            }
        }

    async def search(
        self,
        corpus_ids: list[str],
        query: str,
        config: FusionConfig,  # noqa: ARG002
        *,
        include_vector: bool = True,  # noqa: ARG002
        include_sparse: bool = True,  # noqa: ARG002
        include_graph: bool = True,  # noqa: ARG002
        top_k: int | None = None,  # noqa: ARG002
        cache_mode: str = "default",  # noqa: ARG002
        cache_namespace: str = "search",  # noqa: ARG002
        billing_session_id: str | None = None,  # noqa: ARG002
    ) -> list[ChunkMatch]:
        cid = str(corpus_ids[0] if corpus_ids else "unknown")
        q = str(query or "").strip()
        return [
            ChunkMatch(
                chunk_id=f"{cid}-chunk-1",
                content=f"best match for {q}",
                file_path="good.txt",
                start_line=1,
                end_line=1,
                language="text",
                score=0.91,
                source="vector",
                metadata={"corpus_id": cid},
            ),
            ChunkMatch(
                chunk_id=f"{cid}-chunk-2",
                content=f"second match for {q}",
                file_path="bad.txt",
                start_line=1,
                end_line=1,
                language="text",
                score=0.42,
                source="sparse",
                metadata={"corpus_id": cid},
            ),
        ]


async def test_stream_chat_feedback_mining_linkage(client, tmp_path: Path) -> None:
    corpus_id = f"pytest_stream_link_{tmp_path.name}"
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir(parents=True, exist_ok=True)
    (corpus_root / "good.txt").write_text("good", encoding="utf-8")
    (corpus_root / "bad.txt").write_text("bad", encoding="utf-8")

    log_path = tmp_path / "queries.jsonl"
    triplets_path = tmp_path / "triplets.jsonl"

    set_config(None)
    set_fusion(_DeterministicFusion())

    create = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_root)},
    )
    assert create.status_code == 200

    try:
        r = await client.request(
            "PATCH",
            f"/api/config/tracing?corpus_id={corpus_id}",
            json={"tribrid_log_path": str(log_path), "tracing_enabled": 1},
        )
        assert r.status_code == 200

        r = await client.request(
            "PATCH",
            f"/api/config/training?corpus_id={corpus_id}",
            json={"tribrid_triplets_path": str(triplets_path)},
        )
        assert r.status_code == 200

        payload = {
            "message": "where is auth logic",
            "conversation_id": "stream-link-conv",
            "sources": {"corpus_ids": [corpus_id]},
            "include_vector": True,
            "include_sparse": True,
            "include_graph": False,
            "stream": True,
        }

        sse_body = ""
        async with client.stream("POST", "/api/chat/stream", json=payload) as resp:
            assert resp.status_code == 200
            async for chunk in resp.aiter_text():
                sse_body += chunk

        done: dict[str, object] | None = None
        for block in sse_body.split("\n\n"):
            part = block.strip()
            if not part.startswith("data:"):
                continue
            raw = part[len("data:") :].strip()
            if not raw:
                continue
            parsed = json.loads(raw)
            if parsed.get("type") == "done":
                done = parsed
                break

        assert done is not None
        run_id = done.get("run_id")
        assert isinstance(run_id, str) and run_id.strip()

        fb = await client.post(
            f"/api/feedback?corpus_id={corpus_id}",
            json={"event_id": run_id, "signal": "thumbsup"},
        )
        assert fb.status_code == 200
        assert fb.json().get("ok") is True

        logs_resp = await client.get(f"/api/reranker/logs?corpus_id={corpus_id}&limit=500")
        assert logs_resp.status_code == 200
        logs = logs_resp.json().get("logs") or []
        assert isinstance(logs, list)

        chat_events = [
            row
            for row in logs
            if isinstance(row, dict)
            and str(row.get("kind") or "").strip().lower() == "chat"
            and str(row.get("event_id") or "") == run_id
        ]
        feedback_events = [
            row
            for row in logs
            if isinstance(row, dict)
            and str(row.get("kind") or "").strip().lower() == "feedback"
            and str(row.get("event_id") or "") == run_id
            and str(row.get("signal") or "").strip().lower() == "thumbsup"
        ]
        assert chat_events, "expected streamed chat query log with event_id=run_id"
        assert feedback_events, "expected feedback log tied to streamed run_id"

        mine = await client.post(f"/api/reranker/mine?corpus_id={corpus_id}")
        assert mine.status_code == 200
        assert mine.json().get("ok") is True

        count = await client.get(f"/api/reranker/triplets/count?corpus_id={corpus_id}")
        assert count.status_code == 200
        assert int(count.json().get("count") or 0) >= 1

        lines = [ln for ln in triplets_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert lines
        first = json.loads(lines[0])
        assert first.get("query") == "where is auth logic"
        assert first.get("positive") == "good.txt"
        assert first.get("negative") == "bad.txt"
    finally:
        set_fusion(None)
        set_config(None)
        await client.delete(f"/api/corpora/{corpus_id}")
