from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

from server.models.tribrid_config_model import TriBridConfig

PRODUCTION_MODEL_ALIAS = "openai.gpt-5.6-terra"
PRODUCTION_CHAT_MODEL_ALIAS = "z-ai.glm-5.3-flash"
PRODUCTION_LONG_FORM_MAX_TOKENS = 16000
PRODUCTION_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
PRODUCTION_GRAFANA_URL = "https://ragweld-grafana.dtmont.com"
PRODUCTION_LANGFUSE_PUBLIC_URL = "https://ragweld-langfuse.dtmont.com"
PRODUCTION_LANGFUSE_RUNTIME_URL = "http://127.0.0.1:53000"
# The deployment's own public origin, spelled once. Every value below that has to agree
# with it is derived rather than repeated: the Faro collector already encoded it, and the
# MCP endpoint the workbench advertises has to be the same origin or an MCP client is sent
# somewhere it cannot reach (M-91). Not taken from `tracing.langfuse_public_base_url` --
# that is a different host (`ragweld-langfuse`), and deriving from it would advertise the
# wrong one.
PRODUCTION_PUBLIC_ORIGIN = "https://ragweld.dtmont.com"
PRODUCTION_PUBLIC_HOST = PRODUCTION_PUBLIC_ORIGIN.split("://", 1)[1]
PRODUCTION_FARO_URL = f"{PRODUCTION_PUBLIC_ORIGIN}/faro/collect"
PRODUCTION_TRACE_STORE_PATH = "data/traces/workbench.json"
PRODUCTION_FLYTE_ADMIN_URL = "http://127.0.0.1:30080"
PRODUCTION_FLYTE_CONSOLE_URL = "https://ragweld-flyte.dtmont.com"
PRODUCTION_MLFLOW_URL = "http://127.0.0.1:55500"
PRODUCTION_MLFLOW_CONSOLE_URL = "https://ragweld-mlflow.dtmont.com"
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


def _with_entry(values: list[str], entry: str) -> list[str]:
    """Append `entry` without dropping what is already allowed, and without duplicating it.

    The loopback entries stay: an operator on the box, and the health probes, still reach
    the transport directly.
    """
    return list(values) if entry in values else [*values, entry]


def _apply_production_defaults(config: TriBridConfig) -> TriBridConfig:
    config.generation.gen_model = PRODUCTION_MODEL_ALIAS
    config.generation.enrich_model = PRODUCTION_MODEL_ALIAS
    config.generation.gen_max_tokens = PRODUCTION_LONG_FORM_MAX_TOKENS
    config.chat.max_tokens = PRODUCTION_LONG_FORM_MAX_TOKENS
    config.synthetic.generator.max_tokens = PRODUCTION_LONG_FORM_MAX_TOKENS
    config.chat.litellm.default_model = PRODUCTION_CHAT_MODEL_ALIAS
    config.chat.multimodal.vision_model_override = PRODUCTION_MODEL_ALIAS
    config.chat.vllm.enabled = False
    config.embedding.embedding_backend = "provider"
    config.embedding.embedding_type = "huggingface"
    config.embedding.embedding_model = PRODUCTION_EMBEDDING_MODEL
    config.embedding.embedding_dim = 384
    config.ui.chat_default_model = PRODUCTION_CHAT_MODEL_ALIAS
    config.ui.runtime_mode = "production"
    config.ui.open_browser = False
    config.ui.grafana_base_url = PRODUCTION_GRAFANA_URL
    config.tracing.langfuse_base_url = PRODUCTION_LANGFUSE_RUNTIME_URL
    config.tracing.langfuse_public_base_url = PRODUCTION_LANGFUSE_PUBLIC_URL
    config.tracing.faro_base_url = PRODUCTION_FARO_URL
    config.tracing.trace_store_path = PRODUCTION_TRACE_STORE_PATH
    config.training.ragweld_agent_flyte_admin_base_url = PRODUCTION_FLYTE_ADMIN_URL
    config.training.ragweld_agent_flyte_console_base_url = PRODUCTION_FLYTE_CONSOLE_URL
    config.training.ragweld_agent_flyte_callback_base_url = PRODUCTION_FLYTE_CALLBACK_URL
    config.training.ragweld_agent_mlflow_tracking_url = PRODUCTION_MLFLOW_URL
    config.training.ragweld_agent_mlflow_console_base_url = PRODUCTION_MLFLOW_CONSOLE_URL
    # MCP: the workbench advertises `public_base_url` + the mount path verbatim, and the
    # transport refuses any Host it does not recognise (421). Both have to be set or the
    # Infrastructure > MCP Servers page hands operators an address that does not work --
    # before this the rendered config carried neither, so it advertised the loopback
    # default and only loopback was allowed (M-91).
    #
    # `public_base_url` is the ORIGIN, not origin + "/mcp": the server appends
    # `mcp.mount_path` itself, so including it here would advertise `/mcp/mcp/`.
    config.mcp.public_base_url = PRODUCTION_PUBLIC_ORIGIN
    config.mcp.allowed_hosts = _with_entry(config.mcp.allowed_hosts, PRODUCTION_PUBLIC_HOST)
    config.mcp.allowed_origins = _with_entry(config.mcp.allowed_origins, PRODUCTION_PUBLIC_ORIGIN)
    config.evaluation.ragas_judge_model = PRODUCTION_MODEL_ALIAS
    config.evaluation.promptfoo_grader_model = PRODUCTION_MODEL_ALIAS
    return TriBridConfig.model_validate(config.model_dump(mode="json"))


def _write_output(path: Path, config: TriBridConfig) -> None:
    rendered = json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    try:
        existing_stat = path.lstat()
    except FileNotFoundError:
        existing_stat = None
    if existing_stat is not None and not stat.S_ISREG(existing_stat.st_mode):
        raise ValueError("output must be a regular file when it already exists")
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
            temp_path = Path(handle.name)
            handle.write(rendered)
            if existing_stat is not None:
                os.fchown(handle.fileno(), existing_stat.st_uid, existing_stat.st_gid)
            os.fchmod(handle.fileno(), 0o600)
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
