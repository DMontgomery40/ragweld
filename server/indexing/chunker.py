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
        # Compatibility: allow callers to explicitly request AST-aware chunking
        # regardless of the current config.
        strategy = str(self.config.chunking_strategy or "").strip().lower()
        if strategy not in {"ast", "hybrid"}:
            cfg = self.config.model_copy(update={"chunking_strategy": "ast"})
            return Chunker(cfg, self.tokenization).chunk_file(file_path, content)
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

        spans: list[tuple[int, int]]
        if strategy in {"ast", "hybrid"}:
            spans = self._spans_code_aware(content, language=language, strategy=strategy)
            if not spans:
                # Fallback behavior:
                # - ast: preserve legacy behavior for non-code/parse failures (fixed_chars)
                # - hybrid: prefer token windows when AST/braces cannot be used
                spans = self._spans_fixed_tokens(content) if strategy == "hybrid" else self._spans_fixed_chars(content)
        elif strategy == "fixed_tokens":
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
        return v

    @staticmethod
    def _line_starts(text: str) -> list[int]:
        starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                starts.append(i + 1)
        return starts

    def _pack_units_by_tokens(
        self,
        content: str,
        units: list[tuple[int, int]],
        *,
        target_tokens: int,
    ) -> list[tuple[int, int]]:
        target_tokens = int(target_tokens)
        if target_tokens <= 0:
            target_tokens = 512
        packed: list[tuple[int, int]] = []
        cur_s: int | None = None
        cur_e: int | None = None
        cur_tok = 0
        for s, e in units:
            if e <= s:
                continue
            part = content[s:e]
            part_tok = self._tokenizer.count_tokens(part)
            if cur_s is None:
                cur_s, cur_e, cur_tok = int(s), int(e), int(part_tok)
                continue
            if cur_tok + int(part_tok) <= target_tokens:
                cur_e = int(e)
                cur_tok += int(part_tok)
                continue
            packed.append((int(cur_s), int(cur_e or cur_s)))
            cur_s, cur_e, cur_tok = int(s), int(e), int(part_tok)
        if cur_s is not None:
            packed.append((int(cur_s), int(cur_e or cur_s)))
        return [(s, e) for s, e in packed if e > s]

    def _spans_code_aware(self, content: str, *, language: str | None, strategy: str) -> list[tuple[int, int]]:
        lang = str(language or "").strip().lower()
        if lang == "python":
            spans = self._spans_python_ast(content)
            if spans:
                return spans
            # For hybrid, allow fallback; for ast we'll let caller decide.
            return []
        if lang in {"typescript", "javascript"}:
            spans = self._spans_top_level_brace_units(content)
            if spans:
                return spans
            return []
        return []

    def _spans_python_ast(self, content: str) -> list[tuple[int, int]]:
        import ast

        text = content or ""
        if not text.strip():
            return []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []

        line_starts = self._line_starts(text)
        n_lines = max(1, len(line_starts))

        def _line_to_char(line_no: int) -> int:
            ln = max(1, min(int(line_no), n_lines))
            return int(line_starts[ln - 1])

        def _end_line_to_char(line_no: int) -> int:
            ln = max(1, min(int(line_no), n_lines))
            if ln >= n_lines:
                return len(text)
            return int(line_starts[ln])

        def _char_to_line(char_idx: int) -> int:
            # line_starts is sorted; bisect_right returns 1-based line number.
            return max(1, min(n_lines, bisect.bisect_right(line_starts, int(char_idx))))

        preserve_imports = bool(int(getattr(self.config, "preserve_imports", 1) or 0) == 1)
        overlap = int(getattr(self.config, "ast_overlap_lines", 0) or 0)
        target_tokens = int(getattr(self.config, "target_tokens", 512) or 512)

        nodes: list[ast.stmt] = list(getattr(tree, "body", []) or [])
        boundaries: list[int] = []
        for node in nodes:
            if not preserve_imports and isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            start_line = int(getattr(node, "lineno", 1) or 1)
            end_line = int(getattr(node, "end_lineno", start_line) or start_line)
            start_line = max(1, min(start_line, n_lines))
            end_line = max(start_line, min(end_line, n_lines))
            boundaries.append(_end_line_to_char(end_line))

        # If AST body has no boundaries (e.g., comments-only file), fall back.
        if not boundaries:
            return []

        # Build contiguous units that cover the whole file while only allowing chunk
        # boundaries at statement ends (so we don't split inside blocks).
        boundaries = sorted(set(int(x) for x in boundaries if int(x) > 0))
        units: list[tuple[int, int]] = []
        prev = 0
        for end in boundaries:
            end = max(prev, min(len(text), int(end)))
            if end == prev:
                continue
            units.append((int(prev), int(end)))
            prev = int(end)
        if prev < len(text):
            units.append((int(prev), int(len(text))))

        packed = self._pack_units_by_tokens(text, units, target_tokens=target_tokens)
        if overlap <= 0:
            return packed

        # Expand packed spans by overlap lines for context, without changing offsets lengthwise.
        expanded: list[tuple[int, int]] = []
        for s, e in packed:
            if e <= s:
                continue
            s_line = _char_to_line(s)
            e_line = _char_to_line(max(0, e - 1))
            s2 = _line_to_char(max(1, s_line - overlap))
            e2 = _end_line_to_char(min(n_lines, e_line + overlap))
            expanded.append((int(s2), int(e2)))
        return [(s, e) for s, e in expanded if e > s]

    def _spans_top_level_brace_units(self, content: str) -> list[tuple[int, int]]:
        text = content or ""
        if not text.strip():
            return []

        target_tokens = int(getattr(self.config, "target_tokens", 512) or 512)

        blocks: list[tuple[int, int]] = []
        depth = 0
        block_start: int | None = None
        line_start = 0

        in_sq = False
        in_dq = False
        in_bt = False
        in_lc = False
        in_bc = False
        esc = False

        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            nxt = text[i + 1] if i + 1 < n else ""

            if in_lc:
                if ch == "\n":
                    in_lc = False
                    line_start = i + 1
                i += 1
                continue

            if in_bc:
                if ch == "*" and nxt == "/":
                    in_bc = False
                    i += 2
                    continue
                if ch == "\n":
                    line_start = i + 1
                i += 1
                continue

            if in_sq:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == "'":
                    in_sq = False
                if ch == "\n":
                    line_start = i + 1
                i += 1
                continue

            if in_dq:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_dq = False
                if ch == "\n":
                    line_start = i + 1
                i += 1
                continue

            if in_bt:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == "`":
                    in_bt = False
                if ch == "\n":
                    line_start = i + 1
                i += 1
                continue

            # Not in string/comment
            if ch == "/" and nxt == "/":
                in_lc = True
                i += 2
                continue
            if ch == "/" and nxt == "*":
                in_bc = True
                i += 2
                continue
            if ch == "'":
                in_sq = True
                i += 1
                continue
            if ch == '"':
                in_dq = True
                i += 1
                continue
            if ch == "`":
                in_bt = True
                i += 1
                continue

            if ch == "\n":
                line_start = i + 1
                i += 1
                continue

            if ch == "{":
                if depth == 0:
                    block_start = int(line_start)
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and block_start is not None:
                        end = i + 1
                        # Extend to end of line for stability.
                        nl = text.find("\n", end)
                        if nl >= 0:
                            end = nl + 1
                        blocks.append((int(block_start), int(end)))
                        block_start = None

            i += 1

        if not blocks:
            return []

        # Build contiguous units covering the whole file so we don't drop top-level statements.
        units: list[tuple[int, int]] = []
        prev = 0
        for s, e in blocks:
            s = max(0, int(s))
            e = max(s, int(e))
            if s > prev:
                units.append((int(prev), int(s)))
            units.append((int(s), int(e)))
            prev = int(e)
        if prev < n:
            units.append((int(prev), int(n)))

        packed = self._pack_units_by_tokens(text, units, target_tokens=target_tokens)
        return packed

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
