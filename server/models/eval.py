"""Evaluation-related models - Re-exported from THE LAW.

All domain models are defined in tribrid_config_model.py (THE LAW).
This file re-exports them for backwards compatibility.
"""
from server.models.tribrid_config_model import (
    EvalComparisonResult,
    EvalAnalyzeComparisonResponse,
    EvalDoc,
    EvalDatasetItem,
    EvalMetrics,
    EvalRequest,
    EvalTestRequest,
    EvalResult,
    EvalRun,
    EvalRunMeta,
    EvalRunsResponse,
)

# Backward compatibility alias
DatasetEntry = EvalDatasetItem

__all__ = [
    "DatasetEntry",  # Legacy alias
    "EvalAnalyzeComparisonResponse",
    "EvalDoc",
    "EvalDatasetItem",
    "EvalRequest",
    "EvalTestRequest",
    "EvalMetrics",
    "EvalResult",
    "EvalRun",
    "EvalComparisonResult",
    "EvalRunMeta",
    "EvalRunsResponse",
]
