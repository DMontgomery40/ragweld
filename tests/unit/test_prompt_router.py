from __future__ import annotations

import subprocess
import sys

from scripts import prompt_router


def test_docs_prompts_reference_docs_autopilot_readme_and_not_generated_mkdocs_pages() -> None:
    route = prompt_router.route_prompt("please fix docs-autopilot ownership and mkdocs docs behavior")

    assert "/Users/davidmontgomery/ragweld/scripts/docs_ai/README.md" in route.references
    assert "/Users/davidmontgomery/ragweld/mkdocs/docs/testing.md" not in route.references
    assert any("mkdocs/**" in item for item in route.required_checks)


def test_cli_injects_boundary_policy_without_blanket_pydantic_or_adapter_law() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/prompt_router.py"],
        input='{"prompt":"add a public API response and UI view model"}',
        check=True,
        capture_output=True,
        text=True,
    )

    output = result.stdout
    output_lower = output.lower()
    assert "registered public api" in output_lower
    assert "generated" in output_lower
    assert "local ui" in output_lower
    assert "Pydantic is the law" not in output
    assert "No adapters" not in output
