from __future__ import annotations

import pytest

from server.indexing.tokenizer import TextTokenizer
from server.models.tribrid_config_model import TokenizationConfig


def test_truncate_end_preserves_prefix_tokens() -> None:
    tok = TextTokenizer(TokenizationConfig(strategy="whitespace", normalize_unicode=False, lowercase=False))
    text = "a b c d e f g"
    out = tok.truncate_by_tokens(text, 3, mode="truncate_end")
    assert out.split()[:3] == ["a", "b", "c"]
    assert len(out.split()) <= 3


def test_truncate_middle_inserts_ellipsis() -> None:
    tok = TextTokenizer(TokenizationConfig(strategy="whitespace", normalize_unicode=False, lowercase=False))
    text = "a b c d e f g h i j"
    out = tok.truncate_by_tokens(text, 4, mode="truncate_middle")
    assert "…" in out
    assert len(out.split()) <= 4


def test_truncate_error_raises() -> None:
    tok = TextTokenizer(TokenizationConfig(strategy="whitespace", normalize_unicode=False, lowercase=False))
    with pytest.raises(ValueError):
        tok.truncate_by_tokens("a b c d e", 3, mode="error")


def test_tiktoken_unknown_encoding_falls_back() -> None:
    tok = TextTokenizer(TokenizationConfig(strategy="tiktoken", tiktoken_encoding="__does_not_exist__"))
    assert tok.count_tokens("hello world") > 0

