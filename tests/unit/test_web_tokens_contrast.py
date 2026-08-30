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
    start_of_selector = css.find(selector)
    assert start_of_selector != -1, (
        f"tokens.css structure changed: selector {selector!r} was not found. "
        f"Update DARK_SELECTOR/LIGHT_SELECTOR in this test to match the new "
        f"theme block opener instead of letting this fail as a raw ValueError."
    )
    start = start_of_selector + len(selector)
    end = css.find("}", start)
    assert end != -1, (
        f"tokens.css structure changed: no closing '}}' found after selector "
        f"{selector!r}; the theme block may no longer be a flat, single-level "
        f"rule this test's simple brace-matching can parse."
    )
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
#
# `ok`/`warn`/`err` are added here because they are used as ordinary TEXT color
# in several places (e.g. HelpGlossary.css, EmbeddingMismatchWarning.tsx), so
# the same 4.5:1 support-text floor applies to them against the page surfaces.
#
# `--accent` itself is intentionally NOT included: it is dual-purpose, also a
# BUTTON BACKGROUND paired with `--accent-contrast` (e.g. `.btn-primary`,
# `.top-actions button`, ~21 sites). Lightening the dark value enough to pass
# as text (3.72-4.18:1) would drop that background pairing with white
# `--accent-contrast` text from 4.76:1 to 3.81:1 -- trading one violation for
# another. `--accent-text` is the text-only variant: all 48 standalone
# `color: var(--accent)` call sites (across 22 files) were migrated to it;
# every `background`/`border` use of `--accent` was left untouched (verified
# by count before/after the migration -- see the task report).
TEXT_TOKEN_FLOORS = (
    ("fg", 7.0),
    ("fg-muted", 4.5),
    ("link", 4.5),
    ("ok", 4.5),
    ("warn", 4.5),
    ("err", 4.5),
    ("accent-text", 4.5),
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


# --- Guard: no de-emphasizing text via opacity -----------------------------
#
# design-legibility.md bans dimming text with `opacity` outright ("de-emphasize
# with a brighter-than-you-think muted tier, never with opacity on text
# ... Resting opacity on visible controls >= 0.8"). A contrast-ratio check on
# tokens.css alone can't catch this: `.topbar .tagline { color: var(--fg-muted);
# opacity: 0.6; }` composites a token that passes its own floor down to ~2.8:1
# on screen. This is a *heuristic guard*, not a full CSS/accessibility audit:
# it flags any leaf CSS rule that sets `opacity` strictly between 0 and 0.8
# AND looks like it is styling text -- it also sets `color` or `font-size` in
# the same rule, or its selector targets a known text surface
# (`::placeholder`, `.tagline`, or anything with "muted" in the selector).
# `opacity: 0` is intentionally excluded: that is the hidden half of a
# hide/reveal transition (`.error-message`, `.success-message` fade/slide-ins
# in micro-interactions.css), not a resting dim-text style, and flagging it
# would be a false positive with no fix available.
#
# Scope is `web/src/**/*.css` (every stylesheet under the web app), not just
# `web/src/styles/*.css`: one of the two real violations this guard exists to
# catch (`HelpGlossary.css`'s `::placeholder`) lives under
# `web/src/components/`, so a guard limited to `styles/*.css` would not have
# caught it and would not catch a repeat of it either.

CSS_ROOT = ROOT / "web" / "src"
# Trailing `;` is optional (the last declaration in a rule needs none before
# `}`), and the value may be a percentage (`opacity: 50%` == `opacity: 0.5`).
_OPACITY_RE = re.compile(r"opacity\s*:\s*([0-9.]+)(%)?\s*(?:!important)?\s*;?")
_COLOR_DECL_RE = re.compile(r"(?<![-\w])color\s*:")
_FONT_SIZE_DECL_RE = re.compile(r"font-size\s*:")
_SUSPECT_TEXT_SELECTOR_RE = re.compile(r"::placeholder|\.tagline|muted", re.IGNORECASE)
# `.loading` is word-boundaried (`(?![\w-])`) so it matches the exact class
# `.loading` but not an unrelated compound class like `.loading-spinner` or
# `.app-loading-screen` (a spinner widget's own opacity is not a disabled-
# control affordance question).
_SUSPECT_CONTROL_SELECTOR_RE = re.compile(r":disabled|\.is-disabled|\[disabled\]|\.loading(?![\w-])", re.IGNORECASE)
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _parse_opacity(body: str) -> float | None:
    """Return the rule's `opacity` value as a 0-1 float, or None if unset."""
    match = _OPACITY_RE.search(body)
    if not match:
        return None
    raw_value, is_percent = match.group(1), match.group(2)
    value = float(raw_value)
    return value / 100.0 if is_percent else value


def _iter_leaf_css_blocks(css: str, selector_prefix: str = "") -> list[tuple[str, str]]:
    """Yield (selector, body) for every leaf declaration block in `css`.

    Recurses into at-rule wrappers (`@media`, ...) since this repo's CSS
    nests plain rules inside media queries; only single-level nesting is
    assumed (no rule ever appears directly inside another plain rule), which
    holds for every file currently under `web/src`.
    """
    blocks: list[tuple[str, str]] = []
    i, n = 0, len(css)
    while i < n:
        brace = css.find("{", i)
        if brace == -1:
            break
        selector = css[i:brace].strip()
        depth = 1
        j = brace + 1
        while depth > 0 and j < n:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        body = css[brace + 1 : j - 1]
        if "{" in body:
            blocks.extend(_iter_leaf_css_blocks(body, f"{selector_prefix}{selector} > "))
        else:
            blocks.append((f"{selector_prefix}{selector}", body))
        i = j
    return blocks


def _find_opacity_text_violations(css_path: Path) -> list[str]:
    text = _CSS_COMMENT_RE.sub("", css_path.read_text(encoding="utf-8"))
    violations = []
    for selector, body in _iter_leaf_css_blocks(text):
        value = _parse_opacity(body)
        if value is None or not (0.0 < value < 0.8):
            continue
        looks_like_text_rule = (
            _COLOR_DECL_RE.search(body)
            or _FONT_SIZE_DECL_RE.search(body)
            or _SUSPECT_TEXT_SELECTOR_RE.search(selector)
        )
        if looks_like_text_rule:
            violations.append(f"{css_path.relative_to(ROOT)}: `{selector}` sets opacity: {value}")
    return violations


def test_no_css_rule_dims_text_via_opacity() -> None:
    css_files = sorted(CSS_ROOT.glob("**/*.css"))
    assert css_files, f"expected to find stylesheets under {CSS_ROOT}"

    violations: list[str] = []
    for css_path in css_files:
        violations.extend(_find_opacity_text_violations(css_path))

    assert not violations, (
        "opacity used to de-emphasize text (design-legibility.md bans this; "
        "use a muted color tier instead):\n" + "\n".join(violations)
    )


# --- Guard: visible controls stay at >= 0.8 resting opacity -----------------
#
# design-legibility.md: "Resting opacity on visible controls >= 0.8." This is
# a second, narrower heuristic than the text guard above: a disabled or
# loading control's rule rarely sets `color`/`font-size` itself (it inherits
# them), so the text guard's "looks like a text rule" signal doesn't fire for
# it. Instead this flags any leaf rule whose *selector* names a disabled or
# loading state (`:disabled`, `.is-disabled`, `[disabled]`, `.loading`) and
# sets `0 < opacity < 0.8`. Calibrated against every `web/src/**/*.css` file:
# these four selector substrings, combined with sub-0.8 opacity, currently
# match exactly the four sites this guard was added to catch, and nothing
# else (no keyframe, hover-fade, or hide/reveal rule uses any of them).


def _find_dim_control_violations(css_path: Path) -> list[str]:
    text = _CSS_COMMENT_RE.sub("", css_path.read_text(encoding="utf-8"))
    violations = []
    for selector, body in _iter_leaf_css_blocks(text):
        value = _parse_opacity(body)
        if value is None or not (0.0 < value < 0.8):
            continue
        if _SUSPECT_CONTROL_SELECTOR_RE.search(selector):
            violations.append(f"{css_path.relative_to(ROOT)}: `{selector}` sets opacity: {value}")
    return violations


def test_no_disabled_or_loading_control_dims_below_floor() -> None:
    css_files = sorted(CSS_ROOT.glob("**/*.css"))
    assert css_files, f"expected to find stylesheets under {CSS_ROOT}"

    violations: list[str] = []
    for css_path in css_files:
        violations.extend(_find_dim_control_violations(css_path))

    assert not violations, (
        "a disabled/loading control rests below the 0.8 opacity floor "
        "(design-legibility.md: 'Resting opacity on visible controls >= 0.8'; "
        "keep the disabled/loading affordance via cursor/border/color, not "
        "opacity alone):\n" + "\n".join(violations)
    )


# --- Guard: raw --accent never used as TEXT color --------------------------
#
# --accent is a dual-purpose token: also a BUTTON BACKGROUND paired with
# --accent-contrast (~21 sites: .btn-primary, .top-actions button, and
# component inline styles). Its dark value fails the text-contrast floor
# (3.72-4.18:1); --accent-text exists specifically so standalone text can use
# a lightness-adjusted, still-passing variant instead of raw --accent. This
# guard makes that split durable: it scans every `web/src/**/*.{css,tsx,ts}`
# file for the `color` property -- never `background*`/`border*`/`outline`/
# `fill`/`stroke`/`box-shadow`, enforced by the negative lookbehind excluding
# a preceding `-` or word character, which rules out `border-color`,
# `backgroundColor`, `borderTopColor`, etc. -- whose value contains a literal
# `var(--accent)` (not `--accent-text`/`--accent-contrast`, excluded by the
# trailing negative lookahead).
#
# The property's value is matched up to its next `,`/`;`/`}` terminator
# *allowing embedded newlines*, not just to end of line: a real violation
# this guard exists to catch (`IndexingSubtab.tsx`, a `color:` ternary
# spanning several lines) had its `var(--accent)` branch on a different line
# from the `color:` key, which a same-line-only regex would not see -- that
# is exactly how it survived the first migration pass in this task.
#
# This is a heuristic over source text, not a CSS/JS parser: it cannot see
# through indirection -- a value assigned via an intermediate variable, prop,
# or lookup table (e.g. `const accent = ...; color: accent`, or an object
# literal field consumed elsewhere as `color: card.someField`) is invisible
# to it. Those are reviewed by hand when introduced or changed; this task
# found and fixed three of them (`SystemPromptsSubtab.tsx`'s CATEGORY_COLORS
# map, `IndexDisplayPanels.tsx`'s `card.accent` field) by grepping for every
# raw `var(--accent)` occurrence and checking where each value ultimately
# lands, not by this regex alone.

_COLOR_ACCENT_RE = re.compile(r"(?<![-\w])color\s*[:=]\s*((?:(?!,|;|\}).)*)", re.DOTALL)
_ACCENT_VALUE_RE = re.compile(r"var\(--accent\)(?!-)")


def _find_accent_as_text_color(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    violations = []
    for match in _COLOR_ACCENT_RE.finditer(text):
        value = match.group(1)
        accent_match = _ACCENT_VALUE_RE.search(value)
        if accent_match:
            # Point at the actual `var(--accent)` text, not the `color:` key --
            # for a multi-line ternary those can be several lines apart.
            accent_offset = match.start(1) + accent_match.start()
            line_no = text.count("\n", 0, accent_offset) + 1
            snippet = " ".join(value.split())[:80]
            violations.append(f"{path.relative_to(ROOT)}:{line_no}: color: {snippet}")
    return violations


def test_no_raw_accent_used_as_text_color() -> None:
    source_files = sorted(
        p for pattern in ("**/*.css", "**/*.tsx", "**/*.ts") for p in CSS_ROOT.glob(pattern)
    )
    assert source_files, f"expected to find stylesheets/components under {CSS_ROOT}"

    violations: list[str] = []
    for path in source_files:
        violations.extend(_find_accent_as_text_color(path))

    assert not violations, (
        "raw --accent used as a `color` (text) value -- it is also a button "
        "background paired with --accent-contrast, and its dark value fails "
        "the text-contrast floor on its own; use --accent-text for text "
        "instead:\n" + "\n".join(violations)
    )
