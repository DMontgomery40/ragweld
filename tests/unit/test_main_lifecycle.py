from __future__ import annotations

import pytest
import asyncio

from server.main import _enter_lifecycle_cm


class _FailingLifecycleCM:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False
        self.exit_exc_type = None

    async def __aenter__(self) -> None:
        self.entered = True
        raise RuntimeError("startup failed")

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.exited = True
        self.exit_exc_type = exc_type
        return False


class _CancelledLifecycleCM:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False
        self.exit_exc_type = None

    async def __aenter__(self) -> None:
        self.entered = True
        raise asyncio.CancelledError("startup cancelled")

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.exited = True
        self.exit_exc_type = exc_type
        return False


@pytest.mark.asyncio
async def test_enter_lifecycle_cm_unwinds_when_enter_fails() -> None:
    cm = _FailingLifecycleCM()

    with pytest.raises(RuntimeError, match="startup failed"):
        await _enter_lifecycle_cm(cm)

    assert cm.entered is True
    assert cm.exited is True
    assert cm.exit_exc_type is RuntimeError


@pytest.mark.asyncio
async def test_enter_lifecycle_cm_unwinds_when_enter_cancelled() -> None:
    cm = _CancelledLifecycleCM()

    with pytest.raises(asyncio.CancelledError, match="startup cancelled"):
        await _enter_lifecycle_cm(cm)

    assert cm.entered is True
    assert cm.exited is True
    assert cm.exit_exc_type is asyncio.CancelledError
