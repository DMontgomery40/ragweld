"""Expected-path matching shared by eval scoring, ML-quality summaries and triplet mining.

An eval dataset labels relevance by file path (relative or absolute) and the
retrieval lane returns corpus-relative paths. A label matches a retrieved path
when the two are the same normalized path or one is a whole path-segment suffix
of the other: `row_001162.txt` labels `emails/row_001162.txt`, an absolute label
matches its corpus-relative form. Partial names never match (`mail.txt` is not
`blackmail.txt`), so eval hits and mined negatives cannot be produced by
substring accidents.
"""

from __future__ import annotations


def normalize_path(value: str) -> str:
    text = (value or "").replace("\\", "/").strip().lower()
    while text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def _is_segment_suffix(longer: str, shorter: str) -> bool:
    return len(longer) > len(shorter) and longer.endswith("/" + shorter)


def path_matches(expected: str, actual: str) -> bool:
    left = normalize_path(expected)
    right = normalize_path(actual)
    if not left or not right:
        return False
    return right == left or _is_segment_suffix(right, left) or _is_segment_suffix(left, right)


def matches_any(expected_paths: list[str], actual: str) -> bool:
    return any(path_matches(expected, actual) for expected in expected_paths)
