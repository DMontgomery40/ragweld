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
        assert required_variables.issubset(variables)
