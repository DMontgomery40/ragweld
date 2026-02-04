from __future__ import annotations

from fastapi import HTTPException
import pytest

from server.api import reranker as reranker_api


def test_resolve_safe_log_path_allows_default_data_logs_path() -> None:
    p = reranker_api._resolve_safe_log_path("data/logs/queries.jsonl")
    assert p.suffix.lower() == ".jsonl"
    assert "/data/logs/" in str(p).replace("\\", "/")


def test_resolve_safe_log_path_blocks_paths_outside_allowed_roots() -> None:
    with pytest.raises(HTTPException) as exc:
        reranker_api._resolve_safe_log_path("server/main.py")
    assert exc.value.status_code == 400


def test_resolve_safe_log_path_blocks_paths_outside_project_and_temp() -> None:
    outside = str((reranker_api.PROJECT_ROOT.parent / "outside.jsonl").resolve())
    with pytest.raises(HTTPException) as exc:
        reranker_api._resolve_safe_log_path(outside)
    assert exc.value.status_code == 400

