"""Real-query guard for eval and training signal.

Every query/answer pair is reranker training data, so placeholder inputs
(`test`, `hello`, lorem ipsum, one-word fragments) must never enter an eval
dataset or a mined triplet. The guard is deterministic and shared by the
mining boundaries; it rejects the banned tokens from `.claude/rules/testing.md`
and content-free strings.
"""

from __future__ import annotations

from server.evaluation.text_tokens import has_cjk, tokens

BANNED_QUERIES = frozenset(
    {
        "test",
        "testing",
        "tests",
        "hello",
        "hi",
        "hey",
        "foo",
        "bar",
        "baz",
        "ping",
        "asdf",
        "qwerty",
        "lorem ipsum",
        "placeholder",
        "sample",
        "example",
        "query",
        "question",
    }
)
MIN_WORDS = 2
MIN_CHARS = 8
# A banned token inside a short query ("Please run this test?", "hello there") is a
# placeholder; inside a long domain question ("Which calibration test does the
# Aurora salinity array run after a sensor swap?") it is ordinary vocabulary.
SHORT_QUERY_WORDS = 4


def placeholder_reason(query: str) -> str | None:
    """Return why the query is not a real domain question, or None when it is acceptable."""
    text = " ".join(str(query or "").split()).strip()
    lowered = text.lower().rstrip("?.!")
    if not text:
        return "empty"
    if lowered in BANNED_QUERIES or lowered.startswith("lorem ipsum"):
        return "banned_placeholder"
    words = tokens(lowered)
    # CJK has no whitespace word boundaries: count characters as words there.
    word_count = max(len(words), sum(1 for ch in text if has_cjk(ch))) if has_cjk(text) else len(words)
    if word_count < MIN_WORDS:
        return "too_few_words"
    if len(text) < MIN_CHARS and not any(len(w) >= 2 for w in words if not w.isascii()):
        return "too_short"
    if len(words) <= SHORT_QUERY_WORDS and any(word in BANNED_QUERIES for word in words):
        return "banned_placeholder"
    if all(word in BANNED_QUERIES or word.isdigit() for word in words):
        return "banned_placeholder"
    return None


def is_real_query(query: str) -> bool:
    return placeholder_reason(query) is None
