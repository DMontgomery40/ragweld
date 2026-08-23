"""Finite-number guards for training metrics before they reach events, summaries and JSON.

A NaN/inf metric is an evaluation that produced no number. Letting it into the run
record silently corrupts it: Pydantic constraints are bypassed by attribute assignment
and FastAPI later refuses to serialize the run (`Out of range float values are not JSON
compliant`). These helpers keep the raw value only where the promotion decision needs it.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping

from server.models.tribrid_config_model import _METRIC_DOMAINS as METRIC_DOMAINS


def finite_or_none(value: object) -> float | None:
    """The value as a finite float, or None when it is missing, not numeric or NaN/inf."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


# Value domains per metric family (the persisted-event boundary in tribrid_config_model.py
# enforces the same table). A finite number outside its domain (eval_loss=-1, mrr=2.0) is an
# evaluation that produced an impossible number: it is dropped exactly like NaN, so it can
# neither be persisted as a score nor promote an artifact.
def metric_family(name: str) -> str:
    return str(name).split("@", 1)[0].strip().lower()


def in_metric_domain(name: str, value: float) -> bool:
    bounds = METRIC_DOMAINS.get(metric_family(name))
    if bounds is None:
        return True
    low, high = bounds
    return low <= value <= high


def finite_metrics(metrics: Mapping[str, object]) -> tuple[dict[str, float], list[str]]:
    """Split a metrics mapping into its valid entries (finite and inside the metric's domain)
    and the names that were dropped."""
    kept: dict[str, float] = {}
    dropped: list[str] = []
    for key, value in metrics.items():
        number = finite_or_none(value)
        if number is None or not in_metric_domain(str(key), number):
            dropped.append(str(key))
        else:
            kept[str(key)] = number
    return kept, dropped


def non_negative_or_none(value: object) -> float | None:
    """A finite, non-negative float (durations, counts measured as floats); None otherwise."""
    number = finite_or_none(value)
    return number if number is not None and number >= 0.0 else None


def stability_stddev(series: list[float], *, window: int = 5) -> float | None:
    """Population stddev of the last `window` finite values; None when nothing finite is available
    or when the arithmetic itself overflows (naive sum-of-squares on 1e308 inputs yields inf)."""
    tail = [v for v in series[-window:] if finite_or_none(v) is not None]
    if not tail:
        return None
    try:
        value = statistics.pstdev(tail)
    except (OverflowError, ValueError):
        return None
    return finite_or_none(value)


def step_or_none(value: object) -> int | None:
    """A training step as an int, preserving 0; None when absent, negative or not integral
    (1.5 is not a step and must not be truncated to 1)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        step = int(value)
    elif isinstance(value, int):
        step = value
    elif isinstance(value, str):
        text = value.strip()
        if not text.lstrip("+-").isdigit():
            return None
        step = int(text)
    else:
        return None
    return step if step >= 0 else None
