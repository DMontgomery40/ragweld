from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from server.models.tribrid_config_model import TriBridConfig

PRODUCTION_MODEL_ALIAS = "openai.gpt-5.6-terra"
PRODUCTION_CHAT_MAX_TOKENS = 4096
PRODUCTION_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
PRODUCTION_GRAFANA_URL = "https://grafana.ragweld.com"
PRODUCTION_LANGFUSE_PUBLIC_URL = "https://langfuse.ragweld.com"
PRODUCTION_LANGFUSE_RUNTIME_URL = "http://127.0.0.1:53000"
PRODUCTION_FARO_URL = "https://me.ragweld.com/faro/collect"
PRODUCTION_FLYTE_ADMIN_URL = "http://127.0.0.1:30080"
PRODUCTION_FLYTE_CONSOLE_URL = "https://flyte.ragweld.com"
PRODUCTION_MLFLOW_URL = "http://127.0.0.1:55500"
PRODUCTION_MLFLOW_CONSOLE_URL = "https://mlflow.ragweld.com"
PRODUCTION_FLYTE_CALLBACK_URL = "http://172.17.0.1:58012"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the validated Proxmox production config.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def _canonical_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _paths_identify_same_target(source: Path, output: Path) -> bool:
    try:
        if source.exists() and output.exists() and source.samefile(output):
            return True
    except OSError:
        pass
    return _canonical_path(source) == _canonical_path(output)


def _load_source(path: Path) -> TriBridConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TriBridConfig.model_validate(payload)


def _apply_production_defaults(config: TriBridConfig) -> TriBridConfig:
    config.generation.gen_model = PRODUCTION_MODEL_ALIAS
    config.generation.enrich_model = PRODUCTION_MODEL_ALIAS
    config.chat.max_tokens = PRODUCTION_CHAT_MAX_TOKENS
    config.chat.litellm.default_model = PRODUCTION_MODEL_ALIAS
    config.chat.multimodal.vision_model_override = PRODUCTION_MODEL_ALIAS
    config.chat.vllm.enabled = False
    config.embedding.embedding_backend = "provider"
    config.embedding.embedding_type = "huggingface"
    config.embedding.embedding_model = PRODUCTION_EMBEDDING_MODEL
    config.embedding.embedding_dim = 384
    config.ui.chat_default_model = PRODUCTION_MODEL_ALIAS
    config.ui.runtime_mode = "production"
    config.ui.open_browser = False
    config.ui.grafana_base_url = PRODUCTION_GRAFANA_URL
    config.tracing.langfuse_base_url = PRODUCTION_LANGFUSE_RUNTIME_URL
    config.tracing.langfuse_public_base_url = PRODUCTION_LANGFUSE_PUBLIC_URL
    config.tracing.faro_base_url = PRODUCTION_FARO_URL
    config.training.ragweld_agent_flyte_admin_base_url = PRODUCTION_FLYTE_ADMIN_URL
    config.training.ragweld_agent_flyte_console_base_url = PRODUCTION_FLYTE_CONSOLE_URL
    config.training.ragweld_agent_flyte_callback_base_url = PRODUCTION_FLYTE_CALLBACK_URL
    config.training.ragweld_agent_mlflow_tracking_url = PRODUCTION_MLFLOW_URL
    config.training.ragweld_agent_mlflow_console_base_url = PRODUCTION_MLFLOW_CONSOLE_URL
    config.evaluation.ragas_judge_model = PRODUCTION_MODEL_ALIAS
    config.evaluation.promptfoo_grader_model = PRODUCTION_MODEL_ALIAS
    return TriBridConfig.model_validate(config.model_dump(mode="json"))


def _write_output(path: Path, config: TriBridConfig) -> None:
    rendered = json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(rendered)
            temp_path = Path(handle.name)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    except Exception:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
        raise


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if _paths_identify_same_target(args.source, args.output):
            raise ValueError("source and output must identify different files")
        config = _load_source(args.source)
        rendered = _apply_production_defaults(config)
        _write_output(args.output, rendered)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
