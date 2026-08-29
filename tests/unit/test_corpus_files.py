"""Corpus file resolution and hashing helpers."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from server.services.corpus_files import file_etag, resolve_corpus_file, sha256_file


def test_nested_relative_path_resolves_inside_root(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    target = tmp_path / "docs" / "a.txt"
    target.write_text("x")
    assert resolve_corpus_file(tmp_path, "docs/a.txt") == target.resolve()


def test_dot_dot_absolute_and_empty_paths_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    assert resolve_corpus_file(tmp_path, "../outside.txt") is None
    assert resolve_corpus_file(tmp_path, str(outside)) is None
    assert resolve_corpus_file(tmp_path, "/etc/passwd") is None
    assert resolve_corpus_file(tmp_path, "") is None
    assert resolve_corpus_file(tmp_path, "   ") is None


def test_symlink_pointing_outside_root_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-link-target.txt"
    outside.write_text("secret")
    link = tmp_path / "inside.txt"
    os.symlink(outside, link)
    assert resolve_corpus_file(tmp_path, "inside.txt") is None


def test_absolute_path_inside_root_is_accepted(tmp_path: Path) -> None:
    target = tmp_path / "b.txt"
    target.write_text("x")
    assert resolve_corpus_file(tmp_path, str(target)) == target.resolve()


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    target = tmp_path / "blob.bin"
    payload = os.urandom(3 * 1024 * 1024 + 17)
    target.write_bytes(payload)
    assert sha256_file(target) == hashlib.sha256(payload).hexdigest()


def test_file_etag_changes_with_content_and_suffixes(tmp_path: Path) -> None:
    target = tmp_path / "e.txt"
    target.write_text("one")
    first = file_etag(target, "p1")
    assert first.startswith('W/"') and first.endswith('-p1"')
    assert file_etag(target, "p2") != first
    target.write_text("one two")
    assert file_etag(target, "p1") != first
