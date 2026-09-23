#!/usr/bin/env python3
"""Run every provisioned Grafana panel query (and every alert rule) against the live stores.

Text-contract tests prove what a dashboard *says*; this proves what it *shows*. Each
PromQL target runs against Prometheus or Mimir (by the panel's datasource uid), each LogQL
target against Loki, over the dashboard's default time range, with Grafana's macros and the
dashboard's template variables substituted the way Grafana would on first load.

Every target lands in exactly one bucket:

- ``series``            at least one sample that is not NaN.
- ``empty-explained``   no usable sample, and the panel carries a ``noValue`` text that names
                        the flow that fills it (an index run, an eval run, no traffic ...).
                        The explanation lives in the dashboard, never in an allowlist here.
- ``empty-unexplained`` no usable sample and nothing on the panel says why.
- ``error``             the store rejected the query.

Idle ``histogram_quantile`` and ``0/0`` ratios return NaN-valued series; those count as
empty. For every empty target the report adds lookback evidence: for each metric the
expression reads, how many series exist now and whether any of them changed in 7 days.

Alert rules are evaluated as instant queries and reported as ``firing-now`` / ``quiet`` /
``error`` so a deploy can predict which alerts go out the moment it lands.

Run it on the Ragweld host (LXC100), where the stores listen on loopback:

    PYTHONPATH=$PWD .venv/bin/python scripts/check_grafana_queries.py
    PYTHONPATH=$PWD .venv/bin/python scripts/check_grafana_queries.py --promql-store prometheus

Exit status is 1 when any target errors or is empty without an explanation.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT / "infra" / "grafana" / "provisioning" / "dashboards"
RULES_PATH = ROOT / "infra" / "prometheus-rules.yml"

DEFAULT_PROMETHEUS_URL = "http://127.0.0.1:59090"
DEFAULT_MIMIR_URL = "http://127.0.0.1:59009/prometheus"
DEFAULT_LOKI_URL = "http://127.0.0.1:53100"

# Grafana's default datasource is Mimir (infra/grafana/provisioning/datasources/mimir.yml).
DEFAULT_DATASOURCE_UID = "mimir"
PROMQL_UIDS = {"mimir", "prometheus"}
LOKI_UIDS = {"loki"}

# What Grafana substitutes for its interval macros on a ~1000px panel at the default
# ranges used here; the check only needs a window that holds a few scrapes.
RATE_INTERVAL = "1m"
INTERVAL = "1m"

_METRIC_NAME_RE = re.compile(r"\b((?:tribrid|litellm|traces|vllm|laya|process|up|ALERTS|codex)[a-zA-Z0-9_:]*)\b")
_PROMQL_KEYWORDS = {"up"}
_VARIABLE_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)(?::[a-z]+)?\}?")


@dataclass(frozen=True)
class PanelTarget:
    dashboard_file: str
    dashboard_uid: str
    panel_id: int | None
    panel_title: str
    panel_type: str
    datasource_uid: str
    ref_id: str
    expr: str
    instant: bool
    no_value: str | None
    range_seconds: int
    nan_text: str | None = None


@dataclass
class TargetResult:
    target: PanelTarget
    status: str
    expr: str
    detail: str = ""
    evidence: list[str] = field(default_factory=list)


def parse_relative_range(value: str, *, now: datetime) -> int:
    """Seconds covered by a Grafana ``time.from`` like ``now-6h`` or ``now/d``."""

    text = str(value or "").strip()
    if text == "now/d":
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return max(60, int((now - midnight).total_seconds()))
    match = re.fullmatch(r"now-(\d+)([smhdw])(?:/[smhdw])?", text)
    if not match:
        return 3600
    amount, unit = int(match.group(1)), match.group(2)
    return amount * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


def _duration(seconds: int) -> str:
    return f"{int(seconds)}s"


def variable_values(dashboard: dict[str, Any]) -> dict[str, str]:
    """What each template variable expands to on first load (All -> its allValue)."""

    values: dict[str, str] = {}
    for variable in dashboard.get("templating", {}).get("list", []) or []:
        name = str(variable.get("name") or "")
        if not name:
            continue
        current = variable.get("current") or {}
        current_value = current.get("value")
        if isinstance(current_value, list):
            current_value = current_value[0] if current_value else None
        if variable.get("includeAll") and (current_value in (None, "", "$__all") or current_value == ["$__all"]):
            values[name] = str(variable.get("allValue") or ".*")
        elif current_value not in (None, ""):
            values[name] = str(current_value)
        else:
            values[name] = str(variable.get("query") or ".*")
    return values


def substitute(expr: str, *, variables: dict[str, str], range_seconds: int) -> str:
    text = str(expr)
    text = text.replace("$__rate_interval", RATE_INTERVAL)
    text = text.replace("$__interval", INTERVAL)
    text = text.replace("$__range", _duration(range_seconds))

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return variables.get(name, match.group(0))

    return _VARIABLE_RE.sub(_replace, text)


def _panel_datasource_uid(panel: dict[str, Any], target: dict[str, Any]) -> str:
    for holder in (target, panel):
        datasource = holder.get("datasource")
        if isinstance(datasource, dict) and datasource.get("uid"):
            return str(datasource["uid"])
        if isinstance(datasource, str) and datasource:
            return datasource
    return DEFAULT_DATASOURCE_UID


def _walk_panels(panels: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for panel in panels or []:
        yield panel
        yield from _walk_panels(panel.get("panels") or [])


def iter_dashboard_targets(path: Path, *, now: datetime | None = None) -> Iterator[PanelTarget]:
    now = now or datetime.now(UTC)
    dashboard = json.loads(path.read_text(encoding="utf-8"))
    range_seconds = parse_relative_range(str((dashboard.get("time") or {}).get("from") or "now-1h"), now=now)
    for panel in _walk_panels(dashboard.get("panels") or []):
        defaults = (panel.get("fieldConfig") or {}).get("defaults") or {}
        no_value = defaults.get("noValue")
        nan_text = next(
            (
                str(((mapping.get("options") or {}).get("result") or {}).get("text") or "")
                for mapping in defaults.get("mappings") or []
                if mapping.get("type") == "special" and (mapping.get("options") or {}).get("match") in ("nan", "null+nan")
            ),
            None,
        )
        for position, target in enumerate(panel.get("targets") or []):
            expr = target.get("expr") or target.get("query") or ""
            if not str(expr).strip():
                continue
            # Grafana names targets A, B, C ... when the JSON leaves refId out.
            ref_id = str(target.get("refId") or chr(ord("A") + position))
            yield PanelTarget(
                dashboard_file=path.name,
                dashboard_uid=str(dashboard.get("uid") or ""),
                panel_id=panel.get("id"),
                panel_title=str(panel.get("title") or ""),
                panel_type=str(panel.get("type") or ""),
                datasource_uid=_panel_datasource_uid(panel, target),
                ref_id=ref_id,
                expr=str(expr),
                instant=bool(target.get("instant")) or target.get("queryType") == "instant",
                no_value=str(no_value) if no_value else None,
                range_seconds=range_seconds,
                nan_text=nan_text or None,
            )


def dashboard_variables(path: Path) -> dict[str, str]:
    return variable_values(json.loads(path.read_text(encoding="utf-8")))


class StoreError(RuntimeError):
    pass


def _get_json(url: str, params: dict[str, str], *, timeout: float = 60.0) -> dict[str, Any]:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(full, timeout=timeout) as response:  # noqa: S310 - loopback stores only
            payload: dict[str, Any] = json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        raise StoreError(f"HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StoreError(f"unreachable: {exc}") from exc
    if payload.get("status") != "success":
        raise StoreError(str(payload.get("error") or payload)[:400])
    return payload


def _usable(value: Any) -> bool:
    """A sample Grafana would render: anything but NaN (+Inf is a real 'unlimited')."""

    try:
        return not math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def promql_has_data(base_url: str, expr: str, *, instant: bool, range_seconds: int) -> tuple[bool, int]:
    end = time.time()
    if instant:
        payload = _get_json(f"{base_url}/api/v1/query", {"query": expr, "time": f"{end:.3f}"})
        result = payload["data"].get("result") or []
        if payload["data"].get("resultType") == "scalar":
            return _usable(result[1]), 1
        usable = [row for row in result if _usable((row.get("value") or [None, None])[1])]
        return bool(usable), len(result)
    step = max(15, range_seconds // 250)
    payload = _get_json(
        f"{base_url}/api/v1/query_range",
        {"query": expr, "start": f"{end - range_seconds:.3f}", "end": f"{end:.3f}", "step": str(step)},
    )
    result = payload["data"].get("result") or []
    usable = [row for row in result if any(_usable(sample[1]) for sample in row.get("values") or [])]
    return bool(usable), len(result)


def _is_log_query(expr: str) -> bool:
    return expr.strip().startswith("{")


def logql_has_data(base_url: str, expr: str, *, instant: bool, range_seconds: int) -> tuple[bool, int]:
    end_ns = time.time_ns()
    start_ns = end_ns - range_seconds * 1_000_000_000
    if instant and not _is_log_query(expr):
        payload = _get_json(f"{base_url}/loki/api/v1/query", {"query": expr, "time": str(end_ns)})
        result = payload["data"].get("result") or []
        usable = [row for row in result if _usable((row.get("value") or [None, None])[1])]
        return bool(usable), len(result)
    if _is_log_query(expr):
        payload = _get_json(
            f"{base_url}/loki/api/v1/query_range",
            {"query": expr, "start": str(start_ns), "end": str(end_ns), "limit": "1", "direction": "backward"},
        )
        result = payload["data"].get("result") or []
        return any(stream.get("values") for stream in result), len(result)
    step = max(15, range_seconds // 250)
    payload = _get_json(
        f"{base_url}/loki/api/v1/query_range",
        {"query": expr, "start": str(start_ns), "end": str(end_ns), "step": str(step)},
    )
    result = payload["data"].get("result") or []
    usable = [row for row in result if any(_usable(sample[1]) for sample in row.get("values") or [])]
    return bool(usable), len(result)


def metric_names(expr: str) -> list[str]:
    names: list[str] = []
    for match in _METRIC_NAME_RE.finditer(expr):
        name = match.group(1)
        if name in names:
            continue
        # Skip label names and functions that merely share a prefix.
        following = expr[match.end() : match.end() + 1]
        if following == "=" or following == "~" or following == "!":
            continue
        names.append(name)
    return names


def lookback_evidence(base_url: str, expr: str) -> list[str]:
    evidence: list[str] = []
    for name in metric_names(expr):
        probe = name
        if name.endswith("_bucket"):
            probe = name[: -len("_bucket")] + "_count"
        try:
            present = _get_json(f"{base_url}/api/v1/query", {"query": f"count({probe})"})["data"]["result"]
            count_now = int(float(present[0]["value"][1])) if present else 0
            if name in _PROMQL_KEYWORDS or probe.startswith("ALERTS"):
                evidence.append(f"{probe}: {count_now} series now")
                continue
            changed = _get_json(
                f"{base_url}/api/v1/query", {"query": f"count(changes({probe}[7d]) > 0)"}
            )["data"]["result"]
            changed_series = int(float(changed[0]["value"][1])) if changed else 0
            evidence.append(f"{probe}: {count_now} series now, {changed_series} changed in 7d")
        except StoreError as exc:
            evidence.append(f"{probe}: probe failed ({exc})")
    return evidence


def check_target(
    target: PanelTarget,
    *,
    variables: dict[str, str],
    stores: dict[str, str],
    promql_override: str | None,
) -> TargetResult:
    expr = substitute(target.expr, variables=variables, range_seconds=target.range_seconds)
    uid = target.datasource_uid
    try:
        if uid in LOKI_UIDS:
            base = None
            has_data, series_count = logql_has_data(
                stores["loki"], expr, instant=target.instant, range_seconds=target.range_seconds
            )
        elif uid in PROMQL_UIDS:
            base = promql_override or stores[uid]
            has_data, series_count = promql_has_data(
                base, expr, instant=target.instant, range_seconds=target.range_seconds
            )
        else:
            return TargetResult(target, "error", expr, detail=f"unknown datasource uid {uid!r}")
    except StoreError as exc:
        return TargetResult(target, "error", expr, detail=str(exc))
    if has_data:
        return TargetResult(target, "series", expr)
    evidence = lookback_evidence(base, expr) if base else []
    if series_count:
        # Series exist but every sample is NaN: an idle histogram_quantile or a 0/0 ratio.
        detail = "only NaN samples (no traffic in the window)"
        explained = bool(target.no_value or target.nan_text)
        if target.nan_text:
            detail += f"; panel shows: {target.nan_text}"
    else:
        detail = f"no series; panel shows: {target.no_value}" if target.no_value else "no series"
        explained = bool(target.no_value)
    if explained:
        return TargetResult(target, "empty-explained", expr, detail=detail, evidence=evidence)
    return TargetResult(target, "empty-unexplained", expr, detail=detail + " (no noValue text)", evidence=evidence)


@dataclass
class RuleResult:
    group: str
    alert: str
    status: str
    detail: str = ""


def check_rules(base_url: str, rules_path: Path = RULES_PATH) -> list[RuleResult]:
    payload = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    results: list[RuleResult] = []
    for group in payload.get("groups") or []:
        for rule in group.get("rules") or []:
            if "alert" not in rule:
                continue
            try:
                data = _get_json(f"{base_url}/api/v1/query", {"query": str(rule["expr"])})["data"]
            except StoreError as exc:
                results.append(RuleResult(group["name"], rule["alert"], "error", str(exc)))
                continue
            rows = data.get("result") or []
            if rows:
                labels = [
                    ",".join(f"{k}={v}" for k, v in sorted(row.get("metric", {}).items()) if k != "__name__")
                    for row in rows[:4]
                ]
                results.append(RuleResult(group["name"], rule["alert"], "firing-now", "; ".join(labels) or "{}"))
            else:
                results.append(RuleResult(group["name"], rule["alert"], "quiet"))
    return results


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prometheus-url", default=DEFAULT_PROMETHEUS_URL)
    parser.add_argument("--mimir-url", default=DEFAULT_MIMIR_URL)
    parser.add_argument("--loki-url", default=DEFAULT_LOKI_URL)
    parser.add_argument(
        "--promql-store",
        choices=("by-datasource", "prometheus", "mimir"),
        default="by-datasource",
        help="Route every PromQL target to one store instead of the panel's datasource.",
    )
    parser.add_argument("--dashboard-dir", type=Path, default=DASHBOARD_DIR)
    parser.add_argument("--rules", type=Path, default=RULES_PATH)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable results.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    stores = {"prometheus": args.prometheus_url, "mimir": args.mimir_url, "loki": args.loki_url}
    override = None if args.promql_store == "by-datasource" else stores[args.promql_store]
    results: list[TargetResult] = []
    for path in sorted(args.dashboard_dir.glob("*.json")):
        variables = dashboard_variables(path)
        for target in iter_dashboard_targets(path):
            results.append(check_target(target, variables=variables, stores=stores, promql_override=override))
    rule_results = check_rules(override or args.prometheus_url, args.rules)

    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1

    if args.json:
        print(
            json.dumps(
                {
                    "counts": counts,
                    "targets": [
                        {
                            "dashboard": r.target.dashboard_file,
                            "panel_id": r.target.panel_id,
                            "panel": r.target.panel_title,
                            "ref": r.target.ref_id,
                            "datasource": r.target.datasource_uid,
                            "status": r.status,
                            "detail": r.detail,
                            "evidence": r.evidence,
                            "expr": r.expr,
                        }
                        for r in results
                    ],
                    "rules": [vars(rule) for rule in rule_results],
                },
                indent=2,
            )
        )
    else:
        current = ""
        for result in results:
            if result.target.dashboard_file != current:
                current = result.target.dashboard_file
                print(f"\n== {current} ({result.target.dashboard_uid})")
            target = result.target
            line = f"  [{target.panel_id}] {target.panel_title} ({target.ref_id}, {target.datasource_uid}): {result.status}"
            if result.detail:
                line += f" -- {result.detail}"
            print(line)
            for item in result.evidence:
                print(f"        {item}")
            if result.status == "error":
                print(f"        expr: {result.expr}")
        print("\n== alert rules (instant evaluation now)")
        for rule in rule_results:
            suffix = f" -- {rule.detail}" if rule.detail else ""
            print(f"  {rule.group}/{rule.alert}: {rule.status}{suffix}")
        print("\n== summary")
        for status in ("series", "empty-explained", "empty-unexplained", "error"):
            print(f"  {status}: {counts.get(status, 0)}")
        firing = [rule.alert for rule in rule_results if rule.status == "firing-now"]
        errors = [rule.alert for rule in rule_results if rule.status == "error"]
        print(f"  rules firing now: {', '.join(firing) or 'none'}")
        print(f"  rule errors: {', '.join(errors) or 'none'}")

    failed = counts.get("error", 0) + counts.get("empty-unexplained", 0)
    failed += sum(1 for rule in rule_results if rule.status == "error")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
