"""Real filesystem and Git checks for release and recovery safety boundaries."""

from __future__ import annotations

import importlib.util
import errno
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
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
    original = release.seal_release(source_repo, output, [], [config], "/backups/immutable", project="ragweld-release-check-" + uuid.uuid4().hex)
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
        release.seal_release(source_repo, output, [], [], "/backups/immutable", project="ragweld-release-check-" + uuid.uuid4().hex)


def test_release_rejects_symlinked_frontend_root(source_repo: Path, tmp_path: Path) -> None:
    # Ignore both the build directory and a link at that path, so the rejection
    # exercises artifact validation rather than the clean-source gate.
    (source_repo / ".gitignore").write_text("web/dist\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Recovery acceptance", "-c",
                    "user.email=recovery@example.invalid", "commit", "-m", "Ignore build root"],
                   cwd=source_repo, check=True, capture_output=True)
    root = source_repo / "web/dist"
    assets = tmp_path / "served-assets"
    root.rename(assets)
    root.symlink_to(assets, target_is_directory=True)
    output = tmp_path / "refused"
    with pytest.raises(ValueError, match="Artifact tree contains symlink"):
        release.seal_release(source_repo, output, [], [], "/backups/immutable",
                             project="ragweld-release-check-" + uuid.uuid4().hex)
    assert not output.exists()
    assert (assets / "index.html").read_text() == "<main>Ragweld</main>\n"


@pytest.mark.parametrize("entry", ["frontend-hardlink", "frontend-fifo", "source-symlink"])
def test_release_rejects_unsupported_archive_members(source_repo: Path, tmp_path: Path, entry: str) -> None:
    if entry == "frontend-hardlink":
        os.link(source_repo / "web/dist/index.html", source_repo / "web/dist/copy.html")
    elif entry == "frontend-fifo":
        os.mkfifo(source_repo / "web/dist/leftover.pipe")
    else:
        (source_repo / "lock-link").symlink_to("uv.lock")
        subprocess.run(["git", "add", "lock-link"], cwd=source_repo, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=Recovery acceptance", "-c",
                        "user.email=recovery@example.invalid", "commit", "-m", "Tracked source symlink"],
                       cwd=source_repo, check=True, capture_output=True)
    output = tmp_path / "refused"
    with pytest.raises(ValueError, match="Unsafe release archive member"):
        release.seal_release(source_repo, output, [], [], "/backups/immutable",
                             project="ragweld-release-check-" + uuid.uuid4().hex)
    assert not (output / "manifest.json").exists()
    assert not (output / "manifest.sha256").exists()


@pytest.mark.parametrize("attribute", ["export-ignore", "export-subst"])
def test_release_rejects_archived_lock_content_drift(source_repo: Path, tmp_path: Path, attribute: str) -> None:
    (source_repo / ".gitattributes").write_text(f"uv.lock {attribute}\n")
    if attribute == "export-subst":
        (source_repo / "uv.lock").write_text('revision = "$Format:%H$"\n')
    subprocess.run(["git", "add", ".gitattributes", "uv.lock"], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Recovery acceptance", "-c",
                    "user.email=recovery@example.invalid", "commit", "-m", "Archive export attributes"],
                   cwd=source_repo, check=True, capture_output=True)
    output = tmp_path / "refused"
    with pytest.raises(ValueError, match="Release archive contents differ"):
        release.seal_release(source_repo, output, [], [], "/backups/immutable",
                             project="ragweld-release-check-" + uuid.uuid4().hex)
    assert not (output / "manifest.json").exists()
    assert not (output / "manifest.sha256").exists()


def commit_source(repo: Path) -> None:
    subprocess.run(["git", "add", "--all"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Recovery acceptance", "-c",
                    "user.email=recovery@example.invalid", "commit", "-m", "Committed source fixture"],
                   cwd=repo, check=True, capture_output=True)


@pytest.mark.parametrize("attribute", ["export-ignore", "export-subst"])
def test_release_rejects_archived_runtime_source_drift(source_repo: Path, tmp_path: Path, attribute: str) -> None:
    (source_repo / "server").mkdir()
    (source_repo / "server/runtime.py").write_text('REVISION = "$Format:%H$"\n')
    (source_repo / ".gitattributes").write_text(f"server/runtime.py {attribute}\n")
    commit_source(source_repo)
    output = tmp_path / "refused"
    with pytest.raises(ValueError, match="Committed source archive"):
        release.seal_release(source_repo, output, [], [], "/backups/immutable",
                             project="ragweld-release-check-" + uuid.uuid4().hex)
    assert not (output / "manifest.json").exists()
    assert not (output / "manifest.sha256").exists()


def test_release_rejects_committed_gitlinks(source_repo: Path, tmp_path: Path) -> None:
    commit = release.run(["git", "rev-parse", "HEAD"], source_repo)
    (source_repo / "vendor/module").mkdir(parents=True)
    subprocess.run(["git", "update-index", "--add", "--cacheinfo", f"160000,{commit},vendor/module"],
                   cwd=source_repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Recovery acceptance", "-c",
                    "user.email=recovery@example.invalid", "commit", "-m", "Committed gitlink fixture"],
                   cwd=source_repo, check=True, capture_output=True)
    output = tmp_path / "refused"
    with pytest.raises(ValueError, match="Unsupported committed source entry"):
        release.seal_release(source_repo, output, [], [], "/backups/immutable",
                             project="ragweld-release-check-" + uuid.uuid4().hex)
    assert not (output / "manifest.json").exists()
    assert not (output / "manifest.sha256").exists()


def test_release_rejects_archive_executable_mode_drift(source_repo: Path, tmp_path: Path) -> None:
    script = source_repo / "run-job.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    commit_source(source_repo)
    subprocess.run(["git", "config", "tar.umask", "0100"], cwd=source_repo, check=True, capture_output=True)
    output = tmp_path / "refused"
    with pytest.raises(ValueError, match="Committed source archive executable mode"):
        release.seal_release(source_repo, output, [], [], "/backups/immutable",
                             project="ragweld-release-check-" + uuid.uuid4().hex)
    assert not (output / "manifest.json").exists()
    assert not (output / "manifest.sha256").exists()


def test_release_preserves_binary_executable_and_unusual_source_names(source_repo: Path, tmp_path: Path) -> None:
    binary = source_repo / "binary with tab\tand newline\n.bin"
    binary.write_bytes(bytes(range(256)) * 4097)
    (source_repo / "empty.dat").touch()
    script = source_repo / "run-job.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    commit_source(source_repo)
    output = tmp_path / "sealed"
    manifest = release.seal_release(source_repo, output, [], [], "/backups/immutable",
                                    project="ragweld-release-check-" + uuid.uuid4().hex)
    destination = tmp_path / "restored"
    release.materialize_release(output, destination)
    assert manifest.git_tree == release.run(["git", "rev-parse", "HEAD^{tree}"], source_repo)
    assert (destination / binary.name).read_bytes() == binary.read_bytes()
    assert (destination / "empty.dat").read_bytes() == b""
    assert (destination / script.name).read_bytes() == script.read_bytes()
    assert (destination / script.name).stat().st_mode & 0o100
    assert not (destination / binary.name).stat().st_mode & 0o100


@pytest.mark.parametrize("reserved", [
    "web/dist/index.html", "web/dist/unbuilt.txt",
    "RELEASE-MANIFEST.json", "RELEASE-MANIFEST.json/nested.txt",
])
def test_release_rejects_source_in_materialization_owned_paths(source_repo: Path, tmp_path: Path, reserved: str) -> None:
    path = source_repo / reserved
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("Committed content must survive materialization.\n")
    subprocess.run(["git", "add", "--force", reserved], cwd=source_repo, check=True, capture_output=True)
    commit_source(source_repo)
    output = tmp_path / "refused"
    with pytest.raises(ValueError, match="Committed source overlaps materialization-owned paths"):
        release.seal_release(source_repo, output, [], [], "/backups/immutable",
                             project="ragweld-release-check-" + uuid.uuid4().hex)
    assert not (output / "manifest.json").exists()
    assert not (output / "manifest.sha256").exists()


def test_release_rejects_dirty_source_and_tampered_archive(source_repo: Path, tmp_path: Path) -> None:
    (source_repo / "uv.lock").write_text("version = 2\n")
    with pytest.raises(ValueError, match="dirty"):
        release.seal_release(source_repo, tmp_path / "dirty", [], [], "/backups/immutable", project="ragweld-release-check-" + uuid.uuid4().hex)
    subprocess.run(["git", "restore", "uv.lock"], cwd=source_repo, check=True)
    output = tmp_path / "sealed"
    release.seal_release(source_repo, output, [], [], "/backups/immutable", project="ragweld-release-check-" + uuid.uuid4().hex)
    (output / "web-dist.tar").chmod(0o600)
    with (output / "web-dist.tar").open("ab") as stream:
        stream.write(b"corruption")
    with pytest.raises(ValueError, match="checksum mismatch"):
        release.verify_release(output)


def test_materialize_rejects_archive_traversal_even_with_matching_digest(source_repo: Path, tmp_path: Path) -> None:
    output = tmp_path / "sealed"
    release.seal_release(source_repo, output, [], [], "/backups/immutable", project="ragweld-release-check-" + uuid.uuid4().hex)
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


@pytest.mark.parametrize("change", ["missing", "extra", "changed"])
def test_materialize_rejects_web_archive_content_drift(source_repo: Path, tmp_path: Path, change: str) -> None:
    output = tmp_path / "sealed"
    release.seal_release(source_repo, output, [], [], "/backups/immutable",
                         project="ragweld-release-check-" + uuid.uuid4().hex)
    archive = output / "web-dist.tar"
    archive.chmod(0o600)
    with tarfile.open(archive, "w") as stream:
        if change != "missing":
            body = (b"Changed frontend" if change == "changed" else
                    (source_repo / "web/dist/index.html").read_bytes())
            member = tarfile.TarInfo("web/dist/index.html")
            member.size = len(body)
            stream.addfile(member, io.BytesIO(body))
        if change == "extra":
            stream.addfile(tarfile.TarInfo("web/dist/unrecorded.js"), io.BytesIO())
    manifest_file = output / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["artifacts"]["web-dist.tar"] = release.digest(archive)
    manifest_file.chmod(0o600)
    manifest_file.write_text(json.dumps(manifest))
    checksum = output / "manifest.sha256"
    checksum.chmod(0o600)
    checksum.write_text(release.digest(manifest_file))
    destination = tmp_path / "restored"
    with pytest.raises(ValueError, match="Release archive contents differ"):
        release.materialize_release(output, destination)
    assert not (destination / "web/dist/index.html").exists()


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
        release.seal_release(source_repo, output, [], [], "/backups/immutable", project="ragweld-release-check-" + uuid.uuid4().hex)
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
    release.seal_release(source_repo, output, [], [], "/backups/immutable", project="ragweld-release-check-" + uuid.uuid4().hex)
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


@pytest.mark.parametrize("change", ["first", "second", "retarget", "swap"])
def test_release_rejects_private_config_changes_during_capture(
    source_repo: Path, tmp_path: Path, change: str,
) -> None:
    first = tmp_path / "first-private.json"
    second = tmp_path / "second-private.json"
    original = '{"credential":"private-before-capture"}'
    first.write_text(original)
    second.write_text(original)
    if change in {"retarget", "swap"}:
        target = tmp_path / "initial-target.json"
        first.rename(target)
        first.symlink_to(target)
    if change == "swap":
        second_target = tmp_path / "second-target.json"
        second.rename(second_target)
        second.symlink_to(second_target)

    # The final input is a FIFO: opening its writer proves both earlier config
    # hashes completed. Keep the writer open until the mutation is finished.
    barrier = tmp_path / "capture-barrier.json"
    os.mkfifo(barrier)
    output = tmp_path / "refused"
    script = """
import importlib.util
import sys
import uuid
from pathlib import Path
spec = importlib.util.spec_from_file_location("release_artifact", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
try:
    module.seal_release(Path(sys.argv[2]), Path(sys.argv[3]), [],
                        [Path(value) for value in sys.argv[4:]], "/backups/immutable", project="ragweld-release-check-" + uuid.uuid4().hex)
except ValueError as exc:
    print(str(exc))
    raise SystemExit(17)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(ROOT / "deploy/proxmox/release_artifact.py"),
         str(source_repo), str(output), str(first), str(second), str(barrier)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    writer = None
    try:
        deadline = time.monotonic() + 10
        while writer is None:
            try:
                writer = os.open(barrier, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as exc:
                if exc.errno != errno.ENXIO:
                    raise
                assert process.poll() is None, "Sealer exited before reaching the capture barrier"
                assert time.monotonic() < deadline, "Sealer did not reach the capture barrier"
                time.sleep(0.01)
        os.write(writer, b"capture-barrier")
        if change == "retarget":
            replacement = tmp_path / "replacement-target.json"
            replacement.write_text(original)
            first.unlink()
            first.symlink_to(replacement)
        elif change == "swap":
            first.unlink()
            second.unlink()
            first.symlink_to(second_target)
            second.symlink_to(target)
        else:
            (first if change == "first" else second).write_text('{"credential":"private-after-capture"}')
        # The initial hash reads the open FIFO; final verification reads an
        # ordinary file with identical bytes, so only the private config changed.
        barrier.unlink()
        barrier.write_bytes(b"capture-barrier")
        os.close(writer)
        writer = None
        stdout, stderr = process.communicate(timeout=10)
    finally:
        if writer is not None:
            os.close(writer)
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
    assert process.returncode == 17, (stdout, stderr)
    assert "configuration changed during capture" in stdout
    assert "private-before-capture" not in stdout + stderr
    assert "private-after-capture" not in stdout + stderr
    assert not (output / "manifest.json").exists()
    assert not (output / "manifest.sha256").exists()


@pytest.mark.parametrize("change", ["image", "remove-required", "remove-optional", "add-optional"])
def test_release_rejects_compose_changes_during_capture(
    source_repo: Path, tmp_path: Path, change: str,
) -> None:
    project = "ragweld-release-check-" + uuid.uuid4().hex
    image = release.run(["docker", "image", "inspect", "pgvector/pgvector:pg16", "--format", "{{.Id}}"])
    containers: dict[str, str] = {}
    replacement = None
    process = None
    writer = None

    def create(service: str, image_id: str) -> None:
        containers[service] = release.run([
            "docker", "create", "--network", "none", "--entrypoint", "/bin/sh",
            "--label", f"com.docker.compose.project={project}",
            "--label", f"com.docker.compose.service={service}", image_id, "-c", "exit 0",
        ])

    try:
        create("gateway", image)
        if change != "add-optional":
            create("optional", image)
        captured = release.compose_images(project, {"gateway"}, {"optional"})
        inventory = tmp_path / "captured-images.json"
        inventory.write_text(json.dumps([item.model_dump() for item in captured]))
        barrier = tmp_path / "capture-barrier"
        os.mkfifo(barrier)
        output = tmp_path / "refused"
        script = """
import importlib.util
import json
import sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("release_artifact", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
images = [module.ReleaseImage.model_validate(item) for item in json.loads(Path(sys.argv[5]).read_text())]
try:
    module.seal_release(Path(sys.argv[2]), Path(sys.argv[3]), images,
                        [Path(sys.argv[4])], "/backups/immutable", project=sys.argv[6])
except ValueError as exc:
    print(str(exc))
    raise SystemExit(17)
"""
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(ROOT / "deploy/proxmox/release_artifact.py"),
             str(source_repo), str(output), str(barrier), str(inventory), project],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        deadline = time.monotonic() + 10
        while writer is None:
            try:
                writer = os.open(barrier, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as exc:
                if exc.errno != errno.ENXIO:
                    raise
                assert process.poll() is None, "Sealer exited before reaching the capture barrier"
                assert time.monotonic() < deadline, "Sealer did not reach the capture barrier"
                time.sleep(0.01)
        os.write(writer, b"capture-barrier")
        if change == "image":
            replacement = release.run(["docker", "commit", "--change", f"LABEL release-check={project}", containers["gateway"]])
            assert replacement != image
            release.run(["docker", "rm", "--volumes", containers.pop("gateway")])
            create("gateway", replacement)
        elif change.startswith("remove-"):
            service = "gateway" if change == "remove-required" else "optional"
            release.run(["docker", "rm", "--volumes", containers.pop(service)])
        else:
            create("optional", image)
        barrier.unlink()
        barrier.write_bytes(b"capture-barrier")
        os.close(writer)
        writer = None
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 17, (stdout, stderr)
        expected = {
            "image": "Compose images changed during capture",
            "remove-required": "Missing required Compose services: gateway",
            "remove-optional": "Missing required Compose services: optional",
            "add-optional": "Unexpected Compose service: optional",
        }
        assert expected[change] in stdout
        assert not (output / "manifest.json").exists()
        assert not (output / "manifest.sha256").exists()
    finally:
        if writer is not None:
            os.close(writer)
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
        if containers:
            release.run(["docker", "rm", "--force", "--volumes", *containers.values()])
        if replacement is not None:
            release.run(["docker", "image", "rm", replacement])
    assert not release.run(["docker", "ps", "--all", "-q", "--filter", f"label=com.docker.compose.project={project}"])


def test_image_identities_ignore_enumeration_order_and_reject_duplicate_services() -> None:
    gateway = release.ReleaseImage(service="gateway", image_id="sha256:" + "a" * 64,
        repository_digests=["registry/gateway@sha256:" + "b" * 64, "registry/alias@sha256:" + "b" * 64])
    database = release.ReleaseImage(service="database", image_id="sha256:" + "c" * 64,
        repository_digests=[])
    reordered = gateway.model_copy(update={"repository_digests": list(reversed(gateway.repository_digests))})
    assert release.image_identities([gateway, database]) == release.image_identities([database, reordered])
    with pytest.raises(ValueError, match="Duplicate services"):
        release.image_identities([gateway, gateway])
