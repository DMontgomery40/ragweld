"""Real filesystem and local HTTP checks for the pinned model provisioner."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from scripts.prepare_docling_ci import (
    MANIFEST_PATH,
    check_installed_defaults,
    create_session,
    provision_artifact,
    verify_artifact,
)


@pytest.fixture
def artifact_server():
    payload = b"private provisioning transport fixture\n"
    calls: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            calls.append(self.path)
            status = 200
            if self.path == "/rate-limited" and calls.count(self.path) == 1:
                status = 429
            elif self.path == "/missing":
                status = 404
            self.send_response(status)
            self.send_header("Retry-After", "0")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", payload, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_manifest_pins_frozen_dependencies_and_immutable_model_bytes() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    locked = tomllib.loads((MANIFEST_PATH.parents[1] / "uv.lock").read_text())
    packages = {package["name"]: package["version"] for package in locked["package"]}
    assert manifest["schema_version"] == 1
    for name, pinned in manifest["packages"].items():
        assert packages[name] == pinned
    for model in manifest["huggingface"]:
        assert re.fullmatch(r"[0-9a-f]{40}", model["revision"])
        for artifact in model["files"]:
            assert re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
            assert artifact["size"] > 0
    check_installed_defaults(manifest)


@pytest.mark.parametrize("endpoint, calls_expected", [("/success", 1), ("/rate-limited", 2)])
def test_download_retries_rate_limits_then_cache_and_verify_need_no_reads(tmp_path, artifact_server, endpoint, calls_expected) -> None:
    url, payload, calls = artifact_server
    artifact = {"path": "model/weights.bin", "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
    with create_session() as session:
        provision_artifact(session, tmp_path, artifact, source=url + endpoint, verify_only=False)
        assert (tmp_path / artifact["path"]).read_bytes() == payload
        for verify_only in (False, True):
            provision_artifact(session, tmp_path, artifact, source=url + endpoint, verify_only=verify_only)
    assert len(calls) == calls_expected
    assert not list(tmp_path.rglob("*.partial"))


@pytest.mark.parametrize("state", ["missing", "truncated", "corrupt"])
def test_verify_only_rejects_missing_truncated_and_corrupt_bytes_without_network(tmp_path, artifact_server, state) -> None:
    url, payload, calls = artifact_server
    artifact = {"path": "weights.bin", "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
    if state != "missing":
        existing = payload[:3] if state == "truncated" else b"x" * len(payload)
        (tmp_path / "weights.bin").write_bytes(existing)
    with create_session() as session, pytest.raises(ValueError):
        provision_artifact(session, tmp_path, artifact, source=url + "/success", verify_only=True)
    assert calls == []


@pytest.mark.parametrize("endpoint, correct_hash, error", [
    ("/success", False, ValueError), ("/missing", True, requests.HTTPError),
])
def test_failed_download_never_publishes_or_overwrites_an_artifact(tmp_path, artifact_server, endpoint, correct_hash, error) -> None:
    url, payload, calls = artifact_server
    original = b"previous incomplete cache entry"
    target = tmp_path / "weights.bin"
    target.write_bytes(original)
    artifact = {"path": target.name, "sha256": hashlib.sha256(payload).hexdigest() if correct_hash else "0" * 64, "size": len(payload)}
    with create_session() as session, pytest.raises(error):
        provision_artifact(session, tmp_path, artifact, source=url + endpoint, verify_only=False)
    assert target.read_bytes() == original
    assert len(calls) == 1
    assert not list(tmp_path.rglob("*.partial"))


def test_bundled_assets_are_copied_and_checksum_verified(tmp_path) -> None:
    source = tmp_path / "installed-wheel.bin"
    source.write_bytes(b"wheel asset")
    artifact = {"path": "models/asset.bin", "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "size": source.stat().st_size}
    with create_session() as session:
        provision_artifact(session, tmp_path, artifact, source=source, verify_only=False)
    verify_artifact(tmp_path / artifact["path"], artifact)
