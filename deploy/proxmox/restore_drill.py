#!/usr/bin/env python3
"""Restore logical backups into bounded disposable containers, never production volumes."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request
import uuid
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict


_T = TypeVar("_T")


class DrillEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    drill_id: str
    backup: str
    started_at: str
    status: Literal["running", "passed", "failed"] = "running"
    checksums: dict[str, str]
    image_ids: dict[str, str]
    postgres_tables: dict[str, int] = {}
    qdrant_points: dict[str, int] = {}
    neo4j_nodes: int = 0
    neo4j_relationships: int = 0
    inventory_only: list[str] = []
    cleanup_verified: bool = False


def command(args: list[str], *, stdin: str | None = None, timeout: int = 300) -> str:
    proc = subprocess.run(args, input=stdin, text=True, capture_output=True, timeout=timeout, check=False)
    if proc.returncode:
        raise RuntimeError(f"{args[0]} failed with exit {proc.returncode}; inspect private drill containers")
    return proc.stdout.strip()


def verify_backup(backup: Path) -> dict[str, str]:
    backup = backup.resolve(strict=True)
    entries = {}
    for line in (backup / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  (.+)", line)
        if not match:
            raise ValueError("Invalid backup checksum line")
        expected, name = match.groups()
        path = backup / name
        if (Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink()
                or not path.resolve().is_relative_to(backup) or name in entries):
            raise ValueError("Unsafe or duplicate backup checksum path")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError(f"Backup checksum mismatch: {name}")
        entries[name] = expected
    actual = {path.relative_to(backup).as_posix() for path in backup.rglob("*") if path.is_file()
              and path.name != "SHA256SUMS"}
    if set(entries) != actual:
        raise ValueError("Backup checksum inventory is incomplete")
    required = {"postgres/ragweld.dump", "neo4j/neo4j.dump", "mlflow/mlflow-data.tgz",
                "langfuse/langfuse-postgres.dump", "langfuse/langfuse-minio.tgz", "langfuse/langfuse-clickhouse.tgz"}
    if not required <= entries.keys() or not any(name.startswith("qdrant/") for name in entries):
        raise ValueError("Required backup components are missing")
    return entries


class DisposableDrill:
    def __init__(self, identifier: str) -> None:
        if not re.fullmatch(r"ragweld-restore-[a-z0-9-]+", identifier):
            raise ValueError("Invalid disposable drill identifier")
        self.identifier = identifier
        self.containers: list[str] = []
        self.volumes: list[str] = []

    def volume(self, store: str) -> str:
        name = f"{self.identifier}-{store}"
        if command(["docker", "volume", "ls", "-q", "--filter", f"name=^{name}$"]):
            raise ValueError("Disposable volume already exists")
        command(["docker", "volume", "create", "--label", f"ragweld.restore-drill={self.identifier}", name])
        self.volumes.append(name)
        return name

    def start(self, store: str, image: str, args: list[str], process: list[str] | None = None,
              memory: str = "512m", network: str = "none") -> str:
        name = f"{self.identifier}-{store}"
        command(["docker", "create", "--name", name, "--label", f"ragweld.restore-drill={self.identifier}",
                 "--memory", memory, "--memory-swap", memory, "--cpus", "2", "--pids-limit", "512",
                 "--network", network, "--hostname", "localhost", *args, image, *(process or [])])
        self.containers.append(name)
        command(["docker", "start", name])
        return name

    def remove_container(self, name: str) -> None:
        owner = command(["docker", "inspect", "-f", '{{index .Config.Labels "ragweld.restore-drill"}}', name])
        if name not in self.containers or owner != self.identifier:
            raise ValueError("Refusing removal of a foreign container")
        command(["docker", "rm", "-f", "-v", name])
        self.containers.remove(name)

    def cleanup(self) -> None:
        for name in list(self.containers):
            self.remove_container(name)
        for name in list(self.volumes):
            owner = command(["docker", "volume", "inspect", "-f", '{{index .Labels "ragweld.restore-drill"}}', name])
            if owner != self.identifier:
                raise ValueError("Refusing removal of a foreign volume")
            command(["docker", "volume", "rm", name])
            self.volumes.remove(name)


def wait_for(probe: Callable[[], _T], timeout: int = 120) -> _T:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return probe()
        except (RuntimeError, OSError, ValueError):
            time.sleep(2)
    raise TimeoutError("Disposable restore readiness timed out")


def finalize_drill(drill: DisposableDrill, evidence: DrillEvidence, target: Path) -> None:
    """Remove disposable resources and persist the verified cleanup outcome."""
    evidence.cleanup_verified = False
    try:
        drill.cleanup()
        containers = command(["docker", "ps", "-aq", "--filter", f"label=ragweld.restore-drill={drill.identifier}"])
        volumes = command(["docker", "volume", "ls", "-q", "--filter", f"label=ragweld.restore-drill={drill.identifier}"])
        if containers or volumes:
            raise RuntimeError("Disposable resources remain; review private evidence")
        evidence.cleanup_verified = True
    except BaseException:
        evidence.status = "failed"
        raise
    finally:
        target.write_text(evidence.model_dump_json(indent=2) + "\n")


def restore_drill(backup: Path, evidence_dir: Path) -> DrillEvidence:
    backup = backup.resolve(strict=True)
    checksums = verify_backup(backup)
    identifier = "ragweld-restore-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S-") + uuid.uuid4().hex[:8]
    images = {store: command(["docker", "inspect", "-f", "{{.Image}}", f"ragweld-{store}-1"])
              for store in ("postgres", "qdrant", "neo4j")}
    if any(not re.fullmatch(r"sha256:[a-f0-9]{64}", image) for image in images.values()):
        raise ValueError("Could not pin current store image IDs")
    evidence_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    evidence = DrillEvidence(drill_id=identifier, backup=str(backup), started_at=datetime.now(timezone.utc).isoformat(),
                             checksums=checksums, image_ids=images,
                             inventory_only=sorted(name for name in checksums if name.startswith(("mlflow/", "langfuse/"))))
    drill = DisposableDrill(identifier)
    target = evidence_dir / "evidence.json"
    target.write_text(evidence.model_dump_json(indent=2) + "\n")
    try:
        pg = drill.start("postgres", images["postgres"], ["-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_DB=ragweld",
            "-v", f"{drill.volume('postgres')}:/var/lib/postgresql/data", "-v", f"{backup / 'postgres'}:/backup:ro"])
        wait_for(lambda: command(["docker", "exec", pg, "pg_isready", "-U", "postgres", "-d", "ragweld"]))
        command(["docker", "exec", pg, "pg_restore", "--exit-on-error", "--no-owner", "--no-acl", "-U", "postgres",
                 "-d", "ragweld", "/backup/ragweld.dump"], timeout=600)
        table_sql = "SELECT quote_ident(schemaname)||'.'||quote_ident(tablename) FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        tables = command(["docker", "exec", pg, "psql", "-U", "postgres", "-d", "ragweld", "-Atc", table_sql]).splitlines()
        for table in tables:
            count = command(["docker", "exec", pg, "psql", "-U", "postgres", "-d", "ragweld", "-Atc", f"SELECT count(*) FROM {table}"])
            evidence.postgres_tables[table] = int(count)
        if sum(evidence.postgres_tables.values()) <= 0:
            raise ValueError("Restored Postgres has no rows")
        drill.remove_container(pg)
        target.write_text(evidence.model_dump_json(indent=2) + "\n")

        snapshots = sorted(name for name in checksums if name.startswith("qdrant/") and name.endswith(".snapshot"))
        snapshot_args = []
        for name in snapshots:
            if len(Path(name).parts) != 3 or not re.fullmatch(r"[a-zA-Z0-9_-]+", Path(name).parent.name):
                raise ValueError("Unsupported Qdrant snapshot path")
            snapshot_args.extend(["--snapshot", f"/backup/{name}:{Path(name).parent.name}"])
        qdrant = drill.start("qdrant", images["qdrant"], ["-p", "127.0.0.1::6333", "-v",
            f"{drill.volume('qdrant')}:/qdrant/storage", "-v", f"{backup}:/backup:ro"],
            ["./qdrant", "--disable-telemetry", *snapshot_args], memory="1g", network="bridge")
        binding = json.loads(command(["docker", "inspect", qdrant]))[0]["NetworkSettings"]["Ports"]["6333/tcp"][0]
        if binding["HostIp"] != "127.0.0.1":
            raise ValueError("Restore service escaped loopback")
        base = f"http://127.0.0.1:{binding['HostPort']}"

        def request(path: str) -> Any:
            with urllib.request.urlopen(base + path, timeout=5) as response:
                return json.load(response)["result"]

        collections = wait_for(lambda: request("/collections"), timeout=180)["collections"]
        expected = {Path(name).parent.name for name in snapshots}
        if {item["name"] for item in collections} != expected:
            raise ValueError("Restored Qdrant collection inventory differs from backup")
        for collection in sorted(expected):
            info = request("/collections/" + collection)
            evidence.qdrant_points[collection] = int(info["points_count"])
        if sum(evidence.qdrant_points.values()) <= 0:
            raise ValueError("Restored Qdrant has no points")
        drill.remove_container(qdrant)
        target.write_text(evidence.model_dump_json(indent=2) + "\n")

        neo_volume = drill.volume("neo4j")
        neo_args = ["-v", f"{neo_volume}:/data", "-v", f"{backup / 'neo4j'}:/backup:ro",
                    "-e", "NEO4J_AUTH=none", "-e", "NEO4J_server_memory_heap_initial__size=256m",
                    "-e", "NEO4J_server_memory_heap_max__size=512m", "-e", "NEO4J_server_memory_pagecache_size=256m"]
        loader = drill.start("neo4j-load", images["neo4j"], [*neo_args, "--entrypoint", "neo4j-admin"],
                             ["database", "load", "neo4j", "--from-path=/backup"], memory="2g")
        if command(["docker", "wait", loader], timeout=300) != "0":
            raise ValueError("Neo4j dump load failed")
        drill.remove_container(loader)
        neo = drill.start("neo4j", images["neo4j"], neo_args, memory="2g")

        def cypher_count(query: str) -> int:
            result = command(["docker", "exec", neo, "cypher-shell", "--format", "plain", query], timeout=30)
            return int(result.splitlines()[-1])

        evidence.neo4j_nodes = wait_for(lambda: cypher_count("MATCH (n) RETURN count(n) AS count"), timeout=180)
        evidence.neo4j_relationships = cypher_count("MATCH ()-[r]->() RETURN count(r) AS count")
        if evidence.neo4j_nodes <= 0:
            raise ValueError("Restored Neo4j has no nodes")
        evidence.status = "passed"
    except BaseException:
        evidence.status = "failed"
        raise
    finally:
        finalize_drill(drill, evidence, target)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    result = restore_drill(args.backup, args.evidence_dir)
    print(json.dumps({"status": result.status, "postgres_tables": len(result.postgres_tables),
        "postgres_rows": sum(result.postgres_tables.values()), "qdrant_collections": len(result.qdrant_points),
        "qdrant_points": sum(result.qdrant_points.values()), "neo4j_nodes": result.neo4j_nodes,
        "neo4j_relationships": result.neo4j_relationships, "cleanup_verified": result.cleanup_verified}))


if __name__ == "__main__":
    main()
