"""Private source bytes shared by document extraction and checkpoint identity."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    path: Path
    sha256: str
    byte_size: int

    @classmethod
    def capture(cls, source: Path, *, max_bytes: int) -> SourceSnapshot:
        if max_bytes < 0:
            raise ValueError("Source snapshot file size limit must be nonnegative")
        # Hash the exact bytes written to this private file while streaming.
        # Probe at most one extra byte to reject a growing/non-regular source
        # without writing excess data or waiting for that source's EOF.
        directory = Path(tempfile.mkdtemp(prefix="ragweld-source-"))
        frozen = directory / source.name
        digest = hashlib.sha256()
        size = 0
        created = False
        try:
            descriptor = os.open(frozen, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
                while block := input_file.read(min(1024 * 1024, max_bytes - size + 1)):
                    if size + len(block) > max_bytes:
                        raise ValueError(f"Selected semantic source exceeds the file size limit: {source.name}")
                    output.write(block)
                    digest.update(block)
                    size += len(block)
            return cls(frozen, digest.hexdigest(), size)
        except BaseException:
            # A name rejected by open (e.g. ENAMETOOLONG) is not unlinkable
            # either. Only unlink a path that was actually created.
            if created:
                frozen.unlink(missing_ok=True)
            directory.rmdir()
            raise

    def __enter__(self) -> SourceSnapshot:
        return self

    def __exit__(self, _kind: type[BaseException] | None, _error: BaseException | None,
                 _traceback: TracebackType | None) -> None:
        self.path.unlink(missing_ok=True)
        self.path.parent.rmdir()
