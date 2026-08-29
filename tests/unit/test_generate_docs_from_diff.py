from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "docs_ai" / "generate_docs_from_diff.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_docs_from_diff_test", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=check,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "mkdocs" / "docs").mkdir(parents=True)
    (repo / "mkdocs.yml").write_text("site_name: Test\n", encoding="utf-8")
    (repo / "mkdocs" / "docs" / "index.md").write_text("# Old Title\n", encoding="utf-8")
    (repo / "mkdocs" / "docs" / "api.md").write_text("# API Reference\n", encoding="utf-8")
    _git(tmp_path, "init", "repo")
    _git(repo, "config", "user.name", "Docs Test")
    _git(repo, "config", "user.email", "docs-test@example.com")
    _git(repo, "branch", "-M", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial fixture")
    return repo


def test_apply_patch_accepts_unified_diff(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_repo(tmp_path)
    patch_path = tmp_path / "patch.diff"
    patch_path.write_text(
        "\n".join(
            [
                "diff --git a/mkdocs/docs/index.md b/mkdocs/docs/index.md",
                "--- a/mkdocs/docs/index.md",
                "+++ b/mkdocs/docs/index.md",
                "@@ -1 +1 @@",
                "-# Old Title",
                "+# Updated Title",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module.ROOT = repo
    ok, err = module.apply_patch(patch_path)

    assert ok is True
    assert err == ""
    assert (repo / "mkdocs" / "docs" / "index.md").read_text(encoding="utf-8") == "# Updated Title\n"
    assert "mkdocs/docs/index.md" in _git(repo, "diff", "--cached", "--name-only").stdout


def test_apply_patch_accepts_cursor_patch(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_repo(tmp_path)
    patch_path = tmp_path / "patch.cursor"
    patch_path.write_text(
        "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: mkdocs/docs/index.md",
                "@@",
                "-# Old Title",
                "+# Updated Title",
                "*** End Patch",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module.ROOT = repo
    ok, err = module.apply_patch(patch_path)

    assert ok is True
    assert err == ""
    assert (repo / "mkdocs" / "docs" / "index.md").read_text(encoding="utf-8") == "# Updated Title\n"
    assert "mkdocs/docs/index.md" in _git(repo, "diff", "--cached", "--name-only").stdout


def test_failed_cursor_patch_leaves_worktree_clean(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_repo(tmp_path)
    patch_path = tmp_path / "patch.cursor"
    patch_path.write_text(
        "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: mkdocs/docs/index.md",
                "@@",
                "-# Old Title",
                "+# Updated Title",
                "*** Update File: mkdocs/docs/api.md",
                "@@",
                "-missing line",
                "+replacement",
                "*** End Patch",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module.ROOT = repo
    ok, err = module.apply_patch(patch_path)

    assert ok is False
    assert "Failed to apply Cursor-style hunk" in err
    assert (repo / "mkdocs" / "docs" / "index.md").read_text(encoding="utf-8") == "# Old Title\n"
    assert _git(repo, "status", "--short").stdout.strip() == ""


def test_failed_unified_diff_leaves_worktree_clean(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_repo(tmp_path)
    patch_path = tmp_path / "patch.diff"
    patch_path.write_text(
        "\n".join(
            [
                "diff --git a/mkdocs/docs/index.md b/mkdocs/docs/index.md",
                "--- a/mkdocs/docs/index.md",
                "+++ b/mkdocs/docs/index.md",
                "@@ -1 +1 @@",
                "-# Missing Title",
                "+# Updated Title",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module.ROOT = repo
    ok, err = module.apply_patch(patch_path)

    assert ok is False
    assert "patch does not apply" in err.lower()
    assert (repo / "mkdocs" / "docs" / "index.md").read_text(encoding="utf-8") == "# Old Title\n"
    assert _git(repo, "status", "--short").stdout.strip() == ""


def test_change_context_keeps_pydantic_sources_and_drops_artifact_dirs() -> None:
    """`models/` is the tracked model-artifact tree, not `server/models/`.

    The substring exclusion used to drop the config composition root — the
    primary documented autopilot input — from every LLM context.
    """
    module = _load_module()
    included = [
        "server/models/tribrid_config_model.py",
        "server/models/synthetic.py",
        "server/api/models.py",
        "data/models.json",
        "web/src/api/models.ts",
        "server/runtime_capabilities.py",
    ]
    excluded = [
        "models/learning-agent-active/adapter_config.json",
        "models/reranker/manifest.json",
        "web/node_modules/foo/index.js",
        "data/eval_runs/run.json",
        "mkdocs/docs/index.md",
        "docs/references/retrieval-lane.md",
        "README.md",
    ]
    assert [p for p in included if not module.should_include_file(p)] == []
    assert [p for p in excluded if module.should_include_file(p)] == []


def test_apply_patch_recovers_from_wrong_hunk_line_counts(tmp_path: Path) -> None:
    """Models miscount `@@` headers; the bodies are still correct.

    This is the exact shape that stalled the pipeline from 2026-03 to 2026-08:
    GPT-5.6's patch declared `@@ -91,15 +91,26 @@` over a 36-line body and
    `git apply` rejected the whole run with "corrupt patch at line 42". The
    content was fine, so the counts are recomputed instead of refused.
    """
    module = _load_module()
    repo = _init_repo(tmp_path)
    (repo / "mkdocs" / "docs" / "guide.md").write_text("# Guide\n\nalpha\nbravo\ncharlie\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add guide")
    patch_path = tmp_path / "miscounted.diff"
    patch_path.write_text(
        "\n".join(
            [
                "diff --git a/mkdocs/docs/guide.md b/mkdocs/docs/guide.md",
                "--- a/mkdocs/docs/guide.md",
                "+++ b/mkdocs/docs/guide.md",
                # Declares 2 old / 2 new lines; the body actually carries 5 and 7.
                "@@ -1,2 +1,2 @@",
                " # Guide",
                " ",
                " alpha",
                "+inserted one",
                "+inserted two",
                " bravo",
                " charlie",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module.ROOT = repo
    ok, err = module.apply_patch(patch_path)

    assert ok is True, err
    assert (repo / "mkdocs" / "docs" / "guide.md").read_text(encoding="utf-8") == (
        "# Guide\n\nalpha\ninserted one\ninserted two\nbravo\ncharlie\n"
    )
    # New and modified paths must reach the index: run_ci_autopilot commits from staged state.
    assert "mkdocs/docs/guide.md" in _git(repo, "diff", "--cached", "--name-only").stdout


def test_apply_patch_still_refuses_a_patch_whose_context_does_not_match(tmp_path: Path) -> None:
    """Recounting fixes arithmetic, never invented content."""
    module = _load_module()
    repo = _init_repo(tmp_path)
    patch_path = tmp_path / "bad-context.diff"
    patch_path.write_text(
        "\n".join(
            [
                "diff --git a/mkdocs/docs/index.md b/mkdocs/docs/index.md",
                "--- a/mkdocs/docs/index.md",
                "+++ b/mkdocs/docs/index.md",
                "@@ -1,1 +1,1 @@",
                "-# A Title That Is Not In The File",
                "+# Updated Title",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module.ROOT = repo
    ok, err = module.apply_patch(patch_path)

    assert ok is False
    assert err
    assert (repo / "mkdocs" / "docs" / "index.md").read_text(encoding="utf-8") == "# Old Title\n"
    assert _git(repo, "status", "--short").stdout.strip() == ""


# Captured verbatim from https://openrouter.ai/api/v1/responses for
# z-ai/glm-5.3-flash on 2026-08-28 (trimmed to the fields the reader uses).
_COMPLETED_RESPONSE = {
    "status": "completed",
    "incomplete_details": None,
    "output": [
        {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "thinking"}]},
        {"type": "message", "content": [{"type": "output_text", "text": "diff --git a/x b/x\n"}]},
    ],
}
_TRUNCATED_RESPONSE = {
    "status": "incomplete",
    "incomplete_details": {"reason": "max_output_tokens"},
    "output": [{"type": "reasoning", "content": [{"type": "reasoning_text", "text": "thinking"}]}],
}


def test_response_output_text_reads_a_completed_response() -> None:
    module = _load_module()
    assert module.response_output_text(_COMPLETED_RESPONSE) == "diff --git a/x b/x"


def test_response_output_text_refuses_a_truncated_response() -> None:
    """A half-written patch must fail loudly.

    Recounting would happily renumber a hunk that was cut off mid-body and
    apply a partial page, so truncation has to be caught at the transport.
    """
    module = _load_module()
    with pytest.raises(RuntimeError, match="max_output_tokens"):
        module.response_output_text(_TRUNCATED_RESPONSE)
    # Truncation that still emitted some text is equally unusable.
    partial = {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "diff --git a/x b/x\n@@ -1"}]}],
    }
    with pytest.raises(RuntimeError, match="max_output_tokens"):
        module.response_output_text(partial)


def test_extract_unified_diff_unwraps_a_fenced_patch() -> None:
    """Models wrap patches in code fences; the fence must never reach git.

    Both regexes here used `\\s`/`\\n` inside raw strings, so they matched a
    literal backslash and never fired: every response was passed through
    verbatim. A model that answers with prose or a fence therefore produced a
    guaranteed "corrupt patch".
    """
    module = _load_module()
    body = (
        "diff --git a/mkdocs/docs/index.md b/mkdocs/docs/index.md\n"
        "--- a/mkdocs/docs/index.md\n"
        "+++ b/mkdocs/docs/index.md\n"
        "@@ -1 +1 @@\n"
        "-# Old Title\n"
        "+# Updated Title\n"
    )
    for wrapper in (
        f"Here is the patch:\n```diff\n{body}```\nLet me know!",
        f"```patch\n{body}```",
        f"```\n{body}```",
        f"Sure! Here you go.\n\n{body}",
        body,
    ):
        out = module._extract_unified_diff(wrapper)
        assert out.startswith("diff --git a/mkdocs/docs/index.md"), out[:60]
        assert "```" not in out
        assert "Here is the patch" not in out and "Sure!" not in out and "Let me know" not in out
        assert out.rstrip().endswith("+# Updated Title")


def test_extract_unified_diff_keeps_cursor_style_patches_intact() -> None:
    module = _load_module()
    body = "*** Begin Patch\n*** Update File: mkdocs/docs/index.md\n@@\n-# Old Title\n+# New Title\n*** End Patch\n"
    for wrapper in (f"```\n{body}```", body, f"Here you go:\n\n{body}"):
        out = module._extract_unified_diff(wrapper)
        assert out.startswith("*** Begin Patch")
        assert out.rstrip().endswith("*** End Patch")
        assert "```" not in out


def test_extract_unified_diff_round_trips_through_apply(tmp_path: Path) -> None:
    """The end-to-end shape: fenced model output applies to a real repo."""
    module = _load_module()
    repo = _init_repo(tmp_path)
    fenced = (
        "Happy to help. Here are the docs updates:\n\n```diff\n"
        "diff --git a/mkdocs/docs/index.md b/mkdocs/docs/index.md\n"
        "--- a/mkdocs/docs/index.md\n"
        "+++ b/mkdocs/docs/index.md\n"
        "@@ -1,9 +1,9 @@\n"
        "-# Old Title\n"
        "+# Updated Title\n"
        "```\n"
    )
    patch_path = tmp_path / "from-model.diff"
    patch_path.write_text(module._extract_unified_diff(fenced), encoding="utf-8")

    module.ROOT = repo
    ok, err = module.apply_patch(patch_path)

    assert ok is True, err
    assert (repo / "mkdocs" / "docs" / "index.md").read_text(encoding="utf-8") == "# Updated Title\n"


def test_extract_unified_diff_keeps_code_fences_inside_the_patch(tmp_path: Path) -> None:
    """A fence inside the docs content must not end the patch early.

    Every ragweld page carries mermaid diagrams, so a real patch always
    contains `+```mermaid` lines. The fence regex ended the model's wrapper
    at the first inner fence and silently dropped everything after it: the
    hunk header promised the full page, `git apply --recount` renumbered the
    stump, and a half-written page landed while the pages the nav still
    pointed at were never created (2026-08-29 run: 105 promised, 35 landed).
    """
    module = _load_module()
    body = (
        "diff --git a/mkdocs/docs/guide.md b/mkdocs/docs/guide.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/mkdocs/docs/guide.md\n"
        "@@ -0,0 +1,12 @@\n"
        "+# Guide\n"
        "+\n"
        "+```mermaid\n"
        "+flowchart LR\n"
        "+  A --> B\n"
        "+```\n"
        "+\n"
        "+```python\n"
        "+print(\"still inside the patch\")\n"
        "+```\n"
        "+\n"
        "+Last line after both fences.\n"
        "diff --git a/mkdocs/docs/index.md b/mkdocs/docs/index.md\n"
        "--- a/mkdocs/docs/index.md\n"
        "+++ b/mkdocs/docs/index.md\n"
        "@@ -1 +1 @@\n"
        "-# Old Title\n"
        "+# Updated Title\n"
    )
    for wrapper in (
        f"Here is the patch:\n```diff\n{body}```\nLet me know!",
        f"```patch\n{body}```",
        f"```\n{body}```",
        f"Sure! Here you go.\n\n{body}",
        body,
    ):
        out = module._extract_unified_diff(wrapper)
        assert out == body, f"patch was altered for wrapper {wrapper[:20]!r}:\n{out}"

    repo = _init_repo(tmp_path)
    patch_path = tmp_path / "fenced-with-inner-fences.diff"
    patch_path.write_text(module._extract_unified_diff(f"```diff\n{body}```\n"), encoding="utf-8")
    module.ROOT = repo
    ok, err = module.apply_patch(patch_path)
    assert ok is True, err
    guide = (repo / "mkdocs" / "docs" / "guide.md").read_text(encoding="utf-8")
    assert guide.rstrip().endswith("Last line after both fences.")
    assert guide.count("```") == 4
    assert (repo / "mkdocs" / "docs" / "index.md").read_text(encoding="utf-8") == "# Updated Title\n"


def _diff_block(path: str, removed: int, added: int) -> str:
    lines = [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}", "@@ -1,1 +1,1 @@"]
    lines += [f"-old line {i}" for i in range(removed)]
    lines += [f"+new line {i}" for i in range(added)]
    return "\n".join(lines) + "\n"


def test_patch_paths_outside_mkdocs_are_refused() -> None:
    """The autopilot may only ever write the docs site.

    These guards are the reason an LLM-authored patch can be trusted at all, so
    they get their own coverage rather than riding along with the apply tests.
    """
    module = _load_module()
    assert module._validate_patch_paths(_diff_block("mkdocs/docs/index.md", 1, 1)) == []
    assert module._validate_patch_paths(_diff_block("mkdocs.yml", 1, 1)) == []
    for forbidden in (
        "server/api/chat.py",
        "scripts/docs_ai/generate_docs_from_diff.py",
        ".github/workflows/deploy-docs.yml",
        "docs/index.md",
        "web/src/App.tsx",
    ):
        errors = module._validate_patch_paths(_diff_block(forbidden, 1, 1))
        assert errors, f"{forbidden} should be refused"
        assert any(forbidden in e for e in errors)


def test_wholesale_page_rewrites_are_refused_outside_bootstrap() -> None:
    module = _load_module()
    # A large delete with a token replacement is the accidental-rewrite shape.
    destructive = _diff_block("mkdocs/docs/index.md", module.GENERAL_DELETE_LIMIT + 40, 5)
    assert module._validate_patch_safety(destructive, allow_large_deletes=False)
    # Bootstrap runs legitimately rewrite pages wholesale.
    assert module._validate_patch_safety(destructive, allow_large_deletes=True) == []
    # A normal incremental edit passes either way.
    ordinary = _diff_block("mkdocs/docs/index.md", 3, 9)
    assert module._validate_patch_safety(ordinary, allow_large_deletes=False) == []


def test_patch_line_stats_count_bodies_not_hunk_headers() -> None:
    """Recount changes the headers; the safety guard must not depend on them."""
    module = _load_module()
    patch = "\n".join(
        [
            "diff --git a/mkdocs/docs/index.md b/mkdocs/docs/index.md",
            "--- a/mkdocs/docs/index.md",
            "+++ b/mkdocs/docs/index.md",
            # Header claims 1/1; the body actually removes 2 and adds 3.
            "@@ -1,1 +1,1 @@",
            "-alpha",
            "-bravo",
            "+charlie",
            "+delta",
            "+echo",
            "",
        ]
    )
    stats = module._patch_line_stats(patch)
    assert stats["mkdocs/docs/index.md"] == {"added": 3, "removed": 2}
