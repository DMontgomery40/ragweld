"""Guard the one shared config-save error presentation (GUI-drive M-20).

A config save failure must show the operator WHAT the server refused -- the field and its
bound, or the reason a 409 blocked the write -- never axios's opaque runtime string
``Error: Request failed with status code 422``. That string is synthesised by axios from
``response.status``; the real information lives in ``response.data.detail``.

The fix routes every save/patch/load failure in ``useConfigStore`` through
``formatSaveError`` (``web/src/utils/saveErrorMessage.ts``), which reads the server ``detail``
and is the single formatter used by the footer and the toast. A pure grep for the runtime
string is fake-green (it never appears in source; axios makes it at runtime), so this checks
the FIX is structurally in place: the store no longer forwards ``error.message`` into the
UI-visible ``error`` field, it calls the formatter, and the formatter guards the axios literal.

Zero mocks: parses the real TypeScript sources, the same way
``tests/unit/test_web_tokens_contrast.py`` parses the real token CSS.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORE_TS = ROOT / "web" / "src" / "stores" / "useConfigStore.ts"
FORMATTER_TS = ROOT / "web" / "src" / "utils" / "saveErrorMessage.ts"
APP_TS = ROOT / "web" / "src" / "App.tsx"


def _read(path: Path) -> str:
    assert path.exists(), f"expected source file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_formatter_module_exists_and_guards_the_axios_string() -> None:
    src = _read(FORMATTER_TS)
    # The formatter names and matches the axios runtime message so it can strip it.
    assert "request failed with status code" in src.lower(), (
        "saveErrorMessage.ts must recognise the axios status string to keep it out of the UI"
    )
    assert "formatSaveError" in src and "export function formatSaveError" in src
    # It shapes the structured 409 index-contract detail (reload-and-reindex affordance).
    assert "index_contract_change_requires_reindex" in src, (
        "the formatter must handle the 409 index-contract detail shape"
    )


def test_store_routes_every_failure_through_the_formatter() -> None:
    src = _read(STORE_TS)
    assert 'from "@/utils/saveErrorMessage"' in src or "from '@/utils/saveErrorMessage'" in src, (
        "useConfigStore must import the shared formatter"
    )
    # The M-20 defect was `error: error instanceof Error ? error.message : ...` forwarding the
    # raw axios string into the store's UI-visible `error`. None of those may remain.
    assert "error.message" not in src, (
        "useConfigStore must not forward error.message into the UI; route through formatSaveError"
    )
    # Under the uniform staged model there are three commit/load failure paths that surface an
    # error to the operator -- the Apply PUT (`saveConfig`), the load GET (`loadConfigOnce`) and
    # `resetConfig` -- and each must route through the formatter (the per-section PATCH paths were
    # deleted when every surface moved to staging).
    calls = len(re.findall(r"formatSaveError\s*\(", src))
    assert calls >= 3, f"expected formatSaveError on every failure path, found {calls} call(s)"


def test_footer_shows_the_server_message_without_the_raw_error_prefix() -> None:
    src = _read(APP_TS)
    # The old footer printed `Error: {saveError}` with the axios string as saveError; the fixed
    # footer renders the server-authored sentence directly under a stable testid.
    assert "Error: {saveError}" not in src, "footer must not prefix the raw error string"
    assert 'data-testid="apply-error"' in src
    assert "Request failed with status code" not in src
