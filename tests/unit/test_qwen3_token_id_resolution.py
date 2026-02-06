"""Tests for MLX Qwen3 yes/no token ID resolution.

Skips when MLX or the tokenizer are unavailable.
"""

from __future__ import annotations

import pytest

from server.retrieval.mlx_qwen3 import mlx_is_available


pytestmark = pytest.mark.skipif(
    not mlx_is_available(),
    reason="MLX deps not installed — skipping Qwen3 token ID tests",
)


def _load_tokenizer() -> object:
    """Load the base tokenizer for resolve_yes_no_token_ids testing."""
    try:
        from mlx_lm import load as mlx_lm_load  # type: ignore[import-untyped]

        _model, tokenizer = mlx_lm_load("Qwen/Qwen3-Reranker-0.6B")
        return tokenizer
    except Exception as exc:
        pytest.skip(f"Failed to load Qwen3-Reranker-0.6B tokenizer: {exc}")
        raise  # unreachable but keeps type-checkers happy


def test_resolve_yes_no_returns_distinct_non_special_ids() -> None:
    from server.retrieval.mlx_qwen3 import resolve_yes_no_token_ids

    tokenizer = _load_tokenizer()
    result = resolve_yes_no_token_ids(tokenizer)

    assert isinstance(result.yes_id, int)
    assert isinstance(result.no_id, int)
    assert result.yes_id != result.no_id
    assert result.yes_id >= 0
    assert result.no_id >= 0
    assert isinstance(result.suffix_hash, str)
    assert len(result.suffix_hash) > 0


def test_resolve_yes_no_is_deterministic() -> None:
    from server.retrieval.mlx_qwen3 import resolve_yes_no_token_ids

    tokenizer = _load_tokenizer()
    a = resolve_yes_no_token_ids(tokenizer)
    b = resolve_yes_no_token_ids(tokenizer)

    assert a.yes_id == b.yes_id
    assert a.no_id == b.no_id
    assert a.suffix_hash == b.suffix_hash


def test_resolve_yes_no_rejects_broken_tokenizer() -> None:
    """A tokenizer that encodes everything to empty should raise ValueError."""
    from server.retrieval.mlx_qwen3 import resolve_yes_no_token_ids

    class _BrokenTokenizer:
        all_special_ids: list[int] = []

        def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:  # noqa: ARG002
            return []

    with pytest.raises(ValueError, match="empty"):
        resolve_yes_no_token_ids(_BrokenTokenizer())


def test_resolve_yes_no_rejects_same_id_tokenizer() -> None:
    """A tokenizer that maps both yes and no to the same token should raise ValueError."""
    from server.retrieval.mlx_qwen3 import resolve_yes_no_token_ids

    class _SameIdTokenizer:
        all_special_ids: list[int] = []

        def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:  # noqa: ARG002
            return [42]

    with pytest.raises(ValueError, match="yes_id == no_id"):
        resolve_yes_no_token_ids(_SameIdTokenizer())
