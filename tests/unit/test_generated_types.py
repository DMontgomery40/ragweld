"""Tests for generated TypeScript types containing new models."""

from pathlib import Path


GENERATED_TS = Path(__file__).resolve().parents[2] / "web" / "src" / "types" / "generated.ts"


def test_generated_ts_exists() -> None:
    assert GENERATED_TS.exists(), f"generated.ts not found at {GENERATED_TS}"


def test_model_validation_warning_in_generated_ts() -> None:
    content = GENERATED_TS.read_text()
    assert "export interface ModelValidationWarning" in content


def test_model_validation_result_in_generated_ts() -> None:
    content = GENERATED_TS.read_text()
    assert "export interface ModelValidationResult" in content


def test_generation_config_has_gen_backend() -> None:
    content = GENERATED_TS.read_text()
    assert "gen_backend" in content


def test_model_validation_result_has_warnings_typed() -> None:
    content = GENERATED_TS.read_text()
    assert "ModelValidationWarning[]" in content
