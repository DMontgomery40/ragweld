"""Placeholder queries never become eval or training signal."""

from __future__ import annotations

import pytest

from server.evaluation.query_guard import is_real_query, placeholder_reason


@pytest.mark.parametrize(
    "query",
    [
        "Which flights or plane management did Jeffrey Epstein discuss with Barry Cohen in October 2017?",
        "How often is the Aurora salinity sensor array calibrated?",
        "Who received the email about the Jet Aviation to EJM switch?",
        "Epstein flights?",
        "Which flights did Epstein test on the Gulfstream in 2017?",
        "Кто отправил письмо о самолёте в октябре 2017 года?",
        "张伟在2017年10月发送了哪封关于飞机管理的邮件？",
    ],
)
def test_real_domain_questions_pass(query: str) -> None:
    assert is_real_query(query)
    assert placeholder_reason(query) is None


@pytest.mark.parametrize(
    "query",
    ["test", "Test", " testing ", "hello", "hi", "foo", "ping", "asdf", "lorem ipsum dolor", "q", "auth?", "", "   ",
     "Please run this test?", "hello there", "a test query", "testing 123"],
)
def test_placeholders_and_content_free_strings_are_rejected(query: str) -> None:
    assert not is_real_query(query)
    assert placeholder_reason(query) is not None
