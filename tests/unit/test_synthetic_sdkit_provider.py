from __future__ import annotations

from server.synthetic.providers.sdkit_provider import (
    _build_eval_items_from_sdkit_pairs,
    _match_curated_pairs,
    _messages_to_prompt,
)


def test_messages_to_prompt_promotes_single_prompt_to_user_message() -> None:
    system_prompt, user_message = _messages_to_prompt(
        [
            {
                "role": "system",
                "content": "Generate two factual QA pairs from this source.",
            }
        ]
    )

    assert "return only the requested output" in system_prompt.lower()
    assert user_message == "Generate two factual QA pairs from this source."


def test_match_curated_pairs_preserves_duplicate_pairs_in_order() -> None:
    generated_pairs = [
        {
            "question": "Who is named?",
            "answer": "Alex Rivera",
            "source_path": "a.txt",
        },
        {
            "question": "Who is named?",
            "answer": "Alex Rivera",
            "source_path": "b.txt",
        },
    ]
    rated_pairs = [
        {"question": "Who is named?", "answer": "Alex Rivera", "rating": 8.5},
        {"question": "Who is named?", "answer": "Alex Rivera", "rating": 9.0},
    ]

    matched = _match_curated_pairs(generated_pairs=generated_pairs, rated_pairs=rated_pairs)

    assert [row["source_path"] for row in matched] == ["a.txt", "b.txt"]
    assert [row["rating"] for row in matched] == [8.5, 9.0]


def test_build_eval_items_from_sdkit_pairs_respects_answer_and_tags_flags() -> None:
    items = _build_eval_items_from_sdkit_pairs(
        pairs=[
            {
                "question": "What committee is referenced?",
                "answer": "House Oversight Committee",
                "source_path": "oversight.txt",
                "source_kind": "document",
            }
        ],
        include_expected_answer=False,
        include_tags=True,
    )

    assert len(items) == 1
    assert items[0].question == "What committee is referenced?"
    assert items[0].expected_paths == ["oversight.txt"]
    assert items[0].expected_answer == ""
    assert items[0].tags == ["synthetic", "synthetic_data_kit", "document"]
