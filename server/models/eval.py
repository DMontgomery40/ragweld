"""Evaluation-related models - Re-exported from THE LAW.

All domain models are defined in tribrid_config_model.py (THE LAW).
This file re-exports them for backwards compatibility.
"""
from server.models.tribrid_config_model import (
    EvalComparisonResult,
    EvalDatasetItem,
    EvalMetrics,
    EvalRequest,
    EvalResult,
    EvalRun,
)

# Backward compatibility alias
DatasetEntry = EvalDatasetItem

__all__ = [
    "DatasetEntry",  # Legacy alias
    "EvalDatasetItem",
    "EvalRequest",
    "EvalMetrics",
    "EvalResult",
    "EvalRun",
    "EvalComparisonResult",
]
