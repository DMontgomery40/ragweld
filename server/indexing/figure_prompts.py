"""Prompt profiles and reply parsing for figure description at index time.

The prompts and the reply schema are code, not configuration: they are protocol invariants
between ragweld and the vision alias. Operators choose a profile via
``indexing.figures.prompt_profile``.
"""

from __future__ import annotations

import json
import re
from typing import Any, get_args

from server.models.index import FigureAnnotation, FigureKind

_SCHEMA = (
    'Return ONLY a JSON object with these keys: "kind" (one of diagram, chart, schematic, photo, '
    'table, drawing, other), "summary" (2-6 sentences of dense prose: what the figure shows and '
    'what it establishes), "labels" (every legible callout, axis label, legend entry or part number, '
    'transcribed exactly), "components" (named parts or entities depicted), "connections" '
    '("A -> B" relations that are drawn or stated), "values" (numbers with units exactly as printed), '
    '"references" (sheet, figure, table or section cross-references printed on the figure). '
    "Transcribe text exactly; do not invent values; leave a list empty when nothing is visible."
)

FIGURE_PROMPTS: dict[str, str] = {
    "technical_figure": (
        "You are describing one figure from a technical report so that an engineer can find it by "
        "searching for what it shows. " + _SCHEMA
    ),
    "schematic": (
        "You are describing one engineering drawing or schematic (electrical, hydraulic, mechanical, "
        "panel layout). Read the title block: put the drawing number, sheet, and revision into "
        '"references"; put connector, pin, signal and part designators into "labels"; put every '
        'drawn connection into "connections" as "A -> B"; keep units exactly as printed. ' + _SCHEMA
    ),
}

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_VALID_KINDS: frozenset[str] = frozenset(get_args(FigureKind))


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def parse_figure_reply(text: str) -> FigureAnnotation:
    """Parse a vision reply into a FigureAnnotation; anything unparseable becomes the summary."""
    raw = (text or "").strip()
    if not raw:
        return FigureAnnotation()
    candidate = raw
    m = _FENCE_RE.search(raw)
    if m:
        candidate = m.group(1)
    elif not raw.startswith("{"):
        start, end = raw.find("{"), raw.rfind("}")
        candidate = raw[start : end + 1] if start >= 0 and end > start else ""
    data: Any = None
    if candidate:
        try:
            data = json.loads(candidate)
        except ValueError:
            data = None
    if not isinstance(data, dict):
        return FigureAnnotation(summary=raw)
    kind = str(data.get("kind") or "other").strip().lower()
    return FigureAnnotation(
        kind=kind if kind in _VALID_KINDS else "other",  # type: ignore[arg-type]
        summary=str(data.get("summary") or "").strip(),
        labels=_string_list(data.get("labels")),
        components=_string_list(data.get("components")),
        connections=_string_list(data.get("connections")),
        values=_string_list(data.get("values")),
        references=_string_list(data.get("references")),
    )


def figure_block_markdown(caption: str, cls: str | None, fig: FigureAnnotation | None) -> str:
    """Prose-only markdown for one figure; the JSON never enters the embedded text."""
    caption = (caption or "").strip()
    head = f"Figure ({cls}): {caption}" if cls else f"Figure: {caption}"
    if not caption and (fig is None or not fig.summary):
        return ""
    parts: list[str] = [head.rstrip(": ").rstrip()]
    if fig is not None:
        if fig.summary:
            parts.append(fig.summary.strip())
        for name, items in (("Labels", fig.labels), ("Components", fig.components), ("Connections", fig.connections), ("Values", fig.values), ("References", fig.references)):
            if items:
                parts.append(f"{name}: " + ", ".join(items))
    return "\n".join(parts)
