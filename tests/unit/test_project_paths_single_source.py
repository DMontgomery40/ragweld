"""One `resolve_project_path`, imported everywhere, computed in one module.

Relative-path resolution (config values, lineage rows, a corpus's relative
`root_path`) is load-bearing: the recall corpus resolves its documents only if
every reader resolves the same relative row against the same repo root. Three
modules used to compute that root inline and agreed only by coincidence. They now
all delegate to `server.project_paths`; this pins that so a fourth inline copy —
or a drift in one of the three — fails here rather than in front of an operator.
"""

from __future__ import annotations

import re
from pathlib import Path

from server.lineage import resolve_project_path as from_lineage_pkg
from server.lineage.registry import resolve_project_path as from_registry
from server.project_paths import repo_root, resolve_project_path
from server.reranker.artifacts import resolve_project_path as from_artifacts

REPO_ROOT = Path(__file__).resolve().parents[2]

# The three sites the invariant collapsed. None may recompute the repo root inline
# again; the canonical module (server/project_paths.py) is the only place that does.
FORMER_INLINE_SITES = (
    "server/reranker/artifacts.py",
    "server/lineage/registry.py",
    "server/api/documents.py",
)

# A repo-root-magnitude computation: `parents[N]` or `.parent.parent.parent`.
_INLINE_REPO_ROOT = re.compile(
    r"Path\(__file__\)\.resolve\(\)\.(?:parents\[\d+\]|parent\.parent\.parent)"
)


def test_every_former_site_imports_the_one_function() -> None:
    assert from_artifacts is resolve_project_path
    assert from_registry is resolve_project_path
    assert from_lineage_pkg is resolve_project_path


def test_resolution_matches_the_former_behavior() -> None:
    # Relative resolves against the repo root; absolute passes through; ~ expands.
    assert resolve_project_path("data/reranker") == repo_root() / "data" / "reranker"
    assert resolve_project_path("/tmp/abs") == Path("/tmp/abs")
    assert resolve_project_path("") == repo_root()


def test_former_sites_do_not_recompute_the_repo_root() -> None:
    offenders: list[str] = []
    for rel in FORMER_INLINE_SITES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if _INLINE_REPO_ROOT.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert offenders == [], (
        "these files recompute the repository root inline; import repo_root / "
        "resolve_project_path from server.project_paths instead:\n" + "\n".join(offenders)
    )
