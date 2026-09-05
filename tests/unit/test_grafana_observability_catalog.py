from __future__ import annotations

import json
from pathlib import Path


def test_grafana_observability_dashboard_families_are_provisioned() -> None:
    provisioning_root = Path(__file__).resolve().parents[2] / "infra" / "grafana" / "provisioning"
    root = provisioning_root / "dashboards"
    for directory in ("plugins", "notifiers", "alerting"):
        assert (provisioning_root / directory).is_dir()
    expected = {
        "oncall-overview.json": ("On-call Overview", "ragweld-oncall-overview"),
        "gateway-serving.json": ("Gateway & Serving", "ragweld-gateway-serving"),
        "retrieval-indexing-graph.json": ("Retrieval/Indexing/Graph", "ragweld-retrieval-indexing-graph"),
        "training-workflow.json": ("Training & Workflow", "ragweld-training-workflow"),
        "eval-benchmark-prompt-regressions.json": (
            "Eval/Benchmark/Prompt Regressions",
            "ragweld-eval-regressions",
        ),
        "cost-capacity.json": ("Cost & Capacity", "ragweld-cost-capacity"),
        "frontend-rum.json": ("Frontend/RUM", "ragweld-frontend-rum"),
    }

    required_variables = {"corpus_id", "run_id", "model", "provider", "prompt_set", "workflow_id"}

    for file_name, (title, uid) in expected.items():
        path = root / file_name
        assert path.exists(), f"Missing Grafana dashboard file: {file_name}"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["title"] == title
        assert payload["uid"] == uid
        assert len(payload["uid"]) <= 40
        variables = {item.get("name") for item in payload.get("templating", {}).get("list", [])}
        if file_name == "cost-capacity.json":
            # Gateway counters have no corpus/run attribution. Unused filter
            # controls falsely suggest these deployment totals can be scoped.
            assert not variables
        else:
            assert required_variables.issubset(variables)


def _ml_quality_dashboard() -> dict:
    path = (
        Path(__file__).resolve().parents[2]
        / "infra"
        / "grafana"
        / "provisioning"
        / "dashboards"
        / "eval-benchmark-prompt-regressions.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_ml_quality_dashboard_never_paints_a_quality_collapse_green() -> None:
    """The "Latest" stat panels must read "No data" when unset and red at 0.

    The drive found 0% Top-1 and 0% pass ratio rendered in Grafana's healthy
    green beside "Eval Runs (24h) 3.00", so the screen read as fine during a
    total quality collapse.
    """

    payload = _ml_quality_dashboard()
    ratio_panels = {"Latest Eval Top-1 Accuracy", "Latest Promptfoo Pass Ratio"}
    seen = set()
    for panel in payload["panels"]:
        title = panel.get("title")
        if title not in ratio_panels:
            continue
        seen.add(title)
        defaults = panel["fieldConfig"]["defaults"]
        assert defaults.get("noValue") == "No data"
        steps = defaults["thresholds"]["steps"]
        base = next(step for step in steps if step["value"] is None)
        assert base["color"] != "green", f"{title} paints 0% green"
        assert any(step["color"] == "green" and (step["value"] or 0) > 0.5 for step in steps)
    assert seen == ratio_panels


def test_the_ml_quality_dashboard_formats_run_counts_as_integers() -> None:
    """Counts are integers: the drive read "3.00" and "1.00" beside "0"."""

    payload = _ml_quality_dashboard()
    count_panels = [panel for panel in payload["panels"] if str(panel.get("title", "")).endswith("(24h)")]
    assert len(count_panels) == 5
    for panel in count_panels:
        assert panel["fieldConfig"]["defaults"].get("decimals") == 0, panel["title"]


def test_the_ml_quality_dashboard_does_not_document_the_restart_reset_it_no_longer_has() -> None:
    """The footnote used to explain the defect; it must describe the fixed behaviour.

    It also carried the banned term "Learning Ranker".
    """

    payload = _ml_quality_dashboard()
    text = "\n".join(
        str(panel.get("options", {}).get("content", "")) for panel in payload["panels"] if panel.get("type") == "text"
    )
    assert "reset on API restart" not in text
    assert "scrape time" in text
    assert "No data" in text
    assert "Learning Ranker" not in text
    assert "Learning Reranker" in text
