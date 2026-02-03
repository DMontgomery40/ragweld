from __future__ import annotations

from server.models.retrieval import ChunkMatch


def format_context_for_llm(*, rag_chunks: list[ChunkMatch], recall_chunks: list[ChunkMatch]) -> str:
    """Format retrieval results into structured context for the LLM.

    The output uses two labeled XML sections:
    - <rag_context>...</rag_context> for code/doc chunks (file paths + line ranges + code fences)
    - <recall_context>...</recall_context> for chat memory snippets (role + timestamp + text)
    """

    sections: list[str] = []

    if rag_chunks:
        rag_lines: list[str] = ["<rag_context>"]
        for chunk in rag_chunks:
            rag_lines.append(f"## {chunk.file_path}:{int(chunk.start_line)}-{int(chunk.end_line)}")
            if chunk.language:
                rag_lines.append(f"Language: {chunk.language}")
            rag_lines.append(f"```\n{chunk.content}\n```")
            rag_lines.append("")
        rag_lines.append("</rag_context>")
        sections.append("\n".join(rag_lines))

    if recall_chunks:
        recall_lines: list[str] = ["<recall_context>"]
        for chunk in recall_chunks:
            meta = chunk.metadata or {}
            role = str(meta.get("role") or "unknown")
            timestamp = str(meta.get("timestamp") or "")
            conv_id = str(meta.get("conversation_id") or "")
            conv_short = conv_id[:8] if conv_id else ""
            header = f"## [{role}] {timestamp}".strip()
            if conv_short:
                header = f"{header} (conv:{conv_short})"
            recall_lines.append(header)
            recall_lines.append(chunk.content)
            recall_lines.append("")
        recall_lines.append("</recall_context>")
        sections.append("\n".join(recall_lines))

    return "\n\n".join(sections).strip()

