from __future__ import annotations

import hashlib
import json
from typing import Any

from server.models.tribrid_config_model import TriBridConfig

# Current runtime support in server/indexing/embedder.py when embedding_backend='provider'.
SUPPORTED_PROVIDER_BACKEND_EMBEDDING_PROVIDERS: set[str] = {
    "openai",
    "mlx",
    "local",
    "huggingface",
}


# Tokenizer strategies that are considered compatible for each embedding provider.
# This is intentionally strict to prevent hidden truncation/token budget drift.
_PROVIDER_TOKENIZER_STRATEGIES: dict[str, set[str]] = {
    "openai": {"tiktoken"},
    "mlx": {"huggingface"},
    "local": {"huggingface"},
    "huggingface": {"huggingface"},
}


def _stable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _stable(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, list):
        return [_stable(v) for v in obj]
    return obj


def canonical_contract_json(contract: dict[str, Any]) -> str:
    return json.dumps(_stable(contract), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def contract_hash(contract: dict[str, Any]) -> str:
    payload = canonical_contract_json(contract).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def dense_contract_from_config(config: TriBridConfig) -> dict[str, Any]:
    emb = config.embedding
    tok = config.tokenization
    return {
        "backend": str(emb.embedding_backend or "").strip().lower() or "deterministic",
        "provider": str(emb.embedding_type or "").strip().lower(),
        "model": str(emb.effective_model or "").strip(),
        "dimensions": int(emb.embedding_dim or 0),
        "embed_text_prefix": str(emb.embed_text_prefix or ""),
        "embed_text_suffix": str(emb.embed_text_suffix or ""),
        "input_truncation": str(emb.input_truncation or "").strip().lower(),
        "embedding_max_tokens": int(emb.embedding_max_tokens or 0),
        "contextual_chunk_embeddings": str(emb.contextual_chunk_embeddings or "").strip().lower(),
        "tokenization": {
            "strategy": str(tok.strategy or "").strip().lower(),
            "tiktoken_encoding": str(tok.tiktoken_encoding or "").strip(),
            "hf_tokenizer_name": str(tok.hf_tokenizer_name or "").strip(),
            "normalize_unicode": bool(tok.normalize_unicode),
            "lowercase": bool(tok.lowercase),
            "max_tokens_per_chunk_hard": int(tok.max_tokens_per_chunk_hard or 0),
            "estimate_only": bool(tok.estimate_only),
        },
    }


def sparse_contract_from_config(config: TriBridConfig) -> dict[str, Any]:
    idx = config.indexing
    return {
        "ts_config": str(idx.postgres_ts_config or "").strip(),
        "bm25_tokenizer": str(idx.bm25_tokenizer or "").strip().lower(),
        "bm25_stemmer_lang": str(idx.bm25_stemmer_lang or "").strip().lower(),
    }


def provider_requires_tokenizer(provider: str) -> set[str] | None:
    p = str(provider or "").strip().lower()
    req = _PROVIDER_TOKENIZER_STRATEGIES.get(p)
    if req is None:
        return None
    return set(req)
