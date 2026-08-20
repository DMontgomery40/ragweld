from __future__ import annotations

from pathlib import Path

from scripts.validate_types import GENERATED_TS_PATH, validate_types_file


def test_validate_types_detects_stale_content_without_rewriting_it(tmp_path: Path) -> None:
    candidate = tmp_path / "generated.ts"
    stale = "// deliberately stale\n"
    candidate.write_text(stale, encoding="utf-8")

    result = validate_types_file(candidate)

    assert result == 1
    assert candidate.read_text(encoding="utf-8") == stale


def test_validate_types_accepts_current_generated_contract(tmp_path: Path) -> None:
    candidate = tmp_path / "generated.ts"
    candidate.write_text(GENERATED_TS_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    result = validate_types_file(candidate)

    assert result == 0
    assert candidate.read_text(encoding="utf-8") == GENERATED_TS_PATH.read_text(encoding="utf-8")
