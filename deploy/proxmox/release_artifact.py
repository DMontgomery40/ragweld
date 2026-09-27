#!/usr/bin/env python3
"""Seal and materialize private, immutable releases without changing running services."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReleaseImage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: str
    image_id: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    repository_digests: list[str]


class ReleaseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    created_at: str
    git_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    git_tree: str = Field(pattern=r"^[a-f0-9]{40}$")
    artifacts: dict[str, str]
    locks: dict[str, str]
    web_files: dict[str, str]
    images: list[ReleaseImage]
    private_config_hashes: dict[str, str]
    backup_reference: str
    frontend_provenance: Literal["captured-prebuilt-assets"] = "captured-prebuilt-assets"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(command: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode:
        # Commands may handle secrets: never echo stderr, environment or argument values.
        raise RuntimeError(f"{command[0]} failed with exit {result.returncode}")
    return result.stdout.strip()


def running_images() -> list[ReleaseImage]:
    ids = run(["docker", "ps", "-q", "--filter", "label=com.docker.compose.project=ragweld"]).split()
    if not ids:
        raise ValueError("No running ragweld Compose containers")
    containers = json.loads(run(["docker", "inspect", *ids]))
    result = []
    for container in containers:
        image_id = container["Image"]
        metadata = json.loads(run(["docker", "image", "inspect", image_id]))[0]
        result.append(ReleaseImage(service=container["Config"]["Labels"]["com.docker.compose.service"],
                                   image_id=image_id, repository_digests=metadata.get("RepoDigests") or []))
    return sorted(result, key=lambda image: image.service)


def file_hashes(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Artifact tree contains symlink: {path.relative_to(root)}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def seal_release(repo: Path, output: Path, images: list[ReleaseImage],
                 config_paths: list[Path], backup_reference: str) -> ReleaseManifest:
    repo = repo.resolve(strict=True)
    if run(["git", "status", "--porcelain", "--untracked-files=no"], repo):
        raise ValueError("Tracked source is dirty; commit and verify it before sealing")
    if not (repo / "web/dist/index.html").is_file():
        raise ValueError("Built frontend index.html is missing")
    locks = {name: digest(repo / name) for name in ("uv.lock", "web/package-lock.json")}
    web_files = file_hashes(repo / "web/dist")
    config_hashes = {str(path): digest(path) for path in config_paths}
    git_sha = run(["git", "rev-parse", "HEAD"], repo)
    git_tree = run(["git", "rev-parse", "HEAD^{tree}"], repo)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    source = output / "source.tar"
    run(["git", "archive", "--format=tar", "--output", str(source), git_sha], repo)
    with tarfile.open(output / "web-dist.tar", "w") as archive:
        archive.add(repo / "web/dist", arcname="web/dist")
    # Use only already-present image IDs during owner-controlled recovery; never pull mutable tags.
    (output / "images.compose.json").write_text(json.dumps({"services": {
        image.service: {"image": image.image_id, "pull_policy": "never"} for image in images
    }}, indent=2) + "\n")
    manifest = ReleaseManifest(created_at=datetime.now(timezone.utc).isoformat(), git_sha=git_sha,
        git_tree=git_tree, artifacts={name: digest(output / name) for name in ("source.tar", "web-dist.tar", "images.compose.json")},
        locks=locks, web_files=web_files, images=images, private_config_hashes=config_hashes,
        backup_reference=backup_reference)
    # Refuse a concurrent edit/build instead of sealing mixed source and assets.
    if (run(["git", "rev-parse", "HEAD"], repo) != git_sha
            or run(["git", "status", "--porcelain", "--untracked-files=no"], repo)
            or file_hashes(repo / "web/dist") != web_files
            or any(digest(repo / name) != value for name, value in locks.items())):
        raise ValueError("Source or assets changed during capture; discard this incomplete release")
    (output / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
    (output / "manifest.sha256").write_text(digest(output / "manifest.json") + "\n")
    for path in output.iterdir():
        path.chmod(0o400)
    output.chmod(0o500)
    verify_release(output)
    return manifest


def verify_release(output: Path) -> ReleaseManifest:
    if digest(output / "manifest.json") != (output / "manifest.sha256").read_text().strip():
        raise ValueError("Release manifest checksum mismatch")
    manifest = ReleaseManifest.model_validate_json((output / "manifest.json").read_text())
    if set(manifest.artifacts) != {"source.tar", "web-dist.tar", "images.compose.json"}:
        raise ValueError("Release artifact inventory differs from the contract")
    for name, expected in manifest.artifacts.items():
        if digest(output / name) != expected:
            raise ValueError(f"Release checksum mismatch: {name}")
    return manifest


def materialize_release(output: Path, destination: Path) -> ReleaseManifest:
    manifest = verify_release(output)
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    for name in ("source.tar", "web-dist.tar"):
        with tarfile.open(output / name) as archive:
            # Do not follow archive symlinks or permit special files/path traversal.
            for member in archive.getmembers():
                if (not (member.isfile() or member.isdir()) or member.name.startswith("/")
                        or ".." in Path(member.name).parts):
                    raise ValueError(f"Unsafe release archive member: {member.name}")
            archive.extractall(destination, filter="data")
    if file_hashes(destination / "web/dist") != manifest.web_files:
        raise ValueError("Materialized web assets differ from manifest")
    for name, expected in manifest.locks.items():
        if digest(destination / name) != expected:
            raise ValueError(f"Materialized lock differs: {name}")
    (destination / "RELEASE-MANIFEST.json").write_text(manifest.model_dump_json(indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    seal = sub.add_parser("seal")
    seal.add_argument("--repo", type=Path, default=Path("/opt/ragweld"))
    seal.add_argument("--output", type=Path, required=True)
    seal.add_argument("--backup-reference", required=True)
    seal.add_argument("--config", type=Path, action="append", default=[])
    verify = sub.add_parser("verify")
    verify.add_argument("release", type=Path)
    materialize = sub.add_parser("materialize")
    materialize.add_argument("release", type=Path)
    materialize.add_argument("destination", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == "seal":
        result = seal_release(args.repo, args.output.resolve(), running_images(), args.config, args.backup_reference)
    elif args.action == "verify":
        result = verify_release(args.release)
    else:
        result = materialize_release(args.release, args.destination)
    print(json.dumps({"action": args.action, "git_sha": result.git_sha, "web_files": len(result.web_files),
                      "images": len(result.images)}))


if __name__ == "__main__":
    main()
