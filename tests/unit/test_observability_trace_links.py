"""Every surface that shows a trace's external links goes through one renderer.

M-16 was filed against Chat > Routing Trace and Eval > Trace Viewer, and both
rendered `link.label` alone: no `title`, no `detail`, and no check that Langfuse
holds the trace. So the operator got Langfuse's own "You do not have access to
this trace" with no warning before the click.

Fixing the two call sites is not enough on its own - the next surface to render
`external_links` would reintroduce it. This is a source invariant over
`web/src`, so a third copy fails here rather than in front of an operator.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_SRC = ROOT / "web" / "src"
SHARED_RENDERER = WEB_SRC / "components" / "Observability" / "TraceExternalLinks.tsx"


def _sources() -> list[Path]:
    return [path for path in WEB_SRC.rglob("*.tsx") if path != SHARED_RENDERER]


def test_only_the_shared_renderer_maps_a_trace_s_external_links() -> None:
    mapping = re.compile(r"external_links\s*(?:\?\.)?\.?map\(|external_links\.map\(")
    offenders = [
        str(path.relative_to(ROOT)) for path in _sources() if mapping.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "these surfaces render trace external links themselves; use "
        "components/Observability/TraceExternalLinks so the Langfuse check and the "
        f"membership hint travel with the link: {offenders}"
    )


def test_the_shared_renderer_carries_the_check_and_the_hint() -> None:
    source = SHARED_RENDERER.read_text(encoding="utf-8")

    # The existence check gates the per-trace Langfuse link...
    assert "getLangfuseTraceAccess" in source
    assert "access?.exists === true" in source
    # ...and the membership requirement rides on every link as a tooltip.
    assert "sign_in_hint" in source
    assert "title={" in source
    # "could not ask" stays distinct from "Langfuse says no".
    assert "trace-langfuse-check-failed" in source
    assert "trace-langfuse-withheld" in source


def test_the_two_surfaces_the_defect_was_filed_against_use_it() -> None:
    for relative in (
        "web/src/components/tabs/ChatTab.tsx",
        "web/src/components/Evaluation/TraceViewer.tsx",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "TraceExternalLinks" in source, relative
        assert "traceId=" in source, f"{relative} must pass the trace id, or the check cannot run"
