"""Crash-safe JSON document writes for run records.

`Path.write_text` truncates the existing file before writing: an ENOSPC or I/O error in
between leaves a torn run.json that nothing can reload. Writing a sibling temp file,
fsyncing it, `os.replace`-ing it over the target and fsyncing the directory keeps either
the previous or the new complete document on disk.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, payload: Any, *, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=indent, sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
