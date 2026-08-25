"""The docs-autopilot bootstrap generator must only cite inputs that exist.

`scripts/docs_ai/bootstrap_docs.py` feeds every `source_files` entry of a page to the
documentation model; a path that no longer exists is turned into a literal
"File not found" block and shipped as degraded context (Codex review of #85 caught
four deleted spec YAMLs still listed for the `api` page). This is the invariant for
every page, so a future deletion cannot silently degrade a generator input again.
"""
from __future__ import annotations

from pathlib import Path

from scripts.docs_ai import bootstrap_docs

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_every_generator_source_file_exists() -> None:
    missing: list[str] = []
    for page_key, page in bootstrap_docs.DOC_PAGES.items():
        sources = page.get("source_files") or []
        assert sources, f"page {page_key!r} declares no source files"
        for rel in sources:
            if not (REPO_ROOT / rel).exists():
                missing.append(f"{page_key}: {rel}")
    assert not missing, "generator inputs that no longer exist on disk:\n" + "\n".join(missing)


def test_api_page_no_longer_cites_removed_spec_prose() -> None:
    api_sources = bootstrap_docs.DOC_PAGES["api"]["source_files"]
    assert not [s for s in api_sources if s.startswith("spec/backend/")]
    assert "server/api/config.py" in api_sources
