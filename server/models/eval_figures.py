"""Page-grounded figure retrieval eval dataset.

The eval lane scores retrieval by ``expected_paths``, which is meaningless for a corpus
that is one PDF: every match has the same path, so path-level MRR is 1.0 whatever the
retriever does. Figure chunks are located by *page*, so this dataset grounds each question
on the pages where the answering figure (or prose passage) is actually printed, and the
scorer asks whether those pages came back in the top ranks.

These schemas are serialized to disk (``data/eval_datasets/*.json``) and consumed by
``scripts/eval_figure_grounding.py``. No frontend consumes them, so they are deliberately
not registered for TypeScript generation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

FigureEvalKind = Literal["locate", "content"]
"""``locate``: answerable from the figure's caption. ``content``: only the plotted content answers."""


class FigureEvalItem(BaseModel):
    """One question grounded on the page(s) that actually carry its answer."""

    question: str = Field(description="A real question about the source document")
    expected_pages: list[int] = Field(
        min_length=1,
        description="1-based PDF pages on which the answering figure or passage is printed",
    )
    figure_ref: str = Field(
        description="The figure as the document names it (e.g. 'Figure 5-6'), or the prose section"
    )
    kind: FigureEvalKind = Field(
        description="Whether the caption alone answers it (locate) or only the plotted content does"
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Free-form grouping labels; 'prose' marks a non-figure control item",
    )

    @field_validator("expected_pages")
    @classmethod
    def _pages_are_1_based(cls, pages: list[int]) -> list[int]:
        if any(page < 1 for page in pages):
            raise ValueError("expected_pages are 1-based; every page must be >= 1")
        return pages


class FigureEvalDataset(BaseModel):
    """Every question for one corpus."""

    corpus_id: str = Field(description="Corpus the questions are asked against")
    items: list[FigureEvalItem] = Field(min_length=1, description="The questions")
