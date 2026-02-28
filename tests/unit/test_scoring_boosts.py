from __future__ import annotations

from server.models.tribrid_config_model import ChunkMatch, TriBridConfig
from server.retrieval.scoring_boosts import apply_scoring_boosts


def _match(*, chunk_id: str, path: str, score: float, corpus_id: str = "c1") -> ChunkMatch:
    return ChunkMatch(
        chunk_id=chunk_id,
        content="content",
        file_path=path,
        start_line=1,
        end_line=2,
        language="python",
        score=score,
        source="vector",
        metadata={"corpus_id": corpus_id},
    )


def test_scoring_boosts_rank_retrieval_path_above_vendor() -> None:
    cfg = TriBridConfig()
    cfg.scoring.path_boosts = "/server/retrieval,/web"
    cfg.scoring.vendor_mode = "prefer_first_party"
    cfg.layer_bonus.retrieval = 0.2
    cfg.layer_bonus.vendor_penalty = -0.2
    cfg.keywords.keywords_boost = 1.5

    matches = [
        _match(chunk_id="vendor", path="node_modules/pkg/index.js", score=1.0),
        _match(chunk_id="retrieval", path="server/retrieval/fusion.py", score=1.0),
    ]
    boosted = apply_scoring_boosts(
        matches,
        query="fusion retrieval",
        cfg=cfg,
        corpus_meta_by_id={"c1": {"meta": {"keywords": ["fusion"]}, "last_indexed": "2026-02-01T00:00:00+00:00"}},
    )
    assert boosted[0].chunk_id == "retrieval"
    assert boosted[0].score > boosted[1].score
    assert isinstance((boosted[0].metadata or {}).get("boosts_applied"), list)


def test_scoring_boosts_apply_keyword_multiplier() -> None:
    cfg = TriBridConfig()
    cfg.keywords.keywords_boost = 2.0

    m = _match(chunk_id="auth", path="server/api/auth.py", score=0.5)
    out = apply_scoring_boosts(
        [m],
        query="auth token flow",
        cfg=cfg,
        corpus_meta_by_id={"c1": {"meta": {"keywords": ["auth", "token"]}, "last_indexed": ""}},
    )
    assert len(out) == 1
    assert out[0].score > 0.5
    applied = (out[0].metadata or {}).get("boosts_applied") or []
    assert any(isinstance(x, dict) and x.get("kind") == "keyword" for x in applied)
