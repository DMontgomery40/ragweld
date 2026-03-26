from __future__ import annotations

import json

import pytest

from server.models.tribrid_config_model import Chunk
from server.models.tribrid_config_model import SyntheticRunStartRequest, TriBridConfig
from server.synthetic.materialized_corpus import (
    build_materialized_candidate_paths,
    build_materialized_eval_items,
    load_materialized_corpus_rows,
)
from server.synthetic.recipes import (
    _fallback_eval_candidates_for_chunk,
    _normalize_eval_candidate_payload,
    _strict_bool_flag,
    MaterializedCorpusEvalAdapter,
    generate_recipe_payloads,
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


def test_materialized_manifest_rows_generate_grounded_eval_items(tmp_path) -> None:
    (tmp_path / "mail-1.txt").write_text(
        "\n".join(
            [
                "Source dataset: to-be/epstein-emails",
                "Subject: Trump house",
                "",
                "Message",
                "-------",
                "JP: Can you provide the address for the old Gosman/Trump house?",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "mail-2.txt").write_text(
        "\n".join(
            [
                "Source dataset: to-be/epstein-emails",
                "Subject: Russian House",
                "",
                "Message",
                "-------",
                "Please send over the Russian House details by tonight.",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "materialized_filename": "mail-1.txt",
                        "source_filename": "HOUSE_OVERSIGHT_016693.txt",
                        "document_id": "HOUSE_OVERSIGHT_016693",
                        "from_address": "John Page",
                        "to_address": "Mayor",
                        "subject": "Trump house",
                        "timestamp_iso": "20081119075432",
                    },
                    {
                        "materialized_filename": "mail-2.txt",
                        "source_filename": "HOUSE_OVERSIGHT_016692.txt",
                        "document_id": "HOUSE_OVERSIGHT_016692",
                        "from_address": "Mayor",
                        "to_address": "John Page",
                        "subject": "Russian House",
                        "timestamp_iso": "20090504172318",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    rows = load_materialized_corpus_rows(tmp_path)
    items = build_materialized_eval_items(
        rows=rows,
        max_pairs=4,
        pairs_per_source=2,
        include_expected_answer=True,
        include_tags=True,
    )
    paths = build_materialized_candidate_paths(rows)

    assert len(rows) == 2
    assert len(items) == 4
    assert items[0].expected_paths == ["mail-1.txt"]
    assert "source:materialized_manifest" in items[0].tags
    assert "Trump house" in items[0].question or "John Page" in items[0].question
    assert items[0].expected_answer
    assert paths == ["mail-1.txt", "mail-2.txt"]


@pytest.mark.asyncio
async def test_generate_recipe_payloads_uses_manifest_without_model_resolution(tmp_path) -> None:
    (tmp_path / "mail-1.txt").write_text(
        "\n".join(
            [
                "Subject: Program & Attendee list",
                "",
                "Message",
                "-------",
                "Attached is the updated attendee list for the event.",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "mail-2.txt").write_text(
        "\n".join(
            [
                "Subject: Russian House",
                "",
                "Message",
                "-------",
                "Please send the updated Russian House details before lunch.",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "materialized_filename": "mail-1.txt",
                        "source_filename": "HOUSE_OVERSIGHT_017523.txt",
                        "document_id": "HOUSE_OVERSIGHT_017523",
                        "from_address": "Cecilia Schott",
                        "to_address": "Jeffrey Epstein",
                        "subject": "Program & Attendee list",
                        "timestamp_iso": "20120818084429",
                    },
                    {
                        "materialized_filename": "mail-2.txt",
                        "source_filename": "HOUSE_OVERSIGHT_016692.txt",
                        "document_id": "HOUSE_OVERSIGHT_016692",
                        "from_address": "Mayor",
                        "to_address": "John Page",
                        "subject": "Russian House",
                        "timestamp_iso": "20090504172318",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    rows = load_materialized_corpus_rows(tmp_path)
    adapter = MaterializedCorpusEvalAdapter(
        rows=rows,
        eval_items=build_materialized_eval_items(
            rows=rows,
            max_pairs=10,
            pairs_per_source=2,
            include_expected_answer=True,
            include_tags=True,
        ),
        candidate_paths=build_materialized_candidate_paths(rows),
        repo_path=str(tmp_path),
    )
    request = SyntheticRunStartRequest(
        corpus_id="epstein-files-1",
        provider="synthetic_data_kit",
        recipe="triplets",
        generator_model="definitely-not-a-real-model",
        judge_model="also-not-a-real-model",
        max_pairs=10,
        pairs_per_source=2,
    )

    artifacts, summary = await generate_recipe_payloads(
        repo_id="epstein-files-1",
        recipe="triplets",
        cfg=TriBridConfig(),
        request=request,
        chunks=[],
        materialized_manifest=adapter,
    )

    assert len(artifacts["eval_dataset_json"]) == 4
    assert len(artifacts["triplets_jsonl"]) == 4
    assert "materialized from corpus manifest" in str(artifacts["report_md"])
    assert summary.sources_used == 2


@pytest.mark.asyncio
async def test_generate_recipe_payloads_keywords_recipe_skips_model_route_resolution() -> None:
    request = SyntheticRunStartRequest(
        corpus_id="epstein-files-1",
        provider="internal_ragweld",
        recipe="keywords",
        generator_model="definitely-not-a-real-model",
        judge_model="also-not-a-real-model",
        max_pairs=10,
        pairs_per_source=1,
    )
    chunk = Chunk(
        chunk_id="c1",
        repo_id="epstein-files-1",
        file_path="docs/hearing_notes.txt",
        start_line=1,
        end_line=3,
        content="Jeffrey Epstein hearing notes mention the committee schedule and witness list.",
    )

    artifacts, summary = await generate_recipe_payloads(
        repo_id="epstein-files-1",
        recipe="keywords",
        cfg=TriBridConfig(),
        request=request,
        chunks=[chunk],
    )

    assert artifacts["keywords_json"]
    assert summary.sources_used == 1
