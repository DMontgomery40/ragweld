from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from server.lineage.registry import (
    capture_asset_version,
    capture_published_artifact_version,
    collect_git_snapshot,
    create_or_update_bundle,
    load_bundle,
    make_ref,
    set_alias,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_capture_asset_version_dedupes_identical_payload(tmp_path: Path) -> None:
    first = capture_asset_version(
        kind="config_snapshot",
        payload={"alpha": 1, "nested": {"beta": True}},
        repo_id="corpus-a",
        source="runtime",
        root=tmp_path,
    )
    second = capture_asset_version(
        kind="config_snapshot",
        payload={"nested": {"beta": True}, "alpha": 1},
        repo_id="corpus-a",
        source="runtime",
        root=tmp_path,
    )

    assert first.version_id == second.version_id
    assert first.digest == second.digest


def test_collect_git_snapshot_captures_dirty_file_digest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "pytest@example.com")
    _git(repo, "config", "user.name", "Pytest")

    tracked = repo / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")

    tracked.write_text("after\n", encoding="utf-8")

    snapshot = collect_git_snapshot(root=repo)

    assert snapshot.commit_sha
    assert snapshot.dirty is True
    assert "tracked.txt" in snapshot.dirty_paths
    tracked_file = next((item for item in snapshot.tracked_files if item.path == "tracked.txt"), None)
    assert tracked_file is not None
    assert tracked_file.exists is True
    assert tracked_file.sha256


def test_bundle_alias_requires_existing_bundle(tmp_path: Path) -> None:
    prompt = capture_asset_version(
        kind="prompt_set",
        payload={"system_prompts": {"query_rewrite": "x"}},
        repo_id="corpus-a",
        source="runtime",
        root=tmp_path,
    )
    bundle, aliases = create_or_update_bundle(
        repo_id="corpus-a",
        prompt_set=make_ref("prompt_set", prompt.version_id),
        set_aliases_to=("current",),
        root=tmp_path,
    )

    assert aliases
    loaded = load_bundle("corpus-a", bundle.bundle_id, root=tmp_path)
    assert loaded.prompt_set is not None
    assert loaded.prompt_set.version_id == prompt.version_id

    promoted = set_alias(repo_id="corpus-a", alias="promoted", bundle_id=bundle.bundle_id, root=tmp_path)
    assert promoted.bundle_id == bundle.bundle_id

    with pytest.raises(FileNotFoundError):
        set_alias(repo_id="corpus-a", alias="baseline", bundle_id="bundle__missing", root=tmp_path)


def test_create_or_update_bundle_only_preserves_attached_refs_when_requested(tmp_path: Path) -> None:
    prompt_v1 = capture_asset_version(
        kind="prompt_set",
        payload={"system_prompts": {"query_rewrite": "v1"}},
        repo_id="corpus-a",
        source="runtime",
        root=tmp_path,
    )
    first_bundle, _aliases = create_or_update_bundle(
        repo_id="corpus-a",
        prompt_set=make_ref("prompt_set", prompt_v1.version_id),
        benchmark_runs=[make_ref("benchmark_run", "benchmark_run__one")],
        set_aliases_to=("current",),
        root=tmp_path,
    )
    assert [ref.version_id for ref in first_bundle.benchmark_runs] == ["benchmark_run__one"]

    same_state_bundle, _aliases = create_or_update_bundle(
        repo_id="corpus-a",
        prompt_set=make_ref("prompt_set", prompt_v1.version_id),
        benchmark_runs=[make_ref("benchmark_run", "benchmark_run__two")],
        preserve_attached_refs=True,
        set_aliases_to=("current",),
        root=tmp_path,
    )
    assert [ref.version_id for ref in same_state_bundle.benchmark_runs] == [
        "benchmark_run__one",
        "benchmark_run__two",
    ]

    prompt_v2 = capture_asset_version(
        kind="prompt_set",
        payload={"system_prompts": {"query_rewrite": "v2"}},
        repo_id="corpus-a",
        source="runtime",
        root=tmp_path,
    )
    refreshed_bundle, _aliases = create_or_update_bundle(
        repo_id="corpus-a",
        prompt_set=make_ref("prompt_set", prompt_v2.version_id),
        set_aliases_to=("current",),
        root=tmp_path,
    )
    assert refreshed_bundle.prompt_set is not None
    assert refreshed_bundle.prompt_set.version_id == prompt_v2.version_id
    assert refreshed_bundle.benchmark_runs == []


def test_capture_published_artifact_version_changes_when_source_or_target_bytes_change(tmp_path: Path) -> None:
    source = tmp_path / "artifact.json"
    target = tmp_path / "target.json"
    source.write_text('{"value":"one"}\n', encoding="utf-8")
    target.write_text('{"published":"alpha"}\n', encoding="utf-8")

    first = capture_published_artifact_version(
        repo_id="corpus-a",
        artifact_kind="config_patch_json",
        source_path=str(source),
        target_path=str(target),
        root=tmp_path,
    )

    source.write_text('{"value":"two"}\n', encoding="utf-8")
    target.write_text('{"published":"beta"}\n', encoding="utf-8")

    second = capture_published_artifact_version(
        repo_id="corpus-a",
        artifact_kind="config_patch_json",
        source_path=str(source),
        target_path=str(target),
        root=tmp_path,
    )

    assert first.version_id != second.version_id
    assert first.payload["source_snapshot"]["sha256"] != second.payload["source_snapshot"]["sha256"]
    assert first.payload["target_snapshot"]["sha256"] != second.payload["target_snapshot"]["sha256"]
