from server.models.index import Chunk
from server.models.tribrid_config_model import ChunkingConfig


class Chunker:
    def __init__(self, config: ChunkingConfig):
        self.config = config

    def chunk_file(self, file_path: str, content: str) -> list[Chunk]:
        strategy = (self.config.chunking_strategy or "ast").lower()
        language = None
        if file_path.endswith(".py"):
            language = "python"
        elif file_path.endswith(".ts") or file_path.endswith(".tsx"):
            language = "typescript"
        elif file_path.endswith(".js") or file_path.endswith(".jsx"):
            language = "javascript"

        # We keep a minimal implementation: AST/semantic strategies fall back to fixed chunking.
        if strategy in {"ast", "hybrid", "semantic"}:
            return self.chunk_fixed(file_path, content, language=language)
        return self.chunk_fixed(file_path, content, language=language)

    def chunk_ast(self, file_path: str, content: str, language: str) -> list[Chunk]:
        # Minimal fallback: AST chunking is not implemented yet.
        return self.chunk_fixed(file_path, content, language=language)

    def chunk_semantic(self, file_path: str, content: str) -> list[Chunk]:
        return self.chunk_fixed(file_path, content, language=None)

    def chunk_fixed(self, file_path: str, content: str, language: str | None = None) -> list[Chunk]:
        # Chunk by characters with overlap, then compute line spans.
        size = max(100, int(self.config.chunk_size))
        overlap = max(0, int(self.config.chunk_overlap))
        if overlap >= size:
            overlap = max(0, size // 5)

        chunks: list[Chunk] = []
        start = 0
        n = len(content)
        while start < n:
            end = min(n, start + size)
            chunk_text = content[start:end]

            # Rough line span
            start_line = content[:start].count("\n") + 1
            end_line = start_line + chunk_text.count("\n")

            token_count = len(chunk_text.split())
            chunks.append(
                Chunk(
                    chunk_id=f"{file_path}:{start_line}-{end_line}:{start}",
                    content=chunk_text,
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    language=language,
                    token_count=token_count,
                )
            )

            if end == n:
                break
            start = max(0, end - overlap)
        return chunks
