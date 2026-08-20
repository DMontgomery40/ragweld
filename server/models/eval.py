"""Evaluation-related registered boundary model exports.

These public schemas currently aggregate through tribrid_config_model.py.
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
