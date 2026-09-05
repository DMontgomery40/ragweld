"""Public boundaries for corpus lifecycle operations."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CorpusAlreadyIndexedDetail(BaseModel):
    """Conditional cleanup refused a corpus whose index completed (HTTP 409)."""

    code: Literal["corpus_already_indexed"] = "corpus_already_indexed"
    corpus_id: str = Field(description="Corpus preserved by conditional cleanup")
    last_indexed: datetime = Field(description="Index timestamp read under the corpus write lock")
    message: str = Field(description="Stable, non-sensitive conflict summary")
    operator_hint: str = Field(description="What the operator can do next")


class CorpusAlreadyIndexedResponse(BaseModel):
    """FastAPI response envelope for an indexed corpus skipped by cleanup."""

    detail: CorpusAlreadyIndexedDetail
