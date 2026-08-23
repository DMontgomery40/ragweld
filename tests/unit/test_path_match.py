"""Expected-path matching is boundary-aware: exact paths or whole path suffixes, never substrings."""

from __future__ import annotations

import pytest

from server.evaluation.path_match import matches_any, path_matches


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        ("row_001162.txt", "row_001162.txt"),
        ("row_001162.txt", "emails/HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt".replace("HOUSE_OVERSIGHT_026216__msg_000__", "")),
        ("HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt", "emails/HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt"),
        ("emails/a.txt", "/Users/operator/corpus/emails/a.txt"),
        ("/Users/operator/corpus/emails/a.txt", "emails/a.txt"),
        ("Emails\\A.txt", "emails/a.txt"),
        ("./sensor-calibration.md", "sensor-calibration.md"),
    ],
)
def test_path_matches_accepts_exact_paths_and_whole_suffixes(expected: str, actual: str) -> None:
    assert path_matches(expected, actual)


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        ("mail.txt", "blackmail.txt"),
        ("row_001162.txt", "HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt"),
        ("a.txt", "emails/a.txt.bak"),
        ("emails", "emails/a.txt"),
        ("", "a.txt"),
        ("a.txt", ""),
    ],
)
def test_path_matches_rejects_partial_names_and_substrings(expected: str, actual: str) -> None:
    assert not path_matches(expected, actual)


def test_matches_any_checks_every_expected_label() -> None:
    assert matches_any(["other.txt", "emails/a.txt"], "/corpus/emails/a.txt")
    assert not matches_any(["other.txt", "ail/a.txt"], "/corpus/emails/a.txt")
