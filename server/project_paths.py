"""The one place the repository root is computed.

Several subsystems resolve possibly-relative paths (config values, lineage
registry rows, indexed document roots) against the repository root rather than
the process CWD. That resolution is load-bearing — a corpus registered with a
relative ``root_path`` only resolves correctly if every reader agrees on the
same root — so it lives in exactly one function here. ``server.reranker.artifacts``
and ``server.lineage.registry`` re-export ``resolve_project_path`` from this
module so their existing import sites keep working; nothing else should compute
the repo root inline. `tests/unit/test_project_paths_single_source.py` guards
that invariant.

Pure stdlib, so it stays import-safe for optional ML backends.
"""

from __future__ import annotations

from pathlib import Path

# server/project_paths.py -> parents[0] == server/, parents[1] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_root() -> Path:
    """The repository root (the parent of the ``server/`` package)."""
    return _REPO_ROOT


def resolve_project_path(path_str: str) -> Path:
    """Resolve a possibly-relative path against the repo root.

    Relative paths resolve against the repo root, never the process CWD; absolute
    paths pass through unchanged. ``~`` is expanded first.
    """
    p = Path(str(path_str or "")).expanduser()
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return p
