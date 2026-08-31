"""Vision replies parse into FigureAnnotation; malformed replies degrade, never raise."""

from __future__ import annotations

import json

from server.indexing.figure_prompts import FIGURE_PROMPTS, figure_block_markdown, parse_figure_reply
from server.models.index import FigureAnnotation


def test_prompts_exist_for_both_profiles_and_forbid_invention() -> None:
    assert set(FIGURE_PROMPTS) == {"technical_figure", "schematic"}
    for text in FIGURE_PROMPTS.values():
        assert "JSON" in text and "do not invent" in text.lower()
        for key in ("summary", "labels", "components", "connections", "values", "references", "kind"):
            assert f'"{key}"' in text
    assert "drawing number" in FIGURE_PROMPTS["schematic"].lower()


def test_parse_valid_reply() -> None:
    reply = json.dumps({
        "kind": "chart",
        "summary": "Command module cabin pressure during entry, falling from 5.0 to 4.6 psia.",
        "labels": ["CABIN PRESSURE, PSIA", "TIME, SEC"],
        "components": [], "connections": [],
        "values": ["5.0 psia", "4.6 psia"],
        "references": ["Figure 5-12"],
    })
    fig = parse_figure_reply(reply)
    assert fig.kind == "chart" and fig.values == ["5.0 psia", "4.6 psia"]
    assert fig.references == ["Figure 5-12"]


def test_parse_reply_wrapped_in_fences_and_unknown_kind() -> None:
    fig = parse_figure_reply('```json\n{"kind": "hologram", "summary": "x", "labels": ["A"]}\n```')
    assert fig.kind == "other" and fig.summary == "x" and fig.labels == ["A"]


def test_parse_reply_fenced_with_literal_closing_brace_in_strings() -> None:
    reply = '```json\n{"kind": "chart", "summary": "shows A} B split", "labels": ["X}"]}\n```'
    fig = parse_figure_reply(reply)
    assert fig.kind == "chart"
    assert fig.summary == "shows A} B split"
    assert fig.labels == ["X}"]


def test_parse_reply_fenced_with_literal_closing_brace_and_surrounding_prose() -> None:
    reply = (
        "Here is the figure description:\n"
        '```json\n{"kind": "chart", "summary": "shows A} B split", "labels": ["X}"]}\n```\n'
        "Let me know if you need anything else."
    )
    fig = parse_figure_reply(reply)
    assert fig.kind == "chart"
    assert fig.summary == "shows A} B split"
    assert fig.labels == ["X}"]


def _assert_no_json_syntax_leaks(fig: FigureAnnotation) -> None:
    """No field of a degraded/repaired annotation may carry JSON keys or syntax."""
    for text in (fig.summary, *fig.labels, *fig.components, *fig.connections, *fig.values, *fig.references):
        assert "{" not in text and "}" not in text
        for key in ("kind", "summary", "labels", "components", "connections", "values", "references"):
            assert f'"{key}"' not in text


def test_malformed_reply_with_trailing_comma_is_repaired() -> None:
    """Live-defect regression: a JSON-looking reply json.loads rejects must not leak keys."""
    reply = (
        '{"kind": "chart", "summary": "Cabin pressure falls from 5.0 to 4.6 psia during entry.", '
        '"labels": ["CABIN PRESSURE, PSIA"], "values": ["5.0 psia", "4.6 psia"],}'
    )
    fig = parse_figure_reply(reply)
    assert fig.kind == "chart"
    assert fig.summary == "Cabin pressure falls from 5.0 to 4.6 psia during entry."
    assert fig.labels == ["CABIN PRESSURE, PSIA"]
    assert fig.values == ["5.0 psia", "4.6 psia"]
    _assert_no_json_syntax_leaks(fig)
    block = figure_block_markdown("Figure 5-12. Cabin pressure", "chart", fig)
    assert '"summary"' not in block and "{" not in block


def test_malformed_fenced_reply_with_unescaped_newline_in_string_is_repaired() -> None:
    reply = (
        '```json\n{"kind": "diagram", "summary": "Fuel cell reactant flow\nfrom cryogenic tanks to the bus.", '
        '"labels": ["H2", "O2"]}\n```'
    )
    fig = parse_figure_reply(reply)
    assert fig.kind == "diagram"
    assert "Fuel cell reactant flow" in fig.summary and "cryogenic tanks" in fig.summary
    assert fig.labels == ["H2", "O2"]
    _assert_no_json_syntax_leaks(fig)


def test_truncated_reply_is_repaired_without_leaking_syntax() -> None:
    """A response cut off mid-object (no closing brace) is a realistic provider failure."""
    reply = '{"kind": "schematic", "summary": "Umbilical wiring between the CSM and LM ascent stage.", "labels": ["J1", "P2"'
    fig = parse_figure_reply(reply)
    assert fig.kind == "schematic"
    assert fig.summary == "Umbilical wiring between the CSM and LM ascent stage."
    assert fig.labels == ["J1", "P2"]
    _assert_no_json_syntax_leaks(fig)


def test_json_looking_but_unrecoverable_reply_degrades_to_empty_annotation() -> None:
    reply = '{"completely": {"different": ["shape"]}, "no_reply_keys": true'
    fig = parse_figure_reply(reply)
    assert fig == FigureAnnotation()
    _assert_no_json_syntax_leaks(fig)
    assert figure_block_markdown("Figure 3-3. Umbilical", None, fig) == "Figure: Figure 3-3. Umbilical"


def test_prose_with_incidental_braces_still_becomes_the_summary() -> None:
    reply = "A photograph of the ascent stage; the {bracketed} caption text is part of the print."
    fig = parse_figure_reply(reply)
    assert fig.summary == reply
    assert fig.kind == "other" and fig.labels == []


def test_non_json_reply_becomes_summary() -> None:
    fig = parse_figure_reply("A photograph of the lunar module ascent stage on the pad.")
    assert fig.summary == "A photograph of the lunar module ascent stage on the pad."
    assert fig.labels == [] and fig.kind == "other"


def test_empty_reply_is_empty_annotation() -> None:
    assert parse_figure_reply("") == FigureAnnotation()


def test_block_markdown_is_prose_only_and_omits_empty_parts() -> None:
    fig = FigureAnnotation(kind="diagram", summary="Fuel cell flow.", labels=["H2", "O2"], values=[])
    block = figure_block_markdown("Figure 4-1. Fuel cell", "diagram", fig)
    assert block.startswith("Figure (diagram): Figure 4-1. Fuel cell")
    assert "Fuel cell flow." in block and "Labels: H2, O2" in block
    assert "Values:" not in block and "{" not in block
    assert figure_block_markdown("", None, None) == ""
    assert figure_block_markdown("Figure 2", None, None) == "Figure: Figure 2"


def test_block_markdown_keeps_structured_content_with_blank_caption_and_summary() -> None:
    """A blank caption and blank summary must not drop labels/components/etc.; only a wholly
    empty figure (no caption, no summary, no lists) collapses to "". The header here has no
    trailing colon: with no caption and no cls, head is "Figure: " and the existing
    ``head.rstrip(": ").rstrip()`` normalization strips the dangling "` : `" down to "Figure".
    """
    fig = FigureAnnotation(labels=["J1", "J2"])
    assert figure_block_markdown("", None, fig) == "Figure\nLabels: J1, J2"


def test_block_markdown_keeps_class_header_with_no_caption_and_no_figure() -> None:
    """A classified-but-undescribed picture (``fig`` is ``None``) with no caption — Docling only
    attaches a caption when adjacent text is recognised as one — must still surface the class
    name rather than collapsing to "". With no structured content and no caption, only ``cls``
    keeps the block alive.
    """
    assert figure_block_markdown("", "chart", None) == "Figure (chart)"
    assert figure_block_markdown("", None, None) == "", "no caption, no cls, no figure is still empty"
