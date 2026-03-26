"""Synthetic data pipeline models extracted from the monolith.

This module follows the `runtime_gateway.py` pattern: domain-specific Pydantic
models defined here, re-exported through `tribrid_config_model.py` so the type
generation chain stays intact.

Covers: quality gate config, generator/judge LLM parameters, failure policy,
run degradation tracking.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SyntheticQualityGateConfig(BaseModel):
    """Quality gate thresholds for synthetic data evaluation."""

    top1_min: float = Field(
        default=0.40,
        ge=0.0,
        le=1.0,
        description="Minimum top-1 retrieval accuracy to pass quality gate",
    )
    sample_size: int = Field(
        default=50,
        ge=1,
        le=10000,
        description="Number of eval items to sample for quality gate evaluation",
    )


class SyntheticGeneratorConfig(BaseModel):
    """LLM generation parameters for the synthetic pipeline."""

    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Temperature for synthetic generator LLM calls",
    )
    max_tokens: int = Field(
        default=1200,
        ge=100,
        le=16000,
        description="Max tokens for generator LLM response",
    )
    question_max_chars: int = Field(
        default=180,
        ge=50,
        le=500,
        description="Max characters for generated question text",
    )
    evidence_quote_max_chars: int = Field(
        default=200,
        ge=50,
        le=1000,
        description="Max characters for evidence quote field",
    )
    expected_answer_max_chars: int = Field(
        default=400,
        ge=50,
        le=2000,
        description="Max characters for expected answer field",
    )
    source_excerpt_max_lines: int = Field(
        default=80,
        ge=10,
        le=500,
        description="Max lines of source chunk content sent as context to generator/judge",
    )
    fail_on_error: bool = Field(
        default=True,
        description="If True, fail the run when generator LLM is unreachable instead of silently falling back to deterministic extraction.",
    )


class SyntheticJudgeConfig(BaseModel):
    """LLM judge parameters for synthetic curation."""

    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Temperature for synthetic judge LLM calls",
    )
    max_tokens: int = Field(
        default=400,
        ge=100,
        le=4000,
        description="Max tokens for judge LLM response",
    )
    fail_on_error: bool = Field(
        default=True,
        description="If True, fail the run when judge LLM is unreachable instead of silently auto-passing all items.",
    )


class SyntheticConfig(BaseModel):
    """Top-level synthetic data pipeline configuration."""

    quality_gate: SyntheticQualityGateConfig = Field(
        default_factory=SyntheticQualityGateConfig,
        description="Quality gate thresholds for synthetic data evaluation",
    )
    generator: SyntheticGeneratorConfig = Field(
        default_factory=SyntheticGeneratorConfig,
        description="LLM generation parameters for synthetic pipeline",
    )
    judge: SyntheticJudgeConfig = Field(
        default_factory=SyntheticJudgeConfig,
        description="LLM judge parameters for synthetic curation",
    )


class SyntheticRunDegradation(BaseModel):
    """Degradation flags -- honest about what actually happened during a synthetic run."""

    generator_fallback_used: bool = Field(
        default=False,
        description="True if generator LLM failed and deterministic fallback was used",
    )
    judge_fallback_used: bool = Field(
        default=False,
        description="True if judge LLM failed and all items were auto-passed",
    )
    seed_hydration_used: bool = Field(
        default=False,
        description="True if eval dataset was populated from seed dataset instead of generation",
    )
    seed_hydration_count: int = Field(
        default=0,
        ge=0,
        description="Number of items hydrated from seed dataset",
    )
    degraded: bool = Field(
        default=False,
        description="True if any fallback or degradation occurred during the run",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Human-readable list of degradation reasons",
    )
