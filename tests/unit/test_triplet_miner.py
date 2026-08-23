from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.models.tribrid_config_model import EvalResult
from server.training.triplet_miner import mine_triplets, mine_triplets_from_eval_results
from server.training.triplet_rows import TripletRowsCorruptError

BARRY_COHEN_QUESTION = (
    "Which flights or plane management did Jeffrey Epstein discuss with Barry Cohen in October 2017?"
)
JET_AVIATION_QUESTION = "Why did Barry Cohen consider switching plane management from Jet Aviation to EJM?"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _eval_result(
    *,
    question: str,
    expected_paths: list[str],
    retrieved_paths: list[str],
    entry_id: str = "entry",
) -> EvalResult:
    return EvalResult(
        entry_id=entry_id,
        question=question,
        retrieved_paths=retrieved_paths,
        expected_paths=expected_paths,
        top_paths=retrieved_paths[:5],
        top1_path=retrieved_paths[:1],
        reciprocal_rank=0.0,
        recall=0.0,
        latency_ms=1.0,
    )


def test_eval_results_mine_rank_ordered_hard_negatives() -> None:
    result = _eval_result(
        question=BARRY_COHEN_QUESTION,
        expected_paths=["HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt"],
        retrieved_paths=[
            "HOUSE_OVERSIGHT_026224__msg_009__row_001332.txt",
            "HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt",
            "HOUSE_OVERSIGHT_026455__msg_001__row_001483.txt",
            "HOUSE_OVERSIGHT_026218__msg_005__row_001171.txt",
        ],
    )

    rows = mine_triplets_from_eval_results([result], negative_ratio=2, source="eval_run:unit")

    assert [r["negative"] for r in rows] == [
        "HOUSE_OVERSIGHT_026224__msg_009__row_001332.txt",
        "HOUSE_OVERSIGHT_026455__msg_001__row_001483.txt",
    ]
    assert {r["positive"] for r in rows} == {"HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt"}
    assert {r["query"] for r in rows} == {BARRY_COHEN_QUESTION}
    assert {r["source"] for r in rows} == {"eval_run:unit"}


def test_eval_results_never_use_an_expected_path_as_negative_even_by_suffix() -> None:
    result = _eval_result(
        question=JET_AVIATION_QUESTION,
        expected_paths=["HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt"],
        retrieved_paths=[
            "emails/HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt",
            "emails/HOUSE_OVERSIGHT_026224__msg_009__row_001332.txt",
        ],
    )

    rows = mine_triplets_from_eval_results([result], negative_ratio=5)

    assert len(rows) == 1
    assert rows[0]["negative"] == "emails/HOUSE_OVERSIGHT_026224__msg_009__row_001332.txt"
    # the positive is written as the canonical retrieved path so training can materialize it
    assert rows[0]["positive"] == "emails/HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt"


def test_eval_results_skip_entries_without_positives_or_negatives() -> None:
    no_negatives = _eval_result(
        question=BARRY_COHEN_QUESTION,
        expected_paths=["a.txt"],
        retrieved_paths=["a.txt"],
        entry_id="only-hits",
    )
    no_positive = _eval_result(
        question=JET_AVIATION_QUESTION,
        expected_paths=[],
        retrieved_paths=["b.txt", "c.txt"],
        entry_id="unlabelled",
    )
    empty_retrieval = _eval_result(
        question=JET_AVIATION_QUESTION,
        expected_paths=["d.txt"],
        retrieved_paths=[],
        entry_id="nothing-retrieved",
    )

    assert mine_triplets_from_eval_results([no_negatives, no_positive, empty_retrieval], negative_ratio=3) == []


def test_eval_results_dedupe_and_honor_max_triplets() -> None:
    first = _eval_result(
        question=BARRY_COHEN_QUESTION,
        expected_paths=["pos.txt", "pos.txt"],
        retrieved_paths=["neg1.txt", "neg1.txt", "neg2.txt", "neg3.txt"],
        entry_id="first",
    )
    duplicate = _eval_result(
        question=BARRY_COHEN_QUESTION,
        expected_paths=["pos.txt"],
        retrieved_paths=["neg1.txt", "neg2.txt"],
        entry_id="second",
    )

    unlimited = mine_triplets_from_eval_results([first, duplicate], negative_ratio=3)
    assert [(r["positive"], r["negative"]) for r in unlimited] == [
        ("pos.txt", "neg1.txt"),
        ("pos.txt", "neg2.txt"),
        ("pos.txt", "neg3.txt"),
    ]

    capped = mine_triplets_from_eval_results([first, duplicate], negative_ratio=3, max_triplets=2)
    assert [r["negative"] for r in capped] == ["neg1.txt", "neg2.txt"]


def test_mine_combines_feedback_and_eval_run_sources(tmp_path: Path) -> None:
    log_path = tmp_path / "queries.jsonl"
    triplets_path = tmp_path / "triplets.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "kind": "chat",
                "event_id": "evt_1",
                "corpus_ids": ["epstein-files-1"],
                "query": JET_AVIATION_QUESTION,
                "top_paths": ["good.txt", "bad.txt"],
            },
            {"kind": "feedback", "event_id": "evt_1", "signal": "thumbsup"},
        ],
    )
    eval_result = _eval_result(
        question=BARRY_COHEN_QUESTION,
        expected_paths=["pos.txt"],
        retrieved_paths=["neg1.txt", "pos.txt", "neg2.txt"],
    )

    stats = mine_triplets(
        log_path=log_path,
        triplets_path=triplets_path,
        mine_mode="replace",
        corpus_id="epstein-files-1",
        eval_results=[eval_result],
        eval_run_id="epstein-files-1__20260822_120000",
        negative_ratio=5,
        preserve_existing_on_empty=False,
    )

    rows = _read_jsonl(triplets_path)
    assert stats["triplets_from_feedback"] == 1
    assert stats["triplets_from_eval_run"] == 2
    assert stats["triplets_mined"] == 3
    assert stats["eval_run_id"] == "epstein-files-1__20260822_120000"
    assert [(r["query"], r["positive"], r["negative"]) for r in rows] == [
        (JET_AVIATION_QUESTION, "good.txt", "bad.txt"),
        (BARRY_COHEN_QUESTION, "pos.txt", "neg1.txt"),
        (BARRY_COHEN_QUESTION, "pos.txt", "neg2.txt"),
    ]
    assert rows[0]["source"] == "feedback"
    assert rows[1]["source"] == "eval_run:epstein-files-1__20260822_120000"


def test_replace_mode_preserves_existing_when_no_new_triplets_and_preserve_enabled(tmp_path: Path) -> None:
    log_path = tmp_path / "queries.jsonl"
    triplets_path = tmp_path / "triplets.jsonl"

    _write_jsonl(
        log_path,
        [
            {
                "kind": "search",
                "event_id": "evt_1",
                "query": BARRY_COHEN_QUESTION,
                "top_paths": ["a.txt", "b.txt"],
            }
        ],
    )
    _write_jsonl(
        triplets_path,
        [{"query": JET_AVIATION_QUESTION, "positive": "p.txt", "negative": "n.txt"}],
    )

    result = mine_triplets(
        log_path=log_path,
        triplets_path=triplets_path,
        mine_mode="replace",
        preserve_existing_on_empty=True,
    )

    assert int(result.get("triplets_mined") or 0) == 0
    assert bool(result.get("preserved_existing")) is True
    rows = _read_jsonl(triplets_path)
    assert len(rows) == 1
    assert rows[0]["query"] == JET_AVIATION_QUESTION


def test_replace_mode_clears_existing_when_no_new_triplets_and_preserve_disabled(tmp_path: Path) -> None:
    log_path = tmp_path / "queries.jsonl"
    triplets_path = tmp_path / "triplets.jsonl"

    _write_jsonl(
        log_path,
        [
            {
                "kind": "search",
                "event_id": "evt_1",
                "query": BARRY_COHEN_QUESTION,
                "top_paths": ["a.txt", "b.txt"],
            }
        ],
    )
    _write_jsonl(
        triplets_path,
        [{"query": JET_AVIATION_QUESTION, "positive": "p.txt", "negative": "n.txt"}],
    )

    result = mine_triplets(
        log_path=log_path,
        triplets_path=triplets_path,
        mine_mode="replace",
        preserve_existing_on_empty=False,
    )

    assert int(result.get("triplets_mined") or 0) == 0
    assert bool(result.get("preserved_existing")) is False
    assert _read_jsonl(triplets_path) == []


def test_reset_mining_recovers_from_a_corrupt_triplets_file(tmp_path: Path) -> None:
    # "Reset & mine" is the operator's way out of a corrupt artifact; it must not be blocked by
    # loading the very file it is about to replace.
    log_path = tmp_path / "queries.jsonl"
    triplets_path = tmp_path / "triplets.jsonl"
    _write_jsonl(
        log_path,
        [{"kind": "search", "event_id": "evt_1", "query": BARRY_COHEN_QUESTION, "top_paths": ["a.txt", "b.txt"]}],
    )
    triplets_path.write_text('{"query": "broken\n', encoding="utf-8")

    with pytest.raises(TripletRowsCorruptError):
        mine_triplets(log_path=log_path, triplets_path=triplets_path, mine_mode="append")
    with pytest.raises(TripletRowsCorruptError):
        mine_triplets(log_path=log_path, triplets_path=triplets_path, mine_mode="replace", preserve_existing_on_empty=True)

    result = mine_triplets(
        log_path=log_path, triplets_path=triplets_path, mine_mode="replace", preserve_existing_on_empty=False
    )
    assert result["ok"] is True
    assert _read_jsonl(triplets_path) == []


def test_append_mode_keeps_existing_rows_and_adds_new_ones(tmp_path: Path) -> None:
    log_path = tmp_path / "queries.jsonl"
    triplets_path = tmp_path / "triplets.jsonl"
    _write_jsonl(log_path, [])
    _write_jsonl(
        triplets_path,
        [{"query": JET_AVIATION_QUESTION, "positive": "p.txt", "negative": "n.txt"}],
    )
    eval_result = _eval_result(
        question=BARRY_COHEN_QUESTION,
        expected_paths=["pos.txt"],
        retrieved_paths=["neg1.txt"],
    )

    result = mine_triplets(
        log_path=log_path,
        triplets_path=triplets_path,
        mine_mode="append",
        eval_results=[eval_result],
        eval_run_id="run",
        negative_ratio=1,
    )

    assert result["triplets_mined"] == 1
    rows = _read_jsonl(triplets_path)
    assert [r["query"] for r in rows] == [JET_AVIATION_QUESTION, BARRY_COHEN_QUESTION]


def test_append_mode_is_a_union_with_rows_already_on_disk(tmp_path: Path) -> None:
    log_path = tmp_path / "queries.jsonl"
    triplets_path = tmp_path / "triplets.jsonl"
    _write_jsonl(log_path, [])
    _write_jsonl(
        triplets_path,
        [
            {"query": BARRY_COHEN_QUESTION, "positive": "pos.txt", "negative": "neg1.txt", "source": "synthetic_run:x"},
            {"query": JET_AVIATION_QUESTION, "positive": "p.txt", "negative": "n.txt", "source": "feedback"},
        ],
    )
    eval_result = _eval_result(
        question=BARRY_COHEN_QUESTION,
        expected_paths=["pos.txt"],
        retrieved_paths=["neg1.txt", "neg2.txt"],
    )

    result = mine_triplets(
        log_path=log_path,
        triplets_path=triplets_path,
        mine_mode="append",
        eval_results=[eval_result],
        eval_run_id="run",
        negative_ratio=5,
    )

    assert result["triplets_from_eval_run_candidates"] == 2
    assert result["triplets_from_eval_run"] == 1
    assert result["triplets_mined"] == 1
    assert result["triplets_skipped_existing"] == 1
    rows = _read_jsonl(triplets_path)
    assert [(r["positive"], r["negative"]) for r in rows] == [("pos.txt", "neg1.txt"), ("p.txt", "n.txt"), ("pos.txt", "neg2.txt")]


def test_positive_is_the_canonical_retrieved_path_when_the_label_is_a_suffix() -> None:
    result = _eval_result(
        question=JET_AVIATION_QUESTION,
        expected_paths=["HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt"],
        retrieved_paths=["emails/noise.txt", "emails/HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt"],
    )
    rows = mine_triplets_from_eval_results([result], negative_ratio=3)
    assert rows[0]["positive"] == "emails/HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt"
    assert rows[0]["negative"] == "emails/noise.txt"


def test_placeholder_questions_are_rejected_and_counted(tmp_path: Path) -> None:
    log_path = tmp_path / "queries.jsonl"
    triplets_path = tmp_path / "triplets.jsonl"
    _write_jsonl(
        log_path,
        [
            {"kind": "chat", "event_id": "evt_1", "query": "test", "top_paths": ["good.txt", "bad.txt"]},
            {"kind": "feedback", "event_id": "evt_1", "signal": "thumbsup"},
        ],
    )
    placeholder = _eval_result(question="hello", expected_paths=["pos.txt"], retrieved_paths=["neg.txt"])
    real = _eval_result(question=BARRY_COHEN_QUESTION, expected_paths=["pos.txt"], retrieved_paths=["neg.txt"])

    stats = mine_triplets(
        log_path=log_path,
        triplets_path=triplets_path,
        mine_mode="replace",
        eval_results=[placeholder, real],
        eval_run_id="run",
        negative_ratio=2,
    )

    assert stats["triplets_rejected_placeholder"] == 2
    assert stats["triplets_mined"] == 1
    assert [r["query"] for r in _read_jsonl(triplets_path)] == [BARRY_COHEN_QUESTION]


def test_negatives_that_contain_the_expected_answer_are_not_mined(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "pos.txt").write_text("Thinking of switching from Jet Aviation to EJM.", encoding="utf-8")
    (corpus / "dup.txt").write_text("Fwd: Thinking of switching from Jet Aviation to EJM.", encoding="utf-8")
    (corpus / "other.txt").write_text("Lunch on Thursday?", encoding="utf-8")
    result = _eval_result(
        question=JET_AVIATION_QUESTION,
        expected_paths=["pos.txt"],
        retrieved_paths=["dup.txt", "other.txt", "pos.txt"],
        entry_id="q1",
    )

    result = result.model_copy(update={"expected_answer": "switching from Jet Aviation to EJM"})
    rows, stats = mine_triplets_from_eval_results([result], negative_ratio=3, corpus_root=corpus, with_stats=True)

    assert [r["negative"] for r in rows] == ["other.txt"]
    assert stats["negatives_rejected_answer_leak"] == 1


def test_written_counts_are_reported_per_source_after_union(tmp_path: Path) -> None:
    log_path = tmp_path / "queries.jsonl"
    triplets_path = tmp_path / "triplets.jsonl"
    _write_jsonl(
        log_path,
        [
            {"kind": "chat", "event_id": "evt_1", "query": JET_AVIATION_QUESTION, "top_paths": ["pos.txt", "neg1.txt"]},
            {"kind": "feedback", "event_id": "evt_1", "signal": "thumbsup"},
        ],
    )
    eval_result = _eval_result(question=JET_AVIATION_QUESTION, expected_paths=["pos.txt"], retrieved_paths=["neg1.txt", "neg2.txt"])

    stats = mine_triplets(
        log_path=log_path,
        triplets_path=triplets_path,
        mine_mode="replace",
        eval_results=[eval_result],
        eval_run_id="run",
        negative_ratio=5,
    )

    # feedback and the eval run both propose (pos, neg1); it is written once, attributed to feedback.
    assert stats["triplets_from_feedback"] == 1
    assert stats["triplets_from_eval_run_candidates"] == 2
    assert stats["triplets_from_eval_run"] == 1
    assert stats["triplets_mined"] == 2
    assert stats["triplets_total"] == 2


def test_short_answers_are_protected_as_whole_tokens_and_unreadable_candidates_are_not_mined(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "pos.txt").write_text("Thinking of switching from Jet Aviation to EJM.", encoding="utf-8")
    (corpus / "dup.txt").write_text("EJM is more expensive than Jet Aviation.", encoding="utf-8")
    (corpus / "other.txt").write_text("Lunch on Thursday?", encoding="utf-8")
    # Codex pass 7: a lossy decode used to make binary/invalid-UTF-8 documents "verified" answer-free.
    (corpus / "scan.bin").write_bytes(b"\xff\xfe\x00binary payload with EJM inside")
    (corpus / "latin1.txt").write_bytes("Facture EJM pour l'\xe9t\xe9".encode("latin-1"))
    result = _eval_result(
        question=JET_AVIATION_QUESTION,
        expected_paths=["pos.txt"],
        retrieved_paths=["dup.txt", "missing.txt", "scan.bin", "latin1.txt", "other.txt", "pos.txt"],
        entry_id="q1",
    )
    result = result.model_copy(update={"expected_answer": "EJM"})
    rows, stats = mine_triplets_from_eval_results([result], negative_ratio=5, corpus_root=corpus, with_stats=True)
    assert [r["negative"] for r in rows] == ["other.txt"]
    assert stats["negatives_rejected_answer_leak"] == 1
    assert stats["negatives_rejected_unverifiable"] == 3  # missing, binary, not UTF-8


def test_eval_results_carry_their_own_expected_answer_for_mining(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "pos.txt").write_text("switching from Jet Aviation to EJM", encoding="utf-8")
    (corpus / "dup.txt").write_text("Fwd: switching from Jet Aviation to EJM", encoding="utf-8")
    result = _eval_result(
        question=JET_AVIATION_QUESTION, expected_paths=["pos.txt"], retrieved_paths=["dup.txt", "pos.txt"], entry_id="q1"
    ).model_copy(update={"expected_answer": "switching from Jet Aviation to EJM"})
    rows, stats = mine_triplets_from_eval_results([result], negative_ratio=5, corpus_root=corpus, with_stats=True)
    assert rows == []
    assert stats["negatives_rejected_answer_leak"] == 1


def test_answer_leak_check_handles_non_latin_answers(tmp_path: Path) -> None:
    from server.training.triplet_miner import answer_appears_in

    assert answer_appears_in("张伟", "The sender was 张伟.")
    assert answer_appears_in("Эпштейн", "Письмо отправил Эпштейн вчера")
    assert not answer_appears_in("EJM", "ejmx is unrelated")


def test_results_without_answer_provenance_are_counted_and_mined_without_the_leak_check(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "pos.txt").write_text("switching from Jet Aviation to EJM", encoding="utf-8")
    (corpus / "dup.txt").write_text("Fwd: switching from Jet Aviation to EJM", encoding="utf-8")
    result = _eval_result(question=JET_AVIATION_QUESTION, expected_paths=["pos.txt"], retrieved_paths=["dup.txt", "pos.txt"])
    rows, stats = mine_triplets_from_eval_results([result], negative_ratio=5, corpus_root=corpus, with_stats=True)
    assert [r["negative"] for r in rows] == ["dup.txt"]
    assert stats["entries_without_answer_provenance"] == 1
