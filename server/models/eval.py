"""Evaluation-related models - Re-exported from THE LAW.

All domain models are defined in tribrid_config_model.py (THE LAW).
This file re-exports them for backwards compatibility.
"""
from server.models.tribrid_config_model import (
    EvalAnalyzeComparisonResponse,
    EvalComparisonResult,
    EvalDatasetItem,
    EvalDoc,
    EvalMetrics,
    EvalObservabilitySummaryResponse,
    EvalRequest,
    EvalResult,
    EvalRun,
    EvalRunMeta,
    EvalRunsResponse,
    EvalTestRequest,
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
    "EvalObservabilitySummaryResponse",
    "EvalResult",
    "EvalRun",
    "EvalComparisonResult",
    "EvalRunMeta",
    "EvalRunsResponse",
]
