import os
import fnmatch
from collections.abc import Iterator
from pathlib import Path

from pathspec import PathSpec

_LANG_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".md": "markdown",
    ".toml": "toml",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
}


class FileLoader:
    def __init__(self, ignore_patterns: list[str] | None = None):
        self.ignore_patterns = ignore_patterns or []

    @staticmethod
    def _looks_like_git_dir(name: str) -> bool:
        n = (name or "").strip()
        if n == ".git":
            return True
        # Ignore disabled git dirs like ".git.disabled-2025..." but do NOT ignore ".github".
        return n.startswith(".git.") or n.startswith(".git-") or n.startswith(".git_")

    @staticmethod
    def _read_gitignore_lines(path: Path) -> list[str]:
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        lines: list[str] = []
        for line in raw.splitlines():
            # Git supports escaped leading '#' and trailing spaces; keep it simple but safe.
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            lines.append(stripped)
        return lines

    @classmethod
    def _normalize_gitignore_pattern(cls, pat: str, *, rel_dir: str) -> str:
        """Convert a .gitignore pattern into a root-relative gitwildmatch pattern."""
        neg = pat.startswith("!")
        body = pat[1:] if neg else pat
        body = body.strip()
        if not body:
            return ""

        # Directory patterns: keep trailing slash; anchor detection ignores trailing slash.
        anchored = body.startswith("/")
        body_no_anchor = body.lstrip("/")
        body_check = body_no_anchor[:-1] if body_no_anchor.endswith("/") else body_no_anchor
        has_slash = "/" in body_check

        if rel_dir:
            if anchored:
                out = f"{rel_dir}/{body_no_anchor}"
            elif has_slash:
                out = f"{rel_dir}/{body_no_anchor}"
            else:
                # Basename pattern: applies anywhere under this directory.
                out = f"{rel_dir}/**/{body_no_anchor}"
        else:
            # Root-level patterns.
            out = body_no_anchor

        return f"!{out}" if neg else out

    def _build_gitignore_spec(self, root: Path) -> PathSpec:
        """Build a PathSpec from all nested .gitignore files under root.

        Note: This supports nested .gitignore semantics by prefixing patterns
        with the directory they appear in.
        """
        patterns: list[str] = []

        # Always ignore Git internals + common heavyweight dirs, even when no .gitignore exists.
        patterns.extend(
            [
                ".git/",
                ".venv/",
                ".venv*/",
                "node_modules/",
                "__pycache__/",
                "*.pyc",
                ".DS_Store",
            ]
        )

        for gi in root.rglob(".gitignore"):
            try:
                rel_dir = str(gi.parent.relative_to(root)).replace("\\", "/")
            except Exception:
                continue
            rel_dir = "" if rel_dir == "." else rel_dir

            for raw in self._read_gitignore_lines(gi):
                norm = self._normalize_gitignore_pattern(raw, rel_dir=rel_dir)
                if norm:
                    patterns.append(norm)

        return PathSpec.from_lines("gitwildmatch", patterns)

    def iter_repo_files(self, repo_path: str) -> Iterator[tuple[str, Path]]:
        """Yield (relative_path, absolute_path) for included files."""
        root = Path(repo_path).expanduser().resolve()
        if not root.exists():
            return

        spec = self._build_gitignore_spec(root)

        for dirpath, dirnames, filenames in os.walk(root):
            p = Path(dirpath)
            try:
                rel_dir = str(p.relative_to(root)).replace("\\", "/")
            except Exception:
                continue
            rel_dir = "" if rel_dir == "." else rel_dir

            # Prune ignored directories early for performance.
            kept_dirs: list[str] = []
            for d in dirnames:
                if self._looks_like_git_dir(d):
                    continue
                rel = f"{rel_dir}/{d}" if rel_dir else d
                if spec.match_file(rel + "/"):
                    continue
                kept_dirs.append(d)
            dirnames[:] = kept_dirs

            for fn in filenames:
                if fn == ".DS_Store":
                    continue
                rel = f"{rel_dir}/{fn}" if rel_dir else fn
                # Gitignore
                if spec.match_file(rel):
                    continue
                # Extra ignore patterns (config-derived)
                if not self.should_include(rel):
                    continue
                yield rel, p / fn

    def load_repo(self, repo_path: str) -> Iterator[tuple[str, str]]:  # (path, content)
        for rel, path in self.iter_repo_files(repo_path):
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            yield rel, content

    def should_include(self, file_path: str) -> bool:
        fp = file_path.replace("\\", "/")
        for pat in self.ignore_patterns:
            if not pat:
                continue
            if fnmatch.fnmatch(fp, pat) or fnmatch.fnmatch(Path(fp).name, pat):
                return False
        return True

    def detect_language(self, file_path: str) -> str | None:
        ext = Path(file_path).suffix.lower()
        return _LANG_BY_EXT.get(ext)
