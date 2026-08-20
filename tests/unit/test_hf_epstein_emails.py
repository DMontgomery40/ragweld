from __future__ import annotations

import json
from pathlib import Path

from server.synthetic.hf_epstein_emails import (
    build_eval_item,
    materialize_epstein_email_rows,
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


def test_render_materialized_email_is_body_first_with_compact_metadata_footer() -> None:
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
    assert rendered.startswith("This is the message body.\n\n")
    assert 'Email metadata: Tonja Haddad Coleman emailed Jeffrey Epstein on 2013-05-13 22:28:30. Subject: "Farmer Jaffe is suing Donald Trump!".' in rendered
    assert "Source filename:" not in rendered
    assert "Document id:" not in rendered
    assert "Message\n-------" not in rendered


def test_materialize_epstein_email_rows_keeps_manifest_out_of_corpus_root(tmp_path: Path) -> None:
    row = {
        "id": 7,
        "document_id": "HOUSE_OVERSIGHT_012898",
        "source_filename": "HOUSE_OVERSIGHT_012898.txt",
        "message_order": 1,
        "subject": "Farmer Jaffe is suing Donald Trump!",
        "from_address": "Tonja Haddad Coleman",
        "to_address": "Jeffrey Epstein",
        "other_recipients": [],
        "timestamp_iso": "20130513222830",
        "message_html": "<p>This is the message body.</p>",
        "email_document_id": 1234,
    }
    output_dir = tmp_path / "corpus"
    eval_output_path = tmp_path / "eval" / "epstein-files-1.json"
    manifest_output_path = tmp_path / "metadata" / "hf-epstein-manifest.json"

    manifest = materialize_epstein_email_rows(
        rows=[row],
        output_dir=output_dir,
        eval_output_path=eval_output_path,
        manifest_output_path=manifest_output_path,
        max_eval_rows=1,
    )

    corpus_files = sorted(path.name for path in output_dir.iterdir())
    assert corpus_files == ["HOUSE_OVERSIGHT_012898__msg_001__row_000007.txt"]
    assert not (output_dir / "manifest.json").exists()
    assert eval_output_path.exists()
    assert manifest_output_path.exists()
    assert manifest["written_files"] == 1
    persisted_manifest = json.loads(manifest_output_path.read_text(encoding="utf-8"))
    assert persisted_manifest["rows"][0]["materialized_filename"] == corpus_files[0]
