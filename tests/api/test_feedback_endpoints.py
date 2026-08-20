from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.config import DEFAULT_CONFIG_PATH
from server.models.tribrid_config_model import TriBridConfig


def _set_feedback_log_parent_to_file(tmp_path: Path) -> str:
    config_path = DEFAULT_CONFIG_PATH
    if not config_path.exists():
        pytest.skip("tribrid_config.json missing in test environment")

    original = config_path.read_text(encoding="utf-8")
    cfg = TriBridConfig.model_validate_json(original)
    parent_file = tmp_path / "feedback-log-parent"
    parent_file.write_text("not a directory", encoding="utf-8")
    cfg.tracing.tribrid_log_path = str((parent_file / "queries.jsonl").resolve())
    config_path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    return original


async def test_feedback_endpoint_accepts_chat_signal(client) -> None:
    r = await client.post(
        "/api/feedback",
        json={"event_id": "evt_1", "signal": "thumbsup"},
        headers={"x-tribrid-test": "1"},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


async def test_feedback_endpoint_accepts_ui_rating(client) -> None:
    r = await client.post(
        "/api/feedback",
        json={"rating": 5, "comment": "Great eval UX", "timestamp": "2026-02-04T00:00:00Z", "context": "evaluation"},
        headers={"x-tribrid-test": "1"},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


async def test_feedback_endpoint_rejects_invalid_signal(client) -> None:
    r = await client.post(
        "/api/feedback",
        json={"event_id": "evt_2", "signal": "not_a_real_signal"},
        headers={"x-tribrid-test": "1"},
    )
    assert r.status_code == 400


async def test_feedback_endpoint_rejects_mixed_rating_and_signal(client) -> None:
    r = await client.post(
        "/api/feedback",
        json={"rating": 5, "signal": "thumbsup"},
        headers={"x-tribrid-test": "1"},
    )
    assert r.status_code == 422


@pytest.mark.requires_postgres
async def test_feedback_endpoint_rejects_unknown_corpus_scope(client) -> None:
    r = await client.post(
        "/api/feedback?corpus_id=definitely-not-a-real-corpus",
        json={"event_id": "evt_bad_scope", "signal": "thumbsup"},
    )
    assert r.status_code == 404


async def test_feedback_endpoint_returns_typed_503_on_log_write_failure(client, tmp_path: Path) -> None:
    config_path = DEFAULT_CONFIG_PATH
    original = _set_feedback_log_parent_to_file(tmp_path)
    try:
        r = await client.post("/api/feedback", json={"event_id": "evt_io_fail", "signal": "thumbsup"})
        assert r.status_code == 503
        detail = r.json()["detail"]
        assert detail["code"] == "dependency_unavailable"
        assert detail["dependency"] == "feedback_log"
        assert detail["operation"] == "Feedback API"
        assert detail["retryable"] is True
        assert detail["operator_hint"]
        assert str(tmp_path) not in json.dumps(r.json())
    finally:
        config_path.write_text(original, encoding="utf-8")


async def test_reranker_click_endpoint_accepts_payload(client) -> None:
    r = await client.post(
        "/api/reranker/click",
        json={"event_id": "evt_3", "doc_id": "server/api/chat.py"},
        headers={"x-tribrid-test": "1"},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


@pytest.mark.requires_postgres
async def test_reranker_click_endpoint_rejects_unknown_corpus_scope(client) -> None:
    r = await client.post(
        "/api/reranker/click?corpus_id=definitely-not-a-real-corpus",
        json={"event_id": "evt_bad_click_scope", "doc_id": "missing.md"},
    )
    assert r.status_code == 404


async def test_reranker_click_endpoint_returns_typed_503_on_log_write_failure(client, tmp_path: Path) -> None:
    config_path = DEFAULT_CONFIG_PATH
    original = _set_feedback_log_parent_to_file(tmp_path)
    try:
        r = await client.post(
            "/api/reranker/click",
            json={"event_id": "evt_click_io_fail", "doc_id": "server/api/chat.py"},
        )
        assert r.status_code == 503
        detail = r.json()["detail"]
        assert detail["code"] == "dependency_unavailable"
        assert detail["dependency"] == "feedback_log"
        assert detail["operation"] == "Reranker click feedback"
        assert detail["retryable"] is True
        assert detail["operator_hint"]
        assert str(tmp_path) not in json.dumps(r.json())
    finally:
        config_path.write_text(original, encoding="utf-8")


async def test_reranker_mine_mines_triplets_from_log(client) -> None:
    project_root = Path(__file__).resolve().parents[2]
    cfg = TriBridConfig()
    log_path = project_root / "data" / "logs" / "queries.jsonl"
    triplets_path = project_root / cfg.training.tribrid_triplets_path

    original_log = log_path.read_text(encoding="utf-8") if log_path.exists() else None
    original_triplets = triplets_path.read_text(encoding="utf-8") if triplets_path.exists() else None

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        triplets_path.parent.mkdir(parents=True, exist_ok=True)

        entries = [
            {
                "ts": "2026-02-04T00:00:00Z",
                "kind": "chat",
                "event_id": "evt_mine_1",
                "query": "Where is auth implemented?",
                "top_paths": ["server/api/auth.py", "server/main.py", "README.md"],
            },
            {
                "ts": "2026-02-04T00:00:01Z",
                "kind": "feedback",
                "type": "feedback",
                "event_id": "evt_mine_1",
                "signal": "thumbsup",
            },
        ]
        log_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

        r = await client.post("/api/reranker/mine")
        assert r.status_code == 200
        assert r.json().get("ok") is True

        assert triplets_path.exists()
        lines = [ln for ln in triplets_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 1
        t = json.loads(lines[0])
        assert t["query"] == "Where is auth implemented?"
        assert t["positive"] == "server/api/auth.py"
        assert t["negative"] == "server/main.py"
    finally:
        if original_log is None:
            try:
                log_path.unlink()
            except FileNotFoundError:
                pass
        else:
            log_path.write_text(original_log, encoding="utf-8")

        if original_triplets is None:
            try:
                triplets_path.unlink()
            except FileNotFoundError:
                pass
        else:
            triplets_path.write_text(original_triplets, encoding="utf-8")
