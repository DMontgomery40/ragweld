from __future__ import annotations

from fastapi import APIRouter

from server.models.tribrid_config_model import RuntimeCapabilitiesResponse
from server.runtime_capabilities import build_runtime_capabilities_response

router = APIRouter(prefix="/api/runtime-capabilities", tags=["runtime-capabilities"])


@router.get("", response_model=RuntimeCapabilitiesResponse)
async def get_runtime_capabilities() -> RuntimeCapabilitiesResponse:
    """Return the executable runtime capability matrix for selection and docs surfaces."""
    return build_runtime_capabilities_response()
