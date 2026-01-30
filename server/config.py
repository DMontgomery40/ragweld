import json
from pathlib import Path

from server.models.tribrid_config_model import TriBridConfig

DEFAULT_CONFIG_PATH = Path("tribrid_config.json")


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> TriBridConfig:
    if path.exists():
        return TriBridConfig.model_validate_json(path.read_text())
    raise FileNotFoundError(f"Config file not found: {path}")


def save_config(config: TriBridConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.write_text(config.model_dump_json(indent=2))
