"""Optional service variables are never read bare in the test suite.

`POSTGRES_DSN`, `NEO4J_URI`, and the rest of the integration-service variables
are absent on any box that has not configured that backend. Reading one as
`os.environ["POSTGRES_DSN"]` raises `KeyError` mid-run, which pytest reports as
an *error* rather than a skip — ~20 integration files failed this way on a box
without the DSN composed. Every such read must go through
`tests.service_requirements.require_env`, which skips with the exact missing
variable. This is a source invariant so the next such read fails here rather
than in a full-suite run.

Assignments (`os.environ["NEO4J_URI"] = ...`) are writes — a fixture setting or
restoring an override — and stay allowed; only bare reads are forbidden.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.service_requirements import OPTIONAL_SERVICE_ENV_VARS

TESTS_ROOT = Path(__file__).resolve().parents[1]

# `os.environ[ "VAR" ]` capturing the key literal; whitespace-tolerant.
_SUBSCRIPT = re.compile(r"os\.environ\[\s*(['\"])(?P<var>[A-Z0-9_]+)\1\s*\](?P<after>\s*=?)")

# Files allowed to name these variables outside the helper: the helper itself and
# this invariant.
_ALLOWED = {
    "service_requirements.py",
    "test_optional_service_env_access.py",
}


def _is_write(after: str) -> bool:
    """A single trailing `=` (not `==`) means assignment, i.e. a write."""
    tail = after.strip()
    return tail == "="


def test_optional_service_env_vars_are_never_read_bare() -> None:
    offenders: list[str] = []
    for path in TESTS_ROOT.rglob("*.py"):
        if path.name in _ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            for m in _SUBSCRIPT.finditer(line):
                if m.group("var") not in OPTIONAL_SERVICE_ENV_VARS:
                    continue
                if _is_write(m.group("after")):
                    continue
                offenders.append(f"{path.relative_to(TESTS_ROOT)}:{i}: os.environ[{m.group('var')!r}]")

    assert offenders == [], (
        "these tests read an optional service variable bare, so they raise KeyError instead of "
        "skipping when the service is not configured; read it through "
        "tests.service_requirements.require_env(...) which skips with the exact missing name:\n"
        + "\n".join(offenders)
    )
