from __future__ import annotations

import bisect
from functools import lru_cache
from typing import Any

import torch
from torch import Tensor
from transformers import AutoModel, AutoTokenizer

from server.models.index import Chunk
from server.models.tribrid_config_model import ChunkingConfig, EmbeddingConfig


@lru_cache(maxsize=4)
def _load_hf_tokenizer(model_name: str) -> Any:
    return AutoTokenizer.from_pretrained(model_name, use_fast=True)  # type: ignore[no-untyped-call]


@lru_cache(maxsize=4)
def _load_hf_model(model_name: str) -> Any:
    model = AutoModel.from_pretrained(model_name)
    model.eval()
    return model


def _l2_normalize(vec: Tensor) -> Tensor:
    denom = torch.linalg.norm(vec, ord=2, dim=-1, keepdim=True).clamp_min(1e-12)
    return vec / denom  # type: ignore[no-any-return]


def late_chunk_document(
    file_path: str,
    content: str,
    *,
    chunking: ChunkingConfig,
    embedding: EmbeddingConfig,
) -> list[Chunk]:
    """Late chunking (local-only): embed the whole doc once, then pool per chunk span.

    Requirements (enforced elsewhere):
    - embedding.embedding_backend == 'provider'
    - embedding.embedding_type in {'local','huggingface'}
    - embedding.contextual_chunk_embeddings == 'late_chunking_local_only'

    Notes:
    - Uses HF AutoModel last_hidden_state token embeddings
    - Pools by mean over token vectors in each chunk span
    """
    model_name = str(getattr(embedding, "embedding_model_local", "") or "").strip()
    if not model_name:
        raise RuntimeError("late chunking requires embedding.embedding_model_local")

    tokenizer = _load_hf_tokenizer(model_name)
    model = _load_hf_model(model_name)

    max_doc_tokens = int(getattr(embedding, "late_chunking_max_doc_tokens", 8192) or 8192)
    hard = int(getattr(embedding, "embedding_max_tokens", 0) or 0)
    if hard > 0:
        max_doc_tokens = min(max_doc_tokens, hard)

    enc = tokenizer(
        content,
        return_offsets_mapping=True,
        add_special_tokens=False,
        truncation=True,
        max_length=max_doc_tokens,
        return_tensors="pt",
    )
    input_ids = enc["input_ids"]
    attn = enc.get("attention_mask")
    offsets = enc.get("offset_mapping")
    if offsets is None:
        raise RuntimeError("late chunking requires a fast tokenizer with offset_mapping support")

    with torch.no_grad():
        out = model(input_ids=input_ids, attention_mask=attn)
        h = getattr(out, "last_hidden_state", None)
        if h is None:
            raise RuntimeError("HF model output missing last_hidden_state")
        # [seq, hidden]
        token_vecs = h[0]

    hidden = int(token_vecs.shape[-1])
    expected_dim = int(getattr(embedding, "embedding_dim", 0) or 0)
    if expected_dim and expected_dim != hidden:
        raise RuntimeError(f"Embedding dimension mismatch for late chunking ({hidden} != {expected_dim}). Set embedding_dim to {hidden} and reindex.")

    offsets0 = offsets[0].tolist()
    token_starts = [int(s) for s, _e in offsets0]
    token_ends = [int(e) for _s, e in offsets0]
    seq_len = len(token_starts)

    target = int(getattr(chunking, "target_tokens", 512) or 512)
    overlap = int(getattr(chunking, "overlap_tokens", 64) or 64)
    if overlap >= target:
        overlap = max(0, target // 5)

    nl_positions = [i for i, ch in enumerate(content) if ch == "\n"]

    chunks: list[Chunk] = []
    ordinal = 0
    start_tok = 0
    while start_tok < seq_len:
        end_tok = min(seq_len, start_tok + target)
        start_char = token_starts[start_tok]
        end_char = token_ends[end_tok - 1] if end_tok - 1 < len(token_ends) else len(content)
        if end_char <= start_char:
            break

        text = content[start_char:end_char]
        start_line = 1 + bisect.bisect_left(nl_positions, start_char)
        end_line = 1 + bisect.bisect_left(nl_positions, end_char)

        span_vecs = token_vecs[start_tok:end_tok]
        pooled = span_vecs.mean(dim=0)
        pooled = _l2_normalize(pooled)
        emb_list = [float(x) for x in pooled.cpu().tolist()]

        meta: dict[str, Any] = {"char_start": int(start_char), "char_end": int(end_char)}
        if bool(getattr(chunking, "emit_chunk_ordinal", True)):
            meta["chunk_ordinal"] = int(ordinal)
        if bool(getattr(chunking, "emit_parent_doc_id", True)):
            meta["parent_doc_id"] = file_path

        chunks.append(
            Chunk(
                chunk_id=f"{file_path}:{start_line}-{end_line}:{start_char}",
                content=text,
                file_path=file_path,
                start_line=int(start_line),
                end_line=int(end_line),
                language=None,
                token_count=int(end_tok - start_tok),
                embedding=emb_list,
                metadata=meta,
            )
        )
        ordinal += 1

        if end_tok >= seq_len:
            break
        start_tok = max(0, end_tok - overlap)

    return chunks

