"""The synthetic judge's System One Nouls against the real backends.

Fixed rows from the nasa-apollo-11 eval set (the published dataset as of 2026-09-23): two
are cover-page trivia (the agency name on the cover, the MSC report number) and must be
rejected; two ask about the report's substance (boilerplate spacecraft test missions) and
must be kept. The decision is the product's own (``judge_accepts`` with the default
``synthetic.judge`` minimums), so this pins judgment quality, not just the transport.

TypeSafe Jev: set RAGWELD_LIVE_SYSTEM_ONE=1 with TYPESAFE_API_KEY (LXC100's runtime.env).
Measured 2026-09-23: trivia reader_question 0.06-0.08, kept rows 0.85-0.86, answer_supported
0.95. Paid: 4 requests of about 750 input tokens.

Laya: set RAGWELD_LIVE_LAYA_BASE_URL to a running laya-serve. The base English checkpoint
does not separate these rows (reader_question 0.37-0.59 for both kinds on 2026-09-23), so
only the typed contract is pinned for it, not the keep/reject decision.
"""

from __future__ import annotations

import os

import pytest

from server.models.system_one import SystemOneConfig
from server.models.tribrid_config_model import (
    EvalDatasetItem,
    EvalExpectedLocation,
    SyntheticJudgeConfig,
)
from server.synthetic.providers.grounded_qa_provider import (
    JUDGE_QUESTIONS,
    judge_accepts,
    judge_state,
    judge_verdict,
)
from server.system_one.client import SystemOneClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

PDF = "A11_MissionReport.pdf"


def _row(question: str, answer: str, quote: str, page: int) -> EvalDatasetItem:
    return EvalDatasetItem(
        question=question,
        expected_paths=[PDF],
        expected_locations=[EvalExpectedLocation(path=PDF, unit="page", start=page, end=page)],
        expected_answer=answer,
        evidence_quote=quote,
    )


TRIVIA = [
    _row(
        "What agency's full name appears on the cover of the Apollo 11 Mission Report (A11_MissionReport.pdf)?",
        "National Aeronautics and Space Administration (NASA)",
        "NATIONAL AERONAUTICS AND SPACE ADMINISTRATION",
        1,
    ),
    _row(
        "What is the MSC report number printed on the cover of the Apollo 11 Mission Report issued by the "
        "Manned Spacecraft Center in Houston, Texas in November 1969?",
        "MSC-0017,1",
        "MSC-0017,1",
        1,
    ),
]
SUBSTANCE = [
    _row(
        "What mission objective is listed for boilerplate spacecraft BP-6, launched from White Sands Missile "
        "Range on November 7, 1963?",
        "First pad short",
        "First pad short",
        2,
    ),
    _row(
        "Which boilerplate spacecraft was used for the second pad abort test conducted on June 29, 1965 at "
        "White Sands Missile Range?",
        "BP-23A",
        "BP-23A       | Second pad abort",
        2,
    ),
]


@pytest.mark.skipif(
    not (os.getenv("RAGWELD_LIVE_SYSTEM_ONE") and os.getenv("TYPESAFE_API_KEY")),
    reason="set RAGWELD_LIVE_SYSTEM_ONE=1 and TYPESAFE_API_KEY on LXC100 to call TypeSafe Jev",
)
async def test_jev_rejects_cover_page_trivia_and_keeps_questions_about_the_subject() -> None:
    thresholds = SyntheticJudgeConfig()
    async with SystemOneClient(SystemOneConfig(provider="typesafe")) as client:
        verdicts = {}
        for row in [*TRIVIA, *SUBSTANCE]:
            nouls = await client.nouls(judge_state(row, source_path=PDF), JUDGE_QUESTIONS)
            verdicts[row.question] = judge_verdict(nouls)
    for row in TRIVIA:
        verdict = verdicts[row.question]
        assert not judge_accepts(verdict, thresholds), (row.question, verdict)
        assert verdict.reader_question < 0.3, (row.question, verdict)
    for row in SUBSTANCE:
        verdict = verdicts[row.question]
        assert judge_accepts(verdict, thresholds), (row.question, verdict)
    worst_kept = min(verdicts[row.question].reader_question for row in SUBSTANCE)
    best_trivia = max(verdicts[row.question].reader_question for row in TRIVIA)
    assert worst_kept - best_trivia > 0.4, verdicts


@pytest.mark.skipif(
    not os.getenv("RAGWELD_LIVE_LAYA_BASE_URL"),
    reason="set RAGWELD_LIVE_LAYA_BASE_URL to a running laya-serve",
)
async def test_laya_answers_every_judge_question_with_a_probability() -> None:
    cfg = SystemOneConfig(provider="laya", laya_base_url=str(os.environ["RAGWELD_LIVE_LAYA_BASE_URL"]), timeout_s=120.0)
    async with SystemOneClient(cfg) as client:
        for row in (TRIVIA[0], SUBSTANCE[0]):
            response = await client.ask(judge_state(row, source_path=PDF), JUDGE_QUESTIONS)
            assert set(response.answers) == set(JUDGE_QUESTIONS)
            assert all(0.0 <= answer.noul <= 1.0 for answer in response.answers.values())
            judge_verdict({qid: answer.noul for qid, answer in response.answers.items()})
