from pathlib import Path

from server.indexing.loader import FileLoader


def _write(p: Path, text: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_file_loader_respects_gitignore_and_defaults(tmp_path: Path) -> None:
    # Baseline included files
    _write(tmp_path / "keep.txt", "hello")
    _write(tmp_path / ".github" / "workflows" / "ci.yml", "name: CI")

    # Always-ignore heavies
    _write(tmp_path / "node_modules" / "leftpad" / "index.js", "module.exports = 1")
    _write(tmp_path / ".venv" / "bin" / "python", "binary-ish")

    # Disabled git dir should NOT be indexed (but .github should still be included)
    _write(tmp_path / ".git.disabled-20260101" / "objects" / "x", "nope")

    # Nested gitignore semantics
    _write(
        tmp_path / "sub" / ".gitignore",
        "\n".join(
            [
                "*.log",
                "!keep.log",
                "ignored_dir/",
            ]
        ),
    )
    _write(tmp_path / "sub" / "keep.log", "this should be kept")
    _write(tmp_path / "sub" / "nested" / "test.log", "this should be ignored")
    _write(tmp_path / "sub" / "ignored_dir" / "a.txt", "ignored")

    loader = FileLoader(ignore_patterns=[])
    got = [rel for rel, _p in loader.iter_repo_files(str(tmp_path))]

    assert "keep.txt" in got
    assert ".github/workflows/ci.yml" in got

    assert not any(p.startswith("node_modules/") for p in got)
    assert not any(p.startswith(".venv/") for p in got)
    assert not any(p.startswith(".git.disabled-") for p in got)

    assert "sub/keep.log" in got
    assert "sub/nested/test.log" not in got
    assert not any(p.startswith("sub/ignored_dir/") for p in got)


def test_file_loader_applies_extra_gitignore_patterns(tmp_path: Path) -> None:
    _write(tmp_path / "keep.txt", "ok")
    _write(tmp_path / "public" / "admin-demo" / "assets" / "bundle.js", "x")
    _write(tmp_path / "public" / "admin-demo" / "assets" / "bundle.min.js", "x")
    _write(tmp_path / "public" / "other" / "keep.js", "y")
    _write(tmp_path / "public" / "other" / "keep.min.js", "y")

    loader = FileLoader(
        ignore_patterns=[],
        extra_gitignore_patterns=[
            "public/admin-demo/",  # directory exclusion
            "*.min.js",  # glob exclusion
        ],
    )
    got = [rel for rel, _p in loader.iter_repo_files(str(tmp_path))]

    assert "keep.txt" in got
    assert "public/other/keep.js" in got
    assert not any(p.startswith("public/admin-demo/") for p in got)
    assert "public/other/keep.min.js" not in got
