"""Restore finalization against real, uniquely labelled Docker resources."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from deploy.proxmox.restore_drill import (
    DisposableDrill,
    DrillEvidence,
    command,
    finalize_drill,
)


@pytest.fixture
def drill_case(tmp_path: Path):
    identifier = "ragweld-restore-cleanup-check-" + uuid4().hex
    drill = DisposableDrill(identifier)
    evidence = DrillEvidence(
        drill_id=identifier, backup=str(tmp_path / "backup"),
        started_at=datetime.now(timezone.utc).isoformat(), status="passed",
        checksums={}, image_ids={},
    )
    target = tmp_path / "evidence.json"
    label = f"label=ragweld.restore-drill={identifier}"
    try:
        yield drill, evidence, target
    finally:
        # A failure is the test input; independently remove only this UUID's resources.
        containers = command(["docker", "ps", "-aq", "--filter", label]).split()
        if containers:
            command(["docker", "rm", "-f", "-v", *containers])
        volumes = command(["docker", "volume", "ls", "-q", "--filter", label]).split()
        if volumes:
            command(["docker", "volume", "rm", *volumes])
        assert not command(["docker", "ps", "-aq", "--filter", label])
        assert not command(["docker", "volume", "ls", "-q", "--filter", label])


def test_cleanup_exception_persists_failed_evidence(drill_case) -> None:
    drill, evidence, target = drill_case
    volume = drill.volume("held")
    # The drill owns the volume but has no ownership of the container holding it.
    # Docker must refuse volume removal; the finalizer must record that real failure.
    command([
        "docker", "create", "--label", f"ragweld.restore-drill={drill.identifier}",
        "--network", "none", "--entrypoint", "/bin/sh",
        "--mount", f"type=volume,source={volume},target=/scratch",
        "pgvector/pgvector:pg16", "-c", "sleep 120",
    ])
    with pytest.raises(RuntimeError, match="docker failed"):
        finalize_drill(drill, evidence, target)
    saved = DrillEvidence.model_validate_json(target.read_text())
    assert saved.status == "failed"
    assert saved.cleanup_verified is False


def test_untracked_labelled_volume_persists_failed_evidence(drill_case) -> None:
    drill, evidence, target = drill_case
    command([
        "docker", "volume", "create", "--label", f"ragweld.restore-drill={drill.identifier}",
        f"{drill.identifier}-untracked",
    ])
    with pytest.raises(RuntimeError, match="Disposable resources remain"):
        finalize_drill(drill, evidence, target)
    saved = DrillEvidence.model_validate_json(target.read_text())
    assert saved.status == "failed"
    assert saved.cleanup_verified is False


@pytest.mark.parametrize("status", ["passed", "failed"])
def test_verified_cleanup_preserves_restore_outcome(drill_case, status) -> None:
    drill, evidence, target = drill_case
    evidence.status = status
    volume = drill.volume("owned")
    drill.start(
        "owned", "pgvector/pgvector:pg16",
        ["--entrypoint", "/bin/sh", "--mount", f"type=volume,source={volume},target=/scratch"],
        ["-c", "sleep 120"],
    )
    finalize_drill(drill, evidence, target)
    saved = DrillEvidence.model_validate_json(target.read_text())
    assert saved.status == status
    assert saved.cleanup_verified is True
    assert drill.containers == drill.volumes == []
