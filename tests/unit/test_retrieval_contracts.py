from __future__ import annotations

from server.models.tribrid_config_model import TriBridConfig
from server.retrieval.contracts import (
    contract_hash,
    dense_contract_from_config,
    provider_requires_tokenizer,
    sparse_contract_from_config,
)


def test_dense_contract_hash_is_stable_for_same_config() -> None:
    cfg = TriBridConfig()
    h1 = contract_hash(dense_contract_from_config(cfg))
    h2 = contract_hash(dense_contract_from_config(cfg))
    assert h1 == h2


def test_dense_contract_hash_changes_on_embedding_fields() -> None:
    base = TriBridConfig()
    changed = base.model_copy(deep=True)
    changed.embedding.embedding_dim = int(base.embedding.embedding_dim) + 512

    assert contract_hash(dense_contract_from_config(base)) != contract_hash(dense_contract_from_config(changed))


def test_dense_contract_hash_changes_on_tokenization_fields() -> None:
    base = TriBridConfig()
    changed = base.model_copy(deep=True)
    changed.tokenization.strategy = "huggingface"

    assert contract_hash(dense_contract_from_config(base)) != contract_hash(dense_contract_from_config(changed))


def test_sparse_contract_hash_changes_when_ts_config_changes() -> None:
    base = TriBridConfig()
    changed = base.model_copy(deep=True)
    changed.indexing.bm25_tokenizer = "lowercase"

    assert contract_hash(sparse_contract_from_config(base)) != contract_hash(sparse_contract_from_config(changed))


def test_provider_tokenizer_rules() -> None:
    assert provider_requires_tokenizer("openai") == {"tiktoken"}
    assert provider_requires_tokenizer("local") == {"huggingface"}
    assert provider_requires_tokenizer("mlx") == {"huggingface"}
    assert provider_requires_tokenizer("unknown-provider") is None
