"""Safe access to files that live under a corpus root."""

from __future__ import annotations

import hashlib
from pathlib import Path


def resolve_corpus_file(corpus_root: Path, path_str: str) -> Path | None:
    """Resolve ``path_str`` inside ``corpus_root``; None when empty or escaping the root.

    Both sides are resolved before the containment check, so a symlink that points outside the
    root fails ``relative_to`` exactly like a ``..`` segment does.
    """
    text = str(path_str or "").strip()
    if not text:
        return None
    p = Path(text)
    try:
        root = corpus_root.resolve()
    except Exception:
        root = corpus_root.absolute()
    try:
        resolved = p.resolve() if p.is_absolute() else (corpus_root / p).resolve()
    except Exception:
        return None
    try:
        resolved.relative_to(root)
    except Exception:
        return None
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_etag(path: Path, *suffixes: str) -> str:
    """Weak ETag from the file's size + mtime, plus any render parameters that shape the body."""
    stat = path.stat()
    parts = [str(stat.st_size), str(stat.st_mtime_ns), *suffixes]
    return 'W/"' + "-".join(parts) + '"'
