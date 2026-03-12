from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_readme_uses_safe_positioning_claims() -> None:
    readme = _read(ROOT / "README.md")
    assert "Versioned config, prompts, and specs" in readme
    assert "Manifest-backed training artifacts" in readme
    assert "provenance-minded eval and training workflows" in readme.lower()
    assert "full dsv compliance" not in readme.lower()


def test_agents_and_docs_prompt_base_block_full_dsv_claims() -> None:
    agents = _read(ROOT / "AGENTS.md")
    docs_prompt = _read(ROOT / "scripts" / "docs_ai" / "docs_prompt_base.md")

    assert "Do not market ragweld as fully DSV-compliant today." in agents
    assert "Do **not** claim full DSV compliance" in docs_prompt


def test_landing_and_onboarding_copy_match_safe_positioning() -> None:
    positioning = _read(ROOT / "docs" / "references" / "product-positioning.md")
    start_tab = _read(ROOT / "web" / "src" / "components" / "tabs" / "StartTab.tsx")

    assert "Versioned config, prompts, and specs" in positioning
    assert "Manifest-backed training artifacts" in positioning
    assert "Full DSV compliance" in positioning
    assert "versioned config, prompts, and executable specs" in start_tab
