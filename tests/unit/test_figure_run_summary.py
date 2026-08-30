"""The end-of-run figure summary event: log vs warning, and which hint fires."""

from __future__ import annotations

from server.api.index import figure_run_summary_event


def test_not_describe_is_a_plain_info_log() -> None:
    """describe=False can still have skipped pictures (classify-only run); it must never
    escalate to a warning -- nothing was ever asked to be described.
    """
    event = figure_run_summary_event(describe=False, described=0, failed=0, undescribed=3)
    assert event is not None
    assert event["type"] == "log"
    assert "figures_described=0 figures_failed=0 figures_undescribed=3" in event["message"]
    assert "check" not in event["message"]


def test_all_failed_is_a_warning_with_the_gateway_alias_budget_hint() -> None:
    event = figure_run_summary_event(describe=True, described=0, failed=2, undescribed=0)
    assert event is not None
    assert event["type"] == "warning"
    assert "figures_described=0 figures_failed=2 figures_undescribed=0" in event["message"]
    assert "vision alias returned empty descriptions" in event["message"]
    assert "max_completion_tokens" in event["message"]


def test_all_skipped_is_a_warning_naming_the_filters_that_caused_it() -> None:
    """Nothing reached the vision call, so the alias is not the suspect: every picture was
    filtered out beforehand by the class deny-list, the area threshold, or classify being off.
    Naming the alias here would send the operator to the one setting that cannot be at fault.
    """
    event = figure_run_summary_event(describe=True, described=0, failed=0, undescribed=4)
    assert event is not None
    assert event["type"] == "warning"
    assert "figures_described=0 figures_failed=0 figures_undescribed=4" in event["message"]
    assert "filtered out before the vision call" in event["message"]
    assert "skip_classes" in event["message"]
    assert "min_area_fraction" in event["message"]
    assert "classify" in event["message"]
    # The gateway-side hints belong to the all-failed branch only.
    assert "max_completion_tokens" not in event["message"]
    assert "returned empty descriptions" not in event["message"]


def test_mixed_with_at_least_one_described_is_info_not_warning() -> None:
    event = figure_run_summary_event(describe=True, described=1, failed=1, undescribed=1)
    assert event is not None
    assert event["type"] == "log"
    assert "figures_described=1 figures_failed=1 figures_undescribed=1" in event["message"]
    assert "check" not in event["message"]


def test_nothing_to_report_returns_none() -> None:
    """No pictures were ever processed this run: emitting an all-zero line is noise."""
    assert figure_run_summary_event(describe=True, described=0, failed=0, undescribed=0) is None
    assert figure_run_summary_event(describe=False, described=0, failed=0, undescribed=0) is None
