"""Synthetic data pipeline models extracted from the monolith.

This module follows the `runtime_gateway.py` pattern: domain-specific Pydantic
models defined here, re-exported through `tribrid_config_model.py` so the type
generation chain stays intact.

Covers: quality gate config and generator/judge LLM parameters. Generator and
judge failures fail the run; there is no fallback to record.
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
    concurrency: int = Field(
        default=4,
        ge=1,
        le=16,
        description=(
            "Concurrent generator/judge requests sent to the LiteLLM gateway per synthetic run. "
            "Forced to 1 when the selected alias is the single-stream local vLLM serving row."
        ),
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
