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
    def __init__(
        self,
        ignore_patterns: list[str] | None = None,
        extra_gitignore_patterns: list[str] | None = None,
    ):
        self.ignore_patterns = ignore_patterns or []
        # Additional gitignore-style patterns applied at repo root (e.g., Corpus.exclude_paths).
        self.extra_gitignore_patterns = extra_gitignore_patterns or []

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

    @staticmethod
    def _base_gitignore_patterns() -> list[str]:
        # Always ignore Git internals + common heavyweight dirs, even when no .gitignore exists.
        return [
            ".git/",
            ".venv/",
            ".venv*/",
            "node_modules/",
            "__pycache__/",
            "*.pyc",
            ".DS_Store",
            # Safety: never ingest secrets-by-default.
            ".env",
        ]

    def _gitignore_patterns_for_dir(self, root: Path, dirpath: Path) -> list[str]:
        """Return normalized, root-relative patterns from dirpath/.gitignore (if present)."""
        gi = dirpath / ".gitignore"
        if not gi.exists():
            return []
        try:
            rel_dir = str(dirpath.relative_to(root)).replace("\\", "/")
        except Exception:
            return []
        rel_dir = "" if rel_dir == "." else rel_dir

        out: list[str] = []
        for raw in self._read_gitignore_lines(gi):
            norm = self._normalize_gitignore_pattern(raw, rel_dir=rel_dir)
            if norm:
                out.append(norm)
        return out

    def _normalize_extra_gitignore_patterns(self) -> list[str]:
        """Normalize user-provided gitignore patterns (root-scoped)."""
        out: list[str] = []
        seen: set[str] = set()

        for raw in self.extra_gitignore_patterns or []:
            s = str(raw or "").strip()
            if not s:
                continue
            s = s.replace("\\", "/")
            if s.startswith("./"):
                s = s[2:]
            norm = self._normalize_gitignore_pattern(s, rel_dir="")
            if norm and norm not in seen:
                out.append(norm)
                seen.add(norm)

            # If the user provided a non-glob path without a trailing slash,
            # also add a directory form to ensure directory pruning works.
            if s.startswith("!"):
                continue
            if any(ch in s for ch in ("*", "?", "[")):
                continue
            if s.endswith("/"):
                continue
            norm_dir = self._normalize_gitignore_pattern(s + "/", rel_dir="")
            if norm_dir and norm_dir not in seen:
                out.append(norm_dir)
                seen.add(norm_dir)

        return out

    def iter_repo_files(self, repo_path: str) -> Iterator[tuple[str, Path]]:
        """Yield (relative_path, absolute_path) for included files."""
        root = Path(repo_path).expanduser().resolve()
        if not root.exists():
            return

        base_patterns = self._base_gitignore_patterns()
        extra_patterns = self._normalize_extra_gitignore_patterns()
        patterns_by_dir: dict[str, list[str]] = {
            "": base_patterns + self._gitignore_patterns_for_dir(root, root) + extra_patterns
        }
        spec_by_dir: dict[str, PathSpec] = {"": PathSpec.from_lines("gitignore", patterns_by_dir[""])}

        for dirpath, dirnames, filenames in os.walk(root):
            p = Path(dirpath)
            try:
                rel_dir = str(p.relative_to(root)).replace("\\", "/")
            except Exception:
                continue
            rel_dir = "" if rel_dir == "." else rel_dir

            if rel_dir not in spec_by_dir:
                parent = str(Path(rel_dir).parent).replace("\\", "/")
                parent = "" if parent == "." else parent
                inherited = patterns_by_dir.get(parent, base_patterns)
                merged = list(inherited)
                merged.extend(self._gitignore_patterns_for_dir(root, p))
                patterns_by_dir[rel_dir] = merged
                spec_by_dir[rel_dir] = PathSpec.from_lines("gitignore", merged)

            spec = spec_by_dir[rel_dir]

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
