from __future__ import annotations

from server.models.tribrid_config_model import Chunk
from server.synthetic.recipes import (
    _fallback_eval_candidates_for_chunk,
    _normalize_eval_candidate_payload,
    _strict_bool_flag,
)


def test_normalize_eval_payload_accepts_items_array_in_object() -> None:
    payload = {
        "items": [
            {"question": "q1", "expected_answer": "a1"},
            {"question": "q2", "expected_answer": "a2"},
        ]
    }
    rows = _normalize_eval_candidate_payload(payload)
    assert len(rows) == 2
    assert rows[0]["question"] == "q1"
    assert rows[1]["question"] == "q2"


def test_normalize_eval_payload_accepts_single_row_object() -> None:
    payload = {
        "question": "What changed in the hearing schedule?",
        "expected_answer": "The hearing was canceled.",
        "evidence_quote": "the hearing this morning was canceled",
    }
    rows = _normalize_eval_candidate_payload(payload)
    assert len(rows) == 1
    assert rows[0]["question"].startswith("What changed")


def test_normalize_eval_payload_rejects_non_rows() -> None:
    assert _normalize_eval_candidate_payload("not-json-list") == []
    assert _normalize_eval_candidate_payload({"foo": "bar"}) == []


def test_fallback_eval_candidates_for_chunk_generates_rows() -> None:
    chunk = Chunk(
        chunk_id="c1",
        repo_id="epstein-files-1",
        file_path="transcripts/example.txt",
        start_line=1,
        end_line=4,
        content="The hearing this morning was canceled.\nAn affidavit will be filed tomorrow.\n",
    )
    rows = _fallback_eval_candidates_for_chunk(
        chunk=chunk,
        pairs_per_source=2,
        include_expected_answer=True,
    )
    assert len(rows) == 2
    assert rows[0]["question"]
    assert rows[0]["expected_answer"]
    assert rows[0]["evidence_quote"]


def test_strict_bool_flag_parses_only_explicit_boolean_values() -> None:
    assert _strict_bool_flag(True) is True
    assert _strict_bool_flag(False) is False
    assert _strict_bool_flag("true") is True
    assert _strict_bool_flag("false") is False
    assert _strict_bool_flag("  FALSE ") is False
    assert _strict_bool_flag("not-a-bool") is False
    assert _strict_bool_flag(1) is True
    assert _strict_bool_flag(0) is False
