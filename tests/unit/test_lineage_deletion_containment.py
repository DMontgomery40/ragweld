"""Corpus deletion must never reach outside the corpus's own lineage directories.

Codex review (session 13): `_safe_repo_id` preserved `.`/`..`, so deleting a corpus named
`..` would have removed the lineage root itself. Both the create boundary and the
registry reject such ids, and the deletion helper refuses any target that is not a strict
child of `<root>/aliases` and `<root>/bundles`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.lineage.registry import _safe_repo_id, delete_repo_lineage, lineage_root
from server.models.tribrid_config_model import CorpusCreateRequest


@pytest.mark.parametrize("corpus_id", ["", " ", ".", ".."])
def test_safe_repo_id_rejects_dot_segments_and_empty(corpus_id: str) -> None:
    with pytest.raises(ValueError):
        _safe_repo_id(corpus_id)


@pytest.mark.parametrize("corpus_id", [".", "..", "a/b", "a\\b", "with space"])
def test_corpus_create_boundary_rejects_path_escaping_ids(corpus_id: str) -> None:
    with pytest.raises(ValidationError):
        CorpusCreateRequest(corpus_id=corpus_id, name="x", path="tests/fixtures/acceptance_corpus")


def test_corpus_create_boundary_keeps_ordinary_ids() -> None:
    request = CorpusCreateRequest(corpus_id="aurora_acceptance-2.0", name="x", path="tests/fixtures/acceptance_corpus")
    assert request.repo_id == "aurora_acceptance-2.0"
    assert CorpusCreateRequest(name="x", path="tests/fixtures/acceptance_corpus").repo_id is None


def test_delete_repo_lineage_only_touches_the_corpus_directories(tmp_path: Path) -> None:
    root = tmp_path / "lineage"
    victim_alias = root / "aliases" / "other-corpus" / "current.json"
    victim_alias.parent.mkdir(parents=True)
    victim_alias.write_text(json.dumps({"alias": "current"}), encoding="utf-8")
    mine = root / "aliases" / "mine" / "canary.json"
    mine.parent.mkdir(parents=True)
    mine.write_text(json.dumps({"alias": "canary"}), encoding="utf-8")
    (root / "bundles" / "mine").mkdir(parents=True)
    (root / "bundles" / "mine" / "bundle__1.json").write_text("{}", encoding="utf-8")
    asset = root / "assets" / "config_snapshot" / "v1.json"
    asset.parent.mkdir(parents=True)
    asset.write_text("{}", encoding="utf-8")

    removed = delete_repo_lineage("mine", root=root)

    assert removed == {"aliases": 1, "bundles": 1}
    assert not (root / "aliases" / "mine").exists()
    assert not (root / "bundles" / "mine").exists()
    assert victim_alias.exists()
    assert asset.exists()
    assert (root / "locks" / "mine.lock").exists()  # kept: unlinking a held lock breaks exclusion
    assert lineage_root(root) == root


@pytest.mark.parametrize("corpus_id", [".", "..", ""])
def test_delete_repo_lineage_refuses_root_escaping_ids(tmp_path: Path, corpus_id: str) -> None:
    root = tmp_path / "lineage"
    sentinel = root / "aliases" / "keep" / "current.json"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        delete_repo_lineage(corpus_id, root=root)
    assert sentinel.exists()
    assert root.exists()
