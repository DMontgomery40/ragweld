from __future__ import annotations

from scripts import prompt_router


def test_docs_prompts_reference_docs_autopilot_readme_and_not_generated_mkdocs_pages() -> None:
    route = prompt_router.route_prompt("please fix docs-autopilot ownership and mkdocs docs behavior")

    assert "/Users/davidmontgomery/ragweld/scripts/docs_ai/README.md" in route.references
    assert "/Users/davidmontgomery/ragweld/mkdocs/docs/testing.md" not in route.references
    assert any("mkdocs/**" in item for item in route.required_checks)
