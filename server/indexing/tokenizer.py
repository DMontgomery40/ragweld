from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from server.models.tribrid_config_model import TokenizationConfig


@dataclass(frozen=True)
class TokenizationResult:
    """Tokenization result with stable token start offsets into the (normalized) text."""

    text: str
    token_starts: list[int]
    token_ids: list[int] | None = None


class TextTokenizer:
    """Tokenization helper for chunking/budgeting (LAW-driven by TokenizationConfig)."""

    def __init__(self, config: TokenizationConfig):
        self.config = config

    def normalize(self, text: str) -> str:
        t = text or ""
        if self.config.normalize_unicode:
            # Preserve stable char offsets: if normalization would change string length,
            # skip it (offset mappings must remain valid indices into the original text).
            normed = unicodedata.normalize("NFKC", t)
            if len(normed) == len(t):
                t = normed
        if self.config.lowercase:
            # Lowercasing can change length in some locales (e.g., dotted I). Skip if it would.
            lowered = t.lower()
            if len(lowered) == len(t):
                t = lowered
        return t

    def _normalize_length_preserving(self, text: str) -> str:
        """Apply configured normalization only when it preserves string length.

        Chunking relies on token start offsets being valid indices into the original text.
        Some Unicode normalization/case transforms can change string length (e.g. ligatures,
        dotted-I lowercasing), which would corrupt offsets if applied blindly.
        """
        out = text or ""
        if self.config.normalize_unicode:
            try:
                norm = unicodedata.normalize("NFKC", out)
                if len(norm) == len(out):
                    out = norm
            except Exception:
                pass
        if self.config.lowercase:
            try:
                lowered = out.lower()
                if len(lowered) == len(out):
                    out = lowered
            except Exception:
                pass
        return out

    def estimate_token_count(self, text: str) -> int:
        # Fast heuristic: 4 chars/token is a common rough estimate for English-ish text.
        t = self.normalize(text)
        return max(0, int(math.ceil(len(t) / 4.0)))

    def count_tokens(self, text: str) -> int:
        if self.config.estimate_only:
            return self.estimate_token_count(text)
        res = self.tokenize_with_offsets(text)
        return len(res.token_starts)

    def tokenize_with_offsets(self, text: str) -> TokenizationResult:
        # NOTE: Offsets must remain valid indices into the original `text` used by chunking.
        # Use only length-preserving normalization here.
        t = self._normalize_length_preserving(text)
        if self.config.estimate_only:
            # Best-effort: produce pseudo-token offsets every ~4 chars.
            starts = list(range(0, len(t), 4))
            return TokenizationResult(text=t, token_starts=starts, token_ids=None)

        strat = str(self.config.strategy or "tiktoken").strip().lower()
        if strat == "whitespace":
            return self._tokenize_whitespace(t)
        if strat == "huggingface":
            return self._tokenize_hf(t, self.config.hf_tokenizer_name)
        # default: tiktoken
        return self._tokenize_tiktoken(t, self.config.tiktoken_encoding)

    def truncate_by_tokens(self, text: str, max_tokens: int, *, mode: str) -> str:
        max_tokens = int(max_tokens)
        if max_tokens <= 0:
            return ""
        # Truncation is used for embedding inputs; here we intentionally apply full
        # normalization (even if it changes length) for stability.
        t = self.normalize(text)
        if self.config.estimate_only:
            # Approximate truncation by chars.
            approx_chars = int(max_tokens * 4)
            if len(t) <= approx_chars:
                return t
            if mode == "truncate_middle":
                half = max(1, approx_chars // 2)
                return (t[:half] + "…" + t[-half:]).strip()
            return t[:approx_chars]

        strat = str(self.config.strategy or "tiktoken").strip().lower()
        if strat == "whitespace":
            r = self._tokenize_whitespace(t)
        elif strat == "huggingface":
            r = self._tokenize_hf(t, self.config.hf_tokenizer_name)
        else:
            r = self._tokenize_tiktoken(t, self.config.tiktoken_encoding)
        n = len(r.token_starts)
        if n <= max_tokens:
            return t

        mode = str(mode or "truncate_end").strip().lower()
        if mode == "error":
            raise ValueError(f"text exceeds max tokens ({n} > {max_tokens})")
        if mode == "truncate_middle":
            head = max_tokens // 2
            tail = max_tokens - head
            head_end = r.token_starts[head] if head < n else len(t)
            tail_start_tok = max(0, n - tail)
            tail_start = r.token_starts[tail_start_tok] if tail_start_tok < n else len(t)
            return (t[:head_end] + "…" + t[tail_start:]).strip()

        # truncate_end (default)
        end_char = r.token_starts[max_tokens] if max_tokens < n else len(t)
        return t[:end_char]

    # ---------------------------------------------------------------------
    # Strategy implementations
    # ---------------------------------------------------------------------

    @staticmethod
    def _tokenize_whitespace(text: str) -> TokenizationResult:
        starts: list[int] = []
        in_tok = False
        for i, ch in enumerate(text):
            if ch.isspace():
                in_tok = False
                continue
            if not in_tok:
                starts.append(i)
                in_tok = True
        return TokenizationResult(text=text, token_starts=starts, token_ids=None)

    @staticmethod
    @lru_cache(maxsize=16)
    def _get_tiktoken_encoding(name: str) -> Any:
        import tiktoken

        try:
            return tiktoken.get_encoding(name)
        except Exception:
            return tiktoken.get_encoding("o200k_base")

    @classmethod
    def _tokenize_tiktoken(cls, text: str, encoding_name: str) -> TokenizationResult:
        enc = cls._get_tiktoken_encoding(str(encoding_name or "o200k_base"))
        token_ids = enc.encode(text)
        _decoded, offsets = enc.decode_with_offsets(token_ids)
        # offsets are token start indices in the original string
        return TokenizationResult(text=text, token_starts=[int(x) for x in offsets], token_ids=token_ids)

    @staticmethod
    @lru_cache(maxsize=16)
    def _get_hf_tokenizer(name: str) -> Any:
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(name, use_fast=True)  # type: ignore[no-untyped-call]

    @classmethod
    def _tokenize_hf(cls, text: str, tokenizer_name: str) -> TokenizationResult:
        tok = cls._get_hf_tokenizer(str(tokenizer_name or "gpt2"))
        out = tok(
            text,
            return_offsets_mapping=True,
            add_special_tokens=False,
            truncation=False,
        )
        offsets = out.get("offset_mapping") or []
        # offset_mapping is list[(start,end)]
        starts = [int(s) for s, _e in offsets]
        token_ids = [int(x) for x in (out.get("input_ids") or [])]
        return TokenizationResult(text=text, token_starts=starts, token_ids=token_ids)
