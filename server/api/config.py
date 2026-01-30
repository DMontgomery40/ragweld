from fastapi import APIRouter
from typing import Any

from server.models.tribrid_config_model import TriBridConfig

router = APIRouter(tags=["config"])

# In-memory config store
_config: TriBridConfig | None = None


def _get_default_config() -> TriBridConfig:
    """Get default config - LAW provides all defaults via default_factory."""
    return TriBridConfig()


@router.get("/config", response_model=TriBridConfig)
async def get_config() -> TriBridConfig:
    global _config
    if _config is None:
        _config = _get_default_config()
    return _config


@router.put("/config", response_model=TriBridConfig)
async def update_config(config: TriBridConfig) -> TriBridConfig:
    raise NotImplementedError


@router.patch("/config/{section}", response_model=TriBridConfig)
async def update_config_section(section: str, updates: dict[str, Any]) -> TriBridConfig:
    raise NotImplementedError


@router.post("/config/reset", response_model=TriBridConfig)
async def reset_config() -> TriBridConfig:
    raise NotImplementedError
