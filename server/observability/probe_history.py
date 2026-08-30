"""Per-component readiness-probe history, so one missed probe is not an incident.

A single HTTP probe is a noisy signal: a collector restart, a 2 s stall or a
busy container answers 503 and recovers before the operator can read the deck.
Escalating that to `critical` trains an operator to ignore the deck, so a
component only counts as failed once `probe_failure_threshold` **consecutive**
probes have failed.

State is per process and deliberately not persisted: it is a debounce over the
live signal, not a record. `reset_probe_history()` clears it the way
`invalidate_loki_base_url()` clears the Loki resolver's cache.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Literal

# How many samples the deck can show. Eight covers four minutes at the deck's
# 30 s refresh, which is long enough to read a flap.
PROBE_HISTORY_LENGTH = 8

ProbeSample = Literal["ok", "failed", "unprobeable"]

_LOCK = threading.Lock()
_HISTORY: dict[str, deque[ProbeSample]] = {}


def sample_for(reachable: bool | None, *, probeable: bool = True) -> ProbeSample:
    """Classify one probe outcome.

    `unprobeable` is not a failure: an auth-protected ingress the API cannot
    reach through, or a component with nothing to probe, is an absence of
    evidence rather than evidence of a fault, so it never advances the streak.
    """

    if not probeable:
        return "unprobeable"
    if reachable is True:
        return "ok"
    if reachable is False:
        return "failed"
    return "unprobeable"


def probe_key(component_id: str, url: str | None) -> str:
    """Identity of the thing being probed.

    Most `tracing.*_base_url` fields are per-corpus scopable, so two corpora can
    point the same component at different targets. Keying the streak by
    component id alone would interleave their samples; a component whose URL is
    edited also starts a fresh streak, which is what an operator means by
    pointing it somewhere else.
    """

    return f"{component_id}|{str(url or '').strip()}"


def record_probe(key: str, sample: ProbeSample) -> tuple[list[ProbeSample], int]:
    """Append one sample and return the visible history plus the failure streak."""

    with _LOCK:
        history = _HISTORY.setdefault(key, deque(maxlen=PROBE_HISTORY_LENGTH))
        history.append(sample)
        samples = list(history)
    streak = 0
    for item in reversed(samples):
        if item != "failed":
            break
        streak += 1
    return samples, streak


def reset_probe_history() -> None:
    """Forget every recorded probe (used when a test owns the probe target)."""

    with _LOCK:
        _HISTORY.clear()
