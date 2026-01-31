from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["docker"])


@router.get("/docker/status")
async def get_docker_status() -> dict[str, dict[str, Any]]:
    raise NotImplementedError


@router.post("/docker/{container}/restart")
async def restart_container(container: str) -> dict[str, Any]:
    raise NotImplementedError


@router.get("/docker/{container}/logs")
async def get_container_logs(container: str, lines: int = 100) -> list[str]:
    raise NotImplementedError
