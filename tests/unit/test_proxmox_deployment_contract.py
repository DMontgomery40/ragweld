from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from server.models.tribrid_config_model import TriBridConfig

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "proxmox" / "render_config.py"
SOURCE_CONFIG = ROOT / "tribrid_config.json"
PRODUCTION_DEFAULTS = {
    ("generation", "gen_model"): "openai.gpt-5.4-mini",
    ("generation", "enrich_model"): "openai.gpt-5.4-mini",
    ("chat", "litellm", "default_model"): "openai.gpt-5.4-mini",
    ("chat", "multimodal", "vision_model_override"): "openai.gpt-5.4-mini",
    ("chat", "vllm", "enabled"): False,
    ("embedding", "embedding_backend"): "provider",
    ("embedding", "embedding_type"): "huggingface",
    ("embedding", "embedding_model"): "BAAI/bge-small-en-v1.5",
    ("embedding", "embedding_dim"): 384,
    ("ui", "chat_default_model"): "openai.gpt-5.4-mini",
    ("ui", "runtime_mode"): "production",
    ("ui", "open_browser"): False,
    ("ui", "grafana_base_url"): "https://grafana.ragweld.com",
    ("training", "ragweld_agent_flyte_admin_base_url"): "http://127.0.0.1:30080",
    ("training", "ragweld_agent_flyte_console_base_url"): "https://flyte.ragweld.com",
    ("training", "ragweld_agent_mlflow_tracking_url"): "http://127.0.0.1:55500",
    ("evaluation", "ragas_judge_model"): "openai.gpt-5.4-mini",
    ("evaluation", "promptfoo_grader_model"): "openai.gpt-5.4-mini",
}


def _run_renderer(*, source: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source",
            str(source),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _read_config(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _nested_get(payload: dict[str, object], path: tuple[str, ...]) -> object:
    current: object = payload
    for key in path:
        assert isinstance(current, dict)
        current = current[key]
    return current


def test_proxmox_renderer_writes_validated_production_defaults_atomically(tmp_path: Path) -> None:
    output = tmp_path / "tribrid_config.production.json"

    result = _run_renderer(source=SOURCE_CONFIG, output=output)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = _read_config(output)
    validated = TriBridConfig.model_validate(payload)
    assert output.read_text(encoding="utf-8") == json.dumps(
        validated.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
    ) + "\n"
    for path, expected in PRODUCTION_DEFAULTS.items():
        assert _nested_get(payload, path) == expected
    assert output.stat().st_mode & 0o777 == 0o600
    assert sorted(path.name for path in tmp_path.iterdir()) == [output.name]


def test_proxmox_renderer_preserves_source_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(SOURCE_CONFIG.read_bytes())
    output = tmp_path / "rendered.json"
    before = source.read_bytes()

    result = _run_renderer(source=source, output=output)

    assert result.returncode == 0, result.stdout + result.stderr
    assert source.read_bytes() == before


def test_proxmox_renderer_rejects_invalid_source_without_creating_output(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    payload = _read_config(SOURCE_CONFIG)
    payload["generation"]["gen_model"] = "OpenAI.GPT-5.4-mini"
    source.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "rendered.json"

    result = _run_renderer(source=source, output=output)

    assert result.returncode != 0
    assert not output.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == [source.name]


def test_proxmox_renderer_keeps_existing_output_on_validation_failure(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    payload = _read_config(SOURCE_CONFIG)
    payload["chat"]["litellm"]["default_model"] = "not/a-valid-alias"
    source.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "rendered.json"
    output.write_text('{"keep":"me"}\n', encoding="utf-8")
    before = output.read_text(encoding="utf-8")

    result = _run_renderer(source=source, output=output)

    assert result.returncode != 0
    assert output.read_text(encoding="utf-8") == before
    assert sorted(path.name for path in tmp_path.iterdir()) == [output.name, source.name]
