import bisect
from typing import Any

from server.models.index import Chunk
from server.indexing.tokenizer import TextTokenizer
from server.models.tribrid_config_model import ChunkingConfig, TokenizationConfig


class Chunker:
    def __init__(self, config: ChunkingConfig, tokenization: TokenizationConfig | None = None):
        self.config = config
        self.tokenization = tokenization or TokenizationConfig()
        self._tokenizer = TextTokenizer(self.tokenization)

    def chunk_file(self, file_path: str, content: str) -> list[Chunk]:
        return self.chunk_text(file_path, content, base_char_offset=0, base_line=1, starting_ordinal=0)

    def chunk_ast(self, file_path: str, content: str, language: str) -> list[Chunk]:
        return self.chunk_file(file_path, content)

    def chunk_text(
        self,
        file_path: str,
        content: str,
        *,
        base_char_offset: int,
        base_line: int,
        starting_ordinal: int,
    ) -> list[Chunk]:
        strategy = self._normalize_strategy(self.config.chunking_strategy)
        language = self._detect_language(file_path)
        parent_doc_id = file_path if bool(self.config.emit_parent_doc_id) else None
        nl_positions = [i for i, ch in enumerate(content) if ch == "\n"]

        if strategy == "fixed_tokens":
            spans = self._spans_fixed_tokens(content)
        elif strategy == "recursive":
            spans = self._spans_recursive(content)
        elif strategy == "markdown":
            spans = self._spans_markdown(content)
        elif strategy == "sentence":
            spans = self._spans_sentence(content)
        elif strategy == "qa_blocks":
            spans = self._spans_qa_blocks(content)
        else:
            spans = self._spans_fixed_chars(content)

        min_chars = int(self.config.min_chunk_chars)
        allow_small_singleton = len(spans) == 1 and bool((content or "").strip())

        chunks: list[Chunk] = []
        ordinal = int(starting_ordinal)
        for start_char, end_char in spans:
            if end_char <= start_char:
                continue
            text = content[start_char:end_char]
            if len(text) < min_chars and not allow_small_singleton:
                continue
            abs_start = int(base_char_offset) + int(start_char)
            start_line, end_line = self._line_span(nl_positions, start_char, end_char, base_line=int(base_line))
            token_count = self._tokenizer.count_tokens(text)

            meta: dict[str, Any] = {}
            meta["char_start"] = abs_start
            meta["char_end"] = int(base_char_offset) + int(end_char)
            if bool(self.config.emit_chunk_ordinal):
                meta["chunk_ordinal"] = ordinal
            if parent_doc_id is not None:
                meta["parent_doc_id"] = parent_doc_id

            chunks.append(
                Chunk(
                    chunk_id=f"{file_path}:{start_line}-{end_line}:{abs_start}",
                    content=text,
                    file_path=file_path,
                    start_line=int(start_line),
                    end_line=int(end_line),
                    language=language,
                    token_count=int(token_count),
                    metadata=meta,
                )
            )
            ordinal += 1

        # Hard safety: recursively split any over-limit chunk spans by tokens.
        max_tokens = int(self.config.max_chunk_tokens)
        if max_tokens > 0 and chunks:
            out: list[Chunk] = []
            for ch in chunks:
                if int(ch.token_count or 0) <= max_tokens:
                    out.append(ch)
                    continue
                out.extend(
                    self._split_chunk_by_tokens(
                        ch,
                        max_tokens=max_tokens,
                        language=language,
                        parent_doc_id=parent_doc_id,
                    )
                )
            return out

        return chunks

    @staticmethod
    def _detect_language(file_path: str) -> str | None:
        if file_path.endswith(".py"):
            return "python"
        if file_path.endswith(".ts") or file_path.endswith(".tsx"):
            return "typescript"
        if file_path.endswith(".js") or file_path.endswith(".jsx"):
            return "javascript"
        return None

    @staticmethod
    def _normalize_strategy(value: str | None) -> str:
        v = str(value or "fixed_chars").strip().lower()
        if v == "greedy":
            return "fixed_chars"
        if v in {"ast", "hybrid", "semantic"}:
            return "fixed_chars"
        return v

    @staticmethod
    def _line_span(nl_positions: list[int], start: int, end: int, *, base_line: int) -> tuple[int, int]:
        start = int(start)
        end = int(end)
        base_line = int(base_line)
        start_line = base_line + bisect.bisect_left(nl_positions, start)
        # end_line is inclusive; count newlines strictly before end
        end_line = base_line + bisect.bisect_left(nl_positions, max(start, end))
        if end_line < start_line:
            end_line = start_line
        return (int(start_line), int(end_line))

    def _spans_fixed_chars(self, content: str) -> list[tuple[int, int]]:
        # Chunk by characters with overlap.
        size = max(100, int(self.config.chunk_size))
        overlap = max(0, int(self.config.chunk_overlap))
        if overlap >= size:
            overlap = max(0, size // 5)
        start = 0
        n = len(content)
        spans: list[tuple[int, int]] = []
        while start < n:
            end = min(n, start + size)
            spans.append((int(start), int(end)))

            if end == n:
                break
            start = max(0, end - overlap)
        return spans

    def _spans_fixed_tokens(self, content: str) -> list[tuple[int, int]]:
        r = self._tokenizer.tokenize_with_offsets(content)
        max_hard = int(self.tokenization.max_tokens_per_chunk_hard)
        target = int(min(int(self.config.target_tokens), max_hard))
        overlap = int(min(int(self.config.overlap_tokens), max(0, target - 1)))

        n = len(r.token_starts)
        if n == 0:
            return [(0, len(content))] if content.strip() else []

        spans: list[tuple[int, int]] = []
        start_tok = 0
        while start_tok < n:
            end_tok = min(n, start_tok + target)
            start_char = int(r.token_starts[start_tok])
            end_char = int(r.token_starts[end_tok]) if end_tok < n else len(r.text)
            spans.append((start_char, end_char))
            if end_tok >= n:
                break
            start_tok = max(0, end_tok - overlap)
        return spans

    def _split_span_by_separator(
        self,
        content: str,
        start: int,
        end: int,
        sep: str,
        keep: str,
    ) -> list[tuple[int, int]]:
        if sep == "":
            # Fallback to token windows for hard splits.
            tmp = content[start:end]
            return [(start + s, start + e) for s, e in self._spans_fixed_tokens(tmp)]

        if keep == "prefix":
            # Keep separators at the beginning of the *next* span.
            # Special-case to ensure forward progress when the separator occurs at the current start
            # (including leading/consecutive separators).
            spans: list[tuple[int, int]] = []
            i = int(start)
            e = int(end)
            j = content.find(sep, i, e)
            if j < 0:
                return [(i, e)] if e > i else []

            cuts: list[int] = [i]
            while j >= 0:
                cuts.append(int(j))
                nxt = int(j) + len(sep)
                # Defensive: avoid infinite loops even for unexpected zero-length separators.
                if nxt <= j:
                    nxt = int(j) + 1
                j = content.find(sep, nxt, e)
            cuts.append(e)

            for a, b in zip(cuts, cuts[1:], strict=False):
                if b > a:
                    spans.append((int(a), int(b)))
            return spans

        result_spans: list[tuple[int, int]] = []
        i = int(start)
        while True:
            j = content.find(sep, i, end)
            if j < 0:
                break
            if keep == "suffix":
                cut = j + len(sep)
                result_spans.append((i, cut))
                i = cut
            else:
                result_spans.append((i, j))
                i = j + len(sep)
        if i < end:
            result_spans.append((i, int(end)))
        return [(s, e) for s, e in result_spans if e > s]

    def _spans_recursive(self, content: str) -> list[tuple[int, int]]:
        seps = list(self.config.separators or ["\n\n", "\n", ". ", " ", ""])
        keep = str(self.config.separator_keep or "suffix").strip().lower()
        max_depth = int(self.config.recursive_max_depth)
        target = int(self.config.target_tokens)

        def rec(start: int, end: int, depth: int) -> list[tuple[int, int]]:
            if end <= start:
                return []
            txt = content[start:end]
            if depth >= max_depth:
                return [(start, end)]
            if self._tokenizer.count_tokens(txt) <= target:
                return [(start, end)]
            sep = seps[min(depth, len(seps) - 1)]
            pieces = self._split_span_by_separator(content, start, end, sep, keep)
            out: list[tuple[int, int]] = []
            for s, e in pieces:
                out.extend(rec(s, e, depth + 1))
            return out

        atomic = rec(0, len(content), 0)

        packed: list[tuple[int, int]] = []
        cur_s: int | None = None
        cur_e: int | None = None
        cur_tok = 0
        for s, e in atomic:
            part = content[s:e]
            part_tok = self._tokenizer.count_tokens(part)
            if cur_s is None:
                cur_s, cur_e, cur_tok = int(s), int(e), int(part_tok)
                continue
            if cur_tok + int(part_tok) <= target:
                cur_e = int(e)
                cur_tok += int(part_tok)
                continue
            packed.append((int(cur_s), int(cur_e or cur_s)))
            cur_s, cur_e, cur_tok = int(s), int(e), int(part_tok)
        if cur_s is not None:
            packed.append((int(cur_s), int(cur_e or cur_s)))
        return packed

    def _spans_markdown(self, content: str) -> list[tuple[int, int]]:
        import re

        max_level = int(self.config.markdown_max_heading_level)
        rx = re.compile(rf"^(#{{1,{max_level}}})\s+.+$", re.MULTILINE)
        hits = [m.start() for m in rx.finditer(content)]
        if not hits:
            return self._spans_recursive(content)
        cuts = sorted(set([0, *hits, len(content)]))
        spans: list[tuple[int, int]] = []
        for a, b in zip(cuts, cuts[1:], strict=False):
            if b <= a:
                continue
            for s, e in self._spans_recursive(content[a:b]):
                spans.append((int(a) + int(s), int(a) + int(e)))
        return [(s, e) for s, e in spans if e > s]

    def _spans_sentence(self, content: str) -> list[tuple[int, int]]:
        import re

        rx = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"\'(])')
        parts: list[tuple[int, int]] = []
        start = 0
        for m in rx.finditer(content):
            end = m.start()
            if end > start:
                parts.append((start, end))
            start = m.end()
        if start < len(content):
            parts.append((start, len(content)))

        target = int(self.config.target_tokens)
        spans: list[tuple[int, int]] = []
        cur_s: int | None = None
        cur_e: int | None = None
        cur_tok = 0
        for s, e in parts:
            part = content[s:e]
            part_tok = self._tokenizer.count_tokens(part)
            if cur_s is None:
                cur_s, cur_e, cur_tok = int(s), int(e), int(part_tok)
                continue
            if cur_tok + int(part_tok) <= target:
                cur_e = int(e)
                cur_tok += int(part_tok)
                continue
            spans.append((int(cur_s), int(cur_e or cur_s)))
            cur_s, cur_e, cur_tok = int(s), int(e), int(part_tok)
        if cur_s is not None:
            spans.append((int(cur_s), int(cur_e or cur_s)))
        return spans

    def _spans_qa_blocks(self, content: str) -> list[tuple[int, int]]:
        import re

        rx = re.compile(r"^(?:Q:|A:)", re.MULTILINE)
        hits = [m.start() for m in rx.finditer(content)]
        if not hits:
            return self._spans_sentence(content)
        cuts = sorted(set([0, *hits, len(content)]))
        parts = [(a, b) for a, b in zip(cuts, cuts[1:], strict=False) if b > a]
        target = int(self.config.target_tokens)

        spans: list[tuple[int, int]] = []
        cur_s: int | None = None
        cur_e: int | None = None
        cur_tok = 0
        for s, e in parts:
            part = content[s:e]
            part_tok = self._tokenizer.count_tokens(part)
            if cur_s is None:
                cur_s, cur_e, cur_tok = int(s), int(e), int(part_tok)
                continue
            if cur_tok + int(part_tok) <= target:
                cur_e = int(e)
                cur_tok += int(part_tok)
                continue
            spans.append((int(cur_s), int(cur_e or cur_s)))
            cur_s, cur_e, cur_tok = int(s), int(e), int(part_tok)
        if cur_s is not None:
            spans.append((int(cur_s), int(cur_e or cur_s)))
        return spans

    def _split_chunk_by_tokens(
        self,
        chunk: Chunk,
        *,
        max_tokens: int,
        language: str | None,
        parent_doc_id: str | None,
    ) -> list[Chunk]:
        text = chunk.content or ""
        r = self._tokenizer.tokenize_with_offsets(text)
        n = len(r.token_starts)
        if n <= max_tokens:
            return [chunk]

        spans: list[tuple[int, int]] = []
        start_tok = 0
        while start_tok < n:
            end_tok = min(n, start_tok + max_tokens)
            start_char = int(r.token_starts[start_tok])
            end_char = int(r.token_starts[end_tok]) if end_tok < n else len(r.text)
            spans.append((start_char, end_char))
            start_tok = end_tok

        base_char = int((chunk.metadata or {}).get("char_start") or 0)
        base_line = int(chunk.start_line or 1)
        nl_positions = [i for i, ch in enumerate(text) if ch == "\n"]

        out: list[Chunk] = []
        ordinal = int((chunk.metadata or {}).get("chunk_ordinal") or 0)
        for s, e in spans:
            sub = text[s:e]
            if len(sub) < int(self.config.min_chunk_chars):
                continue
            abs_start = base_char + int(s)
            start_line, end_line = self._line_span(nl_positions, s, e, base_line=base_line)
            tok_count = self._tokenizer.count_tokens(sub)
            meta = dict(chunk.metadata or {})
            meta["char_start"] = abs_start
            meta["char_end"] = base_char + int(e)
            if bool(self.config.emit_chunk_ordinal):
                meta["chunk_ordinal"] = ordinal
            if parent_doc_id is not None:
                meta["parent_doc_id"] = parent_doc_id
            out.append(
                Chunk(
                    chunk_id=f"{chunk.file_path}:{start_line}-{end_line}:{abs_start}",
                    content=sub,
                    file_path=chunk.file_path,
                    start_line=int(start_line),
                    end_line=int(end_line),
                    language=language,
                    token_count=int(tok_count),
                    metadata=meta,
                )
            )
            ordinal += 1
        return out
