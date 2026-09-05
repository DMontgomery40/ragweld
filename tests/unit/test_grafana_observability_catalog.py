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


def _cost_dashboard() -> dict:
    return json.loads((Path(__file__).resolve().parents[2] / "infra/grafana/provisioning/dashboards/cost-capacity.json").read_text())


def test_cost_calendar_range_is_explicit_and_remains_truthful_for_history() -> None:
    from urllib.parse import parse_qs, urlsplit

    dashboard = _cost_dashboard()
    assert dashboard["timezone"] == "utc"
    assert dashboard["time"] == {"from": "now/d", "to": "now"}
    links = {link["title"]: parse_qs(urlsplit(link["url"]).query) for link in dashboard["links"]}
    assert links["Today (UTC)"]["from"] == ["now/d"]
    assert links["Last 7 days"]["from"] == ["now-7d"]
    assert all(link["to"] == ["now"] for link in links.values())
    for panel in dashboard["panels"]:
        if "today" in panel.get("title", "").lower():
            raise AssertionError("A fixed Today title lies when the operator selects an absolute historical range")
        assert "timeFrom" not in panel, "Grafana ignores panel overrides for absolute dashboard ranges"
    text = "\n".join(panel.get("options", {}).get("content", "") for panel in dashboard["panels"])
    assert "midnight UTC" in text
    assert "selected end time" in text


def test_cost_and_token_panels_use_native_reset_aware_counters_without_fake_zero() -> None:
    dashboard = _cost_dashboard()
    panels = {panel["id"]: panel for panel in dashboard["panels"]}
    expected = {5: ("litellm_spend_metric_total", "$__range"), 6: ("litellm_spend_metric_total", "7d"),
                8: ("litellm_total_tokens_metric_total", "$__range"), 9: ("litellm_total_tokens_metric_total", "7d")}
    for panel_id, (metric, window) in expected.items():
        panel = panels[panel_id]
        assert panel["targets"][0]["expr"] == f"sum(increase({metric}[{window}]))"
        assert panel["targets"][0]["instant"] is True
    native_panels = [panel for panel in panels.values() if any("litellm_" in target.get("expr", "") for target in panel.get("targets", []))]
    assert len(native_panels) >= 7
    for panel in native_panels:
        assert panel["fieldConfig"]["defaults"]["noValue"] == "No data"
        for target in panel["targets"]:
            expression = target["expr"]
            assert "increase(" in expression or "rate(" in expression
            assert " or " not in expression and "vector(0)" not in expression
            assert "corpus" not in expression and "run_id" not in expression
            assert "cached" not in expression and "reasoning" not in expression, "Token subsets must not be counted twice"


def test_cost_breakdowns_preserve_unattributed_history_and_native_model_lane_identity() -> None:
    panels = {panel["id"]: panel for panel in _cost_dashboard()["panels"]}
    for panel_id, metrics in [(10, ["litellm_spend_metric_total"]), (11, ["litellm_input_tokens_metric_total", "litellm_output_tokens_metric_total", "litellm_total_tokens_metric_total"])]:
        panel = panels[panel_id]
        assert len(panel["targets"]) == len(metrics)
        for target, metric in zip(panel["targets"], metrics, strict=True):
            expression = target["expr"]
            assert f'increase({metric}[$__range])' in expression
            assert 'sum by (model, metadata_lane)' in expression
            assert '"metadata_lane", "unattributed", "metadata_lane", "^(None)?$"' in expression
            assert 'metadata_lane!=' not in expression, "Do not discard pre-lane spend or tokens"
            assert "{{model}}" in target["legendFormat"] and "{{metadata_lane}}" in target["legendFormat"]


def test_callback_failure_panel_counts_exporter_logs_without_claiming_delivery_health() -> None:
    panel = next(panel for panel in _cost_dashboard()["panels"] if panel["id"] == 12)
    assert panel["datasource"]["uid"] == "loki"
    expression = panel["targets"][0]["expr"]
    assert 'compose_project="ragweld"' in expression and 'compose_service="litellm"' in expression
    assert "count_over_time" in expression and "Failed to export" in expression
    assert "Transient error" not in expression, "Recovered retries are not terminal batch failures"
    assert "litellm_proxy" not in expression and "vector(0)" not in expression
    assert expression.endswith(' or (0 * sum(count_over_time({compose_project="ragweld", compose_service="litellm"} [$__range])))')
    assert panel["fieldConfig"]["defaults"]["noValue"] == "Unavailable / no scoped logs"
    assert "does not prove delivery" in panel["description"]
    assert "batch" in panel["description"] and "generation" in panel["description"]
    assert "Zero means scoped gateway logs were available" in panel["description"]


def test_cost_queries_execute_with_resets_midnight_unattributed_zero_and_missing_series(tmp_path: Path) -> None:
    """Optional real PromQL engine: no fake query responses or reimplemented increase.

    RAGWELD_DASHBOARD_QUERY_TESTS=1 uses the already available pinned Prometheus
    image on LXC. Ordinary credential-free CI retains the source contracts above.
    """
    import os
    import shutil
    import subprocess
    import sys

    import pytest
    import yaml

    from tests.service_requirements import _strict_mode

    if os.environ.get("RAGWELD_DASHBOARD_QUERY_TESTS") != "1":
        if _strict_mode():
            pytest.fail("Strict dashboard query acceptance requires RAGWELD_DASHBOARD_QUERY_TESTS=1")
        pytest.skip("Real dashboard query acceptance requires RAGWELD_DASHBOARD_QUERY_TESTS=1 on LXC")
    assert sys.platform == "linux" and shutil.which("docker"), "Dashboard query acceptance requires LXC Docker"
    panels = {panel["id"]: panel for panel in _cost_dashboard()["panels"]}
    queries = []
    metric_names = ["litellm_spend_metric_total", "litellm_input_tokens_metric_total", "litellm_output_tokens_metric_total", "litellm_total_tokens_metric_total"]
    input_series = []
    for metric in metric_names:
        input_series.extend([
            {"series": metric + '{model="current",metadata_lane="semantic_kg"}', "values": "0+1x1439 0+1x5"},
            {"series": metric + '{model="historical"}', "values": "0+2x1445"},
            {"series": metric + '{model="native-missing",metadata_lane="None"}', "values": "0+1x1445"},
            {"series": metric + '{model="empty-lane",metadata_lane=""}', "values": "0+0x1445"},
            {"series": metric + '{model="free",metadata_lane="generation"}', "values": "0+0x1445"},
        ])
    for panel_id in (10, 11):
        for target in panels[panel_id]["targets"]:
            expression = target["expr"].replace("$__range", "5m")
            queries.append({"expr": expression, "eval_time": "24h5m", "exp_samples": [
                {"labels": '{model="current",metadata_lane="semantic_kg"}', "value": 5},
                {"labels": '{model="historical",metadata_lane="unattributed"}', "value": 10},
                {"labels": '{model="native-missing",metadata_lane="unattributed"}', "value": 5},
                {"labels": '{model="empty-lane",metadata_lane="unattributed"}', "value": 0},
                {"labels": '{model="free",metadata_lane="generation"}', "value": 0},
            ]})
    for panel_id in (5, 8):
        expression = panels[panel_id]["targets"][0]["expr"].replace("$__range", "5m")
        queries.append({"expr": expression, "eval_time": "24h5m", "exp_samples": [{"labels": "{}", "value": 20}]})
    for panel_id in (6, 9):
        queries.append({"expr": panels[panel_id]["targets"][0]["expr"], "eval_time": "24h5m", "exp_samples": [{"labels": "{}", "value": 5779}]})
    empty_queries = [{**query, "exp_samples": []} for query in queries]
    spec = {"evaluation_interval": "1m", "tests": [{"interval": "1m", "input_series": input_series, "promql_expr_test": queries}, {"interval": "1m", "input_series": [], "promql_expr_test": empty_queries}]}
    (tmp_path / "queries.yml").write_text(yaml.safe_dump(spec))
    result = subprocess.run(["docker", "run", "--rm", "--network", "none", "--memory", "128m", "--cpus", "0.5", "--entrypoint", "/bin/promtool", "--mount", f"type=bind,src={tmp_path / 'queries.yml'},dst=/fixtures/queries.yml,readonly", "prom/prometheus:v2.45.0", "test", "rules", "/fixtures/queries.yml"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
