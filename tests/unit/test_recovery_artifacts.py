"""Real filesystem and Git checks for release and recovery safety boundaries."""

from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "deploy/proxmox" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


release = load_tool("release_artifact")
restore = load_tool("restore_drill")


@pytest.fixture
def source_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "web/dist").mkdir(parents=True)
    (repo / "uv.lock").write_text("version = 1\n")
    (repo / "web/package-lock.json").write_text('{"lockfileVersion":3}\n')
    (repo / "web/dist/index.html").write_text("<main>Ragweld</main>\n")
    (repo / ".gitignore").write_text("web/dist/\n")
    for args in (["init"], ["add", "."], ["-c", "user.name=Recovery acceptance", "-c",
                 "user.email=recovery@example.invalid", "commit", "-m", "Recovery fixture"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return repo


def test_release_round_trip_and_refusal_to_overwrite(source_repo: Path, tmp_path: Path) -> None:
    output = tmp_path / "sealed"
    config = tmp_path / "private-config.json"
    config.write_text('{"credential":"only-the-hash-may-leave"}')
    original = release.seal_release(source_repo, output, [], [config], "/backups/immutable")
    assert "only-the-hash-may-leave" not in (output / "manifest.json").read_text()
    assert original.private_config_hashes[str(config)] == release.digest(config)
    destination = tmp_path / "materialized"
    restored = release.materialize_release(output, destination)
    assert restored.git_sha == original.git_sha
    assert (destination / "web/dist/index.html").read_bytes() == (source_repo / "web/dist/index.html").read_bytes()
    assert (destination / "uv.lock").read_bytes() == (source_repo / "uv.lock").read_bytes()
    with pytest.raises(FileExistsError):
        release.materialize_release(output, destination)
    with pytest.raises(FileExistsError):
        release.seal_release(source_repo, output, [], [], "/backups/immutable")


def test_release_rejects_dirty_source_and_tampered_archive(source_repo: Path, tmp_path: Path) -> None:
    (source_repo / "uv.lock").write_text("version = 2\n")
    with pytest.raises(ValueError, match="dirty"):
        release.seal_release(source_repo, tmp_path / "dirty", [], [], "/backups/immutable")
    subprocess.run(["git", "restore", "uv.lock"], cwd=source_repo, check=True)
    output = tmp_path / "sealed"
    release.seal_release(source_repo, output, [], [], "/backups/immutable")
    (output / "web-dist.tar").chmod(0o600)
    with (output / "web-dist.tar").open("ab") as stream:
        stream.write(b"corruption")
    with pytest.raises(ValueError, match="checksum mismatch"):
        release.verify_release(output)


def test_materialize_rejects_archive_traversal_even_with_matching_digest(source_repo: Path, tmp_path: Path) -> None:
    output = tmp_path / "sealed"
    release.seal_release(source_repo, output, [], [], "/backups/immutable")
    archive = output / "source.tar"
    archive.chmod(0o600)
    with tarfile.open(archive, "w") as stream:
        member = tarfile.TarInfo("../escaped")
        member.size = 3
        stream.addfile(member, io.BytesIO(b"bad"))
    manifest_file = output / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["artifacts"]["source.tar"] = release.digest(archive)
    manifest_file.chmod(0o600)
    manifest_file.write_text(json.dumps(manifest))
    checksum = output / "manifest.sha256"
    checksum.chmod(0o600)
    checksum.write_text(release.digest(manifest_file))
    with pytest.raises(ValueError, match="Unsafe"):
        release.materialize_release(output, tmp_path / "restored")
    assert not (tmp_path / "escaped").exists()


@pytest.fixture
def backup(tmp_path: Path) -> Path:
    backup = tmp_path / "backup"
    for name in ("postgres/ragweld.dump", "neo4j/neo4j.dump", "mlflow/mlflow-data.tgz",
                 "langfuse/langfuse-postgres.dump", "langfuse/langfuse-minio.tgz",
                 "langfuse/langfuse-clickhouse.tgz", "qdrant/corpus/corpus.snapshot"):
        path = backup / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    (backup / "SHA256SUMS").write_text("".join(f"{release.digest(path)}  {path.relative_to(backup)}\n"
        for path in sorted(backup.rglob("*")) if path.is_file()))
    return backup


def test_backup_inventory_is_exact_and_corruption_fails(backup: Path) -> None:
    assert len(restore.verify_backup(backup)) == 7
    (backup / "extra.dump").write_bytes(b"unlisted")
    with pytest.raises(ValueError, match="incomplete"):
        restore.verify_backup(backup)
    (backup / "extra.dump").unlink()
    (backup / "postgres/ragweld.dump").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum mismatch"):
        restore.verify_backup(backup)


def test_backup_rejects_checksum_path_escape(backup: Path) -> None:
    checksum = backup / "SHA256SUMS"
    checksum.write_text("0" * 64 + "  ../foreign\n")
    with pytest.raises(ValueError, match="Unsafe"):
        restore.verify_backup(backup)


def test_disposable_resource_names_cannot_target_production() -> None:
    with pytest.raises(ValueError, match="Invalid"):
        restore.DisposableDrill("ragweld")


@pytest.mark.parametrize("relative", [
    "server/untracked_behavior.py", "web/src/untracked_behavior.ts",
    ".claude/skills/gitnexus-unapproved/SKILL.md",
    ".claude/skills/gitnexus-cli/runtime.py",
    "web/.dist-before-unapproved/index.html",
    "web/.dist-dev-copy-20260912-extra/index.html",
    " server/newline\nsource.py",
])
def test_release_rejects_untracked_source(source_repo: Path, tmp_path: Path, relative: str) -> None:
    path = source_repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("This source is absent from the committed archive.\n")
    output = tmp_path / "refused"
    with pytest.raises(ValueError, match="Untracked source"):
        release.seal_release(source_repo, output, [], [], "/backups/immutable")
    assert not output.exists()


@pytest.mark.parametrize("relative", [
    ".claude/skills/gitnexus-cli/SKILL.md",
    ".claude/skills/gitnexus-debugging/SKILL.md",
    ".claude/skills/gitnexus-exploring/SKILL.md",
    ".claude/skills/gitnexus-guide/SKILL.md",
    ".claude/skills/gitnexus-impact-analysis/SKILL.md",
    ".claude/skills/gitnexus-refactoring/SKILL.md",
    "web/.dist-dev-copy-20260912/assets/index.js",
    "web/.dist-before-cb626e9b-20260927/index.html",
])
def test_release_allows_only_recorded_operational_files(
    source_repo: Path, tmp_path: Path, relative: str,
) -> None:
    path = source_repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Retained operational evidence.\n")
    output = tmp_path / "sealed"
    release.seal_release(source_repo, output, [], [], "/backups/immutable")
    with tarfile.open(output / "source.tar") as archive:
        assert relative not in archive.getnames()


def test_launcher_inventory_is_read_only_and_tracks_tunnel_selection(tmp_path: Path) -> None:
    env = {**os.environ, "RAGWELD_ETC_ROOT": str(tmp_path / "absent-private-config")}
    outputs = []
    for skip in ("0", "1"):
        result = subprocess.run(
            ["bash", str(ROOT / "deploy/proxmox/start-runtime.sh"), "--print-release-inventory"],
            env={**env, "RAGWELD_SKIP_TUNNEL": skip}, check=True, capture_output=True, text=True,
        )
        outputs.append(json.loads(result.stdout))
    assert not (tmp_path / "absent-private-config").exists()
    enabled, disabled = outputs
    assert set(enabled["required_services"]) == set(disabled["required_services"]) | {"cloudflared"}
    assert "cloudflared" not in disabled["required_services"]
    assert "postgres" in disabled["required_services"]
    assert enabled["optional_services"] == disabled["optional_services"] == ["laya"]
    assert enabled["compose_files"] == disabled["compose_files"]
    assert all((ROOT / name).is_file() for name in enabled["compose_files"])


def test_compose_inventory_includes_stopped_and_refuses_missing_required(tmp_path: Path) -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is required for real release inventory checks")
    available = subprocess.run(["docker", "info"], capture_output=True)
    if available.returncode:
        pytest.skip("Docker daemon is required for real release inventory checks")
    project = "ragweld-release-check-" + uuid.uuid4().hex
    image = release.run(["docker", "image", "inspect", "pgvector/pgvector:pg16", "--format", "{{.Id}}"])
    containers = []

    def create(service: str, *, oneoff: bool = False) -> str:
        container = release.run([
            "docker", "create", "--network", "none", "--entrypoint", "/bin/sh",
            "--label", f"com.docker.compose.project={project}",
            "--label", f"com.docker.compose.service={service}",
            "--label", f"com.docker.compose.oneoff={str(oneoff)}",
            image, "-c", "sleep 120",
        ])
        containers.append(container)
        return container

    try:
        gateway = create("gateway")
        database = create("database")
        create("optional")
        create("unrelated-oneoff", oneoff=True)
        release.run(["docker", "start", gateway])
        images = release.compose_images(project, {"gateway", "database"}, {"optional"})
        assert {item.service for item in images} == {"gateway", "database", "optional"}
        assert {item.image_id for item in images} == {image}
        assert release.run(["docker", "inspect", database, "--format", "{{.State.Running}}"]) == "false"
        release.run(["docker", "rm", database])
        containers.remove(database)
        create("database", oneoff=True)
        with pytest.raises(ValueError, match="Missing required Compose services: database"):
            release.compose_images(project, {"gateway", "database"}, {"optional"})
    finally:
        if containers:
            release.run(["docker", "rm", "--force", "--volumes", *containers])
    assert not release.run(["docker", "ps", "--all", "-q", "--filter", f"label=com.docker.compose.project={project}"])
