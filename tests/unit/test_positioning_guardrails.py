from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_readme_uses_safe_positioning_claims() -> None:
    # The 2026-08-24 operator repositioning ("one complete, self-hosted AI
    # platform") moved the safe claims from the tagline into the reliability
    # section; the claims themselves must stay present and DSV claims banned.
    readme = _read(ROOT / "README.md")
    assert "Versioned source-of-truth config" in readme
    assert "Manifest-backed training artifacts" in readme
    assert "provenance-minded workflows" in readme.lower()
    assert "without claiming full end-to-end DSV governance" in readme
    assert "full dsv compliance" not in readme.lower()


def test_agents_and_docs_prompt_base_block_full_dsv_claims() -> None:
    # AGENTS.md is a thin pointer to CLAUDE.md (bbdd4525); the positioning guardrail
    # lives in CLAUDE.md's main-canon section now, not in AGENTS.md itself.
    claude_md = _read(ROOT / "CLAUDE.md")
    docs_prompt = _read(ROOT / "scripts" / "docs_ai" / "docs_prompt_base.md")

    assert "Do not market ragweld as fully DSV-compliant today." in claude_md
    assert "Do **not** claim full DSV compliance" in docs_prompt


def test_landing_and_onboarding_copy_match_safe_positioning() -> None:
    positioning = _read(ROOT / "docs" / "references" / "product-positioning.md")
    start_tab = _read(ROOT / "web" / "src" / "components" / "tabs" / "StartTab.tsx")

    assert "Versioned config, prompts, and specs" in positioning
    assert "Manifest-backed training artifacts" in positioning
    assert "Full DSV compliance" in positioning
    assert "versioned config, prompts, and executable specs" in start_tab
