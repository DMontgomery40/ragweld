from __future__ import annotations

from typing import Any


class RetrievalContractMismatchError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        leg: str,
        corpus_id: str,
        expected_contract: dict[str, Any],
        current_contract: dict[str, Any],
        required_action: str,
    ) -> None:
        self.code = str(code)
        self.leg = str(leg)
        self.corpus_id = str(corpus_id)
        self.expected_contract = dict(expected_contract or {})
        self.current_contract = dict(current_contract or {})
        self.required_action = str(required_action)
        super().__init__(
            f"{self.code}: corpus={self.corpus_id}, leg={self.leg}, action={self.required_action}"
        )

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "corpus_id": self.corpus_id,
            "leg": self.leg,
            "expected_contract": self.expected_contract,
            "current_contract": self.current_contract,
            "required_action": self.required_action,
        }


class EmbeddingContractMismatchError(RetrievalContractMismatchError):
    def __init__(
        self,
        *,
        corpus_id: str,
        expected_contract: dict[str, Any],
        current_contract: dict[str, Any],
    ) -> None:
        super().__init__(
            code="embedding_contract_mismatch",
            leg="vector",
            corpus_id=corpus_id,
            expected_contract=expected_contract,
            current_contract=current_contract,
            required_action=(
                "Re-index this corpus with force_reindex=true or restore the embedding configuration "
                "to match the existing index contract."
            ),
        )


class SparseContractMismatchError(RetrievalContractMismatchError):
    def __init__(
        self,
        *,
        corpus_id: str,
        expected_contract: dict[str, Any],
        current_contract: dict[str, Any],
    ) -> None:
        super().__init__(
            code="sparse_contract_mismatch",
            leg="sparse",
            corpus_id=corpus_id,
            expected_contract=expected_contract,
            current_contract=current_contract,
            required_action=(
                "Re-index this corpus with force_reindex=true or restore the sparse tokenization/ts_config "
                "to match the existing index contract."
            ),
        )
