import hashlib
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

# Prompt defaults that were replaced. The System Prompts page persists the default text when
# nothing was edited, so every config written before the replacement carries the old default
# verbatim; a stored value equal to a retired default is the default, not an operator edit,
# and is dropped so the LAW default applies. Keyed by (section, field) -> sha256 of the
# retired text. `semantic_kg_extraction`: the pre-official JSON prompt (no ``{schema}``/``{text}``
# placeholders), replaced by the official extraction template with naming rules (D24).
_RETIRED_PROMPT_DEFAULTS: dict[tuple[str, str], frozenset[str]] = {
    ("system_prompts", "semantic_kg_extraction"): frozenset(
        {"09403fdaed97ddfecf2574ae434da9669bdebe16e5522f61a5ae4f939f71b194"}
    ),
}


def drop_retired_prompt_defaults(raw: Any) -> list[str]:
    """Remove stored prompts equal to a retired default; return the dotted keys dropped."""
    dropped: list[str] = []
    if not isinstance(raw, dict):
        return dropped
    for (section, field), retired_hashes in _RETIRED_PROMPT_DEFAULTS.items():
        block = raw.get(section)
        if not isinstance(block, dict) or field not in block:
            continue
        value = block.get(field)
        if not isinstance(value, str):
            continue
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if digest in retired_hashes:
            del block[field]
            dropped.append(f"{section}.{field}")
    return dropped


def _strip_removed_keys(raw: Any) -> Any:
    """Drop keys removed from the schema so a pre-migration persisted config still loads."""
    if isinstance(raw, dict):
        chat = raw.get("chat")
        if isinstance(chat, dict):
            for key in _REMOVED_CHAT_PROMPT_KEYS:
                chat.pop(key, None)
        drop_retired_prompt_defaults(raw)
    return raw


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> TriBridConfig:
    if path.exists():
        raw = json.loads(path.read_text())
        return TriBridConfig.model_validate(_strip_removed_keys(raw))
    raise FileNotFoundError(f"Config file not found: {path}")


def save_config(config: TriBridConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.write_text(config.model_dump_json(indent=2))
