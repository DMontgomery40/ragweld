"""Tests for the chunker module."""

import signal

import pytest

from server.indexing.chunker import Chunker
from server.indexing.tokenizer import TextTokenizer
from server.models.tribrid_config_model import ChunkingConfig, TokenizationConfig


@pytest.fixture
def chunker() -> Chunker:
    """Create chunker with test config."""
    # Use LAW's ChunkingConfig with its field names
    # LAW has min chunk_size=200, max overlap must be < chunk_size
    config = ChunkingConfig(
        chunking_strategy="fixed_chars",  # keep tests independent of AST/semantic impls
        chunk_size=500,  # LAW minimum is 200
        chunk_overlap=100,  # Must be < chunk_size
        min_chunk_chars=50,  # LAW min is 10, max is 500
    )
    tokenization = TokenizationConfig(strategy="whitespace")
    return Chunker(config, tokenization)


def test_chunker_init(chunker: Chunker) -> None:
    """Test chunker initialization."""
    assert chunker.config.chunk_size == 500
    assert chunker.config.chunk_overlap == 100


def test_chunk_file_returns_chunks(chunker: Chunker) -> None:
    """Test chunk_file returns at least one chunk."""
    chunks = chunker.chunk_file("test.py", "def foo():\n    return 123\n")
    assert len(chunks) >= 1
    assert chunks[0].file_path == "test.py"
    assert chunks[0].chunk_id
    assert chunks[0].start_line >= 1
    assert chunks[0].end_line >= chunks[0].start_line


def test_split_span_by_separator_prefix_makes_progress(chunker: Chunker) -> None:
    """Regression: separator_keep='prefix' must not infinite-loop on leading separators."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("SIGALRM not available on this platform")

    content = "\n\nA\n\nB"

    def _handler(_signum, _frame):  # type: ignore[no-untyped-def]
        raise TimeoutError("_split_span_by_separator hung (prefix mode)")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(1)
    try:
        spans = chunker._split_span_by_separator(content, 0, len(content), "\n\n", "prefix")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)

    assert spans
    assert all(b > a for a, b in spans)


def test_tokenize_with_offsets_skips_length_changing_nfkc() -> None:
    """Regression: token offsets must remain valid indices into the original text."""
    tok = TextTokenizer(TokenizationConfig(strategy="whitespace", normalize_unicode=True, lowercase=False))
    # U+FB01 LATIN SMALL LIGATURE FI expands under NFKC, changing string length.
    res = tok.tokenize_with_offsets("ﬁ")
    assert res.text == "ﬁ"


def test_tokenize_with_offsets_skips_length_changing_lowercase() -> None:
    """Regression: lowercasing can change length (e.g., dotted I); offsets must remain aligned."""
    tok = TextTokenizer(TokenizationConfig(strategy="whitespace", normalize_unicode=False, lowercase=True))
    res = tok.tokenize_with_offsets("İ")
    assert res.text == "İ"


def test_fixed_tokens_chunking_respects_target_and_overlap() -> None:
    cfg = ChunkingConfig(
        chunking_strategy="fixed_tokens",
        chunk_size=500,
        chunk_overlap=100,
        target_tokens=64,
        overlap_tokens=8,
        min_chunk_chars=10,
    )
    tok_cfg = TokenizationConfig(strategy="whitespace", normalize_unicode=False, lowercase=False)
    ch = Chunker(cfg, tok_cfg)

    content = " ".join([f"tok{i}" for i in range(200)])
    chunks = ch.chunk_file("doc.txt", content)
    assert len(chunks) >= 3
    assert all(int(c.token_count or 0) <= 64 for c in chunks)
    # Overlap should repeat boundary tokens.
    assert "tok63" in chunks[0].content
    assert "tok63" in chunks[1].content


def test_recursive_chunking_packs_by_tokens() -> None:
    cfg = ChunkingConfig(
        chunking_strategy="recursive",
        chunk_size=500,
        chunk_overlap=100,
        target_tokens=64,
        overlap_tokens=0,
        separators=["\n\n", "\n", ". ", " ", ""],
        min_chunk_chars=10,
        recursive_max_depth=10,
    )
    tok_cfg = TokenizationConfig(strategy="whitespace", normalize_unicode=False, lowercase=False)
    ch = Chunker(cfg, tok_cfg)

    parts = [
        ("A " * 30).strip() + ".",
        ("B " * 30).strip() + ".",
        ("C " * 30).strip() + ".",
        ("D " * 30).strip() + ".",
    ]
    content = "\n\n".join(parts)
    chunks = ch.chunk_file("doc.txt", content)
    assert len(chunks) >= 2
    assert all(int(c.token_count or 0) <= 64 for c in chunks)


def test_markdown_chunking_splits_on_headings() -> None:
    cfg = ChunkingConfig(
        chunking_strategy="markdown",
        chunk_size=500,
        chunk_overlap=100,
        target_tokens=64,
        overlap_tokens=0,
        markdown_max_heading_level=2,
        min_chunk_chars=10,
    )
    tok_cfg = TokenizationConfig(strategy="whitespace", normalize_unicode=False, lowercase=False)
    ch = Chunker(cfg, tok_cfg)

    para = " ".join([f"w{i}" for i in range(120)])
    content = f"# Title\n\n{para}\n\n## Sub\n\n{para}\n"
    chunks = ch.chunk_file("doc.md", content)
    assert len(chunks) >= 2
    assert any("# Title" in c.content for c in chunks)
    assert any("## Sub" in c.content for c in chunks)


def test_fixed_chars_greedy_fallback_target_changes_boundaries() -> None:
    cfg_default = ChunkingConfig(
        chunking_strategy="greedy",
        chunk_size=1000,
        chunk_overlap=0,
        greedy_fallback_target=400,
        min_chunk_chars=10,
    )
    cfg_tighter = ChunkingConfig(
        chunking_strategy="greedy",
        chunk_size=1000,
        chunk_overlap=0,
        greedy_fallback_target=250,
        min_chunk_chars=10,
    )
    tok_cfg = TokenizationConfig(strategy="whitespace", normalize_unicode=False, lowercase=False)
    ch_default = Chunker(cfg_default, tok_cfg)
    ch_tighter = Chunker(cfg_tighter, tok_cfg)

    content = "x" * 1200
    default_chunks = ch_default.chunk_file("doc.txt", content)
    tighter_chunks = ch_tighter.chunk_file("doc.txt", content)

    assert len(default_chunks) < len(tighter_chunks)
    assert default_chunks[0].content != tighter_chunks[0].content


def test_markdown_include_code_fences_toggle_changes_output() -> None:
    base = dict(
        chunking_strategy="markdown",
        chunk_size=500,
        chunk_overlap=100,
        target_tokens=64,
        overlap_tokens=0,
        markdown_max_heading_level=2,
        min_chunk_chars=10,
    )
    with_fences = Chunker(ChunkingConfig(**base, markdown_include_code_fences=True), TokenizationConfig(strategy="whitespace"))
    without_fences = Chunker(
        ChunkingConfig(**base, markdown_include_code_fences=False), TokenizationConfig(strategy="whitespace")
    )

    content = (
        "# Title\n\n"
        "Intro paragraph for context.\n\n"
        "```python\n"
        "def hello():\n"
        "    return 'world'\n"
        "```\n\n"
        "## Next\n\n"
        "More prose content.\n"
    )

    chunks_with = with_fences.chunk_file("doc.md", content)
    chunks_without = without_fences.chunk_file("doc.md", content)
    joined_with = "\n".join(c.content for c in chunks_with)
    joined_without = "\n".join(c.content for c in chunks_without)

    assert "def hello" in joined_with
    assert "def hello" not in joined_without


def test_ast_chunking_python_preserves_top_level_blocks() -> None:
    cfg = ChunkingConfig(
        chunking_strategy="ast",
        chunk_size=500,
        chunk_overlap=100,
        target_tokens=64,
        overlap_tokens=0,
        ast_overlap_lines=0,
        preserve_imports=0,  # imports merge into the first block chunk
        min_chunk_chars=10,
    )
    tok_cfg = TokenizationConfig(strategy="whitespace", normalize_unicode=False, lowercase=False)
    ch = Chunker(cfg, tok_cfg)

    body_tokens = " ".join([f"tok{i}" for i in range(45)])
    content = (
        "import os\nimport sys\n\n"
        "def foo():\n"
        f"    # {body_tokens}\n"
        "    return 1\n\n"
        "def bar():\n"
        f"    # {body_tokens}\n"
        "    return 2\n"
    )
    chunks = ch.chunk_file("x.py", content)
    assert len(chunks) >= 2
    assert "import os" in chunks[0].content
    assert "def foo" in chunks[0].content
    assert "def bar" not in chunks[0].content
    assert any("def bar" in c.content for c in chunks[1:])


def test_ast_chunking_python_can_isolate_imports_when_enabled() -> None:
    cfg = ChunkingConfig(
        chunking_strategy="ast",
        chunk_size=500,
        chunk_overlap=100,
        target_tokens=64,
        overlap_tokens=0,
        ast_overlap_lines=0,
        preserve_imports=1,
        min_chunk_chars=10,
    )
    tok_cfg = TokenizationConfig(strategy="whitespace", normalize_unicode=False, lowercase=False)
    ch = Chunker(cfg, tok_cfg)

    content = (
        "import os\nimport sys\n\n"
        "def foo():\n"
        "    # " + " ".join(["a" for _i in range(90)]) + "\n"
        "    return 1\n\n"
        "def bar():\n"
        "    # " + " ".join(["b" for _i in range(90)]) + "\n"
        "    return 2\n"
    )
    chunks = ch.chunk_file("x.py", content)
    assert len(chunks) >= 3
    assert "import os" in chunks[0].content
    assert "def foo" not in chunks[0].content
    assert "def foo" in chunks[1].content
    assert "def bar" in chunks[2].content


def test_hybrid_chunking_falls_back_on_syntax_error() -> None:
    cfg = ChunkingConfig(
        chunking_strategy="hybrid",
        chunk_size=500,
        chunk_overlap=100,
        target_tokens=64,
        overlap_tokens=4,
        min_chunk_chars=10,
    )
    tok_cfg = TokenizationConfig(strategy="whitespace", normalize_unicode=False, lowercase=False)
    ch = Chunker(cfg, tok_cfg)

    bad_py = "def oops(:\n    return 1\n"
    chunks = ch.chunk_file("bad.py", bad_py)
    assert len(chunks) >= 1
    assert any("def" in c.content for c in chunks)


def test_ast_chunking_typescript_respects_top_level_brace_blocks() -> None:
    cfg = ChunkingConfig(
        chunking_strategy="ast",
        chunk_size=500,
        chunk_overlap=100,
        target_tokens=64,
        overlap_tokens=0,
        min_chunk_chars=10,
    )
    tok_cfg = TokenizationConfig(strategy="whitespace", normalize_unicode=False, lowercase=False)
    ch = Chunker(cfg, tok_cfg)

    toks = " ".join([f"w{i}" for i in range(45)])
    content = (
        "export function foo() {\n"
        f"  // {toks}\n"
        "  return 1;\n"
        "}\n\n"
        "export function bar() {\n"
        f"  // {toks}\n"
        "  return 2;\n"
        "}\n"
    )
    chunks = ch.chunk_file("x.ts", content)
    assert len(chunks) >= 2
    assert "function foo" in chunks[0].content
    assert "function bar" not in chunks[0].content
    assert any("function bar" in c.content for c in chunks[1:])
