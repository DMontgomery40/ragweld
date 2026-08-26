#!/usr/bin/env python3
"""Export the repo-local contract bundle from code truth.

This script creates a machine-readable bundle that other workstreams can rely on
without scraping prose docs or reverse-engineering the running app.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = PROJECT_ROOT / "docs" / "references" / "contract-bundle"


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _iter_pydantic_models(module: ModuleType) -> dict[str, type[BaseModel]]:
    models: dict[str, type[BaseModel]] = {}
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if name.startswith("_"):
            continue
        if not issubclass(obj, BaseModel):
            continue
        if not obj.__module__.startswith("server.models."):
            continue
        obj.model_rebuild(force=True)
        models[name] = obj
    return dict(sorted(models.items()))


def build_json_schema_bundle() -> dict[str, Any]:
    import server.models.index as index_models
    import server.models.tribrid_config_model as law

    # The aggregate is the composition root; boundary models owned by a domain
    # module that the aggregate does not re-export are walked explicitly.
    model_map = {**_iter_pydantic_models(index_models), **_iter_pydantic_models(law)}
    model_map = dict(sorted(model_map.items()))
    return {
        "module": law.__name__,
        "domain_modules": [index_models.__name__],
        "model_count": len(model_map),
        "root_models": {
            name: model.model_json_schema(ref_template="#/$defs/{model}")
            for name, model in model_map.items()
        },
    }


def build_openapi_bundle() -> dict[str, Any]:
    from server.main import app

    return app.openapi()


def build_surface_target_manifest() -> dict[str, Any]:
    return {
        "program": "oss-composition-fork",
        "status": "kickoff",
        "surfaces": {
            "inference": {
                "current": ["vllm"],
                "target": ["vllm"],
            },
            "gateway_routing": {
                "current": ["litellm"],
                "target": ["litellm"],
            },
            "orchestration": {
                "current": ["router-owned tasks", "jsonl streams", "filesystem run state"],
                "target": ["flyte"],
            },
            "retrieval_indexing": {
                "current": ["custom indexing", "custom fusion", "custom postgres retrieval"],
                "target": ["haystack", "docling", "qdrant"],
            },
            "graph_parity": {
                "current": ["custom neo4j graph builder and traversal"],
                "target": ["neo4j"],
            },
            "training_execution": {
                "current": ["mlx qwen3 trainers"],
                "target": ["unsloth"],
            },
            "runs_evals_regressions": {
                "current": ["file-backed eval and training runs"],
                "target": ["mlflow", "ragas", "promptfoo"],
            },
            "eval_drilldown": {
                "current": ["ragweld-owned drilldown ui and diff logic"],
                "target": ["langfuse", "mlflow", "ragas", "promptfoo"],
                "retain_custom": True,
            },
            "frontend_shell": {
                "current": ["custom dock shell", "custom app orchestration"],
                "target": ["dockview", "react-resizable-panels", "tanstack-query"],
            },
            "chat_surface": {
                "current": ["hand-rolled chat feature tree"],
                "target": ["assistant-ui"],
            },
            "observability": {
                "current": ["prometheus", "custom traces", "custom logs"],
                "target": [
                    "opentelemetry",
                    "grafana-alloy",
                    "prometheus",
                    "mimir",
                    "tempo",
                    "loki",
                    "pyroscope",
                    "faro",
                    "opencost",
                    "langfuse",
                ],
            },
        },
    }


def write_bundle(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "openapi.json": build_openapi_bundle(),
        "json_schema_bundle.json": build_json_schema_bundle(),
        "surface_target_manifest.json": build_surface_target_manifest(),
    }
    written: list[Path] = []
    for name, payload in outputs.items():
        path = out_dir / name
        path.write_text(_canonical_json(payload))
        written.append(path)
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export the repo-local contract bundle.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUT_DIR})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir.resolve()
    written = write_bundle(out_dir)
    print("Exported contract bundle:")
    for path in written:
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(PROJECT_ROOT))
    raise SystemExit(main())
