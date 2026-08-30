from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

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
    # PROJECT_ROOT.parent isn't a reliable "outside" fixture: a worktree checked out
    # under the OS temp root (e.g. /tmp/some-worktree) has PROJECT_ROOT.parent == /tmp,
    # which the allowlist's temp-dir root also covers -- so that path lands *inside* the
    # allowlist instead of outside it. Use a fixed path that is provably outside both
    # allowed roots regardless of where this checkout lives.
    outside = Path("/nonexistent-outside-ragweld/outside.jsonl").resolve()
    for root in (reranker_api._LOGS_ROOT, reranker_api._TMP_ROOT):
        with pytest.raises(ValueError):
            outside.relative_to(root)

    with pytest.raises(HTTPException) as exc:
        reranker_api._resolve_safe_log_path(str(outside))
    assert exc.value.status_code == 400

