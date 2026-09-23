from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROVISIONING_ROOT = ROOT / "infra" / "grafana" / "provisioning"
DASHBOARD_ROOT = PROVISIONING_ROOT / "dashboards"
PRESETS_TS = ROOT / "web" / "src" / "components" / "Grafana" / "dashboardPresets.ts"

EXPECTED_DASHBOARDS = {
    "oncall-overview.json": ("On-call Overview", "ragweld-oncall-overview"),
    "gateway-serving.json": ("Gateway & Serving", "ragweld-gateway-serving"),
    "retrieval-indexing-graph.json": ("Retrieval/Indexing/Graph", "ragweld-retrieval-indexing-graph"),
    "training-workflow.json": ("Training & Workflow", "ragweld-training-workflow"),
    "eval-benchmark-prompt-regressions.json": ("Eval/Benchmark/Prompt Regressions", "ragweld-eval-regressions"),
    "cost-capacity.json": ("Cost & Capacity", "ragweld-cost-capacity"),
    "frontend-rum.json": ("Frontend/RUM", "ragweld-frontend-rum"),
    "tribrid_overview.json": ("TriBrid Overview", "tribrid-overview"),
    "rag-metrics.json": ("TriBridRAG Metrics", "tribrid-rag-metrics"),
    "reranker-training.json": ("Reranker Training", "reranker-training"),
    "chat.json": ("Chat", "ragweld-chat"),
}


def _dashboards() -> dict[str, dict[str, Any]]:
    return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in sorted(DASHBOARD_ROOT.glob("*.json"))}


def _panels(dashboard: dict[str, Any]) -> Iterator[dict[str, Any]]:
    stack = list(dashboard.get("panels") or [])
    while stack:
        panel = stack.pop(0)
        yield panel
        stack.extend(panel.get("panels") or [])


def _exprs(dashboard: dict[str, Any]) -> Iterator[tuple[dict[str, Any], str]]:
    for panel in _panels(dashboard):
        for target in panel.get("targets") or []:
            expr = str(target.get("expr") or "")
            if expr.strip():
                yield panel, expr


def test_grafana_observability_dashboard_families_are_provisioned() -> None:
    for directory in ("plugins", "notifiers", "alerting"):
        assert (PROVISIONING_ROOT / directory).is_dir()
    dashboards = _dashboards()
    # Every provisioned file is an expected family: a dashboard nothing scrapes for
    # (the retired Codex Session Ingest board) must not come back unnoticed.
    assert set(dashboards) == set(EXPECTED_DASHBOARDS)
    for file_name, (title, uid) in EXPECTED_DASHBOARDS.items():
        payload = dashboards[file_name]
        assert payload["title"] == title
        assert payload["uid"] == uid
        assert len(payload["uid"]) <= 40


def test_every_template_variable_is_used_by_a_panel_query() -> None:
    """No decorative filters: a variable no query reads suggests scoping the panels cannot do."""

    for file_name, dashboard in _dashboards().items():
        exprs = [expr for _, expr in _exprs(dashboard)]
        for variable in dashboard.get("templating", {}).get("list", []) or []:
            name = variable["name"]
            pattern = re.compile(r"\$(\{)?" + re.escape(name) + r"\b")
            assert any(pattern.search(expr) for expr in exprs), f"{file_name}: ${name} is never used"


def test_no_ratio_hides_low_traffic_and_no_stat_masks_an_outage() -> None:
    for file_name, dashboard in _dashboards().items():
        for panel, expr in _exprs(dashboard):
            # clamp_min(total, 1) understates the error ratio whenever traffic is < 1/s.
            assert "clamp_min(" not in expr, f"{file_name}: {panel['title']}"
            # `or vector(0)` turns a scrape outage into a healthy-looking 0.
            assert "vector(0)" not in expr, f"{file_name}: {panel['title']}"


def test_every_data_panel_says_what_an_empty_panel_means() -> None:
    for file_name, dashboard in _dashboards().items():
        for panel in _panels(dashboard):
            if not panel.get("targets") or panel.get("type") == "logs":
                continue
            no_value = ((panel.get("fieldConfig") or {}).get("defaults") or {}).get("noValue")
            assert isinstance(no_value, str) and no_value.strip(), f"{file_name}: {panel['title']} has no noValue"


def test_every_charted_stage_label_is_emitted_by_the_server() -> None:
    """A stage literal in a panel must be emitted somewhere, not just pre-registered.

    Pre-registration in server/observability/metrics.py creates a zero series for a label
    that may never be observed, so it is excluded from the search.
    """

    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "server").rglob("*.py")
        if path != ROOT / "server" / "observability" / "metrics.py"
    )
    for file_name, dashboard in _dashboards().items():
        for panel, expr in _exprs(dashboard):
            for stage in re.findall(r'stage="([^"]+)"', expr):
                assert f'"{stage}"' in sources, f"{file_name}: {panel['title']} charts never-emitted stage {stage}"


def test_every_panel_query_resolves_all_variables_for_the_live_check() -> None:
    from scripts.check_grafana_queries import (
        dashboard_variables,
        iter_dashboard_targets,
        substitute,
    )

    for path in sorted(DASHBOARD_ROOT.glob("*.json")):
        variables = dashboard_variables(path)
        targets = list(iter_dashboard_targets(path))
        assert targets, path.name
        for target in targets:
            resolved = substitute(target.expr, variables=variables, range_seconds=target.range_seconds)
            # `$` alone is a regex anchor; `$name` / `${name}` is an unresolved variable.
            assert not re.search(r"\$\{?[A-Za-z_]", resolved), f"{path.name}: unresolved variable in {resolved}"
            assert target.datasource_uid in {"mimir", "prometheus", "loki"}, (path.name, target.datasource_uid)


def test_gateway_system_one_row_charts_what_laya_and_the_client_emit() -> None:
    import yaml

    panels = list(_panels(_dashboards()["gateway-serving.json"]))
    row = next(panel for panel in panels if panel.get("type") == "row" and panel.get("title") == "System One")
    below = [panel for panel in panels if panel.get("type") != "row" and panel["gridPos"]["y"] > row["gridPos"]["y"]]
    exprs = "\n".join(str(target.get("expr") or "") for panel in below for target in panel.get("targets") or [])

    assert 'up{job="laya"}' in exprs
    assert 'process_resident_memory_bytes{job="laya"}' in exprs
    # The client's provider-labelled contract (docs/exec-plans/active/system-one-decisions-2026-09-23.md).
    assert "sum by (provider, outcome) (rate(tribrid_system_one_requests_total[5m]))" in exprs
    assert "sum by (le, provider) (rate(tribrid_system_one_latency_seconds_bucket[15m]))" in exprs
    # Every laya_* series charted is one the Laya entrypoint defines.
    entrypoint = (ROOT / "infra" / "laya" / "ragweld_laya_serve.py").read_text(encoding="utf-8")
    charted = {re.sub(r"_(bucket|count|sum)$", "", name) for name in re.findall(r"\blaya_[a-z_]+", exprs)}
    assert charted == {"laya_inference_seconds"}
    assert all(f'"{name}"' in entrypoint for name in charted)

    # The memory stat turns red before the container's hard cap, not at it.
    memory = next(panel for panel in below if "process_resident_memory_bytes" in panel["targets"][0]["expr"])
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert compose["services"]["laya"]["mem_limit"] == "4g"
    steps = memory["fieldConfig"]["defaults"]["thresholds"]["steps"]
    red = next(step["value"] for step in steps if step["color"] == "red")
    assert 0 < red < 4 * 1024**3


def test_catalog_manifest_presets_and_provisioned_dashboards_agree() -> None:
    from server.models.tribrid_config_model import TriBridConfig
    from server.observability.catalog import build_observability_catalog

    provisioned = {payload["uid"] for payload in _dashboards().values()}
    catalog = build_observability_catalog(TriBridConfig())
    assert {dashboard.uid for dashboard in catalog.dashboards} == provisioned
    presets = set(re.findall(r"uid:\s*'([^']+)'", PRESETS_TS.read_text(encoding="utf-8")))
    assert presets == provisioned

    by_uid = {payload["uid"]: payload for payload in _dashboards().values()}
    for dashboard in catalog.dashboards:
        declared = {item["name"] for item in by_uid[dashboard.uid].get("templating", {}).get("list", []) or []}
        # The catalog advertises exactly the dashboard's own variables plus its time range.
        assert {variable.id for variable in dashboard.variables} == declared | {"time_range"}, dashboard.uid
    gateway = next(dashboard for dashboard in catalog.dashboards if dashboard.uid == "ragweld-gateway-serving")
    model = next(variable for variable in gateway.variables if variable.id == "model")
    assert model.kind == "custom" and model.default_value == "All"
    assert "requested_model" in str(model.description)


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
    ratio_panels = {
        "Newest eval run (any corpus): top-1 accuracy and age",
        "Newest Promptfoo run (any corpus): pass ratio and age",
    }
    seen = set()
    for panel in payload["panels"]:
        title = panel.get("title")
        if title not in ratio_panels:
            continue
        seen.add(title)
        defaults = panel["fieldConfig"]["defaults"]
        assert str(defaults.get("noValue")).startswith("No data")
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
    # Spend and token counters; the budget gauge panel reads litellm_remaining_* gauges.
    native_panels = [
        panel
        for panel in panels.values()
        if any(re.search(r"litellm_\w+_total", target.get("expr", "")) for target in panel.get("targets", []))
    ]
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


# --------------------------------------------------------------------------------------
# Name drift: a panel or rule on a series the server never emits reads "No data" forever,
# and the live check cannot tell that from "not deployed yet" or "no traffic".
# --------------------------------------------------------------------------------------

_TRIBRID_SELECTOR_RE = re.compile(r"\b(tribrid_[a-z0-9_]+)(\{[^}]*\})?")
_LABEL_MATCHER_RE = re.compile(r'([a-z_]+)\s*(=~|!~|!=|=)\s*"([^"]*)"')


def _rule_exprs() -> list[str]:
    import yaml

    rules = yaml.safe_load((ROOT / "infra" / "prometheus-rules.yml").read_text(encoding="utf-8"))
    return [str(rule["expr"]) for group in rules["groups"] for rule in group["rules"]]


def _promql_exprs() -> list[tuple[str, str]]:
    out = [(f"{name}: {panel['title']}", expr) for name, dashboard in _dashboards().items() for panel, expr in _exprs(dashboard)]
    return out + [("prometheus-rules.yml", expr) for expr in _rule_exprs()]


def _server_sources() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "server").rglob("*.py"))


def test_every_charted_or_alerted_tribrid_metric_is_defined_by_the_server() -> None:
    sources = _server_sources()
    for where, expr in _promql_exprs():
        for name, _ in _TRIBRID_SELECTOR_RE.findall(expr):
            base = re.sub(r"_(bucket|count|sum)$", "", name)
            candidates = {base, re.sub(r"_total$", "", base)}
            assert any(f'"{candidate}"' in sources for candidate in candidates), f"{where}: {name} is never defined"


def test_every_label_value_a_panel_or_rule_selects_on_a_tribrid_metric_is_emitted() -> None:
    """`outcome="client_disconnected"` would parse, run, and match nothing forever."""

    sources = _server_sources()
    for where, expr in _promql_exprs():
        for _, selector in _TRIBRID_SELECTOR_RE.findall(expr):
            for label, _, value in _LABEL_MATCHER_RE.findall(selector):
                alternatives = value.split("|")
                if not all(re.fullmatch(r"[A-Za-z0-9_.\-]+", item) for item in alternatives):
                    continue  # a real regex, not a list of literals
                for item in alternatives:
                    assert f'"{item}"' in sources, f"{where}: {label}={item!r} is never emitted"


def test_chat_label_values_are_members_of_the_contract_sets() -> None:
    from typing import get_args

    from server.models.tribrid_config_model import RunOutcome
    from server.observability.metrics import CHAT_TOKEN_KINDS, FEEDBACK_SIGNALS

    allowed = {"outcome": set(get_args(RunOutcome)) - {"cancelled"}, "kind": set(CHAT_TOKEN_KINDS), "signal": set(FEEDBACK_SIGNALS)}
    seen: set[str] = set()
    for where, expr in _promql_exprs():
        for name, selector in _TRIBRID_SELECTOR_RE.findall(expr):
            if not name.startswith(("tribrid_chat_", "tribrid_feedback_")):
                continue
            for label, _, value in _LABEL_MATCHER_RE.findall(selector):
                if label in allowed:
                    seen.add(label)
                    assert set(value.split("|")) <= allowed[label], f"{where}: {label}={value!r}"
    assert seen == {"outcome", "kind", "signal"}


def test_chat_dashboard_ratios_exclude_disconnects_and_never_add_reasoning_to_output() -> None:
    panels = {panel["title"]: panel for panel in _panels(_dashboards()["chat.json"])}
    error_ratio = panels["Chat error ratio, excluding client disconnects (selected range)"]
    expr = error_ratio["targets"][0]["expr"]
    assert 'outcome!~"ok|client_disconnect"' in expr and "or on() (0 * " in expr
    mappings = error_ratio["fieldConfig"]["defaults"]["mappings"]
    assert {"match": "nan", "result": {"text": "No traffic"}} in [item["options"] for item in mappings]
    tokens = panels["Chat tokens per minute by kind (output includes reasoning)"]
    assert tokens["fieldConfig"]["defaults"]["custom"]["stacking"]["mode"] == "none"
    assert "sum by (kind)" in tokens["targets"][0]["expr"]
    # No model variable: the feedback and Recall panels carry no model label.
    assert _dashboards()["chat.json"]["templating"]["list"] == []


def test_index_size_panels_are_per_corpus_not_the_last_run_in_this_process() -> None:
    for file_name, dashboard in _dashboards().items():
        for panel, expr in _exprs(dashboard):
            assert "Last index run" not in panel["title"], f"{file_name}: {panel['title']}"
            assert not re.search(r"tribrid_(chunks_indexed|graph_entities|graph_relationships)_current", expr), file_name
            if "tribrid_corpus_" in expr:
                assert expr.startswith("max by (corpus) (tribrid_corpus_") and panel["type"] == "bargauge", file_name


def test_rum_panels_chart_exactly_the_journeys_and_events_the_web_app_sends() -> None:
    rum_core = (ROOT / "web" / "src" / "observability" / "rumCore.ts").read_text(encoding="utf-8")
    union = rum_core.split("export type RumMeasurementName =", 1)[1].split(";", 1)[0]
    measurements = set(re.findall(r"'([a-z_]+)'", union))
    events = set(re.findall(r"'([a-z_]+)'", rum_core.split("export type RumEventName =", 1)[1].split(";", 1)[0]))
    exprs = [expr for _, expr in _exprs(_dashboards()["frontend-rum.json"])]
    charted = [set(match.split("|")) for expr in exprs for match in re.findall(r'\| type=~"([^"]+)"', expr)]
    assert charted and all(names <= measurements for names in charted)
    assert measurements in charted, "one panel charts every journey"
    assert {name for name in measurements if name.startswith("chat_send_to_")} in charted
    charted_events = {name for expr in exprs for name in re.findall(r'event_name="([a-z_]+)"', expr)}
    assert charted_events == events
