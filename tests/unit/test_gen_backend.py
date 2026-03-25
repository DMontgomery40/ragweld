"""Tests for gen_backend field on GenerationConfig."""

import pytest
from pydantic import ValidationError

from server.models.tribrid_config_model import GenerationConfig, TriBridConfig


def test_gen_backend_default_is_openai() -> None:
    config = GenerationConfig()
    assert config.gen_backend == "openai"


def test_gen_backend_accepts_valid_patterns() -> None:
    for backend in ("openai", "anthropic", "ollama", "mlx", "openrouter", "litellm"):
        config = GenerationConfig(gen_backend=backend)
        assert config.gen_backend == backend


def test_gen_backend_rejects_invalid_pattern() -> None:
    with pytest.raises(ValidationError):
        GenerationConfig(gen_backend="huggingface")


def test_gen_backend_rejects_empty_string() -> None:
    with pytest.raises(ValidationError):
        GenerationConfig(gen_backend="")


def test_gen_backend_round_trip_via_tribrid_config() -> None:
    config = TriBridConfig()
    config.generation.gen_backend = "anthropic"
    dumped = config.model_dump()
    restored = TriBridConfig.model_validate(dumped)
    assert restored.generation.gen_backend == "anthropic"


def test_gen_backend_flat_dict_round_trip() -> None:
    config = TriBridConfig()
    config.generation.gen_backend = "openrouter"
    flat = config.to_flat_dict()
    assert flat["GEN_BACKEND"] == "openrouter"
    restored = TriBridConfig.from_flat_dict(flat)
    assert restored.generation.gen_backend == "openrouter"
