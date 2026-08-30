"""Pin WCAG contrast floors for the GUI's core text tokens.

The operator's external monitors are low-DPI (dpr 1, ~93-94 PPI); dim grays that
look fine on retina collapse into mush there. `~/.claude/rules/design-legibility.md`
sets the floor: body text (`--fg`) >= 7:1, support text (`--fg-muted`, `--link`)
>= 4.5:1, measured against the *composited* surface a component actually paints
on -- `--bg`, `--bg-elev1`, `--bg-elev2`, and `--panel` are all legitimate
surfaces text sits on in this GUI, in both the dark and light themes.

This test parses the real token values out of `web/src/styles/tokens.css`
(zero mocks, no hand-copied color constants) and computes WCAG 2.x relative
luminance / contrast ratio directly, so a future edit to any of these hex
values is checked against the floor automatically instead of by eyeball.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOKENS_CSS = ROOT / "web" / "src" / "styles" / "tokens.css"

DARK_SELECTOR = 'html, :root, [data-theme="dark"] {'
LIGHT_SELECTOR = '[data-theme="light"] {'

_HEX_VAR_RE = re.compile(r"--([a-zA-Z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;")


def _extract_block(css: str, selector: str) -> str:
    """Return the contents between `selector {` and its matching `}`.

    Token declarations inside these blocks are flat `--name: value;` lines
    with no nested braces, so the first `}` after the selector's own `{`
    closes the block.
    """
    start = css.index(selector) + len(selector)
    end = css.index("}", start)
    return css[start:end]


def _parse_hex_vars(block: str) -> dict[str, str]:
    return {name: value.lower() for name, value in _HEX_VAR_RE.findall(block)}


def _linearize(channel: float) -> float:
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b)


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    lum_a, lum_b = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def _load_themes() -> dict[str, dict[str, str]]:
    css = TOKENS_CSS.read_text(encoding="utf-8")
    dark_block = _extract_block(css, DARK_SELECTOR)
    light_block = _extract_block(css, LIGHT_SELECTOR)
    return {
        "dark": _parse_hex_vars(dark_block),
        "light": _parse_hex_vars(light_block),
    }


THEMES = _load_themes()

SURFACES = ("bg", "bg-elev1", "bg-elev2", "panel")

# (token name, WCAG floor) per design-legibility.md: body >= 7:1, support >= 4.5:1
TEXT_TOKEN_FLOORS = (
    ("fg", 7.0),
    ("fg-muted", 4.5),
    ("link", 4.5),
)


def test_theme_blocks_parse_and_disagree() -> None:
    """Guard against a silent mis-parse that would make every other test fake-green."""
    assert TOKENS_CSS.exists()
    for theme_name in ("dark", "light"):
        theme = THEMES[theme_name]
        for token_name, _floor in TEXT_TOKEN_FLOORS:
            assert token_name in theme, f"{theme_name} block is missing --{token_name}"
        for surface in SURFACES:
            assert surface in theme, f"{theme_name} block is missing --{surface}"

    # Dark and light are different palettes; if the parser mangled the split
    # (e.g. matched `:root` instead of `[data-theme="light"]`) both blocks
    # would resolve to the same values and this would silently pass.
    assert THEMES["dark"]["bg"] != THEMES["light"]["bg"]
    assert THEMES["dark"]["fg-muted"] != THEMES["light"]["fg"]


@pytest.mark.parametrize("theme_name", ["dark", "light"])
@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("token_name,floor", TEXT_TOKEN_FLOORS)
def test_text_token_meets_contrast_floor(
    theme_name: str, surface: str, token_name: str, floor: float
) -> None:
    theme = THEMES[theme_name]
    fg_hex = theme[token_name]
    bg_hex = theme[surface]

    ratio = _contrast_ratio(fg_hex, bg_hex)

    assert ratio >= floor, (
        f"{theme_name} theme: --{token_name} {fg_hex} on --{surface} {bg_hex} "
        f"= {ratio:.2f}:1, below the {floor}:1 legibility floor "
        f"(design-legibility.md; measured against the composited surface, "
        f"not the token in isolation)"
    )
