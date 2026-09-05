#!/usr/bin/env python3
"""Provision the real PDF test models, with immutable revisions and verified bytes.

The directory is consumed through Docling's DOCLING_ARTIFACTS_PATH setting.
It does not change the shared Hugging Face cache or other libraries' networking.
Update this manifest alongside uv.lock when Docling's defaults change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from importlib.metadata import distribution, version
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

MANIFEST_PATH = Path(__file__).with_name("docling_ci_models.json")


def verify_artifact(path: Path, artifact: dict[str, Any]) -> None:
    if not path.is_file() or path.stat().st_size != artifact["size"]:
        raise ValueError(f"Missing or wrong-sized Docling CI artifact: {path}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != artifact["sha256"]:
        raise ValueError(f"Checksum mismatch for Docling CI artifact: {path}")


def download_artifact(session: requests.Session, url: str, path: Path) -> None:
    with session.get(url, stream=True, timeout=(15, 90)) as response:
        response.raise_for_status()
        with path.open("wb") as stream:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                stream.write(chunk)


def create_session() -> requests.Session:
    retry = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504], allowed_methods={"GET"})
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def provision_artifact(
    session: requests.Session,
    root: Path,
    artifact: dict[str, Any],
    *,
    source: Path | str,
    verify_only: bool,
) -> None:
    relative = Path(artifact["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Invalid artifact path: {relative}")
    target = root / relative
    try:
        verify_artifact(target, artifact)
        return
    except ValueError:
        if verify_only:
            raise
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".partial", dir=target.parent)
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        if isinstance(source, Path):
            shutil.copyfile(source, temporary_path)
        else:
            download_artifact(session, source, temporary_path)
        verify_artifact(temporary_path, artifact)
        temporary_path.replace(target)
    finally:
        temporary_path.unlink(missing_ok=True)


def check_installed_defaults(manifest: dict[str, Any]) -> None:
    for package, expected in manifest["packages"].items():
        actual = version(package)
        if actual != expected:
            raise ValueError(f"Docling CI manifest requires {package}=={expected}; installed {actual}")
    # The Linux default OCR selects this engine before any fallback. Its exact
    # ONNX weights and dictionary are copied from the frozen RapidOCR wheel.
    version("onnxruntime")
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel

    defaults = PdfPipelineOptions()
    if defaults.layout_options.model_spec.repo_id != "docling-project/docling-layout-heron":
        raise ValueError("Docling's default layout model changed; update the CI manifest")
    if defaults.picture_classification_options.repo_id != "docling-project/DocumentFigureClassifier-v2.0":
        raise ValueError("Docling's default picture classifier changed; update the CI manifest")
    if defaults.table_structure_options.mode != TableFormerMode.ACCURATE:
        raise ValueError("Docling's default table model changed; update the CI manifest")
    expected_ocr = {f"RapidOcr/{row['path']}" for row in RapidOcrModel._default_models["onnxruntime"].values()}
    configured_ocr = {row["path"] for row in manifest["bundled_ocr"] + manifest["downloads"]}
    if configured_ocr != expected_ocr:
        raise ValueError("Docling's default OCR artifact paths changed; update the CI manifest")


def prepare_models(root: Path, *, verify_only: bool) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    check_installed_defaults(manifest)
    with create_session() as session:
        for model in manifest["huggingface"]:
            folder = model["repo_id"].replace("/", "--")
            for artifact in model["files"]:
                url = f"https://huggingface.co/{model['repo_id']}/resolve/{model['revision']}/{artifact['path']}"
                provision_artifact(session, root, {**artifact, "path": f"{folder}/{artifact['path']}"}, source=url, verify_only=verify_only)
            print(f"Verified {model['repo_id']}@{model['revision']}", flush=True)
        rapidocr = Path(distribution("rapidocr").locate_file("rapidocr"))
        for artifact in manifest["bundled_ocr"]:
            provision_artifact(session, root, artifact, source=rapidocr / artifact["source"], verify_only=verify_only)
        for artifact in manifest["downloads"]:
            provision_artifact(session, root, artifact, source=artifact["url"], verify_only=verify_only)
        print("Verified default RapidOCR artifacts", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-path", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true", help="Fail on missing or corrupt files without downloading")
    args = parser.parse_args()
    prepare_models(args.artifacts_path.resolve(), verify_only=args.verify_only)


if __name__ == "__main__":
    main()
