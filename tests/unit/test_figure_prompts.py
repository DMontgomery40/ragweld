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
