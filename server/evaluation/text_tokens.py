"""Unicode-aware text normalization shared by the real-query guard, answer anchoring and leak checks.

Tokens are NFKC-normalized, case-folded runs of letters/digits in any script
(`[^\\W_]+`), so Cyrillic, CJK and Latin text all produce tokens. Scripts without
whitespace word boundaries (CJK) are additionally matched by normalized substring
containment, because a CJK answer is rarely a standalone token in running text.
"""

from __future__ import annotations

import re
import unicodedata

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]")
_WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    folded = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return _WS_RE.sub(" ", folded).strip()


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_text(text))


def has_cjk(text: str) -> bool:
    return _CJK_RE.search(str(text or "")) is not None


def phrase_in(needle: str, haystack: str) -> bool:
    """Whole-token contiguous phrase containment; CJK needles also match as normalized substrings."""
    needle_tokens = tokens(needle)
    if not needle_tokens:
        return False
    haystack_tokens = tokens(haystack)
    width = len(needle_tokens)
    if any(haystack_tokens[i : i + width] == needle_tokens for i in range(0, len(haystack_tokens) - width + 1)):
        return True
    if has_cjk(needle):
        return normalize_text(needle) in normalize_text(haystack)
    return False
