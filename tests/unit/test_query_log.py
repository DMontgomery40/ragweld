from __future__ import annotations

import pytest

from server.dependency_errors import DependencyUnavailableError
from server.models.tribrid_config_model import TriBridConfig
from server.observability.query_log import append_feedback_log


async def test_append_feedback_log_raises_feedback_log_unavailable_when_parent_is_file(tmp_path) -> None:
    cfg = TriBridConfig()
    parent_file = tmp_path / "feedback-log-parent"
    parent_file.write_text("not a directory", encoding="utf-8")
    cfg.tracing.tribrid_log_path = str((parent_file / "queries.jsonl").resolve())

    with pytest.raises(DependencyUnavailableError) as caught:
        await append_feedback_log(
            cfg,
            event_id="evt_feedback_log_failure",
            signal="thumbsup",
        )

    assert caught.value.dependency == "feedback_log"
    assert caught.value.operation == "Feedback log append"
