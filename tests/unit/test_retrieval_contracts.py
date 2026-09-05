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


def test_sparse_contract_is_qdrant_bm25_with_operator_tunables() -> None:
    contract = sparse_contract_from_config(TriBridConfig())
    assert contract["engine"] == "qdrant_sparse_idf"
    assert contract["model"] == "Qdrant/bm25"
    assert set(contract) == {"engine", "model", "k1", "b", "language", "stemmer"}


def test_sparse_contract_hash_changes_on_each_sparse_tunable() -> None:
    base = TriBridConfig()
    base_hash = contract_hash(sparse_contract_from_config(base))
    for mutate in (
        lambda cfg: setattr(cfg.indexing, "bm25_tokenizer", "lowercase"),
        lambda cfg: setattr(cfg.indexing, "bm25_stemmer_lang", "german"),
        lambda cfg: setattr(cfg.sparse_search, "bm25_k1", 1.9),
        lambda cfg: setattr(cfg.sparse_search, "bm25_b", 0.9),
    ):
        changed = base.model_copy(deep=True)
        mutate(changed)
        assert contract_hash(sparse_contract_from_config(changed)) != base_hash


def test_provider_tokenizer_rules() -> None:
    assert provider_requires_tokenizer("openai") == {"tiktoken"}
    assert provider_requires_tokenizer("local") == {"huggingface"}
    assert provider_requires_tokenizer("mlx") == {"huggingface"}
    assert provider_requires_tokenizer("unknown-provider") is None


def test_native_gateway_route_and_billing_context_do_not_change_dense_identity() -> None:
    from server.gateway_catalog import warm_gateway_catalog
    from server.indexing.embedding_gateway import embedding_gateway_for_config
    from server.observability.run_census import RunIdentity

    warm_gateway_catalog()
    cfg = TriBridConfig()
    cfg.embedding.embedding_backend = "provider"
    cfg.embedding.embedding_model = "text-embedding-3-small"
    cfg.embedding.embedding_dim = 128
    original = dense_contract_from_config(cfg)
    for run, corpus, lane in [("index-run", "corpus-a", "index_embeddings"),
                              ("online-run", "corpus-b", "retrieval_embeddings"),
                              ("cache-run", "corpus-a", "cache_embeddings")]:
        route = embedding_gateway_for_config(cfg, identity=RunIdentity(run, corpus, lane))
        assert route is not None and route.alias == "openai.text-embedding-3-small"
        assert route.provider_model == original["model"] == "text-embedding-3-small"
        assert dense_contract_from_config(cfg) == original
    changed_transport = cfg.model_copy(deep=True)
    changed_transport.chat.litellm.base_url = "http://127.0.0.1:54842/v1"
    changed_transport.embedding.embedding_retry_max = 1
    assert contract_hash(dense_contract_from_config(changed_transport)) == contract_hash(original)
