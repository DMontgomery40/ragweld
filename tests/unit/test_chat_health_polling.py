"""The app's health poller must follow tab visibility (M-130/B-35).

A tab nobody is looking at has nothing to report, and the drive found an idle Chat page
still paying for a header no one could see. The behaviour itself cannot be asserted in the
Playwright suite: in that headless Chromium ``document.visibilityState`` stays ``"visible"``
however the page is backgrounded (``bringToFront()`` on another tab and CDP
``Page.setWebLifecycleState: frozen`` were both measured leaving it visible), so a green
hidden-tab test could only be bought by stubbing the very property the code branches on.

This is the source invariant instead: the wiring must be present and must not regress to an
unconditional ``setInterval``. ``web/tests/e2e/exhaustive/chat_idle_polling.spec.ts`` covers
the half a browser can see - that a visible idle page makes no requests beyond the interval.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

APP_TSX = Path(__file__).resolve().parents[2] / "web" / "src" / "App.tsx"


@pytest.fixture(scope="module")
def app_source() -> str:
    assert APP_TSX.is_file(), f"missing {APP_TSX}"
    return APP_TSX.read_text(encoding="utf-8")


def _health_effect(source: str) -> str:
    """The effect that owns health polling, from its first line to its dependency array."""
    start = source.index("HEALTH_POLL_INTERVAL_MS)")
    open_at = source.rindex("useEffect(() => {", 0, start)
    close_at = source.index("}, [checkHealth]);", start)
    return source[open_at : close_at + len("}, [checkHealth]);")]


def test_health_polling_is_bound_to_tab_visibility(app_source: str) -> None:
    effect = _health_effect(app_source)
    assert re.search(r"document\.addEventListener\(\s*['\"]visibilitychange['\"]", effect), (
        "the health effect must react to visibilitychange"
    )
    assert re.search(r"document\.removeEventListener\(\s*['\"]visibilitychange['\"]", effect), (
        "the listener must be removed on unmount, or every remount adds another poller"
    )
    assert re.search(r"document\.visibilityState\s*===\s*['\"]hidden['\"]", effect), (
        "the effect must branch on the hidden state, not merely listen for the event"
    )


def test_a_hidden_tab_clears_the_interval_rather_than_leaving_it_running(app_source: str) -> None:
    effect = _health_effect(app_source)
    hidden_at = re.search(r"document\.visibilityState\s*===\s*['\"]hidden['\"]", effect)
    assert hidden_at is not None
    hidden_branch = effect[hidden_at.start() :]
    hidden_branch = hidden_branch[: hidden_branch.index("return;")]
    assert "stopPolling()" in hidden_branch, (
        "becoming hidden must stop the interval; slowing it down still costs the operator "
        "requests for a page nobody can see"
    )
    assert "clearInterval" in effect


def test_becoming_visible_re_checks_immediately(app_source: str) -> None:
    """Otherwise the header shows a stale verdict until the next tick - up to a full interval."""
    effect = _health_effect(app_source)
    visible_branch = effect[effect.index("return;") :]
    check_at = visible_branch.index("checkHealth()")
    interval_at = visible_branch.index("setInterval")
    assert check_at < interval_at, (
        "the immediate re-check must run before the interval is (re)started"
    )


def test_health_polling_is_never_started_unconditionally(app_source: str) -> None:
    """A bare `setInterval(checkHealth, ...)` at effect top level is the regression."""
    for match in re.finditer(r"setInterval\(\s*checkHealth", app_source):
        window = app_source[max(0, match.start() - 800) : match.start()]
        assert "visibilityState" in window, (
            "every health interval must sit behind the visibility check; found one at "
            f"offset {match.start()} without it"
        )


def test_the_interval_is_a_named_constant(app_source: str) -> None:
    """So the cadence is legible and greppable rather than a bare number in an effect.

    The VALUE is deliberately not asserted: this row's own fix direction invites changing
    the cadence, and a test named for the constant must not be the thing that fails when
    someone does.
    """
    assert re.search(
        r"const HEALTH_POLL_INTERVAL_MS\s*=", app_source
    ), "HEALTH_POLL_INTERVAL_MS must be declared at module scope"
    assert re.search(
        r"setInterval\(\s*checkHealth\s*,\s*HEALTH_POLL_INTERVAL_MS\s*\)", app_source
    ), "the interval must be driven by the named constant, not a literal"
