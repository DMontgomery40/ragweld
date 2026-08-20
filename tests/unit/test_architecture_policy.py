from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY_FILES = (
    ROOT / "AGENTS.md",
    ROOT / "CLAUDE.md",
    ROOT / ".claude/rules/pydantic-first.md",
    ROOT / ".claude/rules/typescript-types.md",
    ROOT / "docs/design-docs/core-beliefs.md",
    ROOT / "scripts/docs_ai/docs_prompt_base.md",
    ROOT / "web/src/ARCHITECTURE.md",
)


def test_authoritative_policy_uses_boundaries_not_a_universal_pydantic_law() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in POLICY_FILES)

    assert "Pydantic is the law" not in combined
    assert "No adapters/transformers/mappers" not in combined
    assert "public API" in combined
    assert "generated" in combined
    assert "local UI" in combined
    assert "compatibility" in combined


def test_guard_does_not_ban_boundary_mapping_by_class_name() -> None:
    guards = json.loads((ROOT / ".claude/hooks/guards.json").read_text(encoding="utf-8"))
    serialized = json.dumps(guards)

    assert "class.*Adapter" not in serialized
    assert "class.*Transformer" not in serialized
    assert "class.*Mapper" not in serialized
