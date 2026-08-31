import json
import os
from pathlib import Path
from typing import Any

from server.models.tribrid_config_model import TriBridConfig

DEFAULT_CONFIG_PATH = Path(os.environ.get("RAGWELD_CONFIG_PATH") or "tribrid_config.json")

# Chat prompt keys removed with the legacy base+suffix composition (M-101/E-53). The store
# path strips these in server.services.config_store._upgrade_raw_config; the flat global-config
# loader must strip them too so a persisted tribrid_config.json that predates the removal still
# loads under the ChatConfig(extra="forbid") boundary. The removed keys are duplicated here
# (rather than imported) because config_store imports this module — importing back would create
# a circular import; server.config is the lowest-level config module.
_REMOVED_CHAT_PROMPT_KEYS = (
    "system_prompt_base",
    "system_prompt_rag_suffix",
    "system_prompt_recall_suffix",
)


def _strip_removed_keys(raw: Any) -> Any:
    """Drop keys removed from the schema so a pre-migration persisted config still loads."""
    if isinstance(raw, dict):
        chat = raw.get("chat")
        if isinstance(chat, dict):
            for key in _REMOVED_CHAT_PROMPT_KEYS:
                chat.pop(key, None)
    return raw


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> TriBridConfig:
    if path.exists():
        raw = json.loads(path.read_text())
        return TriBridConfig.model_validate(_strip_removed_keys(raw))
    raise FileNotFoundError(f"Config file not found: {path}")


def save_config(config: TriBridConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.write_text(config.model_dump_json(indent=2))
