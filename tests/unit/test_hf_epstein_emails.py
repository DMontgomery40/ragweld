from __future__ import annotations

from server.synthetic.hf_epstein_emails import (
    build_eval_item,
    materialized_filename,
    render_materialized_email,
    strip_html_message,
)


def test_strip_html_message_removes_tags_and_entities() -> None:
    html = "<div>Hello&nbsp;<b>world</b><br/>Line 2</div>"
    assert strip_html_message(html) == "Hello world\nLine 2"


def test_materialized_filename_uses_document_order_and_row_id() -> None:
    row = {
        "document_id": "HOUSE_OVERSIGHT_012102",
        "message_order": 3,
        "id": 42,
    }
    assert materialized_filename(row) == "HOUSE_OVERSIGHT_012102__msg_003__row_000042.txt"


def test_build_eval_item_generates_grounded_question_and_expected_path() -> None:
    row = {
        "id": 7,
        "document_id": "HOUSE_OVERSIGHT_012898",
        "source_filename": "HOUSE_OVERSIGHT_012898.txt",
        "message_order": 1,
        "subject": "Farmer Jaffe is suing Donald Trump!",
        "from_address": "Tonja Haddad Coleman",
        "to_address": "Jeffrey Epstein",
        "timestamp_iso": "20130513222830",
    }

    item = build_eval_item(
        row,
        filename="HOUSE_OVERSIGHT_012898__msg_001__row_000007.txt",
        variant=0,
    )

    assert item is not None
    assert item.question == 'Who sent the email with subject "Farmer Jaffe is suing Donald Trump!" to Jeffrey Epstein?'
    assert item.expected_paths == ["HOUSE_OVERSIGHT_012898__msg_001__row_000007.txt"]
    assert item.expected_answer == "Tonja Haddad Coleman"


def test_render_materialized_email_includes_structured_fields() -> None:
    row = {
        "id": 7,
        "document_id": "HOUSE_OVERSIGHT_012898",
        "source_filename": "HOUSE_OVERSIGHT_012898.txt",
        "message_order": 1,
        "subject": "Farmer Jaffe is suing Donald Trump!",
        "from_address": "Tonja Haddad Coleman",
        "to_address": "Jeffrey Epstein",
        "other_recipients": "",
        "timestamp_iso": "20130513222830",
        "message_html": "<p>This is the message body.</p>",
        "email_document_id": 1234,
    }

    rendered = render_materialized_email(row)
    assert "Source filename: HOUSE_OVERSIGHT_012898.txt" in rendered
    assert "Subject: Farmer Jaffe is suing Donald Trump!" in rendered
    assert "This is the message body." in rendered
